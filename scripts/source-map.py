#!/usr/bin/env python3
r"""來源登記檔：哪幾份文件其實是同一個來源。

## 這支在解什麼問題

`eq-dup.py` 找「同一條公式在不同文獻裡係數不一致」，而它的價值完全建立在
**「跨來源」才算數**上 —— 同一本書的 §6.4 與 §10.2 重複一條公式，不算
「兩篇獨立文獻都這樣寫」。

原本 `eq-dup` 用兩條正規表達式**從檔名推論**來源，2026-08-13 逐份核過，五類全錯：

```
一本學位論文的 9 章裂成 4 組     檔名多了人類註記（_Conclusions／_Control of Room Modes）
一本學位論文裂成 2 組            檔名差一個空格（`2012 -Combined` / `2012 - Combined`）
一本手冊的 18 章當成 18 篇       單字母章號看不出是同一本
兩本不同的書併成 1 組            它們**共用同一段編號前綴**
四份附件與正文各自成組           supplementary 的檔名跟正文對不上
```

前四類是**假報方向** —— 把同一本書當成兩篇獨立文獻，於是「兩篇都這樣寫」是假的，
而人會去查一個不存在的分歧。

⚠⚠ **這支不是分類器，是一次性的提案器。** 它產出的是候選，人核過之後結果凍結成
資料（`verdicts/source-map.json`）。**跑完就不再跑** —— 之後的權威是那份資料，
不是這裡的規則。把它當成每次都跑的分類器，就是把剛丟掉的東西撿回來。

## 為什麼鍵是檔名而不是 sha256

雜湊當鍵在**重建**時會整份失聯：重新下載 PDF，檔名留著、雜湊變了，於是每一份都
查不到、報告變空而且沒有人會發現。所以檔名當鍵、**雜湊當守衛** —— 對不上就把那份
降成 unknown 並報出來（「登記在、但檔案換了」），叫人重新確認一次。
⚠ 這跟被丟掉的東西不一樣：丟掉的是「從檔名**推論**分組」，這裡是「用檔名當**索引**」。

⚠ **雜湊不自己算。** 體檢表（`records/ledger/*.pdf.json`）的 `pdf_sha256` 已經有
擁有者了，這裡讀它。本專案的通則：有權威來源時不得自己重算。

用法：
    source-map.py propose                 # 產候選並印審查表（不寫檔）
    source-map.py propose --out FILE      # 候選寫進 FILE，人核完再改名進 verdicts/
    source-map.py check                   # 母體對帳：登記 vs 體檢表 vs 解析成果
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mineru_common import load_env  # noqa: E402
from pp.paths import DEFAULT_DATA_ROOT, DataPaths  # noqa: E402
from pp.sources import DEFAULT_MAP_PATH, SourceMap, ledger_hashes  # noqa: E402

REPO = Path(__file__).resolve().parent.parent

# ── 一次性提案規則。**跑完就作廢，不要拿去當執行期的分類器。** ────────────────

# 兩本書共用 `0xxxx_` 這段編號。實測（229 份有公式的母體、88 份 0 前綴）：
# 前三位當流水號 idx，書 A 的章號 == idx-9、書 B 的章號 == idx-6，
# **兩者皆合 0 份、皆不合 0 份** —— 零歧義，所以這 88 份可以機械分。
_NUMBERED = re.compile(r"^0(\d{4})_(\d+)")
_OFFSETS = {9: "0xxxx-A", 6: "0xxxx-B"}

_CHAPTER = re.compile(r"^(.*?)_CH\d", re.I)
_HANDBOOK = re.compile(r"^([A-R]) [A-Z]")          # `C Equivalent Networks`
_SUPPLEMENT = re.compile(r"supplement|MOESM", re.I)


def _squash(s: str) -> str:
    """空白全拿掉、大小寫抹平 —— `2012 -Combined` 與 `2012 - Combined` 要變成同一串。"""
    return re.sub(r"\s+", "", s).casefold()


def _numbered_source(doc: str) -> str | None:
    """`0xxxx_` 那兩本：用章號差認人。對不上任何一本就回 None（交給人）。"""
    m = _NUMBERED.match(doc)
    if not m:
        return None
    idx, chapter = int(m.group(1)) // 100, int(m.group(2))
    hit = [name for off, name in _OFFSETS.items() if idx - off == chapter]
    return f"book:{hit[0]}" if len(hit) == 1 else None


def _chapter_clusters(docs: list[str]) -> dict[str, str]:
    """`_CH\\d` 的切片按「壓平後的前綴」聚類，短的前綴吸收長的。

    這樣 `…room-modes` 會吸收 `…room-modes_Conclusions`（人類註記），
    而空白差異在 `_squash` 就消掉了。
    """
    pres: dict[str, str] = {}
    for d in docs:
        if m := _CHAPTER.match(d):
            pres[d] = _squash(m.group(1))
    roots = sorted(set(pres.values()), key=len)
    out: dict[str, str] = {}
    for doc, pre in pres.items():
        root = next((r for r in roots if pre.startswith(r)), pre)
        out[doc] = f"book:{root[:60]}"
    return out


def propose(docs: list[str]) -> dict[str, tuple[str | None, str]]:
    """每份文件 →（來源 id 或 None，判斷理由）。**None 就是 unknown，不猜。**"""
    clusters = _chapter_clusters(docs)
    out: dict[str, tuple[str | None, str]] = {}
    for doc in docs:
        if src := _numbered_source(doc):
            out[doc] = (src, "章號差（idx-9 / idx-6，實測零歧義）")
        elif doc in clusters:
            out[doc] = (clusters[doc], "_CH 切片，壓平前綴聚類")
        elif _HANDBOOK.match(doc):
            out[doc] = ("book:a-r-handbook", "單字母章號 A–R，**待人核是不是同一本**")
        elif _SUPPLEMENT.search(doc):
            out[doc] = (None, "附件：正文是哪一篇要人核（檔名對不上）")
        else:
            out[doc] = (f"doc:{doc}", "沒有切片跡象，自己是一個來源")
    return out


def _corpus(root: Path) -> list[str]:
    parsed = DataPaths(root).parsed_dir
    if not parsed.is_dir():
        sys.exit(f"找不到 {parsed}")
    return sorted(p.name.removesuffix(".pdf.mineru_raw") for p in parsed.glob("*.mineru_raw"))


def _candidate(docs: list[str], hashes: dict[str, str]) -> dict:
    guesses = propose(docs)
    sources: dict[str, dict] = {}
    documents: dict[str, dict] = {}
    for doc in docs:
        sid, why = guesses[doc]
        documents[doc] = {"source": sid, "pdf_sha256": hashes.get(doc), "by": "propose", "note": why}
        if sid:
            sources.setdefault(sid, {"label": "", "evidence": "", "same_work_as": []})
    return {"version": 1,
            "_": "候選，未經人核。核完把 by 改成 human 並填 label／evidence。",
            "sources": sources, "documents": documents}


def cmd_propose(root: Path, out: Path | None) -> int:
    docs = _corpus(root)
    hashes = ledger_hashes(root)
    cand = _candidate(docs, hashes)
    by_src: dict[str | None, list[str]] = defaultdict(list)
    for doc, entry in cand["documents"].items():
        by_src[entry["source"]].append(doc)

    multi = {s: d for s, d in by_src.items() if s and len(d) > 1}
    singles = {s: d for s, d in by_src.items() if s and len(d) == 1}
    print(f"=== 來源登記候選：{len(docs)} 份 → {len(by_src)} 組 ===")
    print(f"體檢表查得到雜湊的 {sum(1 for d in docs if d in hashes)} 份"
          f"（查不到的登記為 null，對帳時會被降成 unknown）\n")
    print(f"⚠ 這是**候選**。下面 {len(multi)} 組是機器合併的，每一組都要人核；"
          f"{len(singles)} 份自成一組（風險低）；"
          f"{len(by_src.get(None, []))} 份判不出來，留 unknown 給人填。\n")
    for sid, members in sorted(multi.items(), key=lambda kv: -len(kv[1])):
        print(f"── {sid}　{len(members)} 份　［{cand['documents'][members[0]]['note']}］")
        for d in sorted(members)[:6]:
            print(f"     {d[:76]}")
        if len(members) > 6:
            print(f"     …其餘 {len(members) - 6} 份")
        print()
    if unknown := by_src.get(None, []):
        print(f"── unknown（{len(unknown)} 份，要人填來源）")
        for d in sorted(unknown):
            print(f"     {d[:76]}")
        print()
    print("⚠ 機器看不出來、一定要人判的還有一類：**學位論文的某一章其實就是庫裡的某篇"
          "期刊論文**。那要在 sources 的 same_work_as 裡宣告，這支不會提案。")
    if out:
        out.write_text(json.dumps(cand, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"\n候選已寫到 {out} —— **人核過再放進 verdicts/。**")
    return 0


def cmd_check(root: Path, path: Path) -> int:
    smap = SourceMap.load(path)
    rec = smap.reconcile(_corpus(root), ledger_hashes(root))
    print(f"=== 來源登記對帳：{path} ===")
    print(("**登記檔不存在 —— 全部 unknown，不是全部通過。**\n" if not path.is_file() else "")
          + rec.line())
    for title, items in (("檔案換過（登記的雜湊對不上體檢表）", rec.hash_changed),
                         ("未登記", rec.unregistered),
                         ("體檢表查不到雜湊", rec.no_ledger),
                         ("登記了但語料裡沒有", rec.stale)):
        if items:
            print(f"\n── {title}：{len(items)} 份")
            for d in items[:10]:
                print(f"     {d[:76]}")
            if len(items) > 10:
                print(f"     …其餘 {len(items) - 10} 份")
    return 0 if rec.usable == rec.corpus else 2


def main() -> int:
    env = load_env(REPO)
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path,
                    default=Path(env.get("DATA_ROOT", str(DEFAULT_DATA_ROOT))))
    ap.add_argument("--map", type=Path, default=DEFAULT_MAP_PATH)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("propose", help="產候選（一次性，跑完就作廢）")
    p.add_argument("--out", type=Path)
    sub.add_parser("check", help="母體對帳")
    a = ap.parse_args()
    return cmd_propose(a.root, a.out) if a.cmd == "propose" else cmd_check(a.root, a.map)


if __name__ == "__main__":
    sys.exit(main())
