"""資料根目錄契約的 smoke test。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from pp.paths import ContainerPaths, DataPaths  # noqa: E402


def test_data_and_container_paths_cover_new_layout() -> None:
    root = Path("/data/lightrag")
    workspace = "acoustics_v2"
    document = "paper.pdf"
    paths = DataPaths(root)

    assert paths.inbox_dir == root / "inbox"
    assert paths.library_dir == root / "library"
    assert paths.intake_dir == root / "intake"
    assert paths.intake_jobs_dir == root / "intake" / "jobs"
    assert paths.intake_events_path == root / "intake" / "teaching-events.jsonl"
    assert paths.intake_job_dir("job") == root / "intake" / "jobs" / "job"
    assert paths.library_source_dir("source") == root / "library" / "source"
    assert paths.work_dir == root / "work"
    assert paths.parsed_dir == root / "work" / "parsed"
    assert paths.crops_dir == root / "work" / "crops"
    assert paths.equations_dir == root / "work" / "crops" / "_equations"
    assert paths.records_dir == root / "records"
    assert paths.ledger_dir == root / "records" / "ledger"
    assert paths.checks_dir == root / "checks"
    assert paths.inputs_root == root / "inputs"
    assert paths.rag_storage_dir == root / "rag_storage"
    assert paths.backup_stamp == root / ".backup-cold.stamp"
    assert paths.inputs_dir(workspace) == root / "inputs" / workspace
    assert paths.parsed_bundle_dir(document) == (
        root / "work" / "parsed" / f"{document}.mineru_raw"
    )
    assert paths.crop_document_dir(document) == root / "work" / "crops" / document

    container = ContainerPaths()
    assert container.inputs_dir(workspace) == Path("/app/data/inputs") / workspace
    assert container.parsed_dir(workspace) == (
        Path("/app/data/inputs") / workspace / "__parsed__"
    )
    assert container.parsed_bundle_dir(workspace, document) == (
        Path("/app/data/inputs") / workspace / "__parsed__" /
        f"{document}.mineru_raw"
    )


# ── 頁面尺寸容差（2026-08-08 加入）──────────────────────────────────────


def test_one_point_rounding_is_within_tolerance() -> None:
    """同一張 A4 的捨入差不得擋下整份文件。

    **實測案例**：2017 那篇 22 頁裡前 14 頁 594×842、後 8 頁 595×842，差 1 點。
    舊判準是「所有頁必須完全相同」，於是那篇從 2026-08-08 起天天紅燈，
    而 bbox 換算的實際誤差是 0.2%。
    """
    from pp.docctx import page_sizes_compatible
    assert page_sizes_compatible([(594.0, 842.0)] * 14 + [(595.0, 842.0)] * 8)


def test_a4_mixed_with_a3_is_still_refused() -> None:
    """真正要擋的是這個 —— 尺寸真的不同時 bbox 換算會錯，而且錯得很安靜。"""
    from pp.docctx import page_sizes_compatible
    assert not page_sizes_compatible([(595.0, 842.0), (842.0, 1191.0)])


def test_a4_mixed_with_letter_is_still_refused() -> None:
    """A4 與 Letter 差 17×50 點，遠超容差 —— 容差不能大到把這種放過去。"""
    from pp.docctx import page_sizes_compatible
    assert not page_sizes_compatible([(595.0, 842.0), (612.0, 792.0)])


def test_page_size_uses_the_majority_not_the_first_page() -> None:
    """回傳最常見的尺寸，不是第一頁的 —— 那讓換算誤差最小。

    ⚠ 2026-08-10 起 `page_size` 也會讀 `content_list.json`：判準改成
    「**要裁的那幾頁**與基準相容嗎」，所以它必須知道表格落在哪幾頁。
    真實的 bundle 一定兩個檔都有（`_run_parse` 會明確檢查），這裡補上。
    """
    import json
    import pathlib
    import tempfile

    from pp.docctx import DocContext
    with tempfile.TemporaryDirectory() as d:
        raw = pathlib.Path(d) / "x.mineru_raw"
        raw.mkdir()
        pages = ([{"page_idx": i, "page_size": [595, 842]} for i in range(3)]
                 + [{"page_idx": i + 3, "page_size": [594, 842]} for i in range(14)])
        (raw / "layout.json").write_text(json.dumps({"pdf_info": pages}), encoding="utf-8")
        (raw / "content_list.json").write_text("[]", encoding="utf-8")
        assert DocContext(raw).page_size == (594.0, 842.0), "14 頁那組才是多數"
