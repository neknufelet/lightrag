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
    assert paths.work_dir == root / "work"
    assert paths.parsed_dir == root / "work" / "parsed"
    assert paths.crops_dir == root / "work" / "crops"
    assert paths.equations_dir == root / "work" / "crops" / "_equations"
    assert paths.records_dir == root / "records"
    assert paths.ledger_dir == root / "records" / "ledger"
    assert paths.checks_dir == root / "checks"
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
