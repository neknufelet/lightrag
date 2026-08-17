"""審核台上的拆章勾選：畫得出來、確認之後存得下去。

`intake.py` 在這件事上只做**接線** —— 算在 `chapters.selection`、畫在
`chapters.picker_html`、存在 `chapters.split_record`，三者都是純函式或純 I/O，
已各自測過。這支測的是接線本身：找不找得到那本書、拒不拒絕不該碰的檔、
確認之後紀錄有沒有落在該落的地方。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import fitz  # noqa: E402
import pytest  # noqa: E402
from chapters.split_record import read_record  # noqa: E402
from intake import DataPaths, IntakeApp, IntakeError  # noqa: E402

DOC = "W7M3NDKV 2015 - Acoustics.pdf"


def _book(path: Path) -> None:
    """造一本有目錄的假書：前言、兩章（第一章底下一節）、參考文獻。"""
    doc = fitz.open()
    try:
        for n in range(1, 51):
            doc.new_page().insert_text((72, 72), f"Page {n}")
        doc.set_toc([
            [1, "Preface", 1],
            [1, "Chapter 1 Sound", 5],
            [2, "1.1 Waves", 6],
            [1, "Chapter 2 Rooms", 20],
            [1, "References", 40],
        ])
        doc.save(path)
    finally:
        doc.close()


def _app(tmp_path: Path) -> IntakeApp:
    data_root = tmp_path / "data"
    app = IntakeApp(DataPaths(data_root), "test", [], repo=tmp_path / "repo")
    app.paths.inbox_dir.mkdir(parents=True, exist_ok=True)
    _book(app.paths.inbox_dir / DOC)
    return app


def test_the_picker_draws_every_chapter_of_the_book_in_the_inbox(tmp_path: Path) -> None:
    """收件匣裡那本書的每一章都要畫出來，含規則不勾的前言與參考文獻。"""
    html = _app(tmp_path).chapter_picker(DOC)

    assert DOC in html
    for title in ("Preface", "Chapter 1 Sound", "1.1 Waves", "Chapter 2 Rooms", "References"):
        assert title in html


def test_a_file_outside_the_inbox_is_refused(tmp_path: Path) -> None:
    """只准勾收件匣裡的東西 —— 沿用 `delete_inbox_file` 同一條界線。

    不擋的話，`../` 就能讓畫面去讀部署機上任何一個 PDF。
    """
    app = _app(tmp_path)

    with pytest.raises(IntakeError):
        app.chapter_picker("../../etc/passwd")
    with pytest.raises(IntakeError):
        app.chapter_picker("沒有這本書.pdf")


def test_confirming_writes_the_record_where_the_design_says(tmp_path: Path) -> None:
    """確認之後，紀錄落在 repo 的 `verdicts/records/chapter-splits/`。

    落在 `/data` 的話它不會進版控，而人手改的勾選重跑不出來 —— 那正是
    PO 2026-08-17 裁「跟程式碼一起」的理由。
    """
    app = _app(tmp_path)

    path = app.confirm_chapter_split(DOC, level=2, selected=[2, 3], notes={})

    assert path == tmp_path / "repo" / "verdicts" / "records" / "chapter-splits" / f"{DOC}.json"
    assert path.is_file()


def test_the_record_keeps_what_the_person_changed(tmp_path: Path) -> None:
    """人改過的那幾列要標成 human 並留下理由；沒動的仍是 rule。

    分不出來的話，半年後沒人知道哪些是人判的 —— 而那才是不可再生的部分。
    """
    app = _app(tmp_path)

    # 規則本來勾 Chapter 1 / 1.1 Waves / Chapter 2（第 2、3、4 列）。
    # 人把 Chapter 2 取消勾選，並寫了理由。
    app.confirm_chapter_split(DOC, level=2, selected=[2, 3],
                              notes={4: "這章跟別本重複"})
    record = read_record(app.chapter_record_path(DOC))

    by_serial = {r.serial: r for r in record.rows}
    assert by_serial[4].selected is False
    assert by_serial[4].decided_by == "human"
    assert by_serial[4].note == "這章跟別本重複"
    assert by_serial[2].decided_by == "rule", "沒被人動過的列不得標成 human"


def test_the_record_remembers_which_pdf_it_was(tmp_path: Path) -> None:
    """紀錄要帶著那份 PDF 的指紋，之後才擋得住「書被換掉」。"""
    app = _app(tmp_path)
    app.confirm_chapter_split(DOC, level=2, selected=[2, 3], notes={})

    record = read_record(app.chapter_record_path(DOC))

    assert record.pdf_sha256.startswith("sha256:")
    assert record.doc == DOC
    assert record.chosen_level == 2
