"""只讀 PDF 的總頁數 —— 收件匣清單那一格。

收件匣每 3 秒被重畫一次，而清單上要顯示的只有「幾頁」。用 `read_toc` 也拿得到
頁數，但那會順便把整份目錄解出來 —— 一本幾百章的書因此多做一輪白工，而畫面
一個字都不會用到。

錯誤契約跟 `read_toc`／`pdf_has_toc` 同一套：檔案不在丟 `FileNotFoundError`，
壞檔／加密／不是 PDF 丟 `ValueError`。**不回 0 也不回 None** —— 呼叫端要能分辨
「這份是 0 頁」與「這份讀不出來」，而 0 兩種都像。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import fitz  # noqa: E402
import pytest  # noqa: E402
from chapters.pdf_splitter import read_page_count  # noqa: E402


def _write_pdf(path: Path, pages: int) -> None:
    doc = fitz.open()
    try:
        for page_number in range(1, pages + 1):
            page = doc.new_page()
            page.insert_text((72, 72), f"Page {page_number}")
        doc.save(path)
    finally:
        doc.close()


def test_the_page_count_comes_back(tmp_path: Path) -> None:
    """這條是整個改動的目的：一份 14 頁的 PDF 回 14。"""
    pdf = tmp_path / "paper.pdf"
    _write_pdf(pdf, 14)

    assert read_page_count(pdf) == 14


def test_a_missing_file_says_so(tmp_path: Path) -> None:
    """檔案不在是呼叫端寫錯了，不是這份 PDF 有問題 —— 兩種要分得開。"""
    with pytest.raises(FileNotFoundError):
        read_page_count(tmp_path / "nope.pdf")


def test_a_broken_pdf_raises_value_error(tmp_path: Path) -> None:
    """壞檔跟 `read_toc` 同一套處置，呼叫端只要接一種例外。

    收件匣裡真的會有壞檔（下載中斷、改名成 .pdf 的別種檔）。它必須是**這一列**
    的問題，不能讓整張清單掛掉 —— 那條界線由呼叫端守，這裡只負責說得清楚。
    """
    pdf = tmp_path / "truncated.pdf"
    pdf.write_bytes(b"%PDF-1.7 this is not a real pdf")

    with pytest.raises(ValueError):
        read_page_count(pdf)
