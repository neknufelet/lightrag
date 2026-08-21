#!/usr/bin/env python3
"""攤開後處理從一份文件裡**拿掉**了什麼，讓人逐項判讀「消對了沒有」。

**為什麼需要這支。** `pp.preflight` 在消音比例超標時會擋下並要求人工確認
（`pp/apply.py` 的 `_ratio_guard`），但它只給得出一個百分比 —— 而百分比本身
無法判斷「消掉的是頁首頁尾還是正文」。2026-08-21 之前，這個判讀是逐次手寫
一次性腳本做的，於是三份文件查過了、結論只留在對話與 `cairn/LOG.md` 的句子裡，
**下一個人沒有辦法重跑**（藍桶第 9 條：斷言要附得出可重現的驗證指令）。

⚠ **兩條路都要看，只看一條會少算。** 原文備份有兩個欄位：

    _pp_original_text         散文、頁首頁尾、標題頁那一類
    _pp_original_list_items   參考文獻清單（MinerU 把它放進 `list_items`，
                              `text` 本來就是空的）

2026-08-21 第一次量只看了前者，XVK63KEV 得到「拿掉 10.8%」，而體檢表記的是
32.4% —— 帳對不上。真正的差額是 43 條參考文獻，全部在 `list_items` 裡。
**帳對不上的時候不要調整結論去遷就數字，要先找出漏算的那條路。**

⚠ **改寫不是拿掉。** 有 `_pp_original_*` 但現值仍有內容的是 LaTeX 正規化或
人工裁定的文字修補（`verified_text`），那是換掉不是刪掉，不計入損失。

用法：
    ./scripts/muted-audit.py --doc ZX35VPDU            # 摘要
    ./scripts/muted-audit.py --doc ZX35VPDU --details  # 逐項印出被拿掉的原文
    ./scripts/muted-audit.py                           # 全 workspace 摘要
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mineru_common import load_env  # noqa: E402
from pp.paths import DEFAULT_DATA_ROOT, DataPaths  # noqa: E402

REPO = Path(__file__).resolve().parent.parent

#: 原文備份欄位 → 它備份的是哪個現值欄位。兩條都要走（見檔頭）。
BACKUP_FIELDS: dict[str, str] = {
    "_pp_original_text": "text",
    "_pp_original_list_items": "list_items",
}


def chars_of(value: object) -> int:
    """一個欄位的字元數。`list_items` 是字串陣列，`text` 是字串。"""
    if isinstance(value, str):
        return len(value)
    if isinstance(value, list):
        return sum(len(str(entry)) for entry in value)
    return 0


def audit_doc(raw_dir: Path) -> dict[str, object]:
    """清點一份文件被拿掉的內容。回摘要 ＋ 逐項明細。"""
    listing = raw_dir / "content_list.json"
    if not listing.is_file():
        return {"error": "缺少 content_list.json（解析未完成或失敗）"}

    items = json.loads(listing.read_text(encoding="utf-8"))
    removed: list[dict[str, object]] = []
    kinds: Counter[str] = Counter()
    gone_chars = 0
    kept_chars = 0
    n_list_entries = 0

    for index, item in enumerate(items):
        kept_chars += chars_of(item.get("text")) + chars_of(item.get("list_items"))
        for backup, live in BACKUP_FIELDS.items():
            if backup not in item:
                continue
            # 現值還有東西 ⇒ 這是改寫（LaTeX 正規化／文字修補），不是拿掉。
            if chars_of(item.get(live)):
                continue
            original = item[backup]
            gone = chars_of(original)
            gone_chars += gone
            kind = f"{item.get('type')}/{item.get('sub_type') or '-'}"
            kinds[kind] += 1
            if isinstance(original, list):
                n_list_entries += len(original)
            removed.append({
                "index": index, "page": item.get("page_idx"), "kind": kind,
                "chars": gone, "field": live,
                "entries": len(original) if isinstance(original, list) else 1,
                "text": original if isinstance(original, str) else "\n".join(
                    str(entry) for entry in original),
            })

    total = gone_chars + kept_chars
    return {
        "removed": removed,
        "kinds": dict(kinds),
        "gone_chars": gone_chars,
        "total_chars": total,
        "ratio": (gone_chars / total) if total else 0.0,
        "list_entries": n_list_entries,
        "items": len(items),
    }


def scan(root: Path, workspace: str, doc: str | None) -> list[tuple[str, dict[str, object]]]:
    parsed = DataPaths(root).parsed_dir
    if not parsed.is_dir():
        print(f"找不到解析目錄：{parsed}", file=sys.stderr)
        return []
    out: list[tuple[str, dict[str, object]]] = []
    for raw in sorted(parsed.glob("*.mineru_raw")):
        # `--doc` 只縮小範圍，不改變預設 —— 預設仍是掃全部（同 parse-check 的理由：
        # 你不會對「沒想到的那一份」指定關鍵字）。
        if doc and doc.lower() not in raw.name.lower():
            continue
        out.append((raw.name.removesuffix(".pdf.mineru_raw"), audit_doc(raw)))
    out.sort(key=lambda row: -float(row[1].get("ratio") or 0.0))
    return out


def report(rows: list[tuple[str, dict[str, object]]], details: bool) -> int:
    if not rows:
        print("沒有符合的文件")
        return 0
    print(f"{'文件':<46}{'拿掉%':>8}{'字元':>10}{'項':>6}{'文獻條':>8}")
    print("-" * 78)
    for name, r in rows:
        if r.get("error"):
            print(f"{name[:44]:<46}{'—':>8}  {r['error']}")
            continue
        print(f"{name[:44]:<46}{r['ratio']:>7.1%}{r['gone_chars']:>10,}"
              f"{len(r['removed']):>6}{r['list_entries']:>8}")
    print("-" * 78)

    if not details:
        return 0
    for name, r in rows:
        if r.get("error"):
            continue
        print(f"\n=== {name} ===")
        print(f"  型別分布：{r['kinds']}")
        for entry in r["removed"]:
            head = str(entry["text"]).replace("\n", " ⏎ ")[:100]
            tail = f"（{entry['entries']} 條）" if entry["entries"] > 1 else ""
            print(f"  #{entry['index']:<4} p{entry['page']:<3} {entry['kind']:<18}"
                  f"{entry['chars']:>6} 字{tail} {head!r}")
    return 0


def main() -> int:
    env = load_env(REPO)
    ap = argparse.ArgumentParser(description="攤開後處理拿掉了什麼，供人逐項判讀")
    workspace = os.environ.get("WORKSPACE") or env.get("WORKSPACE") or None
    ap.add_argument("--workspace", default=workspace, required=workspace is None)
    ap.add_argument("--root", type=Path, default=DEFAULT_DATA_ROOT)
    ap.add_argument("--doc", help="檔名關鍵字，只看符合的文件（預設全部）")
    ap.add_argument("--details", action="store_true", help="逐項印出被拿掉的原文")
    a = ap.parse_args()
    # 指定單一文件時就是在看那一份，細節一律印出來。
    return report(scan(a.root, a.workspace, a.doc), a.details or bool(a.doc))


if __name__ == "__main__":
    sys.exit(main())
