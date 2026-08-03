"""Run with: `uvx --quiet pytest tests/test_llm_bench.py -q`.

llm-bench 的 CLI smoke、fixture 與量測契約。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import random
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "llm-bench.py"


def _bench_module() -> ModuleType:
    """以檔案路徑載入帶連字號名稱的 CLI 模組。"""
    spec = importlib.util.spec_from_file_location("llm_bench", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _FakeResponse:
    """避免測試成功回應解析時真的連線到 llama.cpp。"""

    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> bool:
        return False

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def _item(bench: ModuleType) -> object:
    """建立最小但真實結構的 fixture item。"""
    return bench._CacheRow("item-1", "prompt", "answer", "chunk-1")


def _timings(cache_n: int = 0) -> dict[str, object]:
    """提供可同時計算 prefill、decode 與 cache hit 的 timings。"""
    return {"prompt_n": 12, "prompt_ms": 3.0, "predicted_n": 4,
            "predicted_ms": 2.0, "cache_n": cache_n}


def _success_result(bench: ModuleType, item: object, finish_reason: str = "stop",
                    cache_n: int = 0) -> object:
    """建立可用的 request result，供 run 層測試免除網路細節。"""
    return bench._RequestResult(item_id=item.id, latency_s=0.5, prompt_tokens=12,
                                completion_tokens=4, output_sha256="output", reference_matches=True,
                                error_type=None, finish_reason=finish_reason, timings=_timings(cache_n))


def _table_report(bench: ModuleType, run: object, item: object,
                  server: dict[str, object] | None = None) -> dict[str, object]:
    """補上表格所需的 report 根欄位，讓單元測試不依賴 CLI。"""
    runs = [run]
    return {"runs": [run.report], "round_orders": [{"round": 1, "concurrency": [1]}],
            "order_effects": bench._order_effects(runs), "server": server or {},
            "config": {"cache_prompt": False},
            "determinism": bench._determinism(runs, (item,))}


def test_help_does_not_require_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                   capsys: pytest.CaptureFixture[str]) -> None:
    """三個 help 路徑均可在沒有 .env 的 coder 使用。"""
    bench = _bench_module()
    monkeypatch.setattr(bench, "REPO", tmp_path)
    for arguments in ([], ["fixture"], ["run"]):
        with pytest.raises(SystemExit) as exited:
            bench.main([*arguments, "--help"])
        assert exited.value.code == 0
        output = capsys.readouterr().out
        assert "usage:" in output
        if arguments == ["run"]:
            assert "這會佔滿伺服器的 slot" in output


def test_fixture_sampling_prefix() -> None:
    """固定種子抽樣必須可延伸。"""
    bench = _bench_module()
    rows = tuple(bench._CacheRow(id=f"id-{index}", prompt=f"prompt-{index}",
                                 reference_output=f"output-{index}", chunk_id=f"chunk-{index}")
                 for index in range(10))
    fixture = bench._fixture_document(rows, "acoustics_v2", 17, 4)
    larger = bench._fixture_document(rows, "acoustics_v2", 17, 7)
    indices = list(range(len(rows)))
    random.Random(17).shuffle(indices)
    expected = [f"id-{index}" for index in indices]
    assert [item["id"] for item in fixture["items"]] == expected[:4]
    assert [item["id"] for item in larger["items"]] == expected[:7]
    assert fixture["sha256"] == bench._json_sha256(fixture["items"])


def test_extract_rows_streams_psql_query_with_workspace_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """psql 必須從 stdin 讀取含 workspace 變數的 extract 查詢。"""
    bench = _bench_module()
    captured: dict[str, object] = {}

    def capture_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured.update(kwargs)
        return subprocess.CompletedProcess(command, 0, "[]\n", "")

    monkeypatch.setattr(bench.subprocess, "run", capture_run)
    assert bench._extract_rows(
        {"POSTGRES_HOST": "lightrag-postgres", "POSTGRES_USER": "reader",
         "POSTGRES_DATABASE": "lightrag"},
        "acoustics_v2",
    ) == []

    command = captured["command"]
    assert isinstance(command, list)
    assert command[:4] == ["docker", "exec", "-i", "lightrag-postgres"]
    workspace_index = command.index("-v")
    assert command[workspace_index + 1] == "workspace=acoustics_v2"
    assert command[-2:] == ["-f", "-"]
    assert "-c" not in command
    sql = captured["input"]
    assert isinstance(sql, str)
    assert sql not in command
    assert "where workspace = :'workspace'" in sql.lower()
    assert "cache_type = 'extract'" in sql.lower()


def test_run_missing_fixture_is_a_clear_error(tmp_path: Path) -> None:
    """run 的不存在題本錯誤不可退化成 traceback。"""
    missing = tmp_path / "does-not-exist.json"
    completed = subprocess.run([sys.executable, SCRIPT, "run", "--fixture", missing],
                               capture_output=True, text=True, check=False)
    assert completed.returncode == 2
    assert f"題本不存在：{missing}" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_cross_concurrency_determinism_counts_mismatch() -> None:
    """跨併發輸出不一致必須從 tok/s 之外被明確報出。"""
    bench = _bench_module()
    items = (bench._CacheRow("one", "p1", "r1", "c1"),
             bench._CacheRow("two", "p2", "r2", "c2"))
    runs = (bench._RunResult({}, {"one": "same", "two": "left"}),
            bench._RunResult({}, {"one": "same", "two": "right"}))
    result = bench._determinism(runs, items)
    assert result["matching"] == 1
    assert result["mismatches"] == ["two"]
    assert "1/2 題跨併發度逐字相同" in result["summary"]


def test_successful_http_response_preserves_usage_finish_reason_and_timings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """成功 HTTP 回應必須解析 usage、finish_reason 與 server timings。"""
    bench = _bench_module()
    item = _item(bench)
    payload = {"choices": [{"message": {"content": "answer"}, "finish_reason": "stop"}],
               "usage": {"prompt_tokens": 12, "completion_tokens": 4},
               "timings": _timings()}

    def fake_urlopen(*_args: object, **_kwargs: object) -> _FakeResponse:
        return _FakeResponse(payload)

    monkeypatch.setattr(bench.request, "urlopen", fake_urlopen)
    result = bench._request_once(item, "http://bench.invalid", "model", "key", 7, 64)
    assert result.error_type is None
    assert result.prompt_tokens == 12
    assert result.completion_tokens == 4
    assert result.finish_reason == "stop"
    assert result.timings == _timings()


def test_request_sends_cache_prompt_and_defaults_to_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """每個 completion 都必須顯式傳 cache_prompt，預設量 cold prefill。"""
    bench = _bench_module()
    item = _item(bench)
    payload = {"choices": [{"message": {"content": "answer"}, "finish_reason": "stop"}],
               "usage": {"prompt_tokens": 12, "completion_tokens": 4}, "timings": _timings()}
    bodies: list[dict[str, object]] = []

    def fake_urlopen(sent_request: object, **_kwargs: object) -> _FakeResponse:
        bodies.append(json.loads(sent_request.data.decode("utf-8")))
        return _FakeResponse(payload)

    monkeypatch.setattr(bench.request, "urlopen", fake_urlopen)
    bench._request_once(item, "http://bench.invalid", "model", "key", 7, 64)
    bench._request_once(item, "http://bench.invalid", "model", "key", 7, 64, True)
    assert [body["cache_prompt"] for body in bodies] == [False, True]


def test_cache_tokens_with_disabled_cache_invalidates_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """cache_prompt=false 下任一 cache token 都必須讓 run 失效並在表格警告。"""
    bench = _bench_module()
    item = _item(bench)
    monkeypatch.setattr(
        bench, "_request_once",
        lambda request_item, *_args: _success_result(bench, request_item, cache_n=37),
    )
    run = bench._run_once((item,), 1, "http://bench.invalid", "model", "key", 7, 64, 0.0)
    assert run.report["cache_tokens_total"] == 37
    assert run.report["cache_hit_n"] == 1
    assert run.report["cache_hit_ratio"] == pytest.approx(37 / 12)
    assert run.report["valid"] is False
    assert run.report["invalid_reason"] == "cache_prompt=false but cache_tokens_total=37"
    table = bench._report_table(_table_report(bench, run, item))
    assert "⚠ CACHE PROMPT DISABLE FAILED" in table
    assert "cache_tokens_total" in table


def test_multi_item_cache_tokens_are_summed_and_ratio_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """多題 run 的 Σcache_n 與快取重用比例都必須由逐題結果彙總。"""
    bench = _bench_module()
    items = (
        bench._CacheRow("one", "prompt one", "answer", "chunk-one"),
        bench._CacheRow("two", "prompt two", "answer", "chunk-two"),
    )

    def cached_result(request_item: object, *_args: object) -> object:
        cache_n = {"one": 4, "two": 8}[request_item.id]
        return _success_result(bench, request_item, cache_n=cache_n)

    monkeypatch.setattr(bench, "_request_once", cached_result)
    run = bench._run_once(items, 2, "http://bench.invalid", "model", "key", 7, 64, 0.0,
                          cache_prompt=True)
    assert run.report["prompt_tokens"] == 24
    assert run.report["cache_tokens_total"] == 12
    assert run.report["cache_hit_n"] == 2
    assert run.report["cache_hit_ratio"] == pytest.approx(0.5)
    table_report = _table_report(bench, run, items[0])
    table_report["config"] = {"cache_prompt": True, "order_threshold": 0.05}
    table = bench._report_table(table_report)
    assert "cache_hit_ratio" in table
    assert "50.0%" in table


def test_timeout_invalidates_run_and_main_returns_nonzero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """timeout 不能留下可用 tok/s，且 CLI 必須用非零狀態表示量測失敗。"""
    bench = _bench_module()
    item = _item(bench)

    def timeout_result(request_item: object, *_args: object) -> object:
        return bench._RequestResult(item_id=request_item.id, latency_s=1.0, prompt_tokens=0,
                                    completion_tokens=0, output_sha256=None,
                                    reference_matches=None, error_type="timeout",
                                    finish_reason=None, timings=None)

    monkeypatch.setattr(bench, "_request_once", timeout_result)
    run = bench._run_once((item,), 1, "http://bench.invalid", "model", "key", 7, 64, 0.0)
    assert run.report["valid"] is False
    assert run.report["invalid_reason"] == "errors.total=1"
    assert run.report["tok_s_aggregate"] is None
    assert "⚠ INVALID" in bench._report_table(_table_report(bench, run, item))
    fixture_path = tmp_path / "fixture.json"
    bench._write_json(fixture_path, bench._fixture_document((item,), "workspace", 7, 1))
    monkeypatch.setattr(bench, "_server_props", lambda *_args: {"model_path": "fake.gguf"})
    assert bench.main(["run", "--fixture", str(fixture_path), "--api-key", "key",
                       "--concurrency", "1", "--repeat", "1"]) == 1


def test_length_finish_reason_is_reported_as_truncated(monkeypatch: pytest.MonkeyPatch) -> None:
    """finish_reason=length 必須明確計入 truncated_n，但不令 run invalid。"""
    bench = _bench_module()
    item = _item(bench)
    monkeypatch.setattr(bench, "_request_once",
                        lambda request_item, *_args: _success_result(bench, request_item, "length"))
    run = bench._run_once((item,), 1, "http://bench.invalid", "model", "key", 7, 64, 0.0)
    assert run.report["valid"] is True
    assert run.report["truncated_n"] == 1
    assert run.report["items"][0]["finish_reason"] == "length"
    assert "⚠ TRUNCATED=1" in bench._report_table(_table_report(bench, run, item))


def test_missing_timings_stays_runnable_but_marks_server_rates_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """舊版 server 少了 timings 時，completion 仍可量但 prefill/decode 不可用。"""
    bench = _bench_module()
    item = _item(bench)
    payload = {"choices": [{"message": {"content": "answer"}, "finish_reason": "stop"}],
               "usage": {"prompt_tokens": 12, "completion_tokens": 4}}

    def fake_urlopen(*_args: object, **_kwargs: object) -> _FakeResponse:
        return _FakeResponse(payload)

    monkeypatch.setattr(bench.request, "urlopen", fake_urlopen)
    run = bench._run_once((item,), 1, "http://bench.invalid", "model", "key", 7, 64, 0.0)
    assert run.report["valid"] is True
    assert run.report["timings_available"] is False
    assert run.report["prefill_tok_s"] is None
    assert run.report["decode_tok_s"] is None
    assert "⚠ TIMINGS UNAVAILABLE" in bench._report_table(_table_report(bench, run, item))


def test_existing_output_requires_force_for_fixture_and_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """fixture 與 run 都拒絕覆寫，明確 force 後才可寫入。"""
    bench = _bench_module()
    item = _item(bench)
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text("old fixture", encoding="utf-8")
    fixture_args = argparse.Namespace(out=fixture_path, force=False, workspace="workspace", seed=7, n=1)
    with pytest.raises(bench.BenchError, match="輸出檔已存在"):
        bench._run_fixture(fixture_args, {})
    monkeypatch.setattr(bench, "_extract_rows", lambda *_args: [item])
    fixture_args.force = True
    bench._run_fixture(fixture_args, {})
    run_output = tmp_path / "report.json"
    run_output.write_text("old report", encoding="utf-8")
    run_args = argparse.Namespace(fixture=fixture_path, api_key="key", host="http://bench.invalid",
                                  model="model", concurrency=[1], repeat=1, max_tokens=64,
                                  cache_prompt=False, out=run_output, force=False)
    with pytest.raises(bench.BenchError, match="輸出檔已存在"):
        bench._run_benchmark(run_args)
    monkeypatch.setattr(bench, "_server_props", lambda *_args: {"model_path": "fake.gguf"})
    monkeypatch.setattr(bench, "_request_once",
                        lambda request_item, *_args: _success_result(bench, request_item))
    run_args.force = True
    assert bench._run_benchmark(run_args) is True
    report = json.loads(run_output.read_text(encoding="utf-8"))
    assert report["fixture"] == str(fixture_path.resolve())
    assert report["server"] == {"model_path": "fake.gguf"}
    assert report["config"] == {"cache_prompt": False, "order_threshold": 0.05}
    assert report["warmup"]["used"] is True
    assert report["warmup"]["source"] == "synthetic"
    assert report["warmup"]["error_type"] is None
    assert report["max_tokens"] == 64
    assert report["concurrency"] == [1]
    assert report["repeat"] == 1
    item_report = report["runs"][0]["items"][0]
    assert set(item_report) == {"id", "concurrency", "round", "latency_s", "prompt_tokens",
                                "completion_tokens", "finish_reason", "timings", "output_sha256",
                                "error_type"}
    assert report["runs"][0]["prefill_tok_s"] == 4000.0
    assert report["runs"][0]["decode_tok_s"] == 2000.0
    assert report["runs"][0]["cache_tokens_total"] == 0
    assert report["runs"][0]["cache_hit_n"] == 0
    assert report["runs"][0]["cache_hit_ratio"] == 0
    assert "server-side pooled rate" in report["rate_definitions"]["note"]


def test_warmup_prompt_is_synthetic_and_not_in_fixture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """warm-up 只能使用固定合成 prompt，不可預先暖任何 fixture 題目。"""
    bench = _bench_module()
    items = (bench._CacheRow("one", "fixture prompt one", "answer", "chunk-one"),
             bench._CacheRow("two", "fixture prompt two", "answer", "chunk-two"))
    fixture_path = tmp_path / "fixture.json"
    bench._write_json(fixture_path, bench._fixture_document(items, "workspace", 7, 2))
    report_path = tmp_path / "report.json"
    sent_items: list[object] = []

    def capture_request(request_item: object, *_args: object) -> object:
        sent_items.append(request_item)
        return _success_result(bench, request_item)

    monkeypatch.setattr(bench, "_server_props", lambda *_args: {"model_path": "fake.gguf"})
    monkeypatch.setattr(bench, "_request_once", capture_request)
    assert bench._run_benchmark(argparse.Namespace(
        fixture=fixture_path, api_key="key", host="http://bench.invalid", model="model",
        concurrency=[1], repeat=1, max_tokens=64, cache_prompt=False, out=report_path, force=False,
    )) is True
    fixture_hashes = {hashlib.sha256(item.prompt.encode("utf-8")).hexdigest() for item in items}
    warmup = sent_items[0]
    warmup_sha256 = hashlib.sha256(warmup.prompt.encode("utf-8")).hexdigest()
    assert warmup_sha256 not in fixture_hashes
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["warmup"] == {
        "used": True,
        "source": "synthetic",
        "concurrency": 1,
        "requests": 1,
        "success_n": 1,
        "prompt_sha256": warmup_sha256,
        "error_type": None,
        "errors": {"total": 0, "by_type": {}},
        "valid": True,
    }


def test_multiround_benchmark_reaches_json_and_table(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """多輪的 run、順序效應與限制說明必須一路寫進 JSON 與表格。"""
    bench = _bench_module()
    item = _item(bench)
    fixture_path = tmp_path / "fixture.json"
    report_path = tmp_path / "report.json"
    bench._write_json(fixture_path, bench._fixture_document((item,), "workspace", 7, 1))
    sent_items: list[object] = []

    def capture_request(request_item: object, *_args: object) -> object:
        sent_items.append(request_item)
        return _success_result(bench, request_item)

    monkeypatch.setattr(bench, "DRAIN_INTERVAL_S", 0.0)
    monkeypatch.setattr(bench, "_server_props", lambda *_args: {"model_path": "fake.gguf"})
    monkeypatch.setattr(bench, "_request_once", capture_request)
    assert bench._run_benchmark(argparse.Namespace(
        fixture=fixture_path, api_key="key", host="http://bench.invalid", model="model",
        concurrency=[1, 2], repeat=2, max_tokens=64, cache_prompt=False, order_threshold=0.05,
        out=report_path, force=False,
    )) is True
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["warmup"]["concurrency"] == 2
    assert report["warmup"]["requests"] == 2
    assert report["warmup"]["success_n"] == 2
    assert report["warmup"]["valid"] is True
    assert [item.id for item in sent_items[:2]] == ["synthetic-warmup", "synthetic-warmup"]
    assert [(run["round"], run["concurrency"]) for run in report["runs"]] == [
        (1, 1), (1, 2), (2, 2), (2, 1),
    ]
    assert report["round_orders"] == [
        {"round": 1, "concurrency": [1, 2]}, {"round": 2, "concurrency": [2, 1]},
    ]
    assert all(effect["rounds"] == [1, 2] for effect in report["order_effects"])
    assert all(len(effect["tok_s_aggregate_by_round"]) == 2 for effect in report["order_effects"])
    table = bench._report_table(report)
    assert "R1=" in table
    assert "R2=" in table
    assert "2 輪" in table
    assert "兩輪無法分辨漂移與雜訊" in table


def test_repeat_two_reverses_second_round_order() -> None:
    """第 2 輪必須反序，供純函式測試避免碰到 server。"""
    bench = _bench_module()
    assert bench._round_concurrency_orders([1, 2, 4, 8], 2) == [[1, 2, 4, 8], [8, 4, 2, 1]]


@pytest.mark.parametrize(
    ("first", "last", "expected_direction", "expected_spread", "expected_observed"),
    [(100.0, 80.0, "slower", 2 / 9, True), (80.0, 100.0, "faster", 2 / 9, True),
     (100.0, 99.0, "slower", 2 / 199, False)],
)
def test_order_effects_report_first_to_last_direction(
    first: float, last: float, expected_direction: str, expected_spread: float,
    expected_observed: bool,
) -> None:
    """相同 spread 的正反假資料必須保留 first-to-last 的方向。"""
    bench = _bench_module()
    runs = (
        bench._RunResult({"round": 1, "concurrency": 2, "valid": True,
                          "tok_s_aggregate": first}, {}),
        bench._RunResult({"round": 2, "concurrency": 2, "valid": True,
                          "tok_s_aggregate": last}, {}),
    )
    effect = bench._order_effects(runs)[0]
    assert effect["tok_s_aggregate_by_round"] == [
        {"round": 1, "tok_s_aggregate": first}, {"round": 2, "tok_s_aggregate": last},
    ]
    assert effect["relative_spread"] == pytest.approx(expected_spread)
    assert effect["direction"] == expected_direction
    assert effect["first_to_last_delta_tok_s"] == last - first
    assert effect["threshold"] == 0.05
    assert effect["observed"] is expected_observed


def test_server_props_failure_is_preserved_warned_and_invalidates_benchmark(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """抓不到 /props 要保存原因、表格警告且讓整體以非零結果失敗。"""
    bench = _bench_module()
    item = _item(bench)

    def offline(*_args: object, **_kwargs: object) -> object:
        raise bench.error.URLError("offline")

    monkeypatch.setattr(bench.request, "urlopen", offline)
    server = bench._server_props("http://bench.invalid", "key")
    assert server["error"] == "/props network: offline"
    monkeypatch.setattr(bench, "_request_once",
                        lambda request_item, *_args: _success_result(bench, request_item))
    run = bench._run_once((item,), 1, "http://bench.invalid", "model", "key", 7, 64, 0.0)
    assert "⚠ SERVER PROVENANCE UNAVAILABLE" in bench._report_table(
        _table_report(bench, run, item, server)
    )
    fixture_path = tmp_path / "fixture.json"
    report_path = tmp_path / "report.json"
    bench._write_json(fixture_path, bench._fixture_document((item,), "workspace", 7, 1))
    monkeypatch.setattr(bench, "_server_props", lambda *_args: server)
    assert bench._run_benchmark(argparse.Namespace(
        fixture=fixture_path, api_key="key", host="http://bench.invalid", model="model",
        concurrency=[1], repeat=1, max_tokens=64, cache_prompt=False, out=report_path, force=False,
    )) is False
    assert json.loads(report_path.read_text(encoding="utf-8"))["server"] == server


def test_main_returns_nonzero_when_server_props_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """/props provenance 失敗時，main 必須回傳非零退出碼。"""
    bench = _bench_module()
    item = _item(bench)
    fixture_path = tmp_path / "fixture.json"
    report_path = tmp_path / "report.json"
    bench._write_json(fixture_path, bench._fixture_document((item,), "workspace", 7, 1))
    monkeypatch.setattr(bench, "REPO", tmp_path)
    monkeypatch.setattr(bench, "_server_props", lambda *_args: {"error": "/props timeout"})
    monkeypatch.setattr(bench, "_request_once",
                        lambda request_item, *_args: _success_result(bench, request_item))
    assert bench.main([
        "run", "--fixture", str(fixture_path), "--api-key", "key", "--concurrency", "1",
        "--repeat", "1", "--out", str(report_path),
    ]) == 1
    assert json.loads(report_path.read_text(encoding="utf-8"))["server"] == {
        "error": "/props timeout"
    }


def test_missing_docker_container_names_postgres_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """docker exec 找不到容器時，錯誤必須說明 POSTGRES_HOST 被視為容器名。"""
    bench = _bench_module()
    completed = subprocess.CompletedProcess(
        args=["docker", "exec"], returncode=1, stdout="",
        stderr="Error response from daemon: No such container: postgres-host",
    )
    monkeypatch.setattr(bench.subprocess, "run", lambda *_args, **_kwargs: completed)
    with pytest.raises(bench.BenchError, match="找不到容器 postgres-host.*POSTGRES_HOST 當成容器名"):
        bench._extract_rows({"POSTGRES_HOST": "postgres-host"}, "workspace")
