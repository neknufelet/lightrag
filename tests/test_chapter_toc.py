"""PDF 假目錄（退化 TOC）辨識測試。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import fitz
from chapters.pdf_splitter import pdf_has_toc, preview_pdf_split
from chapters.split_plan import is_degenerate_pdf_toc


def _write_pdf(path: Path, pages: int, toc: list[list[int | str]]) -> None:
    doc = fitz.open()
    try:
        for page_number in range(1, pages + 1):
            page = doc.new_page()
            page.insert_text((72, 72), f"Page {page_number}")
        doc.set_toc(toc)
        doc.save(path)
    finally:
        doc.close()


def test_dense_flat_toc_is_degenerate() -> None:
    toc = [(1, str(page), page) for page in range(1, 431)]
    assert is_degenerate_pdf_toc(toc, total_pages=448)


def test_dense_flat_text_titles_are_still_degenerate() -> None:
    toc = [(1, f"Page marker {page}", page) for page in range(1, 91)]
    assert is_degenerate_pdf_toc(toc, total_pages=100)


def test_real_hierarchical_toc_is_not_degenerate() -> None:
    toc = [
        (1, "第一章 基礎", 1),
        (2, "1.1 聲音", 5),
        (2, "1.2 頻率", 12),
        (1, "第二章 實務", 20),
    ]
    assert not is_degenerate_pdf_toc(toc, total_pages=40)


def test_short_numeric_toc_is_not_overclassified() -> None:
    toc = [(1, str(page), page) for page in range(1, 11)]
    assert not is_degenerate_pdf_toc(toc, total_pages=10)


def test_pdf_probe_treats_degenerate_toc_as_no_toc(tmp_path: Path) -> None:
    pdf = tmp_path / "degenerate.pdf"
    _write_pdf(pdf, 24, [[1, str(page), page] for page in range(1, 25)])

    assert not pdf_has_toc(pdf)


def test_degenerate_toc_uses_fixed_page_strategy(tmp_path: Path) -> None:
    pdf = tmp_path / "degenerate.pdf"
    _write_pdf(pdf, 24, [[1, str(page), page] for page in range(1, 25)])

    records = preview_pdf_split(
        pdf,
        max_pages=12,
        no_toc_strategy="pages",
    )

    assert len(records) == 2
    assert [record.title for record in records] == [
        "第 1 段（頁 1-12）",
        "第 2 段（頁 13-24）",
    ]
