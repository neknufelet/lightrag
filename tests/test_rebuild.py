"""REBUILD-1／REBUILD-3 的容器路由與空母體行為測試。"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class _FakeOracle:
    def __init__(self, statuses: dict[str, int]) -> None:
        self.statuses = statuses
        self.chunk_calls = 0

    def indexed_docs(self, api_key: str, port: int = 9621) -> dict[str, int]:
        return self.statuses

    def pipeline_idle(self, api_key: str, port: int = 9621) -> dict[str, object]:
        return {"busy": False, "scanning": False, "destructive_busy": False}

    def chunk_top_k_effect(self, api_key: str, port: int = 9621) -> dict[str, int]:
        self.chunk_calls += 1
        return {"2": 2, "8": 8}


def _results(checker: object) -> dict[str, object]:
    return {result.id: result for result in checker.results}  # type: ignore[attr-defined]


def test_postgres_container_defaults_and_respects_env() -> None:
    common = _load("mineru_common_rebuild", SCRIPTS / "mineru_common.py")

    assert common.postgres_container({}) == "lightrag-postgres"
    assert common.postgres_container({"POSTGRES_HOST": "pg-custom"}) == "pg-custom"
    assert common.postgres_container({"PP_PG_CONTAINER": "pg-override",
                                      "POSTGRES_HOST": "pg-custom"}) == "pg-override"


def test_extract_and_compare_psql_use_the_new_default_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extract = _load("extract_check_rebuild", SCRIPTS / "extract-check.py")
    compare = _load("compare_ws_rebuild", SCRIPTS / "compare-ws.py")
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(command)
        stdout = "[]\n" if len(calls) == 1 else "\n"
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(extract.subprocess, "run", fake_run)
    monkeypatch.setattr(compare.subprocess, "run", fake_run)
    assert extract.psql("select 1", {}) == []
    assert compare.psql({}, "select 1") == []
    assert [command[2] for command in calls] == ["lightrag-postgres", "lightrag-postgres"]


def test_compat_empty_mother_is_unverifiable_and_does_not_probe_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compat = _load("compat_check_rebuild_empty", SCRIPTS / "compat-check.py")
    oracle = _FakeOracle({"processed": 0})
    monkeypatch.setattr(compat, "load_env", lambda _repo: {})

    commands: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        commands.append(command)
        assert command[:4] == ["docker", "exec", "lightrag-postgres", "psql"]
        assert command[-2] == "-c"
        if "lightrag_doc_status" in command[-1]:
            assert "where workspace = 'acoustics_v2';" in command[-1]
            return SimpleNamespace(returncode=0, stdout="0\n", stderr="")
        return SimpleNamespace(
            returncode=0, stdout="vector_table|1\n", stderr="",
        )

    monkeypatch.setattr(
        compat.subprocess, "run", fake_run,
    )

    checker = compat.Checker(oracle, "acoustics_v2")
    checker.environment("", 9621)
    results = _results(checker)

    assert results["A-25"].ok is None
    assert results["A-26"].ok is None
    assert oracle.chunk_calls == 0
    assert "驗不了" in results["A-26"].detail


def test_compat_a26_catches_api_and_postgres_document_count_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compat = _load("compat_check_rebuild_mismatch", SCRIPTS / "compat-check.py")
    oracle = _FakeOracle({"processed": 2})
    env = {"POSTGRES_HOST": "lightrag-postgres",
           "LLM_MODEL": "qwen3.6-35b-a3b",
           "PP_EYE_B_MODEL": "gpt-5.6-luna"}
    monkeypatch.setattr(compat, "load_env", lambda _repo: env)

    commands: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        commands.append(command)
        assert command[:4] == ["docker", "exec", "lightrag-postgres", "psql"]
        assert command[-2] == "-c"
        if "lightrag_doc_status" in command[-1]:
            assert "where workspace = 'acoustics_v2';" in command[-1]
            return SimpleNamespace(returncode=0, stdout="20\n", stderr="")
        return SimpleNamespace(
            returncode=0, stdout="vector_table|1\n", stderr="",
        )

    monkeypatch.setattr(
        compat.subprocess, "run", fake_run,
    )

    checker = compat.Checker(oracle, "acoustics_v2")
    checker.environment("", 9621)
    result = _results(checker)["A-26"]

    assert result.ok is False
    assert result.data["api_documents"] == 2
    assert result.data["postgres_documents"] == 20
    assert "不一致" in result.detail


def test_compat_a22_uses_configured_postgres_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compat = _load("compat_check_rebuild_a22", SCRIPTS / "compat-check.py")
    oracle = _FakeOracle({"processed": 1})
    env = {"POSTGRES_HOST": "pg-configured",
           "EMBEDDING_MODEL": "text-embedding-3-large",
           "EMBEDDING_DIM": "3072",
           "LLM_MODEL": "qwen3.6-35b-a3b",
           "PP_EYE_B_MODEL": "gpt-5.6-luna"}
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        commands.append(command)
        if "lightrag_doc_status" in command[-1]:
            assert command[-2] == "-c"
            return SimpleNamespace(returncode=0, stdout="1\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="vector_table|1\n", stderr="")

    monkeypatch.setattr(compat, "load_env", lambda _repo: env)
    monkeypatch.setattr(compat.subprocess, "run", fake_run)

    checker = compat.Checker(oracle, "acoustics_v2")
    checker.environment("", 9621)
    result = _results(checker)["A-22"]

    assert result.ok is True
    assert commands and commands[0][2] == "pg-configured"
