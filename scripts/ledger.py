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


def cmd_set(a: argparse.Namespace) -> int:
    if a.gate not in GATES:
        sys.exit(f"ledger: 未知的閘門 {a.gate!r}。允許的是：\n  " + "\n  ".join(GATES))
    if a.state not in STATES:
        sys.exit(f"ledger: state 只能是 {'/'.join(STATES)}")
    # 「驗不了」沒有理由就跟「沒檢查」無法區分 —— 那是三態要防的事，直接拒收。
    if a.state == "unverifiable" and not (a.note or "").strip():
        sys.exit("ledger: unverifiable 必須附 --note（當時為什麼驗不了、證據是什麼）。"
                 "沒有理由的『驗不了』跟沒檢查在表上長得一樣。")

    doc = resolve_doc(a.root, a.workspace, a.doc)
    rec = load(a.root, a.workspace, doc)
    entry: dict = {"state": a.state}
    if a.value is not None:
        entry["value"] = a.value
    if a.threshold is not None:
        entry["threshold"] = a.threshold
    if (a.note or "").strip():
        entry["note"] = a.note.strip()
    entry["at"] = now()

    old = rec["gates"].get(a.gate)
    rec["gates"][a.gate] = entry
    p = save(a.root, a.workspace, rec)
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
        print("\n  為什麼拒絕而不是照印：那些幽靈文件貢獻了總表上絕大部分的『通過』，")
        print("  於是畫面顯示一個漂亮的高通過數，而現役文件其實幾乎一格都沒驗。")
        print("  比印出 0 更難察覺——0 會讓人懷疑，高通過數不會。")
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
