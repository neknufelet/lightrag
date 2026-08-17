"""拆章勾選紀錄的存檔與讀回。

格式與四條裁決在 `docs/chapter-selection-record-20260817.md`：

    規則之後改了，同一本書再切一次？  照舊的切，檔名不變
    紀錄放哪裡？                      跟程式碼一起（repo，進版控）
    書的檔案被換掉、頁碼對不上？      停下來問人，不照舊頁碼硬切
    改勾選要不要寫一句為什麼？        不強迫，可留空白
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import pytest  # noqa: E402
from chapters.selection import DECIDED_BY_HUMAN, build_selection  # noqa: E402
from chapters.split_plan import plan_pdf_split  # noqa: E402
from chapters.split_record import (  # noqa: E402
    PdfChangedError,
    read_record,
    require_same_pdf,
    write_record,
)

BOOK_TOC = [
    (1, "Preface", 1),
    (1, "Chapter 1 Sound", 5),
    (2, "1.1 Waves", 6),
    (1, "References", 40),
]
SHA = "sha256:" + "a" * 64


def _rows() -> list:
    return build_selection(
        plan_pdf_split(BOOK_TOC, 50, max_level=2, chapter_prefix=True),
        key="W7M3NDKV", tail="2015 - Acoustics",
    )


def _write(tmp_path: Path, rows: list) -> Path:
    return write_record(
        tmp_path, doc="W7M3NDKV 2015 - Acoustics.pdf", pdf_sha256=SHA,
        key="W7M3NDKV", chosen_level=2, rows=rows,
        at="2026-08-17T14:00:00+08:00", rules_commit="d9ed038",
    )


def test_round_trip_keeps_every_row_including_the_unchecked_ones(tmp_path: Path) -> None:
    """寫進去再讀回來，每一列都在、狀態一樣。

    沒勾的列必須活著回來（藍桶第 2 條）。整列消失的話，重來時那幾章會被當成
    「規則沒偵測到」而重新勾上 —— 你當初取消勾選的決定就被安靜地推翻了。
    """
    rows = _rows()
    rows[1].selected = False          # 人把 Chapter 1 取消勾選
    rows[1].decided_by = DECIDED_BY_HUMAN
    rows[1].note = "這章跟第 7 章重複"

    back = read_record(_write(tmp_path, rows))

    assert [r.title for r in back.rows] == [t for _, t, _ in BOOK_TOC]
    assert [r.selected for r in back.rows] == [False, False, True, False]
    assert [r.serial for r in back.rows] == [1, 2, 3, 4]


def test_who_decided_and_why_survive_the_round_trip(tmp_path: Path) -> None:
    """「這格是人改的」與那句理由要存得住。

    存不住的話，半年後沒人分得出「規則剛好也這樣勾」與「有人特地改成這樣」，
    而後者是不可再生的 —— 那正是這個檔案要進版控的理由。
    """
    rows = _rows()
    rows[1].selected = False
    rows[1].decided_by = DECIDED_BY_HUMAN
    rows[1].note = "這章跟第 7 章重複"

    back = read_record(_write(tmp_path, rows))

    assert back.rows[1].decided_by == DECIDED_BY_HUMAN
    assert back.rows[1].note == "這章跟第 7 章重複"
    assert back.rows[0].decided_by == "rule", "沒被人動過的列仍是規則決定的"


def test_an_empty_reason_is_allowed(tmp_path: Path) -> None:
    """理由不強迫填（PO 2026-08-17 裁）。留空白要能存能讀，不得擋下來。"""
    rows = _rows()
    rows[0].selected = True
    rows[0].decided_by = DECIDED_BY_HUMAN   # 人改了，但沒寫理由

    back = read_record(_write(tmp_path, rows))

    assert back.rows[0].decided_by == DECIDED_BY_HUMAN
    assert back.rows[0].note == ""


def test_a_swapped_pdf_is_refused_not_silently_recut(tmp_path: Path) -> None:
    """指紋對不上就拒絕（PO 2026-08-17 裁：停下來問人）。

    PDF 被換掉時舊的頁碼可能指到完全不同的內容。照舊頁碼硬切會切錯而且**不報錯**，
    要很久之後才發現 —— 所以這裡寧可吵人。
    """
    record = read_record(_write(tmp_path, _rows()))

    require_same_pdf(record, "sha256:" + "a" * 64)          # 一樣 → 放行

    with pytest.raises(PdfChangedError) as exc:
        require_same_pdf(record, "sha256:" + "b" * 64)
    assert "W7M3NDKV 2015 - Acoustics.pdf" in str(exc.value), "要講是哪一本對不上"


def test_the_file_explains_itself_in_plain_words(tmp_path: Path) -> None:
    """檔案裡要有一句人話寫來歷，沿用 `verdicts/eq-labels.json` 的 `_` 欄位慣例。

    半年後打開這個檔的人不會記得今天談了什麼；只有欄位沒有來歷的話，
    他無從判斷這份還算不算數。
    """
    payload = json.loads(_write(tmp_path, _rows()).read_text(encoding="utf-8"))

    assert payload["version"] == 1
    assert "2026-08-17T14:00:00+08:00" in payload["_"]
    assert payload["rules_commit"] == "d9ed038"
    assert payload["chosen_level"] == 2


def test_the_record_lands_next_to_the_other_human_verdicts(tmp_path: Path) -> None:
    """檔案落在 `verdicts/records/chapter-splits/`，一本書一個檔（PO 裁：跟程式碼一起）。"""
    path = _write(tmp_path, _rows())

    assert path.parent == tmp_path / "verdicts" / "records" / "chapter-splits"
    assert path.name == "W7M3NDKV 2015 - Acoustics.pdf.json"
