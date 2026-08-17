"""從 PDF 讀出目錄與總頁數 —— 勾選畫面的入口。

畫面需要兩樣東西才畫得出來：這本書的目錄（決定有幾層、有哪幾列）與總頁數
（決定最後一章切到哪）。這支是 fitz adapter 的職責 —— 開檔在這裡發生，
`selection` 與 `picker_html` 兩層維持純函式、不碰磁碟。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import fitz  # noqa: E402
import pytest  # noqa: E402
from chapters.pdf_splitter import read_toc  # noqa: E402


def _write_pdf(path: Path, pages: int, toc: list[list[int | str]]) -> None:
    doc = fitz.open()
    try:
        for page_number in range(1, pages + 1):
            page = doc.new_page()
            page.insert_text((72, 72), f"Page {page_number}")
        if toc:
            doc.set_toc(toc)
        doc.save(path)
    finally:
        doc.close()


def test_read_toc_returns_the_outline_and_the_page_count(tmp_path: Path) -> None:
    """目錄照原樣讀出來，總頁數一起回。

    兩個一起回是因為少了總頁數就算不出最後一章的結束頁 —— 分兩次開檔既慢又
    可能讀到不同的檔（中途被換掉）。
    """
    pdf = tmp_path / "book.pdf"
    _write_pdf(pdf, 30, [[1, "Chapter 1", 1], [2, "1.1 Waves", 3], [1, "Chapter 2", 20]])

    toc, total_pages = read_toc(pdf)

    assert toc == [(1, "Chapter 1", 1), (2, "1.1 Waves", 3), (1, "Chapter 2", 20)]
    assert total_pages == 30


def test_a_pdf_without_an_outline_reads_as_an_empty_toc(tmp_path: Path) -> None:
    """沒有目錄的 PDF 回空清單，**不是**丟例外、也不是硬編一個第 1 層。

    空清單會讓 `level_options` 回空的選項，畫面因此說「這份讀不到目錄」——
    那是誠實的。硬編一層等於宣稱知道書的結構，而我們不知道。
    """
    pdf = tmp_path / "flat.pdf"
    _write_pdf(pdf, 5, [])

    toc, total_pages = read_toc(pdf)

    assert toc == []
    assert total_pages == 5


def test_missing_file_is_refused_not_guessed(tmp_path: Path) -> None:
    """檔案不存在就明講，不要回空目錄假裝那本書沒有章節。"""
    with pytest.raises(FileNotFoundError):
        read_toc(tmp_path / "nope.pdf")
