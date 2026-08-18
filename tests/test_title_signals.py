"""封面上的投稿日期、分類碼、出版商標章要自己丟；關鍵字要自己留。

PO 2026-08-18 在 19 份真資料上做完決定，規律非常清楚：

    標題區塊 32 項，他丟了 31 項（97%）—— 作者名、單位、投稿日期、PACS 碼
    唯一留下的 1 項是摘要

然後逐條裁：

    關鍵字（Index Terms／Keywords）  **留**（作者自己標的主題詞，正是內容圖譜要的）
    投稿日期（Received／Revised…）    **丟**
    分類碼（PACS numbers）            **丟**
    'Check for updates'               **丟** —— PO 原話：「我以為那是你寫的字」

⚠ 最後那句是最強的訊號：一個使用者把語料裡的字當成介面文字，那它就不是內容。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from pp.rules import title_block as tb  # noqa: E402


def _first(text: str) -> dict:
    return {"type": "text", "text": "A theoretical framework for room acoustics",
            "text_level": 1, "page_idx": 0}


def _row(text: str) -> dict:
    return {"type": "text", "text": text, "page_idx": 0}


def _plan(*texts: str) -> tb.TitlePlan:
    items = [_first("t"), *(_row(t) for t in texts),
             {"type": "text", "text": "1. Introduction", "text_level": 1, "page_idx": 0}]
    return tb.plan(items)


def test_submission_dates_are_dropped_by_the_rule() -> None:
    """投稿日期是期刊流程的紀錄，不回答任何聲學問題。PO 在 19 份裡丟過 12 次。"""
    p = _plan("(Received 9 May 1990; revised 15 August 1990; accepted 5 September 1990)")

    assert [m.signal for m in p.mutes] == ["submission"]
    assert p.held == []


def test_classification_codes_are_dropped_too() -> None:
    """PACS／MSC 是期刊的分類碼，不是內容。"""
    p = _plan("PACS numbers: 43.20.Mv")

    assert [m.signal for m in p.mutes] == ["classification"]


def test_publisher_furniture_on_the_cover_is_dropped() -> None:
    """`Check for updates` 那類是網頁按鈕，不是文獻內容。

    ⚠ 判準跟 `layout_noise` 共用同一支 —— **同一件事不要有兩個定義**，
    不然兩邊會慢慢漂開，而漂開不會有錯誤訊息。
    """
    p = _plan("Check for updates")

    assert [m.signal for m in p.mutes] == ["publisher"]


def test_keywords_are_kept_and_the_rule_says_why() -> None:
    """關鍵字**留著**（PO 裁）—— 作者自己標的主題詞，正是內容圖譜要連的東西。

    ⚠ 留著的方式是進 `held` 並標明判準，**不是憑空消失**：
    規則要報得出自己看到什麼（`plan --details` 的安全網）。
    要不要拿來問人是**確認清單**那一層的事。
    """
    p = _plan("Index Terms—FDTD, image-source, auralization, hybrid acoustic modeling.")

    assert p.mutes == []
    assert [h.why for h in p.held] == ["關鍵字"]


def test_the_other_keyword_spelling_counts_too() -> None:
    """`Keywords:` 與 `Index Terms—` 是同一件事的兩種寫法（不同期刊）。"""
    p = _plan("Keywords: sound intensity; acoustic vector sensor; calibration")

    assert [h.why for h in p.held] == ["關鍵字"]


def test_real_prose_is_not_swept_up_by_the_new_signals() -> None:
    """⚠ **正文不能被新規則掃到。** 誤消的代價是丟掉真內容而且不報錯。

    「received」「keywords」這些字在正文裡本來就會出現。
    """
    p = _plan("The microphone received the signal after it had travelled through the duct, "
              "and the keywords used in the search were selected accordingly.")

    assert p.mutes == []
