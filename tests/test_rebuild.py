"""REBUILD-1／REBUILD-3 的容器路由與空母體行為測試。"""
from __future__ import annotations

import base64
import importlib.util
import json
import sys
import time
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


def test_extract_psql_uses_the_new_default_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """原本這條同時涵蓋 compare-ws.py，2026-08-07 那支隨「只用一個 workspace」
    的裁決一起刪除（ADR-0001；它的自述前提是「v155 凍結當對照組」，而 v155
    已不存在）。斷言的意思不變：SQL 要走新的預設容器名。"""
    extract = _load("extract_check_rebuild", SCRIPTS / "extract-check.py")
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="[]\n", stderr="")

    monkeypatch.setattr(extract.subprocess, "run", fake_run)
    assert extract.psql("select 1", {}) == []
    assert [command[2] for command in calls] == ["lightrag-postgres"]


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


def _jwt_with_expiry(expiry: int) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps({"exp": expiry}).encode("utf-8"),
    ).rstrip(b"=").decode("ascii")
    return f"header.{payload}.signature"


def _a21_result(monkeypatch: pytest.MonkeyPatch, token: str) -> object:
    compat = _load(f"compat_check_rebuild_a21_{token[-8:]}", SCRIPTS / "compat-check.py")
    env = {"MINERU_API_TOKEN": token, "EMBEDDING_MODEL": "model", "EMBEDDING_DIM": "3"}
    monkeypatch.setattr(compat, "load_env", lambda _repo: env)
    monkeypatch.setattr(compat, "postgres_document_count", lambda *_args: 0)
    monkeypatch.setattr(
        compat.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0, stdout="vector_table|1\n", stderr="",
        ),
    )
    checker = compat.Checker(_FakeOracle({"processed": 0}), "acoustics_v2")
    checker.environment("", 9621)
    return _results(checker)["A-21"]


def test_compat_a21_expiring_token_is_a_soft_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _a21_result(monkeypatch, _jwt_with_expiry(int(time.time()) + 13 * 86400))

    assert result.level == "soft"
    assert result.ok is False
    assert result.data["soft_fail_below_days"] == 14
    assert "整批解析" in result.detail


def test_compat_a21_token_with_margin_stays_green(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _a21_result(monkeypatch, _jwt_with_expiry(int(time.time()) + 30 * 86400))

    assert result.level == "soft"
    assert result.ok is True


def test_run_tests_entry_names_both_non_collecting_test_paths() -> None:
    source = (SCRIPTS / "run-tests.sh").read_text(encoding="utf-8")

    assert "python3 -m pytest tests/ -q" in source
    assert "python3 tests/test_gates.py" in source
    assert "pytest_rc=0" in source and "gates_rc=0" in source


def test_daily_check_wires_test_entry_into_check_red_path() -> None:
    source = (SCRIPTS / "daily-check.sh").read_text(encoding="utf-8")

    assert "scripts/run-tests.sh > \"$CHECK_DIR/tests-$ts.txt\"" in source
    assert "tests_rc=$?" in source
    assert 'fail_msgs+=("測試入口失敗' in source
    assert '"tests_rc":%d' in source
