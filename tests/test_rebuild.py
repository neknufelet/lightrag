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
    """兩個入口都要被叫到 —— pytest 收集不到 `test_gates.py`，缺一個那半就靜靜不跑。

    ⚠ **2026-08-17 換了直譯器，意圖沒換。** 原本斷言 `python3 -m pytest …`，
    現在走 `uv sync` 建的 `.venv/bin/python`（PyMuPDF 只在那裡面）。
    """
    source = (SCRIPTS / "run-tests.sh").read_text(encoding="utf-8")

    assert '"$PY" -m pytest tests/ -q' in source
    assert '"$PY" tests/test_gates.py' in source
    assert "pytest_rc=0" in source and "gates_rc=0" in source


def test_entry_points_use_the_locked_venv_not_system_python() -> None:
    """⚠ **不准偷偷 fallback 回系統 python3。**

    dker 的系統 python 沒有 PyMuPDF（切章工具要它），而「用錯環境跑出來的綠」
    比紅燈更難查 —— 那正是 2026-08-17 才修掉的「跑著的是舊碼」同一族。
    環境沒建起來要當場停（exit 2），不是往下跑。
    """
    for name in ("run-tests.sh", "daily-check.sh"):
        src = (SCRIPTS / name).read_text(encoding="utf-8")
        assert 'PY="$REPO_DIR/.venv/bin/python"' in src, f"{name} 沒有指向 .venv"
        assert 'if [ ! -x "$PY" ]' in src, f"{name} 沒有在環境缺席時停下來"
        # 只看真正會被執行的行（開頭就是 python3），註解裡提到 python3 是說明不是呼叫。
        calls = [ln for ln in src.splitlines() if ln.strip().startswith("python3 ")]
        assert not calls, f"{name} 還有直接叫系統 python3 的行：{calls}"


def test_daily_check_wires_test_entry_into_check_red_path() -> None:
    """測試入口的離開碼要跑得到、存得下、並被判成三態之一。

    ⚠ **2026-08-17 換了機制，意圖沒換。** 原本這裡斷言的是
    `fail_msgs+=("測試入口失敗` 與 printf 的 `"tests_rc":%d` —— 兩者都隨
    「任何非零都是失敗」那段邏輯一起搬進 `check-levels.py` 了，daily-check.sh
    現在只負責跑與記離開碼。所以改成斷言**新的那條路**，不是刪掉這條守衛。

    為什麼要換：`run-tests.sh` 在 dker 上永遠回 3（沒有 node ＝ 那支 JS 測試
    根本沒跑），舊機制把它算成失敗，於是 `status` 天天是 `fail`，真的紅燈
    （`fresh_rc=2` 跑著舊碼）被淹在裡面。三態的判準見 tests/test_check_levels.py。
    """
    source = (SCRIPTS / "daily-check.sh").read_text(encoding="utf-8")

    assert "scripts/run-tests.sh > \"$CHECK_DIR/tests-$ts.txt\"" in source
    assert "tests_rc=$?" in source
    assert '--rc "tests=$tests_rc"' in source, "測試的離開碼沒有被餵進判準"
    assert "scripts/check-levels.py" in source
