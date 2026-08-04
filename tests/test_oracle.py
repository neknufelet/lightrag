"""Oracle 的 docker exec 身分與參數順序測試。"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import pp.oracle as oracle_module  # noqa: E402


def test_run_uses_current_host_uid_gid_before_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_uid() -> int:
        return 1234

    def fake_gid() -> int:
        return 2345

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        captured["command"] = command
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr(oracle_module.os, "getuid", fake_uid)
    monkeypatch.setattr(oracle_module.os, "getgid", fake_gid)
    monkeypatch.setattr(oracle_module.subprocess, "run", fake_run)

    oracle = oracle_module.Oracle(container="lightrag-test")

    assert oracle._run(["python", "-c", "print(1)"]) == "ok\n"
    assert captured["command"] == [
        "docker", "exec", "-u", "1234:2345", "lightrag-test",
        "python", "-c", "print(1)",
    ]


def test_run_allows_explicit_user_override(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []

    def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        captured.extend(command)
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr(oracle_module.subprocess, "run", fake_run)

    oracle_module.Oracle(container="lightrag-test", user="0:0")._run(["true"])

    assert captured[:5] == ["docker", "exec", "-u", "0:0", "lightrag-test"]
