"""`docs/NEXT.md` 的完成項不得堆積。

**為什麼需要這支**：BASELINE 的「done 項紀律」寫著完成的剩項要刪整行，累積之後
要掃進 archive——但沒有任何東西會發現沒做。上游自己記的血淚是 2026-06-12，
NEXT 漲到 **37 done vs 8 待辦**。

**判準直接用 BASELINE 的原句，不自己發明**：

> done 指標行一累積（里程碑收尾、或 **done 行數 ≳ 待辦行數**）就收成
> 「✅ 全收線 → checkpoint」一句、或掃進對應 checkpoint/archive。

比例判準的好處是**自動縮放**：不管專案節奏是一天 3 個 commit 還是 50 個，
它都在同一個時機響——所有事做完時 done 必然超過待辦，那正是該掃的那一刻。
用「N 天前完成的就掃走」不行，日期跟工作節奏無關。

與 `standards-check` A02（NEXT.md ≤ 80 行）分工：A02 抓總量爆掉，這支抓比例
失衡。兩個都會在「該掃了」的時候響，但抓的是不同的失衡方式。

**掃到哪裡**：`cairn/LOG.md`。它本來就是時間軸，而且有 `test_log_freshness.py`
盯著不能落後。不另開封存檔——那會是第三個地方（見 `docs/knowledge-routing.md`）。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NEXT = ROOT / "docs" / "NEXT.md"

# BASELINE 1.4.0 的統一 legend。⚠️ 帶 variation selector，用字元類會漏。
DONE_MARKS = ("✅",)
OPEN_MARKS = ("⬜", "🔵", "⏸", "⚠️")

# 只算清單項目。狀態總表是 `|` 開頭、章節標題是 `#` 開頭、legend 說明行不是
# `- ` 開頭 —— 三者都含這些符號，不排除的話這支會把自己的說明文字算進去。
_ITEM = re.compile(r"^- (✅|⬜|🔵|⏸|⚠️)", re.MULTILINE)

# 舊格式。混用會讓上面的計數漏掉一半，而漏掉的那半不會有任何訊號。
_LEGACY_CHECKBOX = re.compile(r"^- \[[ xX]\]", re.MULTILINE)


def _marks() -> list[str]:
    return _ITEM.findall(NEXT.read_text(encoding="utf-8"))


def test_next_exists() -> None:
    """NEXT.md 要在——它是「接下來做什麼」的唯一 SSOT。"""
    assert NEXT.is_file(), f"{NEXT.relative_to(ROOT)} 不見了"


def test_no_legacy_checkbox_format() -> None:
    """不得混用 `- [ ]` 舊格式。

    混用的後果不是難看，是**這支檢查會靜靜地少算一半**——而少算的那半
    不會有任何訊號。屬於「乾淨的 0 要先當成量錯」那一族（鐵則第 7 條）。
    """
    legacy = _LEGACY_CHECKBOX.findall(NEXT.read_text(encoding="utf-8"))
    assert not legacy, (
        f"docs/NEXT.md 有 {len(legacy)} 行還在用 `- [ ]` 舊格式。"
        f"改用 BASELINE 1.4.0 的 legend：{' '.join(OPEN_MARKS)} / {DONE_MARKS[0]}。"
        "混用會讓完成／待辦的計數少算一半，而且不會有訊號。")


def test_done_items_do_not_outnumber_open_ones() -> None:
    """完成行數 ≥ 待辦行數 ⇒ 該掃了。"""
    marks = _marks()
    if not marks:
        pytest.skip("docs/NEXT.md 沒有任何狀態標記項目 ⇒ 沒東西可比，不當成通過")

    done = sum(1 for m in marks if m in DONE_MARKS)
    open_ = len(marks) - done
    if done == 0 or done < open_:
        return

    pytest.fail(
        f"docs/NEXT.md 有 {done} 個完成項、{open_} 個待辦項——完成的追上待辦了。\n"
        "BASELINE done 項紀律：完成的剩項刪整行，摘要收成一句寫進 cairn/LOG.md。\n"
        "證據天生在 git，不必留在 NEXT.md 裡當 log。")
