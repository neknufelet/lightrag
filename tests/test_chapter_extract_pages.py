"""真的動刀：把指定頁範圍各自存成一個 PDF。

這一層只做「按頁切」，**不決定切哪裡** —— 切哪裡是勾選紀錄說了算
（`docs/chapter-selection-record-20260817.md`：照舊的切、檔名不變）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import fitz  # noqa: E402
import pytest  # noqa: E402
from chapters.pdf_splitter import extract_pages  # noqa: E402


def _write_pdf(path: Path, pages: int) -> None:
    doc = fitz.open()
    try:
        for n in range(1, pages + 1):
            doc.new_page().insert_text((72, 72), f"PAGE {n}")
        doc.save(path)
    finally:
        doc.close()


def _text_of(path: Path) -> list[str]:
    doc = fitz.open(path)
    try:
        return [page.get_text().strip() for page in doc]
    finally:
        doc.close()


def test_each_cut_becomes_its_own_pdf_with_the_right_pages(tmp_path: Path) -> None:
    """每一段各自存成一個檔，內容剛好是那幾頁（含頭含尾）。"""
    src = tmp_path / "book.pdf"
    _write_pdf(src, 20)
    out = tmp_path / "out"

    written = extract_pages(src, out, [("a.pdf", 1, 3), ("b.pdf", 10, 11)])

    assert [p.name for p in written] == ["a.pdf", "b.pdf"]
    assert _text_of(out / "a.pdf") == ["PAGE 1", "PAGE 2", "PAGE 3"]
    assert _text_of(out / "b.pdf") == ["PAGE 10", "PAGE 11"]


def test_nothing_is_written_when_a_range_is_impossible(tmp_path: Path) -> None:
    """有一段的頁碼超出範圍 ⇒ **整批不寫**，丟例外。

    寫一半更糟：收件匣裡會多出幾個章、少了幾個章，而**沒有任何地方會說少了**。
    人看到檔案出現就會以為切完了。
    """
    src = tmp_path / "book.pdf"
    _write_pdf(src, 5)
    out = tmp_path / "out"

    with pytest.raises(ValueError) as exc:
        extract_pages(src, out, [("ok.pdf", 1, 2), ("bad.pdf", 4, 99)])

    assert "bad.pdf" in str(exc.value), "要講是哪一段有問題"
    assert not (out / "ok.pdf").exists(), "不得留下寫到一半的成果"


def test_an_existing_file_is_not_silently_overwritten(tmp_path: Path) -> None:
    """目的地已經有同名檔 ⇒ 拒絕，不覆蓋。

    覆蓋會讓「我剛剛切的那一份呢」變成無解的問題；而同名多半代表這本書已經切過，
    那是要人決定的事，不是這一層該猜的。
    """
    src = tmp_path / "book.pdf"
    _write_pdf(src, 5)
    out = tmp_path / "out"
    out.mkdir()
    (out / "a.pdf").write_bytes(b"%PDF-1.4 old")

    with pytest.raises(FileExistsError):
        extract_pages(src, out, [("a.pdf", 1, 2)])

    assert (out / "a.pdf").read_bytes() == b"%PDF-1.4 old", "原本那份不得被動到"


def test_an_empty_cut_list_writes_nothing(tmp_path: Path) -> None:
    """一段都沒有就什麼都不寫，也不建空目錄以外的東西 —— 不丟例外。

    「全部取消勾選」是使用者的合法選擇（例如這本書整本都不想要）。
    """
    src = tmp_path / "book.pdf"
    _write_pdf(src, 5)

    assert extract_pages(src, tmp_path / "out", []) == []
