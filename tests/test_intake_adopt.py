"""把「索引裡有、審核台卻不認」的文件收回簿記。

2026-08-30：`compat-check --json` 的 stdout 被 stderr 的 `#scope` 污染，整批 12 份
被判「輸出讀不出來」—— 而它們其實已經 processed 進庫了。判失敗觸發 rollback，
PO 按了重置，job 目錄被刪。於是 LightRAG 說 184 份、審核台只認 172 份。

根因修在 `intake.py` 的 `_run`（見 `test_batch_verify.py`）。這一支釘的是**補救**：
收回來的條件要嚴到不會把「其實沒進去」的東西洗白，鬆到救得了這 12 份。
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import pytest  # noqa: E402
from _scripts import load  # noqa: E402
from intake import Candidate  # noqa: E402

adopt = load("intake_adopt", "intake-adopt.py")


# ── 判準 ───────────────────────────────────────────────────────────────────

def test_a_document_the_index_calls_processed_is_adopted() -> None:
    verdict, _ = adopt.adopt_verdict("processed", has_bundle=True, source_matches=True)
    assert verdict is adopt.ADOPT


def test_a_document_the_index_never_heard_of_is_not_adopted() -> None:
    """**控制組。** 索引裡沒有就不是被誤殺的，是真的沒進去。

    沒有這一條的話，這支會把「解析過但從來沒索引成功」的文件標成已進知識庫 ——
    畫面說進去了、其實沒有，而那種錯誤沒有人會發現。
    """
    verdict, why = adopt.adopt_verdict(None, has_bundle=True, source_matches=True)
    assert verdict is adopt.SKIP
    assert "索引裡沒有" in why


def test_a_document_still_being_processed_is_not_adopted() -> None:
    """`pending`／`processing` 是「還沒定案」，不是「進去了」。"""
    verdict, _ = adopt.adopt_verdict("processing", has_bundle=True, source_matches=True)
    assert verdict is adopt.SKIP


def test_a_document_without_a_parse_bundle_is_not_adopted() -> None:
    """沒有解析成果就沒有 `source_content_hash`，也就無從證明收的是哪一份。"""
    verdict, _ = adopt.adopt_verdict("processed", has_bundle=False, source_matches=True)
    assert verdict is adopt.SKIP


def test_a_source_pdf_that_no_longer_matches_is_not_adopted() -> None:
    """**控制組。** 收件匣裡同名的檔案不一定是同一份。

    對不上 `source_content_hash` 就代表原檔被換過 —— 收回去等於把 A 的解析成果
    掛在 B 的 PDF 上，而後面每一支檢查都會以為它們是同一份。
    """
    verdict, why = adopt.adopt_verdict("processed", has_bundle=True, source_matches=False)
    assert verdict is adopt.SKIP
    assert "換過" in why


# ── 補出來的紀錄 ───────────────────────────────────────────────────────────

def _candidate(tmp_path: Path) -> Candidate:
    return Candidate(
        candidate_id="c1", source_root=tmp_path, source_path=tmp_path / "甲.pdf",
        source_name="inbox", source_key="inbox-abc", filename="甲.pdf",
        sha256="sha256:x", size=1, pages=1)


def test_the_adopted_job_lands_directly_in_indexed(tmp_path: Path) -> None:
    job = adopt._adopted_job(_candidate(tmp_path), "ws",
                             tmp_path / "lib/甲.pdf", tmp_path / "parsed/甲.pdf")
    assert job.status == "indexed"
    assert job.library_path and job.parsed_source_path
    assert job.candidate_id == "c1", "candidate_id 要沿用掃描算出來的，否則收件匣還會再提一次"


def test_the_adopted_job_does_not_invent_a_plan(tmp_path: Path) -> None:
    """**計畫救不回來就留空。** 重置把它刪了，而且沒有備份。

    捏一份出來會讓畫面顯示一組沒有人量過的頁數與項目數 —— 那正是體檢表三態
    要防的事。`_metrics(None)` 會顯示「未取得」，那才是實話。
    """
    job = adopt._adopted_job(_candidate(tmp_path), "ws",
                             tmp_path / "lib/甲.pdf", tmp_path / "parsed/甲.pdf")
    assert job.plan is None
    assert any("計畫" in line for line in job.details)


# ── 補檔案 ─────────────────────────────────────────────────────────────────

def _write(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return "sha256:" + hashlib.sha256(data).hexdigest()


def test_restoring_a_missing_pdf_verifies_the_hash_after_copying(tmp_path: Path) -> None:
    want = _write(tmp_path / "inbox/甲.pdf", b"PDF-A")
    destination = tmp_path / "parsed/甲.pdf"

    adopt._restore(tmp_path / "inbox/甲.pdf", destination, want)

    assert destination.read_bytes() == b"PDF-A"
    assert not list(destination.parent.glob(".*adopt-partial")), "暫存檔要清掉"


def test_restoring_never_overwrites_a_file_whose_content_differs(tmp_path: Path) -> None:
    """**控制組。** 目的地已經有東西而且內容不同時，停下來問人。

    直接覆蓋會把某份文件在這台的唯一副本蓋掉，而它可能正是別份 job 的來源。
    """
    want = _write(tmp_path / "inbox/甲.pdf", b"PDF-A")
    _write(tmp_path / "parsed/甲.pdf", b"PDF-B")

    with pytest.raises(RuntimeError, match="不覆蓋"):
        adopt._restore(tmp_path / "inbox/甲.pdf", tmp_path / "parsed/甲.pdf", want)

    assert (tmp_path / "parsed/甲.pdf").read_bytes() == b"PDF-B"


def test_restoring_an_identical_file_is_a_no_op(tmp_path: Path) -> None:
    """**控制組。** 已經對了就不要動它 —— 這支要能重跑而不製造副作用。"""
    want = _write(tmp_path / "inbox/甲.pdf", b"PDF-A")
    _write(tmp_path / "parsed/甲.pdf", b"PDF-A")

    adopt._restore(tmp_path / "inbox/甲.pdf", tmp_path / "parsed/甲.pdf", want)

    assert (tmp_path / "parsed/甲.pdf").read_bytes() == b"PDF-A"
