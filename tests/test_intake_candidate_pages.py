"""收件匣每一列要顯示頁數 —— 判斷「這份要不要切章」靠的就是這個數字。

檔案大小回答不了這個問題：一份 9.7 MiB 的可能是 13 頁的彩圖論文，也可能是
400 頁的書。掃描時本來就已經逐檔 stat 過一次，順手把頁數帶上。

⚠ **一份壞掉的 PDF 不准讓整張清單消失。** 收件匣裡真的會有下載到一半的檔，
讀不出頁數是那**一列**的事 —— 那一列照樣列出來（藍桶第 2 條：不得無聲消失），
只是頁數那格說讀不出來。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import fitz  # noqa: E402
from intake import CandidateScanner, DataPaths, _render_candidate_row  # noqa: E402


def _write_pdf(path: Path, pages: int) -> None:
    doc = fitz.open()
    try:
        for page_number in range(1, pages + 1):
            page = doc.new_page()
            page.insert_text((72, 72), f"Page {page_number}")
        doc.save(path)
    finally:
        doc.close()


def _row(pages: object) -> str:
    return _render_candidate_row({
        "candidate_id": "abc",
        "source": "inbox",
        "filename": "W7M3NDKV 2015 - Acoustics.pdf",
        "size": 1234,
        "pages": pages,
    })


def test_the_row_shows_the_page_count() -> None:
    """這條是整個改動的目的。"""
    assert "14 頁" in _row(14)


def test_an_unreadable_pdf_still_gets_a_row() -> None:
    """讀不出頁數的那一列照樣在，只是那一格說讀不出來。

    整張清單因為一個壞檔而消失，使用者不會知道少了什麼 —— 而少掉的正是他
    最需要處理的那一份。
    """
    html = _row(None)

    assert "W7M3NDKV" in html, "那一列不見了"
    assert "讀不出頁數" in html
    assert "None" not in html, "不要把 None 印給使用者看"


def test_the_scanner_fills_in_the_page_count(tmp_path: Path) -> None:
    """掃描時真的去讀，不是畫面自己猜。"""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _write_pdf(inbox / "paper.pdf", 14)
    scanner = CandidateScanner(DataPaths(tmp_path / "data"), [inbox])

    candidates, _ = scanner.scan(set(), set())

    assert [c.filename for c in candidates] == ["paper.pdf"]
    assert candidates[0].pages == 14
    assert candidates[0].public()["pages"] == 14


def test_a_broken_pdf_is_still_a_candidate(tmp_path: Path) -> None:
    """壞檔的頁數是 None，但它**還在清單裡**。

    它必須看得見才刪得掉 —— 收件匣是唯一給刪除按鈕的地方。
    """
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "truncated.pdf").write_bytes(b"%PDF-1.7 this is not a real pdf")
    scanner = CandidateScanner(DataPaths(tmp_path / "data"), [inbox])

    candidates, _ = scanner.scan(set(), set())

    assert [c.filename for c in candidates] == ["truncated.pdf"]
    assert candidates[0].pages is None
