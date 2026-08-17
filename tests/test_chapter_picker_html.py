"""勾選畫面的 HTML 產生。

**為什麼不放進 `intake.py`**：那支已經四千多行，而畫面是純函式、不需要起服務
就能測。放這裡讓「算得對不對」與「畫得對不對」都能在 coder 上驗完
（coder 沒有 LightRAG 的 `.env` 也沒有它的 docker，起不了審核台）。

畫面的形狀是 PO 2026-08-17 給的：先問切到哪一層，再跳勾選框、規則先幫你勾好、
只改勾錯的。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from chapters.picker_html import render_picker  # noqa: E402
from chapters.selection import build_selection, level_options  # noqa: E402
from chapters.split_plan import plan_pdf_split  # noqa: E402

BOOK_TOC = [
    (1, "Preface", 1),
    (1, "Chapter 1 Sound", 5),
    (2, "1.1 Waves", 6),
    (1, "Chapter 2 Rooms", 20),
    (1, "References", 40),
]
BOOK_PAGES = 50


def _page(level: int = 2) -> str:
    plans = plan_pdf_split(BOOK_TOC, BOOK_PAGES, max_level=level, chapter_prefix=True)
    return render_picker(
        doc="W7M3NDKV 2015 - Acoustics.pdf",
        options=level_options(BOOK_TOC, BOOK_PAGES),
        chosen_level=level,
        rows=build_selection(plans, key="W7M3NDKV", tail="2015 - Acoustics"),
    )


def test_every_row_is_on_the_page_including_the_unchecked_ones() -> None:
    """沒勾的列也要畫出來（藍桶第 2 條）。

    整列不畫的話，人分不出「規則看過決定不要」與「規則根本沒偵測到」——
    而這個畫面存在的意義就是讓人改規則勾錯的地方。看不到就改不了。
    """
    html = _page()

    for _, title, _ in BOOK_TOC:
        assert title in html, f"{title} 沒有出現在畫面上"


def test_rule_pre_checks_show_as_ticked_boxes() -> None:
    """規則勾好的那幾列，勾選框要是打勾的；沒勾的不能打勾。"""
    html = _page()

    boxes = dict(re.findall(r"data-title='([^']+)'[^>]*?(\schecked)?>", html))
    assert boxes.get("Chapter 1 Sound"), "正文要預先勾好"
    assert not boxes.get("Preface"), "前言不得預先勾好"
    assert not boxes.get("References"), "參考文獻不得預先勾好"


def test_level_choices_are_radio_buttons_with_counts() -> None:
    """第一步：選層次。每個選項要附「會切出幾個檔」，而且現在選的那個要是選中的。"""
    html = _page(level=2)

    assert html.count("type='radio'") == len(level_options(BOOK_TOC, BOOK_PAGES))
    assert "value='1'" in html and "value='2'" in html
    assert re.search(r"value='2'[^>]*checked", html), "現在選的層次要標成選中"


def test_titles_with_html_characters_do_not_break_the_page() -> None:
    """標題裡的 `&` `<` `>` `'` 必須跳脫。

    聲學論文的章名真的會有 `<` 與 `&`（例如 `Ka < 1` 與 `Absorption & Scattering`）。
    不跳脫的話輕則畫面壞掉，重則整個勾選框消失而使用者以為那幾章不存在。
    """
    nasty = [(1, "Ka < 1 & 'quoted' \"double\"", 1), (1, "Chapter 2", 10)]
    plans = plan_pdf_split(nasty, 20, max_level=1, chapter_prefix=True)
    html = render_picker(
        doc="X.pdf", options=level_options(nasty, 20), chosen_level=1,
        rows=build_selection(plans, key="K", tail="T"),
    )

    assert "Ka &lt; 1 &amp;" in html
    assert "Ka < 1 &" not in html, "原始的 < 與 & 不得直接落進 HTML"


def test_page_says_which_book_it_is() -> None:
    """畫面要講清楚現在勾的是哪一本，否則同時開兩本會勾錯。"""
    assert "W7M3NDKV 2015 - Acoustics.pdf" in _page()
