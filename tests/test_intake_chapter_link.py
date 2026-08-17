"""收件匣那一列要有進得去勾選畫面的入口。

沒有這個入口的話，`/chapters` 那一頁只能靠手打網址進去 —— 而網址裡還要塞
書名（含空格與符號）。功能做了卻進不去，等於沒做。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from intake import _render_candidate_row  # noqa: E402


def _row(source: str, filename: str = "W7M3NDKV 2015 - Acoustics.pdf") -> str:
    return _render_candidate_row(
        {"candidate_id": "abc", "source": source, "filename": filename, "size": 1234})


def test_an_inbox_book_has_a_way_into_the_picker() -> None:
    """收件匣裡的檔案要有「切章」入口，而且網址要指到那一本。"""
    html = _row("inbox")

    assert "切章" in html
    assert "/chapters?doc=" in html


def test_the_filename_is_url_encoded_in_the_link() -> None:
    """書名有空格與 `&`，直接塞進網址會斷在第一個特殊字元。

    `W7M3NDKV 2015 - Acoustics.pdf` 的空格不編碼的話，瀏覽器只會送出
    `W7M3NDKV`，畫面就報「收件匣裡沒有這個檔案」而使用者不知道為什麼。
    """
    html = _row("inbox", "A&B 2015 - Sound.pdf")

    assert "A%26B%202015" in html
    assert "doc=A&B" not in html, "沒編碼的話 & 會被當成下一個查詢參數"


def test_other_sources_do_not_get_the_link() -> None:
    """不是收件匣的東西沒有這個入口 —— 勾選畫面只讀收件匣，沿用刪除同一條界線。

    給了入口卻點進去被擋，使用者只會看到一個沒頭沒尾的錯誤。
    """
    html = _row("zotero")

    assert "切章" not in html
    assert "/chapters?doc=" not in html
