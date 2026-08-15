"""`verdicts/` 的守衛 —— 不可再生的人工判定只准變多，不准變少。

**為什麼需要這支**：進了版控但沒有任何程式讀它的資產，會被當成暫存檔刪掉。
本專案已有活生生的例子：`tests/symbol2-results.json` 進版控、全 repo grep 不到
任何消費者（坑清單 PIT-156）。**沒有消費者的資產等於沒有備份。**

**為什麼是「只准變多」**：人工裁定是人看著裁圖一格一格判出來的，只會累積。
數字變少只有兩種可能，都是事故：有東西被誤刪，或同步方向搞反了
（用舊的 repo 覆蓋掉 dker 上的新裁定）。

方向與 `tests/test_pits.py`（已於 2026-08-07 刪除）相反但同理：那邊守
「backlog 只准變短」，這邊守
「資產只准變多」。兩者都把基準寫進版控，所以變動一定出現在 `git diff` 裡。
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERDICTS = ROOT / "verdicts"

# 2026-08-07 從 dker 的 /data/lightrag 拉進版控時的實際檔數。
# 新增裁定之後把數字往上調，並在 commit 訊息說明多的是哪幾份。
BASELINE = {
    # 2026-08-16：173 → 180。dker 上有 5 個裁定檔（C 的 #380 #434 #453 #476 #524）
    # 從來沒進過版控，只活在一顆磁碟上；另外 #466／#525 兩張兩邊都有而內容不同，
    # 現役的 dker 版收成 `<idx>.html`、repo 舊版留成 `<idx>.alt-repo-20260802.html`
    # 等 PO 裁（`_curated()` 只讀 stem 全是數字的檔，帶後綴的那兩個不會被載入）。
    "verified": 180,      # work/crops/<doc>/verified/*.html|txt
    "ledger": 20,         # records/ledger/*.pdf.json
    "review_md": 5,       # records/review/*.md（各族群的定案）
    "review_bundle": 27,  # records/review/20260803-speedup-symbol3/
    "doc_review": 1,      # work/crops/<doc>/review.md
}


def _count(pattern_root: Path, glob: str) -> int:
    return sum(1 for p in pattern_root.glob(glob) if p.is_file())


def _actual() -> dict[str, int]:
    crops = VERDICTS / "work" / "crops"
    records = VERDICTS / "records"
    return {
        "verified": _count(crops, "*/verified/*"),
        "ledger": _count(records / "ledger", "*.pdf.json"),
        "review_md": _count(records / "review", "*.md"),
        "review_bundle": _count(records / "review" / "20260803-speedup-symbol3", "*"),
        "doc_review": _count(crops, "*/review.md"),
    }


def test_verdicts_dir_exists_and_is_not_empty() -> None:
    """目錄不見了要當場紅。

    空目錄會讓下面每一條「>= 0」都通過 —— 那是「乾淨的 0」那一族：
    看起來像通過，實際是母體不見了。
    """
    assert VERDICTS.is_dir(), "verdicts/ 不見了 —— 那是不可再生的人工裁定，不是暫存檔"
    assert (VERDICTS / "README.md").is_file(), \
        "verdicts/README.md 不見了 —— 資產要能自己說明為什麼存在、怎麼同步"
    assert any(VERDICTS.rglob("*")), "verdicts/ 是空的"


def test_verdicts_only_grow() -> None:
    """每一類都不得少於基準。人工裁定只會累積。"""
    actual = _actual()
    shrunk = {k: (BASELINE[k], v) for k, v in actual.items() if v < BASELINE[k]}
    assert not shrunk, (
        "不可再生的人工裁定變少了（基準 → 現在）：\n  "
        + "\n  ".join(f"{k}: {a} → {b}" for k, (a, b) in shrunk.items())
        + "\n這只有兩種可能，都是事故：有東西被誤刪，或同步方向搞反了"
          "（用舊的 repo 覆蓋掉 dker 上的新裁定）。"
          "\n人工裁定沒有第二份 —— 先查清楚哪一邊多，不要直接覆蓋。"
    )


def test_verified_files_are_not_empty() -> None:
    """裁定檔本身不得是空的。

    空的裁定檔比沒有裁定更糟：`_curated()` 會把它當成「這格已經判過了」，
    於是用一個空字串覆蓋掉 MinerU 的現值。
    """
    empties = [p.relative_to(VERDICTS).as_posix()
               for p in (VERDICTS / "work" / "crops").glob("*/verified/*")
               if p.is_file() and not p.read_text(encoding="utf-8").strip()]
    assert not empties, f"這些裁定檔是空的：{empties}"


def test_ledger_records_are_readable_json() -> None:
    """體檢表要讀得動 —— 它的 note 欄是 waiver 的原文，壞掉就查不回來。"""
    bad = []
    for p in (VERDICTS / "records" / "ledger").glob("*.pdf.json"):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            bad.append(f"{p.name}: {exc}")
            continue
        if "gates" not in rec:
            bad.append(f"{p.name}: 缺少 gates 欄")
    assert not bad, "體檢表壞了：\n  " + "\n  ".join(bad)
