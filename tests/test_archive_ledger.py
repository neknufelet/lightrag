"""REBUILD-9 舊 ledger 歸檔工具的 dry-run 與移動 smoke tests。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "archive-ledger.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("archive_ledger", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ledger_fixture(root: Path) -> tuple[Path, Path, Path]:
    ledger = root / "records" / "ledger"
    review = root / "records" / "review"
    ledger.mkdir(parents=True)
    review.mkdir(parents=True)
    old = ledger / "old-paper.pdf.json"
    current = ledger / "current-paper.pdf.json"
    old.write_text(json.dumps({"doc": "old-paper.pdf"}), encoding="utf-8")
    current.write_text(json.dumps({"doc": "current-paper.pdf"}), encoding="utf-8")
    review_file = review / "durable-rule.md"
    review_file.write_text("保留。\n", encoding="utf-8")
    return old, current, review_file


def _fake_index(module: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        module,
        "load_env",
        lambda _repo: {"WORKSPACE": "acoustics_v2"},
    )
    monkeypatch.setattr(
        module,
        "indexed_documents",
        lambda _env, _workspace: {"current-paper.pdf"},
    )


def test_archive_defaults_to_dry_run_and_does_not_touch_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    module = _module()
    old, current, review_file = _ledger_fixture(tmp_path)
    _fake_index(module, monkeypatch)

    assert module.main([
        "--workspace", "acoustics_v2", "--root", str(tmp_path), "--date", "20260804",
    ]) == 0

    output = capsys.readouterr().out
    archive = tmp_path / "records" / "ledger-archive-20260804"
    assert "dry-run" in output
    assert str(old) in output and str(current) not in output
    assert old.is_file() and current.is_file()
    assert review_file.read_text(encoding="utf-8") == "保留。\n"
    assert not archive.exists()


def test_archive_move_preserves_old_record_and_writes_readme(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    module = _module()
    old, current, review_file = _ledger_fixture(tmp_path)
    old_bytes = old.read_bytes()
    _fake_index(module, monkeypatch)

    assert module.main([
        "--workspace", "acoustics_v2", "--root", str(tmp_path), "--date", "20260804",
        "--move",
    ]) == 0

    archive = tmp_path / "records" / "ledger-archive-20260804"
    archived = archive / old.name
    readme = archive / "README.md"
    assert not old.exists()
    assert current.is_file()
    assert archived.read_bytes() == old_bytes
    assert "這批對應重建前的文件，已不在索引中，保留供追溯。" in readme.read_text(encoding="utf-8")
    assert review_file.read_text(encoding="utf-8") == "保留。\n"
    assert "已移動 1 份" in capsys.readouterr().out


def test_index_query_uses_workspace_and_rejects_bad_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout='["/data/current.pdf"]\n', stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    assert module.indexed_documents({}, "acoustics_v2") == {"current.pdf"}
    sql = calls[0][-1]
    assert "where workspace = 'acoustics_v2'" in sql
    assert "lightrag_doc_status" in sql
