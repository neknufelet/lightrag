#!/usr/bin/env python3
r"""實體碎片化：找出同一個概念被抽成多個節點的情形，並**照實際代價排序**。

為什麼不是「找出重複就合併」：

1. 碎片化**不會讓你查不到東西**。實測查 "wavenumber k0"，10 個變體全部回到
   結果裡 —— 向量檢索用的是名稱與描述的 embedding，這些名字在向量空間裡
   本來就緊鄰。「問 k₀ 只會找到其中一個」是錯的直覺。

2. 真正的代價是**佔格位**，而格位會直接擠掉原文：
       operate.py:5230
       available_chunk_tokens = max_total_tokens - (… + kg_context_tokens + …)
   實測 5 個查詢平均浪費 4.8% 的實體格位，但分布極不平均 —— 符號密集的
   查詢 18%，散文查詢 0%。

3. 合併不可逆（來源節點被刪除，關係搬到目標）。用 4.8% 的平均值去換 388 次
   不可逆操作不划算，而且數學裡 `S_n` 與 `S_N` 可能真的是兩回事。

所以這支做的是：分層 → 跑代表性查詢 → **只把真的出現在檢索結果裡的組**列成
候選，按浪費的格位數排序。沒被檢索到的長尾不值得冒險。

用法：
    ./entity-merge.py plan                 # 唯讀，產出候選清單
    ./entity-merge.py plan --queries 30    # 多跑幾個查詢，統計更穩
    ./entity-merge.py review --top 8       # 產人工審查表（附原文段落）

輸出：DATA_ROOT/<ws>/postprocess/entity-merge.json（含分層、代價、建議正規名）
      DATA_ROOT/<ws>/postprocess/entity-merge-review.md（審查表）

為什麼審查表一定要附原文：實測第一組 `Z m` / `ZM` / `Zm`，三個節點的
description 看起來像三個相關概念，撈出原文才發現

    Z m   chunk-008  電-力學類比表          → 真的是力學阻抗
    ZM    chunk-019  \mathrm{Z_{Ma}, Z_{Mi}}  → 一整族的截斷
    Zm    chunk-102  $Z_{\mathrm{Mi}} = …$    → 其實是 Z_Mi，讀掉了 i

合併它們是錯的，而 `Zm` 該併的是**另一組** `Z Mi / ZMi / Z_Mi / Zmi`。
description 是模型的轉述，會錯；原文不會。所以兩欄並列，不一致時以原文為準。
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import subprocess
import sys
import unicodedata
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mineru_common import load_env  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DATA_ROOT = Path(os.environ.get("PP_DATA_ROOT", "/data/rag/lightrag"))
SEP = re.compile(r"[\s_\-.,()]+")
# LightRAG 用這個字串串接多值欄位（source_id、file_path）
def SEPS(v: str) -> list[str]:
    return [x for x in (v or "").split("<SEP>") if x.strip()]


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def toks(s: str) -> list[str]:
    """在**原字串**上斷詞。

    先拿掉分隔符再找詞邊界會毀掉「這個字元是下標」的訊息 —— 實測第一版就是
    這樣：`Eta_N` 去掉底線變成 `EtaN`，於是 `N` 落在一個四字母的「詞」裡，
    `Eta_N` 與 `Eta_n` 被判成「只差英文詞大小寫」的安全組。它們差的正是下標。
    """
    return [t for t in SEP.split(fold(s)) if t]


def group_key(s: str) -> str:
    return "".join(toks(s)).lower()


def tier(group: list[str]) -> str:
    """A：只差分隔符（大小寫完全一致）—— 純排版差異，沒有語意風險
       B：只差長度 >= 3 的英文詞大小寫 —— 標題式大寫，安全
       C：差在下標／短記號，或 token 數對不齊 —— 數學裡那是意義，要人看

    C 不是「壞的候選」，是「不能自動判斷的候選」。實測最貴的一組
    （Wavenumber / Wave Number 家族，單一查詢就佔 10 格）正是落在 C ——
    token 數不同。所以 C 必須人工過目，不能因為它需要人力就跳過。
    """
    ts = [toks(x) for x in group]
    if len({"".join(t) for t in ts}) == 1:
        return "A"
    if len({len(t) for t in ts}) != 1:
        return "C"
    ref = ts[0]
    for other in ts[1:]:
        for a, b in zip(ref, other):
            if a == b:
                continue
            if a.lower() != b.lower() or len(a) < 3 or not a.isalpha():
                return "C"
    return "B"


def canonical(group: list[str]) -> str:
    """建議保留哪一個。

    偏好：有分隔符的（`k_0` 讀得出下標，`k0` 讀不出）> 長的 > 字典序。
    這只是建議，最終由人決定 —— 合併會刪掉其餘節點。
    """
    return sorted(group, key=lambda s: (-len(SEP.findall(s)), -len(s), s))[0]


class Rag:
    def __init__(self, env: dict):
        self.host = f"http://{env.get('BIND_ADDR', '100.87.88.7')}:{env.get('HOST_PORT', '9621')}"
        self.key = env.get("LIGHTRAG_API_KEY", "")

    def _req(self, path: str, method="GET", body=None, timeout=240):
        r = urllib.request.Request(
            self.host + path, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"X-API-Key": self.key, "Content-Type": "application/json"})
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return json.loads(resp.read() or "{}")

    def labels(self) -> list[str]:
        return self._req("/graph/label/list")

    def popular(self, n: int) -> list[str]:
        return self._req(f"/graph/label/popular?limit={n}")

    def subgraph(self, label: str) -> dict:
        import urllib.parse
        return self._req(f"/graphs?label={urllib.parse.quote(label)}"
                         f"&max_depth=1&max_nodes=60", timeout=90)

    def entities_for(self, query: str, top_k: int) -> list[str]:
        # chunk_top_k=1：我們只要實體清單，不需要原文。設 0 會被當成「不限制」，
        # 所以給 1 —— 少搬幾十 KB 的 chunk 過來。
        d = self._req("/query/data", "POST",
                      {"query": query, "mode": "mix", "only_need_context": True,
                       "top_k": top_k, "chunk_top_k": 1}).get("data") or {}
        return [e.get("entity_name") for e in (d.get("entities") or []) if e.get("entity_name")]


def cmd_plan(a, env) -> int:
    rag = Rag(env)
    labels = rag.labels()
    print(f"實體 {len(labels)} 個")

    groups: dict[str, list[str]] = collections.defaultdict(list)
    for l in labels:
        groups[group_key(l)].append(l)
    dups = {k: sorted(v) for k, v in groups.items() if len(v) > 1}
    by_tier = collections.Counter(tier(v) for v in dups.values())
    extra = sum(len(v) - 1 for v in dups.values())
    print(f"重複組 {len(dups)}、多餘節點 {extra}（{extra/len(labels):.1%}）"
          f"　A {by_tier['A']}　B {by_tier['B']}　C {by_tier['C']} 組")

    # ── 查詢集：用高分支度的實體名當種子 ──
    # 不自己編查詢 —— 編出來的會偏向我想得到的主題。用圖譜自己回報的熱門標籤，
    # 反映的是這個知識庫實際被檢索時的樣子。
    seeds = rag.popular(a.queries)
    print(f"\n跑 {len(seeds)} 個查詢統計實際佔用（每個都要 LLM 抽關鍵詞，會慢）…")

    cost: dict[str, int] = collections.Counter()      # group_key → 浪費的格位數
    hits: dict[str, set] = collections.defaultdict(set)
    slots = 0
    for i, q in enumerate(seeds, 1):
        try:
            ents = rag.entities_for(q, a.top_k)
        except Exception as e:                        # noqa: BLE001
            print(f"  [{i}/{len(seeds)}] {q[:40]:42s} 查詢失敗：{type(e).__name__}")
            continue
        slots += len(ents)
        c = collections.Counter(group_key(e) for e in ents)
        waste = 0
        for k, n in c.items():
            if n > 1 and k in dups:
                cost[k] += n - 1
                hits[k].update(e for e in ents if group_key(e) == k)
                waste += n - 1
        print(f"  [{i}/{len(seeds)}] {q[:40]:42s} 實體 {len(ents):3d}　浪費 {waste:2d}")

    ranked = []
    for k, w in cost.most_common():
        g = dups[k]
        ranked.append({"tier": tier(g), "wasted_slots": w, "members": g,
                       "seen_together": sorted(hits[k]), "suggest_keep": canonical(g)})
    silent = [k for k in dups if k not in cost]

    out_dir = DATA_ROOT / a.workspace / "postprocess"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "entity-merge.json"
    out.write_text(json.dumps({
        "entities": len(labels), "duplicate_groups": len(dups), "extra_nodes": extra,
        "queries": len(seeds), "entity_slots": slots,
        "wasted_slots": sum(cost.values()),
        "candidates": ranked,
        "never_retrieved": [{"tier": tier(dups[k]), "members": dups[k]} for k in silent],
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n{'-'*74}")
    print(f"{slots} 個實體格位中浪費 {sum(cost.values())} 格"
          f"（{sum(cost.values())/max(slots,1):.1%}）")
    print(f"真的被檢索到的重複組 {len(ranked)}／{len(dups)}；"
          f"另外 {len(silent)} 組從未出現在結果裡 —— 那些合併了也不會改善什麼")
    print(f"\n── 值得處理的（按浪費格位排序，前 20）──")
    for r in ranked[:20]:
        print(f"  {r['wasted_slots']:2d} 格  [{r['tier']}]  保留 {r['suggest_keep']!r}")
        print(f"          {r['members']}")
    print(f"\n候選清單：{out}")
    print("這一步完全唯讀。合併是破壞性的（來源節點會被刪掉），"
          "動手前要先把受影響節點的邊 dump 下來。")
    return 0



# ── 讓原文讀得懂 ──────────────────────────────────────────────
# chunk 裡的數學是 MinerU 吐的 LaTeX，字體指令多到蓋掉內容：
#   $\mathsf { Z } _ { \mathsf { M i } } = \mathsf { Z } _ { \mathsf { s h } }$
# 直接貼進審查表，人得先在腦裡剝一層才看得到符號。剝掉字體指令、把
# `_ { M i }` 收成 `_Mi` 之後變成 `$Z_Mi = Z_sh$`，一眼就認得出來。
# 這裡只為了**閱讀**，不參與任何比對判斷 —— 比對用 crosscheck.eq_normalize。
_FONT = re.compile(
    r"\\(?:displaystyle|textstyle|scriptstyle|mathrm|mathit|mathbf|mathsf|mathcal|"
    r"mathtt|mathfrak|mathbb|mathnormal|boldsymbol|boldmath|pmb|"
    r"bf|rm|it|sf|tt|text|left|right|Bigg|bigg|Big|big|,|;|!|:|quad|qquad)"
    r"(?![a-zA-Z])")


def readable(latex: str) -> str:
    t = _FONT.sub("", latex or "")
    t = re.sub(r"\{\s*([^{}]*?)\s*\}", lambda m: m.group(1).replace(" ", ""), t)
    t = re.sub(r"\s*([_^])\s*", r"\1", t)
    return re.sub(r"\s{2,}", " ", t).strip()


def _runs(tok: str) -> list[str]:
    """把一個 token 拆成字母／數字的連續段，並在大寫後接小寫處斷開。

    `J0` → ['J','0']、`Zm` → ['Z','m']、`Bessel` → ['Bessel']。
    因為原文寫的是 `$J_{0}$`、`Z_{m}`，實體名卻是 `J0`、`Zm` —— 不拆就永遠
    對不上，審查表整欄變成「找不到原樣字串」而那是假的。
    """
    return re.findall(r"[A-Z][a-z]+|[A-Z]+(?![a-z])|[a-z]+|\d+", tok) or [tok]


_GLUE = r"(?:[\s_^{}$()\\]|\\[a-zA-Z]+)*"


def variant_patterns(name: str) -> list[tuple[str, re.Pattern]]:
    """由嚴到寬的幾種找法。回傳 (層級說明, pattern)，第一個命中的就用。

    嚴格比對對多詞概念名沒有用：`Bessel Function J0` 在原文裡是
    「Bessel function $J_{0}$」，中間隔著 `$` 與 `_{}`。所以 token 之間允許
    任何分隔／括號／字體指令。真的找不到時才退到只找符號尾巴 —— 那才是
    同組成員之間唯一不同的地方。
    """
    runs = [r for t in toks(name) for r in _runs(t)]
    out = [("完整名稱", re.compile(_GLUE.join(map(re.escape, runs)) + r"(?![A-Za-z])", re.I))]
    if len(runs) > 1:
        tail = runs[-2:]
        out.append(("符號部分 " + "".join(tail),
                    re.compile(_GLUE.join(map(re.escape, tail)) + r"(?![A-Za-z])", re.I)))
    # 最後一層：拿掉「後面不可以接字母」這個限制。命中代表原文其實是更長的
    # 符號，實體名是被截斷的 —— 那不是該合併，是該改名。
    # 實測 `Zm` 的來源寫的是 $Z_{Mi}$、`ZM` 的來源寫的是 Z_{Ma}, Z_{Mi}；
    # 只報「找不到」的話，看的人不知道原文到底寫了什麼，也就無從判斷。
    # 逐字元拆。`Zm` 用 _runs 會被 [A-Z][a-z]+ 整個吃成一個「詞」，於是 Z 與 m
    # 中間插不進 `_{\mathrm{`，永遠對不到原文的 $Z_{Mi}$ —— 實測就是這樣。
    # 黏著長度封在 12 以內，否則兩個字母可以隔半個 chunk 相認。
    chars = [c for c in "".join(toks(name)) if c.strip()]
    loose = f"(?:[\\s_^{{}}$()\\\\]|\\\\[a-zA-Z]+){{0,12}}"
    out.append(("延伸形式（原文比這個名字長）",
                re.compile(loose.join(map(re.escape, chars)), re.I)))
    return out


class Pg:
    """chunk 原文只在 Postgres 裡，而 Postgres 只在 docker 網路內（host 解不到
    這個名字，也沒有 psycopg2）。POSTGRES_HOST 剛好就是容器名，直接 exec。"""

    def __init__(self, env: dict):
        self.c = env.get("POSTGRES_HOST", "")
        self.env = env

    def chunks(self, ids: list[str]) -> dict[str, str]:
        if not ids or not self.c:
            return {}
        lst = ",".join("'" + i.replace("'", "''") + "'" for i in ids)
        sql = (f"SELECT id || E'\\x01' || content || E'\\x02' "
               f"FROM lightrag_doc_chunks WHERE id IN ({lst});")
        out = subprocess.run(
            ["docker", "exec", "-i", "-e", f"PGPASSWORD={self.env.get('POSTGRES_PASSWORD','')}",
             self.c, "psql", "-U", self.env.get("POSTGRES_USER", ""),
             "-d", self.env.get("POSTGRES_DATABASE", ""), "-At", "-c", sql],
            capture_output=True, text=True, timeout=120)
        res = {}
        for blk in out.stdout.split("\x02"):
            if "\x01" in blk:
                k, _, v = blk.partition("\x01")
                res[k.strip()] = v
        return res


def cmd_review(a, env) -> int:
    rag, pg = Rag(env), Pg(env)
    src = DATA_ROOT / a.workspace / "postprocess" / "entity-merge.json"
    if not src.is_file():
        sys.exit(f"找不到 {src}，先跑 `entity-merge.py plan`")
    plan = json.loads(src.read_text())
    cands = plan["candidates"][: a.top]
    print(f"審查前 {len(cands)} 組（共 {len(plan['candidates'])} 組被檢索到）")

    # 先把節點資料抓齊，再一次向 Postgres 要 chunk —— 每組各問一次會開 N 個
    # docker exec，慢且吵。
    info: dict[str, dict] = {}
    for g in cands:
        for m in g["members"]:
            if m in info:
                continue
            try:
                ns = rag.subgraph(m)
            except Exception:                                  # noqa: BLE001
                ns = {"nodes": [], "edges": []}
            node = next((n for n in (ns.get("nodes") or []) if n["labels"][0] == m), None)
            p = (node or {}).get("properties") or {}
            # 邊的 source/target 是**數值節點 id**，不是 label。拿 label 去比
            # 永遠不相等，度數整欄變成 0 —— 而 0 看起來像「這個節點沒關係、
            # 合併很安全」，剛好是最會誤導人的方向。
            nid = str((node or {}).get("id", ""))
            deg = sum(1 for e in (ns.get("edges") or [])
                      if nid and nid in (str(e.get("source")), str(e.get("target"))))
            # source_id / file_path 是 **<SEP> 串接的清單**，不是單一值 ——
            # 一個實體可能被多個 chunk 提到。實測拿整串當 id 查，26 個只回 14 個，
            # 而缺的那些不會報錯，只是審查表上出現「找不到原文」。
            info[m] = {"docs": SEPS(p.get("file_path", "")),
                       "chunks": SEPS(p.get("source_id", "")),
                       "desc": p.get("description", ""), "degree": deg,
                       "type": p.get("entity_type", "")}
    want = sorted({c for v in info.values() for c in v["chunks"]})
    texts = pg.chunks(want)
    print(f"取得 {len(texts)}／{len(want)} 個 chunk 原文")

    L = ["# 實體合併審查", "",
         f"前 {len(cands)} 組，來自 `entity-merge.py plan` 的代價排序。", "",
         "## 怎麼判", "",
         "每組要決定的是：**這幾個名字指的是同一個東西嗎?**", "",
         "| 判斷 | 動作 | 後果 |",
         "|---|---|---|",
         "| 是同一個 | 合併 | 關係搬到你選的名字，其餘節點**刪除**，不可逆 |",
         "| 不是 | 不動 | 維持現狀，繼續各佔一格 |",
         "| 名字讀錯了 | 改名 | 用 `/graph/entity/edit`，不刪節點 |", "",
         "看兩欄：**抽取器認為**是模型寫的描述，**原文寫的**是它實際讀到的字。",
         "兩者不一致時**以原文為準** —— 描述是模型的轉述，會錯。已經標了 ⚠️。", "",
         "> 標「比對到延伸形式」的那幾列，比對規則放得很寬（允許符號中間插入",
         "> LaTeX 指令），**可能配到不相干的位置**。看起來不像的就當作沒找到，",
         "> 不要拿它當證據。標「完整名稱」「符號部分」的才是可靠的命中。", "",
         "`關係數` 是這個節點連著幾條邊。合併時這些邊會搬到目標節點。", "", "---", ""]

    for i, g in enumerate(cands, 1):
        L += [f"## {i}. {' / '.join(g['members'])}", "",
              f"浪費 **{g['wasted_slots']} 格**　層級 **{g['tier']}**"
              f"　建議保留 `{g['suggest_keep']}`", "",
              "| 名字 | 出處 | 關係數 | 抽取器認為 | 原文寫的 |",
              "|---|---|---|---|---|"]
        mismatch = False
        for m in g["members"]:
            d = info[m]
            quote, where = "", ""
            for level, pat in variant_patterns(m):
                for cid in d["chunks"]:             # 逐個來源找，第一個命中就用
                    body = texts.get(cid, "")
                    hit = pat.search(body)
                    if not hit:
                        continue
                    lo, hi = max(0, hit.start() - 90), min(len(body), hit.end() + 90)
                    quote = "…" + readable(body[lo:hi]).replace("|", r"\|") + "…"
                    if level != "完整名稱":
                        quote = f"（比對到{level}）" + quote
                    where = cid[-9:]
                    break
                if quote:
                    break
            if not quote:
                quote = (f"**{len(d['chunks'])} 個來源 chunk 都找不到原樣字串**")
                where = d["chunks"][0][-9:] if d["chunks"] else "?"
                mismatch = True
            docs = "、".join(sorted({Path(x).stem[:18] for x in d["docs"]})) or "?"
            L.append(f"| `{m}` | {docs}<br>`{where}` | "
                     f"{d['degree']} | {d['desc'][:90].replace('|', chr(92)+'|')} | {quote[:200]} |")
        L += ["", "**選一個**（打勾）", "",
              f"- [ ] 合併成 `{g['suggest_keep']}`",
              "- [ ] 合併成別的：`________`",
              "- [ ] 不合併（是不同的東西）",
              "- [ ] 改名：`________` → `________`", ""]
        if mismatch:
            L += ["> ⚠️ 有成員在來源 chunk 裡找不到原樣的字串。",
                  "> 那代表名字是模型「推」出來的，不是照抄 —— 特別要看原文再決定。", ""]
        L += ["---", ""]

    out = DATA_ROOT / a.workspace / "postprocess" / "entity-merge-review.md"
    out.write_text("\n".join(L), encoding="utf-8")
    print(f"\n審查表：{out}")
    print("全程唯讀。勾完把檔案給我，我再做邊的 dump 與實際合併。")
    return 0

def main() -> int:
    env = load_env(REPO)
    ap = argparse.ArgumentParser(description="實體碎片化：分層 + 依實際代價排序")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="唯讀，產出候選清單")
    p.add_argument("--workspace", default=env.get("WORKSPACE", "acoustics_v155"))
    p.add_argument("--queries", type=int, default=30, help="用幾個熱門標籤當查詢種子")
    p.add_argument("--top-k", type=int, default=40, help="每個查詢取幾筆圖譜內容")

    r = sub.add_parser("review", help="產人工審查表（附原文段落）")
    r.add_argument("--workspace", default=env.get("WORKSPACE", "acoustics_v155"))
    r.add_argument("--top", type=int, default=8, help="審查前幾組")

    a = ap.parse_args()
    return {"plan": cmd_plan, "review": cmd_review}[a.cmd](a, env)


if __name__ == "__main__":
    sys.exit(main())
