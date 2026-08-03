"""prepare 的順序、失敗短路與 pass marker 測試。"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "postprocess.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("postprocess_prepare", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _args(workspace: str = "test", *, commit: bool = True) -> argparse.Namespace:
    return argparse.Namespace(workspace=workspace, commit=commit, no_tables=False, workers=1)


def _paths(module: ModuleType, tmp_path: Path) -> tuple[Path, Path]:
    module.DATA_ROOT = tmp_path / "data"
    inputs = module.DATA_ROOT / "test" / "inputs" / "test"
    parsed = inputs / "__parsed__"
    parsed.mkdir(parents=True)
    return inputs, parsed


def _raw(inputs: Path, parsed: Path, name: str, *, passed: bool = False,
         items: list[dict[str, object]] | None = None) -> Path:
    pdf = inputs / f"{name}.pdf"
    pdf.write_bytes(b"pdf fixture")
    raw = parsed / f"{pdf.name}.mineru_raw"
    raw.mkdir()
    (raw / "content_list.json").write_text(json.dumps(items or []), encoding="utf-8")
    manifest: dict[str, object] = {}
    if passed:
        manifest["_pp_pass"] = {"version": 1, "completed_at": "2026-08-04T00:00:00"}
    (raw / "_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return raw


def test_parse_failure_stops_before_apply_and_scan(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    module = _module()
    inputs, _ = _paths(module, tmp_path)
    (inputs / "new.pdf").write_bytes(b"pdf fixture")
    calls = {"apply": 0, "scan": 0}

    def fake_run(command: list[str], *, check: bool) -> subprocess.CompletedProcess[str]:
        assert check is False
        return subprocess.CompletedProcess(command, 7, "", "MinerU timeout")

    def fake_apply(*_args: object, **_kwargs: object) -> int:
        calls["apply"] += 1
        return 0

    def fake_api(*_args: object, **_kwargs: object) -> dict[str, str]:
        calls["scan"] += 1
        return {"status": "scheduled"}

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module, "cmd_apply", fake_apply)
    monkeypatch.setattr(module, "_api", fake_api)

    assert module.cmd_prepare(_args(), {}) == 7
    output = capsys.readouterr().out
    assert "MinerU timeout" in output
    assert "解析失敗" in output and "待解析 1 份" in output
    assert "未發出 scan" in output
    assert calls == {"apply": 0, "scan": 0}


def test_apply_failure_stops_before_scan(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    module = _module()
    inputs, parsed = _paths(module, tmp_path)
    raw = _raw(inputs, parsed, "ready", items=[{"_pp_repaired_at": "old"}])
    calls = {"scan": 0}

    def fake_apply(_args: argparse.Namespace, _env: dict[str, str], *,
                   bundles: list[Path]) -> int:
        assert bundles == [raw]
        return 2

    def fake_api(*_args: object, **_kwargs: object) -> dict[str, str]:
        calls["scan"] += 1
        return {"status": "scheduled"}

    monkeypatch.setattr(module, "cmd_apply", fake_apply)
    monkeypatch.setattr(module, "_api", fake_api)

    assert module.cmd_prepare(_args(), {}) == 2
    output = capsys.readouterr().out
    assert "修補失敗" in output
    assert "已解析未修補 1 份" in output and "未發出 scan" in output
    assert calls["scan"] == 0


def test_scan_busy_is_failure_and_reports_unindexed_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    module = _module()
    inputs, parsed = _paths(module, tmp_path)
    raw = _raw(inputs, parsed, "ready")

    def fake_apply(_args: argparse.Namespace, _env: dict[str, str], *,
                   bundles: list[Path]) -> int:
        assert bundles == [raw]
        manifest_path = raw / "_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["_pp_pass"] = {"version": 1, "completed_at": "2026-08-04T00:00:00"}
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return 0

    monkeypatch.setattr(module, "cmd_apply", fake_apply)
    monkeypatch.setattr(module, "_api",
                        lambda *_args, **_kwargs: {"data": {
                            "status": "scanning_skipped_pipeline_busy"}})

    assert module.cmd_prepare(_args(), {}) == 2
    output = capsys.readouterr().out
    assert "scanning_skipped_pipeline_busy" in output
    assert "沒有排程" in output and "重跑 prepare --commit" in output
    assert "已修補未索引 1 份" in output


def test_commit_scope_matches_unpassed_dry_run_inventory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    module = _module()
    inputs, parsed = _paths(module, tmp_path)
    ready = _raw(inputs, parsed, "ready")
    passed = _raw(inputs, parsed, "already-done", passed=True)
    captured: list[Path] = []

    def fake_apply(_args: argparse.Namespace, _env: dict[str, str], *,
                   bundles: list[Path]) -> int:
        captured.extend(bundles)
        return 0

    monkeypatch.setattr(module, "cmd_apply", fake_apply)
    monkeypatch.setattr(module, "_api", lambda *_args, **_kwargs: {"status": "scheduled"})

    assert module.cmd_prepare(_args(), {}) == 0
    assert captured == [ready]
    assert passed not in captured


def test_pass_marker_wins_over_item_change_traces(tmp_path: Path) -> None:
    module = _module()
    inputs, parsed = _paths(module, tmp_path)
    traced = _raw(inputs, parsed, "zero-change", items=[{"_pp_repaired_at": "old"}])
    marked = _raw(inputs, parsed, "marked", passed=True)

    pending, ready, passed = module._prepare_inventory("test")

    assert pending == []
    assert ready == [traced]
    assert passed == [marked]
