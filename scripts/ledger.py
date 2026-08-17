#!/usr/bin/env python3
"""體檢表：每份文件一張三態表，記錄它通過了哪些閘門。

為什麼要有這個：上一輪的檢查結果散在 commit 訊息、終端機捲軸和人的記憶裡，
「這份文件到底驗過沒有」只能靠翻歷史。體檢表把它變成一個檔案 —— 接手的人看表，
不翻 commit。

**三態不是兩態加一個雜項。** `pass` / `fail` / `unverifiable` 各自的意思是：

    pass          驗過了，通過
    fail          驗過了，沒通過 —— 文件不得進下一段
    unverifiable  **沒得驗**，而且理由要留下來

把 unverifiable 併進 pass，等於宣稱驗過了；併進 fail，等於宣稱壞了。兩種都是
把「不知道」講成「知道」，而這個專案一路在防的就是那個。所以 `unverifiable`
沒有 `--note` 直接拒收 —— 沒有理由的「驗不了」跟沒檢查無法區分。

格式原定在 docs/rebuild-plan.md（已於 2026-08-07 刪除，在 tag
archive/pre-rebuild-20260807 裡），**不要自創欄位**：欄位一長出來
就沒有第二個人知道該不該填，表也就不再是同一張表。

用法：
    ledger.py set 'C Equivalent' parse.coverage pass --value 0.031 --threshold 0.05
    ledger.py set 'C Equivalent' pp.tables unverifiable --note '3 表 bbox 有、body 與 img_path 皆空'
    ledger.py show 'C Equivalent'
    ledger.py show                     # 全部文件逐張印
    ledger.py summary                  # 全部文件 × 全部閘門的三態總表
    ledger.py summary --problems       # 只列有問題的（通過的份數仍會報出來）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mineru_common import add_workspace_arg, load_env  # noqa: E402
from pp.paths import DEFAULT_DATA_ROOT, DataPaths  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DEFAULT_ROOT = DEFAULT_DATA_ROOT

# 閘門清單與順序照原 rebuild-plan 的「體檢表格式」（見上方 docstring）。白名單不是提示：
# 打錯字的閘門名會安靜地長出第八個欄位，總表少一格沒人會發現（鐵則 1：拒絕，不猜）。
GATES = [
    "parse.coverage",
    "parse.checks",
    "pp.preflight",
    "pp.tables",
    "pp.equations",
    "extract.grounding",
    "extract.format",
    "retrieval.smoke",
]
# 總表的欄寬要塞得下，縮寫只用在顯示，檔案裡一律是全名。
ABBR = {g: g.split(".")[1][:5] for g in GATES}

STATES = ("pass", "fail", "unverifiable")
MARK = {"pass": "  o  ", "fail": " FAIL", "unverifiable": " 驗不了", None: "   -  "}

# 接地率超過此值就判 fail。**這是這個門檻唯一的家。**
#
# 2026-08-16 搬到這裡：原本 `ledger-backfill.py` 的 `--threshold` 預設與
# `extract-check.py` 的 `T_UNGROUNDED` 各有一份，值剛好都是 0.10。**兩份同值的
# 常數不是「一致」，是「還沒漂」** —— 改了其中一個，總表會說 ⚠ 而體檢表說 pass，
# 兩邊打架而且沒有人會發現。這個專案已經被「兩條路」咬過（十二道閘門）。
#
# 值不變（2026-08-16 全庫 317 份實測：中位 0.76%、95% 6.84%、最高 15.56%；
# 10% 會讓 6 份判 fail，約 1.9%）。鐵則第 5 條：門檻用量的不要用調的 ——
# 這次的量沒有提供「10% 是錯的」的理由，所以只搬家不改值。
GROUNDING_SUSPECT_RATIO = 0.10


def grounding_entry(
    stats: Mapping[str, int], threshold: float = GROUNDING_SUSPECT_RATIO,
) -> tuple[str, str, float | None]:
    """`extract-check` 的一份逐份統計 →（三態, 理由, 比率）。**純函式。**

    **住在這裡而不是某支腳本裡**，是因為它有三個呼叫端（進料的批次收尾、手動
    回填、測試），而帶連字號的腳本檔名 `import` 不動 —— 放在那裡只會逼每個
    呼叫端各自 `spec_from_file_location` 一份，然後慢慢長成三份判準。

    ⚠ **分母只算「字串比對有鑑別力」的那些**（接得回原文的 ＋ 可疑的）。
    - 符號型（來源 chunk 全是表格／公式）算進分母會稀釋比例，而一份幾乎全是
      公式的文件永遠不會超標 —— 那正是最需要被看的那種。
    - 來源 chunk 找不到的是**簿記問題不是幻覺**，兩邊都不算；算成可疑的話，
      索引重建期間的一次不一致會在表上看起來像模型在編東西。

    分母 0 ⇒ **沒得驗**，不是通過。
    """
    total = int(stats.get("total") or 0)
    ok = int(stats.get("ok") or 0)
    missing = int(stats.get("missing_chunk") or 0)
    symbolic = int(stats.get("symbolic") or 0)
    suspect = total - ok - missing - symbolic
    denom = ok + suspect

    if denom <= 0:
        if total == 0:
            return "unverifiable", "這份沒有抽出任何實體 —— 沒東西可驗", None
        return ("unverifiable",
                f"全部 {total} 個實體的來源都是表格／公式（符號型 {symbolic}、"
                f"來源不見 {missing}），字串比對沒有鑑別力", None)

    ratio = suspect / denom
    note = (f"{suspect}/{denom} 個字串比對有鑑別力的實體接不回原文"
            f"（總計 {total} 個：符號型 {symbolic} 驗不了、來源不見 {missing}）")
    return ("pass" if ratio <= threshold else "fail"), note, ratio


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def ledger_dir(root: Path, ws: str) -> Path:
    return DataPaths(root).ledger_dir


def inputs_dir(root: Path, ws: str) -> Path:
    return DataPaths(root).inputs_dir(ws)


def known_pdfs(root: Path, ws: str) -> list[str]:
    """這個 workspace 認得的 PDF 檔名。

    兩個地方都要看：解析前 PDF 在 `inputs/<workspace>/`，解析後 LightRAG 的
    archive_source 會把它搬進 `work/parsed/`。只看一邊的話，體檢表在流程中途會
    突然找不到文件。
    """
    d = inputs_dir(root, ws)
    names = {p.name for p in d.glob("*.pdf")} if d.is_dir() else set()
    par = DataPaths(root).parsed_dir
    if par.is_dir():
        names |= {p.name for p in par.glob("*.pdf")}
    return sorted(names)


def resolve_doc(root: Path, ws: str, key: str) -> str:
    """關鍵字 → 唯一的 PDF 檔名。對不到或對到多個都拒絕，不挑一個。"""
    names = known_pdfs(root, ws)
    if key in names:
        return key
    hits = [n for n in names if key.lower() in n.lower()]
    if len(hits) == 1:
        return hits[0]
    # 已經有體檢表但 PDF 不在（例如檔案被搬走）時，也讓它對得到。
    have = [p.name.removesuffix(".json") for p in
            sorted(ledger_dir(root, ws).glob("*.pdf.json"))] if ledger_dir(root, ws).is_dir() else []
    hits2 = [n for n in have if key.lower() in n.lower()]
    if not hits and len(hits2) == 1:
        return hits2[0]
    if not hits and not hits2:
        sys.exit(f"ledger: 在 {ws} 找不到符合 {key!r} 的 PDF（有 {len(names)} 份）")
    sys.exit(f"ledger: {key!r} 對到 {len(hits or hits2)} 份，請寫得更明確：\n  "
             + "\n  ".join(hits or hits2))


def sha256_of(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return "sha256:" + h.hexdigest()


def find_pdf(root: Path, ws: str, doc: str) -> Path | None:
    for c in (inputs_dir(root, ws) / doc, DataPaths(root).parsed_dir / doc):
        if c.is_file():
            return c
    return None


def load(root: Path, ws: str, doc: str) -> dict:
    p = ledger_dir(root, ws) / f"{doc}.json"
    if p.is_file():
        return json.loads(p.read_text())
    # 首次建檔才算 sha256 —— 之後每次 set 都重算的話，PDF 被換掉會被靜靜地
    # 覆蓋過去，而「來源換了」正是最該留下痕跡的事。
    pdf = find_pdf(root, ws, doc)
    return {"doc": doc,
            "pdf_sha256": sha256_of(pdf) if pdf else None,
            "gates": {}}


def save(root: Path, ws: str, rec: dict) -> Path:
    d = ledger_dir(root, ws)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{rec['doc']}.json"
    p.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n")
    return p


def record(
    root: Path,
    workspace: str,
    doc: str,
    gate: str,
    state: str,
    *,
    note: str | None = None,
    value: float | None = None,
    threshold: float | None = None,
) -> tuple[str, dict, dict | None]:
    """寫一格判定。回 `(解析後的文件名, 新的那一格, 原本那一格或 None)`。

    **判準只有這一支。** CLI（`cmd_set`）與 intake 的自動寫入都走它 ——
    直接呼叫 `load`／`save` 會繞過下面三道守衛，而繞過的症狀是「表上多出一個
    沒人認得的閘門」或「一堆沒有理由的驗不了」：兩者都不報錯，只會讓這張表
    慢慢失去意義。

    丟 `ValueError` 而不是 `sys.exit`：這一支現在有非 CLI 的呼叫端，
    直接結束行程會把 intake 的 worker 一起帶走。
    """
    if gate not in GATES:
        raise ValueError(f"未知的閘門 {gate!r}。允許的是：" + "、".join(GATES))
    if state not in STATES:
        raise ValueError(f"state 只能是 {'/'.join(STATES)}")
    # 「驗不了」沒有理由就跟「沒檢查」無法區分 —— 那是三態要防的事，直接拒收。
    if state == "unverifiable" and not (note or "").strip():
        raise ValueError("unverifiable 必須附理由（當時為什麼驗不了、證據是什麼）。"
                         "沒有理由的『驗不了』跟沒檢查在表上長得一樣。")

    # ⚠ **關鍵字解析留在 CLI 層。** `resolve_doc()` 是給人打關鍵字用的便利功能，
    # 而且找不到時直接 `sys.exit` —— 那在 intake 的 worker 裡會把整個行程帶走。
    # 程式化的呼叫端手上本來就有精確檔名，不需要猜。
    resolved = doc
    rec = load(root, workspace, resolved)
    entry: dict = {"state": state}
    if value is not None:
        entry["value"] = value
    if threshold is not None:
        entry["threshold"] = threshold
    if (note or "").strip():
        entry["note"] = (note or "").strip()
    entry["at"] = now()

    old = rec["gates"].get(gate)
    # **變了才留一層。** 這一格記的仍然是「現在的判定」，不是歷史日誌 ——
    # 但重抽之後同一格從 pass 變 fail 時，舊值直接被蓋掉的話，表上只看得到新值，
    # **沒有任何東西說它變壞了**。而重建就是一次三百多份的重抽。
    #
    # 只取 state／value／at 三個鍵，所以 `previous` 不可能巢狀下去 ——
    # 巢狀就是無界成長的歷史，而無界成長的欄位沒有人會讀。
    #
    # 沒變就不寫：每次重跑都塞一筆的話，這個欄位很快就跟沒有一樣。
    if old and old.get("state") != state:
        entry["previous"] = {k: old[k] for k in ("state", "value", "at") if k in old}
    rec["gates"][gate] = entry
    save(root, workspace, rec)
    return resolved, entry, old


def cmd_set(a: argparse.Namespace) -> int:
    try:
        doc, entry, old = record(a.root, a.workspace,
                                 resolve_doc(a.root, a.workspace, a.doc),
                                 a.gate, a.state,
                                 note=a.note, value=a.value, threshold=a.threshold)
    except ValueError as exc:
        sys.exit(f"ledger: {exc}")
    p = ledger_dir(a.root, a.workspace) / f"{doc}.json"
    was = f"（原本 {old['state']}）" if old else ""
    print(f"{doc}　{a.gate} = {a.state}{was}")
    if a.value is not None:
        print(f"  value={a.value}" + (f" threshold={a.threshold}" if a.threshold is not None else ""))
    if entry.get("note"):
        print(f"  note: {entry['note']}")
    print(f"  → {p}")
    return 0


def cmd_show(a: argparse.Namespace) -> int:
    d = ledger_dir(a.root, a.workspace)
    if a.doc:
        docs = [resolve_doc(a.root, a.workspace, a.doc)]
    else:
        docs = [p.name.removesuffix(".json") for p in sorted(d.glob("*.pdf.json"))] if d.is_dir() else []
    if not docs:
        print(f"{a.workspace} 還沒有任何體檢表（{d}）")
        return 0
    for doc in docs:
        p = d / f"{doc}.json"
        if not p.is_file():
            print(f"\n=== {doc} ===\n  （還沒有體檢表）")
            continue
        rec = json.loads(p.read_text())
        print(f"\n=== {rec['doc']} ===")
        print(f"  pdf_sha256: {rec.get('pdf_sha256')}")
        for g in GATES:
            e = rec["gates"].get(g)
            if not e:
                print(f"  {g:<19} -")
                continue
            bits = [e["state"]]
            if "value" in e:
                bits.append(f"value={e['value']}")
            if "threshold" in e:
                bits.append(f"threshold={e['threshold']}")
            print(f"  {g:<19} {'  '.join(bits)}　{e.get('at','')}")
            if e.get("note"):
                print(f"  {'':<19} └ {e['note']}")
    return 0


def ghost_docs(root: Path, ws: str) -> tuple[list[str], int]:
    """有體檢表、但文件已不在現役母體的份數，以及現役母體的大小。

    回傳 `(幽靈清單, 現役份數)`。現役份數為 0 時**不要**把所有體檢表當成幽靈 ——
    那是「母體讀不到」（例如在 coder 上跑，根本沒有 /data），不是「文件都不見了」。
    兩者的正確處置不同，混在一起就是把「不知道」講成「知道」。
    """
    d = ledger_dir(root, ws)
    have = {p.name.removesuffix(".json") for p in d.glob("*.pdf.json")} if d.is_dir() else set()
    current = set(known_pdfs(root, ws))
    if not current:
        return [], 0
    return sorted(have - current), len(current)


def ghost_verdicts(root: Path, ws: str, ghosts: list[str]) -> dict[str, int]:
    """幽靈體檢表實際帶著幾格**判定**，以及那些格子的三態分佈。

    只數有 state 的格子（未設定的不算）—— 未設定的格子在總表上不影響任何結論，
    會誤導人的是那些帶著 pass／fail 的。

    **這個數字必須量，不能寫死。** 2026-08-07 的原始訊息把「幽靈貢獻了總表上
    絕大部分的『通過』」寫成固定文字，於是不管情況怎麼變都照印同一句；
    2026-08-17 在 dker 實測是 1218 格通過裡幽靈只佔 2 格 —— 那句話錯了六百倍，
    而且因為它讀起來像結論，沒有人會想到要去數。**嚴重程度是量測值，不是文案。**
    """
    d = ledger_dir(root, ws)
    tally: dict[str, int] = {}
    for name in ghosts:
        p = d / f"{name}.json"
        if not p.is_file():
            continue
        gates = json.loads(p.read_text(encoding="utf-8")).get("gates", {})
        for gate in GATES:
            state = (gates.get(gate) or {}).get("state")
            if state is not None:
                tally[str(state)] = tally.get(str(state), 0) + 1
    return tally


def cmd_summary(a: argparse.Namespace) -> int:
    d = ledger_dir(a.root, a.workspace)
    files = sorted(d.glob("*.pdf.json")) if d.is_dir() else []

    # ── 停用閘門：母體脫節時拒絕輸出總表 ────────────────────────────────
    # 2026-08-07 實測到的問題：語料在 08-04 整批換掉，但舊的 20 張體檢表還在，
    # 於是總表印出「264 格：通過 151、fail 9」——**那 151 個通過與 9 個 fail
    # 全部屬於已經不在庫裡的文件**，而現役 18 份幾乎一格都沒驗（未設定 104）。
    #
    # 這比印出 0 更危險：漂亮的高通過數會讓人放心，而它量的是不存在的東西。
    # 所以這裡拒絕輸出，不做「順便標記一下」——標記過的假結論還是假結論，
    # 而人只會看最後那一行總計。
    ghosts, n_current = ghost_docs(a.root, a.workspace)
    if n_current == 0:
        print(f"{a.workspace}　**驗不了**：讀不到現役文件母體（{inputs_dir(a.root, a.workspace)} "
              f"與 {DataPaths(a.root).parsed_dir} 都沒有 PDF）。")
        print("  這不是「沒有文件」，是「這台機器看不到資料」——體檢表要在 dker 上跑。")
        return 3
    if ghosts:
        print(f"{a.workspace}　**已停用**：體檢表與現役母體脫節，拒絕輸出總表。")
        print(f"  現役文件 {n_current} 份，其中 {len(ghosts)} 張體檢表的文件已不存在：")
        for name in ghosts[:8]:
            print(f"    {name.removesuffix('.pdf')}")
        if len(ghosts) > 8:
            print(f"    …另外 {len(ghosts) - 8} 份")
        verdicts = ghost_verdicts(a.root, a.workspace, ghosts)
        n_cells = sum(verdicts.values())
        detail = "、".join(f"{s} {verdicts[s]}" for s in ("pass", "fail", "unverifiable")
                           if verdicts.get(s)) or "沒有任何判定"
        print(f"\n  這 {len(ghosts)} 張幽靈表帶著 {n_cells} 格判定（{detail}），"
              "它們會被算進總計那一行。")
        print("  為什麼拒絕而不是照印：總計是唯一一定會被看的一行，"
              "而它有一部分量的是已經不在庫裡的文件。")
        print("  ⚠ 那個格數是**量出來的**，不是估的——它決定這件事該多急，"
              "看數字判斷，別只看「已停用」三個字。")
        print("\n  處置：先歸檔幽靈體檢表，再回來跑這支。")
        print("    python3 scripts/archive-ledger.py            # 先 dry-run 看清單")
        print("    python3 scripts/archive-ledger.py --move      # 確認後才移動")
        print("  （歸檔會移到 records/ledger-archive-<日期>/，不刪除；")
        print("   版控副本在 repo 的 verdicts/records/ledger/）")
        return 3

    # 沒有體檢表的文件也要出現在總表上。少一列跟「那份全過」在畫面上長得一樣。
    docs = sorted({p.name.removesuffix(".json") for p in files}
                  | set(known_pdfs(a.root, a.workspace)))
    if not docs:
        print(f"{a.workspace} 還沒有任何文件或體檢表。")
        return 0

    recs = {}
    for doc in docs:
        p = d / f"{doc}.json"
        recs[doc] = json.loads(p.read_text()) if p.is_file() else {"gates": {}}

    tally = {"pass": 0, "fail": 0, "unverifiable": 0, None: 0}
    rows = []
    for doc in docs:
        g = recs[doc]["gates"]
        states = [(g.get(x) or {}).get("state") for x in GATES]
        for s in states:
            tally[s] += 1
        rows.append((doc, states))

    hidden_docs = 0
    print(f"{a.workspace}　體檢表總表　（{len(docs)} 份 × {len(GATES)} 閘門）")
    print(f"{'文件':<40} " + " ".join(f"{ABBR[g]:^7}" for g in GATES))
    print("-" * (41 + 8 * len(GATES)))
    for doc, states in rows:
        if a.problems and all(s == "pass" for s in states):
            hidden_docs += 1
            continue
        cells = " ".join(f"{MARK[s]:^7}" for s in states)
        print(f"{doc.removesuffix('.pdf')[:39]:<40} {cells}")
    print("-" * (41 + 8 * len(GATES)))
    print("  ".join(f"{ABBR[g]}={g}" for g in GATES[:4]))
    print("  ".join(f"{ABBR[g]}={g}" for g in GATES[4:]))
    print("-" * (41 + 8 * len(GATES)))
    total = len(docs) * len(GATES)
    # 鐵則 6：收合時必須報出「幾項通過未列出」，否則「沒印出來」跟「沒檢查」
    # 在畫面上長得一樣。未設定（-）也單獨報 —— 它既不是通過也不是失敗。
    print(f"共 {total} 格：通過 {tally['pass']}　fail {tally['fail']}　"
          f"驗不了 {tally['unverifiable']}　未設定 {tally[None]}")
    if a.problems:
        print(f"（--problems：{hidden_docs} 份全數通過未列出，"
              f"合計 {hidden_docs * len(GATES)} 格）")
    if tally["fail"]:
        bad = [f"{doc.removesuffix('.pdf')}：" +
               "、".join(g for g, s in zip(GATES, st, strict=False) if s == "fail")
               for doc, st in rows if "fail" in st]
        print("fail 的文件不得進下一段：\n  " + "\n  ".join(bad))
    return 1 if tally["fail"] else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="體檢表：每份文件一張三態表")
    add_workspace_arg(ap, load_env(REPO))
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("set", help="設定某份文件某個閘門的狀態")
    s.add_argument("doc", help="PDF 檔名或關鍵字")
    s.add_argument("gate", help="／".join(GATES))
    s.add_argument("state", help="／".join(STATES))
    s.add_argument("--value", type=float)
    s.add_argument("--threshold", type=float)
    s.add_argument("--note", default="")
    s.set_defaults(fn=cmd_set)

    s = sub.add_parser("show", help="印出單份或全部的體檢表")
    s.add_argument("doc", nargs="?")
    s.set_defaults(fn=cmd_show)

    s = sub.add_parser("summary", help="全部文件 × 全部閘門的三態總表")
    s.add_argument("--problems", action="store_true", help="只列有問題的文件")
    s.set_defaults(fn=cmd_summary)

    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
