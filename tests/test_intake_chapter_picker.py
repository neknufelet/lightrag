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


def test_confirming_writes_the_record_into_the_data_area(tmp_path: Path) -> None:
    """確認之後，紀錄落在資料區的 `records/chapter-splits/`。

    ⚠ **不是 repo 底下。** 這支服務跑在 dker，而 dker 的 repo 唯讀只 pull ——
    寫進去的檔會躺在那裡永遠上不了 GitHub（2026-08-17 實測，`git status`
    只看得到一個 `??`）。版控副本靠 `pull-verdicts.py` 拉回 coder 再提交。
    """
    app = _app(tmp_path)

    path = app.confirm_chapter_split(DOC, level=2, selected=[2, 3], notes={})

    assert path == tmp_path / "data" / "records" / "chapter-splits" / f"{DOC}.json"
    assert path.is_file()
    assert not (tmp_path / "repo" / "verdicts").exists(), "不得直接寫進 repo"


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


def test_running_the_split_puts_the_chapters_in_the_inbox(tmp_path: Path) -> None:
    """真的切：勾好的那幾章各自變成一個檔，落在收件匣等你送去解析。

    落在收件匣而不是別的地方，是因為收件匣就是這條生產線的入口 ——
    切出來的章跟其他文件走完全一樣的路，不另立一條。
    """
    app = _app(tmp_path)
    app.confirm_chapter_split(DOC, level=2, selected=[2, 3], notes={})

    made = app.run_chapter_split(DOC)

    names = sorted(p.name for p in made)
    assert names == ["W7M3NDKV_02 2015 - Acoustics_Chapter 1 Sound.pdf",
                     "W7M3NDKV_03 2015 - Acoustics_1.1 Waves.pdf"]
    assert all((app.paths.inbox_dir / n).is_file() for n in names)


def test_the_original_leaves_the_inbox_but_is_not_deleted(tmp_path: Path) -> None:
    """切完之後原書要離開收件匣，**但不刪掉**。

    留著的話它會跟著被送去解析 —— 一本 37 MB、幾百頁的書，MinerU 收不下
    （200 頁上限），而且內容會跟切出來的章重複進知識庫。
    刪掉則是另一個極端：切錯了就沒得重來，而重下載未必拿得到同一份。
    """
    app = _app(tmp_path)
    app.confirm_chapter_split(DOC, level=2, selected=[2], notes={})

    app.run_chapter_split(DOC)

    assert not (app.paths.inbox_dir / DOC).exists(), "原書要離開收件匣"
    kept = tmp_path / "data" / "records" / "split-originals" / DOC
    assert kept.is_file(), "但要留著，不能刪"


def test_a_swapped_pdf_stops_the_split_and_touches_nothing(tmp_path: Path) -> None:
    """PDF 換過了就不切（PO 2026-08-17 裁：停下來問人）。

    舊的頁碼可能指到完全不同的內容，照切會切出錯的章**而且不報錯**。
    """
    app = _app(tmp_path)
    app.confirm_chapter_split(DOC, level=2, selected=[2, 3], notes={})
    _book(app.paths.inbox_dir / DOC)          # 同名換一份內容（指紋就變了）

    with pytest.raises(IntakeError) as exc:
        app.run_chapter_split(DOC)

    assert "不一樣" in str(exc.value)
    assert (app.paths.inbox_dir / DOC).is_file(), "擋下時原書不得被搬走"
    assert not list((tmp_path / "data" / "records" / "split-originals").glob("*")) \
        if (tmp_path / "data" / "records" / "split-originals").exists() else True


def test_splitting_without_a_record_is_refused(tmp_path: Path) -> None:
    """沒有勾選紀錄就不切 —— 不猜「大概全部都要」。"""
    app = _app(tmp_path)

    with pytest.raises(IntakeError):
        app.run_chapter_split(DOC)


def test_the_record_remembers_which_pdf_it_was(tmp_path: Path) -> None:
    """紀錄要帶著那份 PDF 的指紋，之後才擋得住「書被換掉」。"""
    app = _app(tmp_path)
    app.confirm_chapter_split(DOC, level=2, selected=[2, 3], notes={})

    record = read_record(app.chapter_record_path(DOC))

    assert record.pdf_sha256.startswith("sha256:")
    assert record.doc == DOC
    assert record.chosen_level == 2
