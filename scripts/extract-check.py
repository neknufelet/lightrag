#!/usr/bin/env python3
"""抽取品質檢查：接地(grounding) + 數量帳。

為什麼需要：後處理一路在驗「解析對不對」，但**抽取層完全沒驗過**。
數量好看不代表內容對 —— 1,135 個實體可能全是幻覺，計數一模一樣。
這跟解析層做兩雙眼睛之前是同一個處境。

接地檢查的原理跟 pdfcrop 抽文字層當 ground truth 一樣：**拿產出去對來源，
而不是相信它**。每個抽出的實體名字，應該在它來源的那個 chunk 裡找得到；
模型編出來的實體不會。確定性、不呼叫任何模型、不花錢。

比對是刻意寬鬆的（大小寫、空白、連字號正規化，並允許逐詞命中），因為
LLM 會合理地改寫大小寫與斷字。目標是抓**憑空捏造**，不是抓改寫。
判定為未接地的才是需要看的東西。

用法：
    extract-check.py                     # 全部
    extract-check.py --doc Equivalent
    extract-check.py --list-ungrounded 30
    extract-check.py --dump-symbolic symbolic.json
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mineru_common import add_workspace_arg, load_env, postgres_container  # noqa: E402
from pp import findings  # noqa: E402

REPO = Path(__file__).resolve().parent.parent

# 散文 chunk 的未接地比例超過此值才算異常。
# 只看散文 —— 符號型 chunk 的「未接地」不代表幻覺，見 SYMBOLIC 說明。
T_UNGROUNDED = 0.10

# chunk 裡表格標記與 LaTeX 佔比超過此值，視為符號型。
SYMBOLIC_RATIO = 0.35

_MARKUP = re.compile(r"<[^>]+>|\$[^$]*\$|\\[a-zA-Z]+")


def is_symbolic(text: str) -> bool:
    r"""這個 chunk 主要是表格與公式，而不是散文。

    為什麼要分：接地檢查用字串比對，只對散文有效。表格裡常常只有符號 ——
    實測 C 的 chunk-002 是一張表，儲存格是 `G` 與 $G=I/\Delta U=1/Z$，
    完全沒有 'Conductance' 這個英文字，但模型抽出 Conductance 是**正確的**：
    從符號推論概念名稱正是它該做的事。要求那個字出現在原文，等於要求它別做。

    實測未接地率與符號密度高度相關，與幻覺無關：
      A Conventions（純散文）0% / 論文 3.4–3.6% / G 34% / C（57 張表）55%
    所以符號型 chunk 的未接地只能標成「無法驗證」，交人工，不能算失敗。
    """
    if not text:
        return False
    return len("".join(_MARKUP.findall(text))) / max(len(text), 1) > SYMBOLIC_RATIO


def q(s: str) -> str:
    """SQL 字串字面值。自己包引號，不用 shell 插值。"""
    return "'" + s.replace("'", "''") + "'"


def psql(sql: str, env: dict) -> list[dict]:
    """走 JSON 而不是分隔符 —— chunk 內容含換行，逐行切會把一列拆散
    （第一版就是這樣 IndexError）。json_agg 讓 psql 只吐一行。"""
    wrapped = f"select coalesce(json_agg(t), '[]'::json)::text from ({sql}) t"
    cmd = ["docker", "exec", postgres_container(env), "psql",
           "-U", env.get("POSTGRES_USER", "deeptutor"),
           "-d", env.get("POSTGRES_DATABASE", "lightrag"), "-tAqX", "-c", wrapped]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=False)
    if r.returncode != 0:
        sys.exit(f"psql 失敗：{r.stderr.strip()[:300]}")
    return json.loads(r.stdout.strip() or "[]")


_NORM = re.compile(r"[^a-z0-9]+")


def norm(s: str) -> str:
    """大小寫、標點、空白、變音符號一律抹平。

    折疊變音符號是必要的：原文寫 'Michał Raczyński'，模型很合理地抽成
    'Michal Raczynski'（自己去掉了變音），不折疊的話 ł/ń 會被當成標點抹成
    空白，兩邊永遠對不上 —— 實測讓兩個作者名被誤判成幻覺。
    """
    t = unicodedata.normalize("NFKD", s or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    # NFKD 拆不開的（ł、ø、ð 等）另外對映
    t = t.translate(str.maketrans("łŁøØðÐþÞđĐıŒœæÆß", "lLoOdDtTdDiOoaAs"))
    return _NORM.sub(" ", t.lower()).strip()


def grounded(name: str, text: str) -> bool:
    """名字整串出現，或它的每個詞都出現在來源裡。

    逐詞退路是必要的：LLM 常把 'Orifice Partition Impedance Z_Mi' 這種
    合併命名寫出來，整串不會在原文出現，但每個詞都在。要求整串命中會產生
    大量假警報，把真正的幻覺淹掉。
    """
    n, t = norm(name), norm(text)
    if not n:
        return False
    if n in t:
        return True
    words = [w for w in n.split() if len(w) > 2]
    if not words:
        return n in t
    return all(w in t for w in words)


def main() -> int:
    env = load_env(REPO)
    ap = argparse.ArgumentParser(description="抽取品質：接地檢查與數量帳")
    ap.add_argument("--doc", help="file_path 關鍵字，預設全部")
    add_workspace_arg(ap, env)
    ap.add_argument("--list-ungrounded", type=int, default=12,
                    help="列出「可疑」桶（非符號型且未接地）的前 N 個；不包含符號型／驗不了項目")
    ap.add_argument("--dump-symbolic", type=Path, metavar="FILE",
                    help="將符號型／驗不了的實體與其來源 chunk 原文寫成 JSON")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    dim = env.get("EMBEDDING_DIM", "3072")
    # ⚠ 表名要把**所有**非英數字元換掉，不能只換 `-`。2026-08-08 embedding 從
    # `text-embedding-3-large` 換成 `BAAI/bge-m3` 之後，只換 `-` 的版本會拼出
    # `lightrag_vdb_entity_BAAI/bge_m3_1024d`，psql 直接 syntax error ——
    # **也就是說接地檢查從那天起就一直跑不起來**，而沒有人發現，因為它只在
    # 有人主動跑的時候才會炸。這一版沿用 `graph-shape.py` 已經在用的正規化。
    model = re.sub(r"[^0-9a-z]+", "_", env.get("EMBEDDING_MODEL",
                                               "text-embedding-3-large").lower())
    etab = f"lightrag_vdb_entity_{model}_{dim}d"
    # **每一句都要帶 workspace。** 多個知識庫共存於同一組 Postgres，靠 workspace
    # 欄位隔離；沒有這個條件時 v155 與 v2 的列會混在一起，而且兩邊的 file_path
    # 是同一批 PDF 檔名，逐份表會把兩個 workspace 的同一份文件併成一列——
    # 數字看起來完全正常（只是大約兩倍），不會有任何錯誤訊息。
    # 實測踩過（2026-08-03，v2 階段 3）：合計實體 14,402＝v155 7,191＋v2 7,211。
    ws = q(a.workspace)

    # 一次把 chunk 全撈進來（很小），避免 N 次查詢
    chunks = {r["id"]: r["content"] or "" for r in psql(
        f"select id, content from lightrag_doc_chunks where workspace = {ws}", env)}

    rows = psql(f"""
        select entity_name, chunk_ids, coalesce(file_path, '') as file_path
        from {etab} where chunk_ids is not null and workspace = {ws}
    """, env)

    per_doc: dict[str, dict] = {}
    ungrounded: list[tuple[str, str]] = []
    symbolic_entities: list[tuple[str, str, list[str]]] = []
    for row in rows:
        name, cids = row["entity_name"], row["chunk_ids"] or []
        doc = ((row["file_path"] or "").split("<SEP>")[0]).strip() or "?"
        if a.doc and a.doc.lower() not in doc.lower():
            continue
        d = per_doc.setdefault(doc, {"total": 0, "ok": 0, "missing_chunk": 0,
                                     "symbolic": 0})
        d["total"] += 1
        texts = [chunks.get(c, "") for c in cids if c]
        if not any(texts):
            d["missing_chunk"] += 1
            continue
        if any(grounded(name, t) for t in texts):
            d["ok"] += 1
        elif all(is_symbolic(t) for t in texts if t):
            # 三態：來源全是符號型，字串比對沒有鑑別力 —— 無法驗證，不是失敗
            d["symbolic"] += 1
            if a.dump_symbolic:
                symbolic_entities.append((doc, name, sorted({c for c in cids if c in chunks})))
        else:
            ungrounded.append((doc, name))

    if a.dump_symbolic:
        symbolic_entities.sort(key=lambda entity: (entity[0], entity[1], entity[2]))
        symbolic_chunk_ids = sorted({c for _, _, cids in symbolic_entities for c in cids})
        a.dump_symbolic.write_text(json.dumps({
            "workspace": a.workspace,
            "generated_from": "extract-check.py --dump-symbolic",
            "counts": {"entities": len(symbolic_entities),
                       "chunks_referenced": len(symbolic_chunk_ids)},
            "entities": [{"doc": doc, "name": name, "chunk_ids": cids}
                         for doc, name, cids in symbolic_entities],
            "chunks": {c: chunks[c] for c in symbolic_chunk_ids},
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if not per_doc:
        print("沒有符合的實體")
        return 0

    if a.json:
        print(json.dumps({"per_doc": per_doc,
                          "ungrounded": [{"doc": d, "name": n} for d, n in ungrounded]},
                         ensure_ascii=False, indent=1))
        return 0

    print(f"{'文件':<46}{'實體':>6}{'接地':>6}{'符號型':>8}{'可疑':>6}{'可疑率':>8}")
    print("-" * 82)
    bad_docs = 0
    for doc, d in sorted(per_doc.items()):
        un = d["total"] - d["ok"] - d["missing_chunk"] - d["symbolic"]
        # 分母只算「字串比對有鑑別力」的那些 —— 拿符號型稀釋會讓比例失去意義
        denom = d["ok"] + un
        ratio = un / max(denom, 1)
        over = ratio > T_UNGROUNDED
        flag = "  ⚠" if over else ""
        bad_docs += over
        print(f"{doc[:44]:<46}{d['total']:>6}{d['ok']:>6}{d['symbolic']:>8}"
              f"{un:>6}{ratio:>7.1%}{flag}")
        # 超標時把「這份查過了、結論是什麼」直接印在旁邊。不這樣做的話，
        # 同一個查證會被重做 —— K Muffler 查過一次、L Capsules 又查一次（見
        # tests/verified-findings.json 的 _why）。過期的紀錄會自己說要重查。
        if over:
            hit = findings.lookup("extract-check", "grounding_suspect_rate", doc,
                                  current={"suspect": un, "rate": ratio,
                                           "entities": d["total"], "symbolic": d["symbolic"]})
            if hit:
                for line in hit.lines():
                    print(line)

    tot = sum(d["total"] for d in per_doc.values())
    ok = sum(d["ok"] for d in per_doc.values())
    miss = sum(d["missing_chunk"] for d in per_doc.values())
    sym = sum(d["symbolic"] for d in per_doc.values())
    un = tot - ok - miss - sym
    print("-" * 82)
    print(f"{'合計':<46}{tot:>6}{ok:>6}{sym:>8}{un:>6}{un/max(ok+un,1):>7.1%}")
    print(f"\n符號型 {sym} 個 —— 來源 chunk 全是表格/公式，字串比對沒有鑑別力，"
          "不是幻覺也不是通過")
    if miss:
        print(f"\n⚠ {miss} 個實體的來源 chunk 在資料庫裡找不到 —— 那是參照斷裂，比未接地嚴重")

    if ungrounded:
        print(f"\n── 對不到原文的實體（前 {a.list_ungrounded} 個，這些是要看的）──")
        for doc, name in ungrounded[:a.list_ungrounded]:
            print(f"  {doc[:34]:<36} {name[:60]}")

    # ── 關係 ──────────────────────────────────────────────
    rtab = etab.replace("_vdb_entity_", "_vdb_relation_")
    rels = psql(f"""
        select source_id, target_id, chunk_ids, coalesce(file_path,'') as file_path
        from {rtab} where chunk_ids is not null and workspace = {ws}
    """, env)
    if rels:
        rstat = {"total": 0, "ok": 0, "one_side": 0, "neither": 0, "symbolic": 0}
        bad_rel: list[tuple[str, str, str]] = []
        for r in rels:
            doc = ((r["file_path"] or "").split("<SEP>")[0]).strip() or "?"
            if a.doc and a.doc.lower() not in doc.lower():
                continue
            rstat["total"] += 1
            texts = [chunks.get(c, "") for c in (r["chunk_ids"] or []) if c]
            texts = [t for t in texts if t]
            if not texts:
                continue
            src, tgt = r["source_id"] or "", r["target_id"] or ""
            # 兩端都要在同一段原文裡找得到。關係說「A 和 B 有關聯」，
            # 那段原文至少要同時提到 A 和 B —— 只提到一邊的是模型跨段腦補，
            # 兩邊都沒有的是憑空捏造。
            hit = max((grounded(src, t), grounded(tgt, t)).count(True) for t in texts)
            if hit == 2:
                rstat["ok"] += 1
            elif all(is_symbolic(t) for t in texts):
                rstat["symbolic"] += 1
            elif hit == 1:
                rstat["one_side"] += 1
                bad_rel.append((doc, src, tgt))
            else:
                rstat["neither"] += 1
                bad_rel.append((doc, src, tgt))

        n = rstat["total"]
        judged = rstat["ok"] + rstat["one_side"] + rstat["neither"]
        print(f"\n{'='*82}\n關係：共 {n:,} 條")
        print(f"  兩端都對得到原文    {rstat['ok']:,}")
        print(f"  符號型（驗不了）    {rstat['symbolic']:,}")
        print(f"  只有一端對得到      {rstat['one_side']:,}"
              f"　（{rstat['one_side']/max(judged,1):.1%}）← 跨段腦補")
        print(f"  兩端都對不到        {rstat['neither']:,}"
              f"　（{rstat['neither']/max(judged,1):.1%}）← 最可疑")
        if bad_rel:
            print(f"\n── 可疑的關係（前 {a.list_ungrounded} 條）──")
            for doc, src, tgt in bad_rel[:a.list_ungrounded]:
                print(f"  {doc[:26]:<28} {src[:26]:<28} → {tgt[:24]}")

    return 2 if bad_docs else 0


if __name__ == "__main__":
    sys.exit(main())
