#!/usr/bin/env python3
"""受控量測 llama.cpp 抽取吞吐量的題本與基準工具。"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import random
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence, cast
from urllib import error, request

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mineru_common import add_workspace_arg, load_env  # noqa: E402


REPO = Path(__file__).resolve().parent.parent
DEFAULT_HOST = "http://100.71.26.77:8080"
DEFAULT_MODEL = "qwen3.6-35b-a3b"
DEFAULT_SEED = 20260803
REQUEST_TIMEOUT_S = 600
DRAIN_INTERVAL_S = 5.0
DEFAULT_ORDER_THRESHOLD = 0.05
LOGGER = logging.getLogger(__name__)

# llama.cpp 的 prompt cache 預設開啟；量測真實抽取的 cold prefill 時必須明確關閉。
# 此 prompt 僅供 server warm-up，刻意與 fixture 的真實抽取題目無關且固定可重現。
SYNTHETIC_WARMUP_PROMPT = (
    "Synthetic benchmark warm-up only. This text is deliberately unrelated to every "
    "LightRAG extraction fixture and must never be used as an extraction question. "
) * 16

# psql 的 -c 不展開 :'var'；必須由 stdin 餵入 SQL 才會插值。
_CACHE_QUERY = """
select id, original_prompt, return_value, chunk_id
from lightrag_llm_cache
where workspace = :'workspace' and cache_type = 'extract'
order by id
"""


class BenchError(Exception):
    """可預期且應以清楚 CLI 訊息呈現的錯誤。"""


class ResponseFormatError(Exception):
    """伺服器回應沒有基準所需的 completion 格式。"""


@dataclass(frozen=True)
class _CacheRow:
    id: str
    prompt: str
    reference_output: str
    chunk_id: str


@dataclass(frozen=True)
class _FixtureBook:
    sha256: str
    seed: int
    items: tuple[_CacheRow, ...]


@dataclass(frozen=True)
class _RequestResult:
    item_id: str
    latency_s: float
    prompt_tokens: int
    completion_tokens: int
    output_sha256: str | None
    reference_matches: bool | None
    error_type: str | None
    finish_reason: str | None
    timings: Mapping[str, object] | None


@dataclass(frozen=True)
class _RunResult:
    report: dict[str, object]
    hashes: dict[str, str | None]


def _positive_int(value: str) -> int:
    """解析必須為正整數的 CLI 值。"""
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("必須是正整數") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("必須是正整數")
    return parsed


def _concurrencies(value: str) -> list[int]:
    """解析逗號分隔且不重複的併發度清單。"""
    try:
        parsed = [_positive_int(part.strip()) for part in value.split(",")]
    except argparse.ArgumentTypeError as exc:
        raise argparse.ArgumentTypeError("--concurrency 需為 1,2,4 形式") from exc
    if not parsed or len(set(parsed)) != len(parsed):
        raise argparse.ArgumentTypeError("--concurrency 不得空白或重複")
    return parsed


def _nonnegative_float(value: str) -> float:
    """解析有限且不小於零的浮點 CLI 值。"""
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("必須是非負有限數") from exc
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError("必須是非負有限數")
    return parsed


def _as_mapping(value: object, label: str) -> Mapping[str, object]:
    """驗證 JSON 物件，避免讓不完整題本靜默進入量測。"""
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise BenchError(f"{label} 必須是 JSON 物件")
    return cast(Mapping[str, object], value)


def _text_field(row: Mapping[str, object], field: str, label: str) -> str:
    """讀取不可缺漏的字串欄位。"""
    value = row.get(field)
    if not isinstance(value, str):
        raise BenchError(f"{label} 的 {field} 必須是字串")
    return value


def _int_field(row: Mapping[str, object], field: str, label: str) -> int:
    """讀取不可缺漏的整數欄位。"""
    value = row.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise BenchError(f"{label} 的 {field} 必須是整數")
    return value


def _json_sha256(value: object) -> str:
    """以固定 JSON 編碼計算可跨機重現的 SHA-256。"""
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _extract_rows(env: Mapping[str, str], workspace: str) -> list[_CacheRow]:
    """透過 dker 的既有 docker-exec psql 路徑唯讀擷取抽取快取。"""
    container = env.get("POSTGRES_HOST", "")
    if not container:
        raise BenchError("fixture 需要 .env 的 POSTGRES_HOST（請在 florian-dker 執行）")
    wrapped = "select coalesce(json_agg(t), '[]'::json)::text from (" + _CACHE_QUERY + ") t"
    command = ["docker", "exec", "-i", container, "psql", "-U",
               env.get("POSTGRES_USER", "deeptutor"), "-d",
               env.get("POSTGRES_DATABASE", "lightrag"), "-v", f"workspace={workspace}",
               "-tAqX", "-f", "-"]
    completed = subprocess.run(
        command, input=wrapped, capture_output=True, text=True, timeout=300,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip()[:300]
        if "No such container" in stderr:
            raise BenchError(
                f"找不到容器 {container} —— 這裡把 .env 的 POSTGRES_HOST 當成容器名用"
                f"（docker exec 失敗：{stderr}）"
            )
        raise BenchError(f"psql（透過 docker exec 容器 {container}）失敗：{stderr}")
    try:
        decoded: object = json.loads(completed.stdout.strip() or "[]")
    except json.JSONDecodeError as exc:
        raise BenchError("psql 回傳不是 JSON") from exc
    if not isinstance(decoded, list):
        raise BenchError("psql 回傳不是資料列陣列")
    return [_cache_row(row, position) for position, row in enumerate(decoded, start=1)]


def _cache_row(value: object, position: int) -> _CacheRow:
    """驗證單列真實快取資料，不以空值或自編 prompt 補洞。"""
    row = _as_mapping(value, f"資料庫第 {position} 列")
    return _CacheRow(id=_text_field(row, "id", f"資料庫第 {position} 列"),
                     prompt=_text_field(row, "original_prompt", f"資料庫第 {position} 列"),
                     reference_output=_text_field(row, "return_value", f"資料庫第 {position} 列"),
                     chunk_id=_text_field(row, "chunk_id", f"資料庫第 {position} 列"))


def _fixture_document(rows: Sequence[_CacheRow], workspace: str, seed: int,
                      n: int) -> dict[str, object]:
    """以固定種子排列資料庫母體並輸出可延伸的題本前綴。"""
    if n > len(rows):
        raise BenchError(f"要求 {n} 題，但 extract 母體只有 {len(rows)} 筆")
    if len({row.id for row in rows}) != len(rows):
        raise BenchError("extract 母體有重複 id，拒絕靜默覆蓋題目")
    indices = list(range(len(rows)))
    random.Random(seed).shuffle(indices)
    selected = [rows[index] for index in indices[:n]]
    items: list[dict[str, object]] = [
        {"id": row.id, "chunk_id": row.chunk_id, "prompt": row.prompt,
         "reference_output": row.reference_output, "prompt_chars": len(row.prompt),
         "output_chars": len(row.reference_output)}
        for row in selected
    ]
    return {"generated_from": "lightrag_llm_cache cache_type=extract",
            "workspace": workspace, "seed": seed, "n": n, "items": items,
            "sha256": _json_sha256(items)}


def _ensure_output_available(path: Path, force: bool) -> None:
    """拒絕覆寫既有量測產物，除非呼叫端明確要求。"""
    if path.exists() and not force:
        raise BenchError(f"輸出檔已存在：{path}（若要覆寫請加 --force）")


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    """將明確指定的 JSON 目的地寫入 UTF-8 檔案。"""
    try:
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except OSError as exc:
        raise BenchError(f"無法寫入 {path}：{exc}") from exc


def _read_fixture(path: Path) -> _FixtureBook:
    """讀取並驗證題本的欄位、長度與 items 雜湊。"""
    if not path.is_file():
        raise BenchError(f"題本不存在：{path}")
    try:
        with path.open(encoding="utf-8") as handle:
            decoded: object = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchError(f"無法讀取題本 {path}：{exc}") from exc
    root = _as_mapping(decoded, "題本")
    items_value = root.get("items")
    if not isinstance(items_value, list):
        raise BenchError("題本的 items 必須是陣列")
    if _int_field(root, "n", "題本") != len(items_value):
        raise BenchError("題本的 n 與 items 長度不一致")
    expected_sha = _text_field(root, "sha256", "題本")
    if _json_sha256(items_value) != expected_sha:
        raise BenchError("題本 items 的 sha256 不符，拒絕量測不明題本")
    items = tuple(_fixture_item(value, position) for position, value in enumerate(items_value, 1))
    if len({item.id for item in items}) != len(items):
        raise BenchError("題本有重複 id，拒絕靜默覆蓋輸出")
    return _FixtureBook(sha256=expected_sha, seed=_int_field(root, "seed", "題本"), items=items)


def _fixture_item(value: object, position: int) -> _CacheRow:
    """驗證題本單題及其字元計數沒有被更動。"""
    item = _as_mapping(value, f"題本第 {position} 題")
    row = _CacheRow(id=_text_field(item, "id", f"題本第 {position} 題"),
                    prompt=_text_field(item, "prompt", f"題本第 {position} 題"),
                    reference_output=_text_field(item, "reference_output", f"題本第 {position} 題"),
                    chunk_id=_text_field(item, "chunk_id", f"題本第 {position} 題"))
    if _int_field(item, "prompt_chars", f"題本第 {position} 題") != len(row.prompt):
        raise BenchError(f"題本第 {position} 題的 prompt_chars 不符")
    if _int_field(item, "output_chars", f"題本第 {position} 題") != len(row.reference_output):
        raise BenchError(f"題本第 {position} 題的 output_chars 不符")
    return row


def _completion_fields(
    value: object,
) -> tuple[str, int, int, str | None, Mapping[str, object] | None]:
    """取出 completion、token 用量、終止原因及 llama.cpp server timings。"""
    try:
        root = _as_mapping(value, "伺服器回應")
        choices = root.get("choices")
        if not isinstance(choices, list) or not choices:
            raise BenchError("伺服器回應缺 choices[0]")
        choice = _as_mapping(choices[0], "伺服器回應 choices[0]")
        message = _as_mapping(choice.get("message"), "伺服器回應 message")
        content = _text_field(message, "content", "伺服器回應 message")
        usage = _as_mapping(root.get("usage"), "伺服器回應 usage")
        finish_reason_value = choice.get("finish_reason")
        if finish_reason_value is not None and not isinstance(finish_reason_value, str):
            raise BenchError("伺服器回應 choices[0] 的 finish_reason 必須是字串或 null")
        timings_value = root.get("timings")
        timings: Mapping[str, object] | None = None
        if isinstance(timings_value, dict) and all(
            isinstance(key, str) for key in timings_value
        ):
            timings = cast(Mapping[str, object], timings_value)
        return (content, _int_field(usage, "prompt_tokens", "伺服器回應 usage"),
                _int_field(usage, "completion_tokens", "伺服器回應 usage"),
                cast(str | None, finish_reason_value), timings)
    except BenchError as exc:
        raise ResponseFormatError(str(exc)) from exc


def _failure(item: _CacheRow, started: float, error_type: str) -> _RequestResult:
    """建立保留實測延遲的失敗請求結果。"""
    return _RequestResult(item_id=item.id, latency_s=time.perf_counter() - started,
                          prompt_tokens=0, completion_tokens=0, output_sha256=None,
                          reference_matches=None, error_type=error_type,
                          finish_reason=None, timings=None)


def _request_once(item: _CacheRow, host: str, model: str, api_key: str, seed: int,
                  max_tokens: int, cache_prompt: bool = False) -> _RequestResult:
    """送出一個固定參數的非串流 completion，並量測它的延遲。"""
    body = {"model": model, "messages": [{"role": "user", "content": item.prompt}],
            "temperature": 0, "seed": seed, "max_tokens": max_tokens, "stream": False,
            "cache_prompt": cache_prompt}
    started = time.perf_counter()
    try:
        req = request.Request(host.rstrip("/") + "/v1/chat/completions",
                              data=json.dumps(body).encode("utf-8"), method="POST",
                              headers={"Authorization": f"Bearer {api_key}",
                                       "Content-Type": "application/json"})
        with request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as response:
            decoded: object = json.loads(response.read().decode("utf-8"))
        content, prompt_tokens, completion_tokens, finish_reason, timings = _completion_fields(decoded)
    except error.HTTPError as exc:
        with exc:
            status = exc.code
        LOGGER.warning("題目 %s 收到 HTTP %s", item.id, status)
        return _failure(item, started, "http")
    except TimeoutError:
        LOGGER.warning("題目 %s 逾時", item.id)
        return _failure(item, started, "timeout")
    except error.URLError as exc:
        kind = "timeout" if isinstance(exc.reason, TimeoutError) else "network"
        LOGGER.warning("題目 %s %s：%s", item.id, kind, exc.reason)
        return _failure(item, started, kind)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ResponseFormatError) as exc:
        LOGGER.warning("題目 %s 回應無法量測：%s", item.id, type(exc).__name__)
        return _failure(item, started, "response")
    except Exception as exc:
        LOGGER.warning("題目 %s 非預期失敗：%s", item.id, type(exc).__name__)
        return _failure(item, started, "unexpected")
    output_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return _RequestResult(item_id=item.id, latency_s=time.perf_counter() - started,
                          prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                          output_sha256=output_hash,
                          reference_matches=(content == item.reference_output), error_type=None,
                          finish_reason=finish_reason, timings=timings)


def _timing_number(timings: Mapping[str, object], field: str) -> float | None:
    """讀取非負數 timing 欄位；不完整 timings 不應使整個量測失敗。"""
    value = timings.get(field)
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
        return float(value)
    return None


def _has_complete_timings(result: _RequestResult) -> bool:
    """確認 server timings 足以重算 prefill、decode 與 cache 指標。"""
    if result.timings is None:
        return False
    fields = ("prompt_n", "prompt_ms", "predicted_n", "predicted_ms", "cache_n")
    return all(_timing_number(result.timings, field) is not None for field in fields)


def _server_rate(results: Sequence[_RequestResult], token_field: str,
                 milliseconds_field: str) -> float | None:
    """以 llama.cpp 的 server-side timings 計算 token/s。"""
    token_total = sum(_timing_number(cast(Mapping[str, object], result.timings), token_field)
                      for result in results)
    milliseconds_total = sum(
        _timing_number(cast(Mapping[str, object], result.timings), milliseconds_field)
        for result in results
    )
    if milliseconds_total <= 0:
        return None
    return token_total * 1000.0 / milliseconds_total


def _item_report(result: _RequestResult, concurrency: int, round_number: int) -> dict[str, object]:
    """保留可重算與追查 outlier 所需的逐題原始觀測值。"""
    return {"id": result.item_id, "concurrency": concurrency, "round": round_number,
            "latency_s": result.latency_s, "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "finish_reason": result.finish_reason, "timings": result.timings,
            "output_sha256": result.output_sha256, "error_type": result.error_type}


def _run_once(items: Sequence[_CacheRow], concurrency: int, host: str, model: str,
              api_key: str, seed: int, max_tokens: int, drain_after_s: float,
              round_number: int = 1, cache_prompt: bool = False) -> _RunResult:
    """以一個固定併發度跑完整題本，失敗時停用所有可決策速率。"""
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(_request_once, item, host, model, api_key, seed, max_tokens,
                                   cache_prompt)
                   for item in items]
        results = [future.result() for future in futures]
    wall_s = time.perf_counter() - started
    successful = [result for result in results if result.error_type is None]
    latencies = [result.latency_s for result in successful]
    error_types: dict[str, int] = {}
    for result in results:
        if result.error_type is not None:
            error_types[result.error_type] = error_types.get(result.error_type, 0) + 1
    completion_tokens = sum(result.completion_tokens for result in results)
    prompt_tokens = sum(result.prompt_tokens for result in results)
    reference_matches = sum(result.reference_matches is True for result in results)
    error_total = sum(error_types.values())
    timings_available = bool(successful) and all(_has_complete_timings(result) for result in successful)
    truncated_n = sum(result.finish_reason == "length" for result in successful)
    cache_hit_n: int | None = None
    cache_tokens_total: float | None = None
    cache_token_counts = [
        _timing_number(result.timings, "cache_n") if result.timings is not None else None
        for result in successful
    ]
    cache_timings_available = bool(successful) and all(
        cache_tokens is not None for cache_tokens in cache_token_counts
    )
    if cache_timings_available:
        complete_cache_token_counts = [
            cache_tokens for cache_tokens in cache_token_counts if cache_tokens is not None
        ]
        cache_tokens_total = sum(complete_cache_token_counts)
        cache_hit_n = sum(cache_tokens > 0 for cache_tokens in complete_cache_token_counts)
    cache_hit_ratio = (
        cache_tokens_total / prompt_tokens
        if cache_tokens_total is not None and prompt_tokens > 0
        else None
    )
    invalid_reasons: list[str] = []
    if error_total:
        invalid_reasons.append(f"errors.total={error_total}")
    observed_cache_tokens = sum(
        cache_tokens for cache_tokens in cache_token_counts if cache_tokens is not None
    )
    if not cache_prompt and observed_cache_tokens > 0:
        cache_reason = (
            f"cache_tokens_total={cache_tokens_total:g}"
            if cache_tokens_total is not None
            else f"timings.cache_n>0 (at least {observed_cache_tokens:g} observed tokens)"
        )
        invalid_reasons.append(
            "cache_prompt=false but "
            + cache_reason
        )
    valid = not invalid_reasons
    aggregate_tok_s = completion_tokens / wall_s if valid and wall_s else None
    prefill_tok_s = (
        _server_rate(successful, "prompt_n", "prompt_ms") if valid and timings_available else None
    )
    decode_tok_s = (
        _server_rate(successful, "predicted_n", "predicted_ms") if valid and timings_available else None
    )
    report = {"round": round_number, "concurrency": concurrency, "wall_s": wall_s,
              "completion_tokens": completion_tokens, "prompt_tokens": prompt_tokens,
              "tok_s_aggregate": aggregate_tok_s, "prefill_tok_s": prefill_tok_s,
              "decode_tok_s": decode_tok_s, "timings_available": timings_available,
              "cache_timings_available": cache_timings_available,
              "cache_tokens_total": cache_tokens_total, "cache_hit_n": cache_hit_n,
              "cache_hit_ratio": cache_hit_ratio,
              "truncated_n": truncated_n, "valid": valid,
              "invalid_reason": None if valid else "; ".join(invalid_reasons),
              "success_n": len(successful),
              "latency_p50": statistics.median(latencies) if latencies else None,
              "latency_max": max(latencies) if latencies else None,
              "errors": {"total": error_total, "by_type": error_types},
              "output_sha256": {result.item_id: result.output_sha256 for result in results},
              "reference_output_comparison": {"matching": reference_matches,
                                                "total": len(items), "purpose": "reference_only"},
              "items": [_item_report(result, concurrency, round_number) for result in results],
              "drain_after_s": drain_after_s}
    return _RunResult(report=report, hashes={result.item_id: result.output_sha256 for result in results})


def _round_concurrency_orders(concurrencies: Sequence[int], repeat: int) -> list[list[int]]:
    """交替正向與反向掃描，以平衡單調的時間漂移。"""
    forward = list(concurrencies)
    backward = list(reversed(concurrencies))
    return [forward if index % 2 == 0 else backward for index in range(repeat)]


def _is_number(value: object) -> bool:
    """判別 JSON 報告中可安全格式化的數值（排除 bool）。"""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _order_effects(
    runs: Sequence[_RunResult], threshold: float = DEFAULT_ORDER_THRESHOLD,
) -> list[dict[str, object]]:
    """保留各輪 aggregate tok/s，並標出 first-to-last 的方向。"""
    grouped: dict[int, list[Mapping[str, object]]] = {}
    for run_result in runs:
        run = run_result.report
        concurrency = _int_field(run, "concurrency", "run")
        grouped.setdefault(concurrency, []).append(run)
    effects: list[dict[str, object]] = []
    for concurrency, group in grouped.items():
        group.sort(key=lambda run: _int_field(run, "round", "run"))
        rounds = [_int_field(run, "round", "run") for run in group]
        by_round = [
            {"round": _int_field(run, "round", "run"),
             "tok_s_aggregate": float(run["tok_s_aggregate"])
             if _is_number(run.get("tok_s_aggregate")) else None}
            for run in group
        ]
        valid_values = [float(run["tok_s_aggregate"]) for run in group
                        if run.get("valid") is True and _is_number(run.get("tok_s_aggregate"))]
        if len(group) < 2:
            effects.append({"concurrency": concurrency, "rounds": rounds,
                            "tok_s_aggregate_by_round": by_round,
                            "relative_spread": None, "direction": "unavailable",
                            "first_to_last_delta_tok_s": None, "observed": None,
                            "threshold": threshold,
                            "available": False, "reason": "repeat 小於 2，無從比較"})
        elif len(valid_values) != len(group):
            effects.append({"concurrency": concurrency, "rounds": rounds,
                            "tok_s_aggregate_by_round": by_round,
                            "relative_spread": None, "direction": "unavailable",
                            "first_to_last_delta_tok_s": None, "observed": None,
                            "threshold": threshold,
                            "available": False, "reason": "含 invalid run，差異不可用"})
        else:
            mean = statistics.fmean(valid_values)
            if mean == 0:
                effects.append({"concurrency": concurrency, "rounds": rounds,
                                "tok_s_aggregate_by_round": by_round,
                                "relative_spread": None, "direction": "unavailable",
                                "first_to_last_delta_tok_s": None, "observed": None,
                                "threshold": threshold,
                                "available": False, "reason": "mean=0，relative_spread 無定義"})
                continue
            first, last = valid_values[0], valid_values[-1]
            delta = last - first
            direction = "faster" if delta > 0 else "slower" if delta < 0 else "flat"
            relative_spread = (max(valid_values) - min(valid_values)) / mean
            effects.append({"concurrency": concurrency, "rounds": rounds,
                            "tok_s_aggregate_by_round": by_round,
                            "relative_spread": relative_spread,
                            "direction": direction, "first_to_last_delta_tok_s": delta,
                            "observed": relative_spread > threshold,
                            "threshold": threshold,
                            "available": True, "reason": None})
    return effects


def _determinism(runs: Sequence[_RunResult], items: Sequence[_CacheRow]) -> dict[str, object]:
    """比對每題在所有併發度都有回應時的逐字輸出是否相同。"""
    if len(runs) < 2:
        return {"matching": 0, "comparable": 0, "total": len(items), "mismatches": [],
                "summary": "0/0 題跨併發度逐字相同（僅一個併發度，無從比較）"}
    comparable: list[str] = []
    mismatches: list[str] = []
    for item in items:
        hashes = [run.hashes[item.id] for run in runs]
        if all(value is not None for value in hashes):
            comparable.append(item.id)
            if len(set(hashes)) != 1:
                mismatches.append(item.id)
    matching = len(comparable) - len(mismatches)
    return {"matching": matching, "comparable": len(comparable), "total": len(items),
            "mismatches": mismatches,
            "summary": f"{matching}/{len(items)} 題跨併發度逐字相同"
                       f"（可比較 {len(comparable)} 題）"}


def _report_table(report: Mapping[str, object]) -> str:
    """產生終端機可讀的吞吐、timings、快取與可用性結論。"""
    lines = [
        "輪  併發  wall_s  completion  prompt  aggregate  prefill_srv  decode_srv  p50_s(n)  max_s(n)  "
        "err  trunc  cache_tokens_total  cache_hit  cache_hit_ratio  ref 相同",
        "-" * 184,
    ]
    runs = report.get("runs")
    if not isinstance(runs, list):
        raise BenchError("內部錯誤：report 缺 runs")
    for value in runs:
        run = _as_mapping(value, "run")
        errors = _as_mapping(run.get("errors"), "errors")
        p50, maximum = run.get("latency_p50"), run.get("latency_max")
        success_n = _int_field(run, "success_n", "run")
        p50_text = f"{float(p50):.2f}({success_n})" if _is_number(p50) else f"-({success_n})"
        max_text = f"{float(maximum):.2f}({success_n})" if _is_number(maximum) else f"-({success_n})"
        reference = _as_mapping(run.get("reference_output_comparison"), "reference")
        aggregate = run.get("tok_s_aggregate")
        prefill = run.get("prefill_tok_s")
        decode = run.get("decode_tok_s")
        cache_tokens_total = run.get("cache_tokens_total")
        cache_hit_n = run.get("cache_hit_n")
        cache_hit_ratio = run.get("cache_hit_ratio")
        cache_tokens_text = (
            f"{float(cache_tokens_total):g}" if _is_number(cache_tokens_total) else "n/a"
        )
        cache_hit_text = str(cache_hit_n) if isinstance(cache_hit_n, int) else "n/a"
        cache_hit_ratio_text = (
            f"{float(cache_hit_ratio):.1%}" if _is_number(cache_hit_ratio) else "n/a"
        )
        tail: list[str] = []
        if run.get("valid") is not True:
            tail.append(f"⚠ INVALID: {run.get('invalid_reason')}")
        if run.get("timings_available") is not True:
            tail.append("⚠ TIMINGS UNAVAILABLE")
        truncated_n = _int_field(run, "truncated_n", "run")
        if truncated_n:
            tail.append(f"⚠ TRUNCATED={truncated_n}")
        if isinstance(cache_hit_n, int) and cache_hit_n:
            tail.append(f"⚠ CACHE_HIT={cache_hit_n}")
        config = _as_mapping(report.get("config", {}), "config")
        invalid_reason = run.get("invalid_reason")
        if (config.get("cache_prompt") is False and (
                (_is_number(cache_tokens_total) and float(cache_tokens_total) > 0)
                or (isinstance(invalid_reason, str) and "cache_prompt=false" in invalid_reason)
        )):
            tail.append("⚠ CACHE PROMPT DISABLE FAILED")
        line = (f"{_int_field(run, 'round', 'run'):>2}  "
                f"{_int_field(run, 'concurrency', 'run'):>4}  "
                f"{float(run['wall_s']):>6.2f}  {_int_field(run, 'completion_tokens', 'run'):>10}  "
                f"{_int_field(run, 'prompt_tokens', 'run'):>6}")
        line += f"  {float(aggregate):>9.2f}" if _is_number(aggregate) else "          -"
        line += f"  {float(prefill):>7.2f}" if _is_number(prefill) else "        -"
        line += f"  {float(decode):>6.2f}" if _is_number(decode) else "       -"
        line += (f"  {p50_text:>9}  {max_text:>9}  {_int_field(errors, 'total', 'errors'):>3}  "
                 f"{truncated_n:>5}  {cache_tokens_text:>9}  {cache_hit_text:>9}  "
                 f"{cache_hit_ratio_text:>15}  "
                 f"{_int_field(reference, 'matching', 'reference')}/"
                 f"{_int_field(reference, 'total', 'reference')}")
        if tail:
            line += "  " + "  ".join(tail)
        lines.append(line)
    round_orders = report.get("round_orders")
    if not isinstance(round_orders, list):
        raise BenchError("內部錯誤：report 缺 round_orders")
    order_summary: list[str] = []
    for value in round_orders:
        round_order = _as_mapping(value, "round_orders")
        order = round_order.get("concurrency")
        if not isinstance(order, list) or not all(isinstance(item, int) for item in order):
            raise BenchError("內部錯誤：round_orders concurrency 非整數陣列")
        order_summary.append(
            f"R{_int_field(round_order, 'round', 'round_orders')}="
            + "→".join(str(item) for item in order)
        )
    lines.append("輪次順序：" + ", ".join(order_summary))
    order_effects = report.get("order_effects")
    if not isinstance(order_effects, list):
        raise BenchError("內部錯誤：report 缺 order_effects")
    effect_summary: list[str] = []
    for value in order_effects:
        effect = _as_mapping(value, "order_effect")
        concurrency = _int_field(effect, "concurrency", "order_effect")
        by_round = effect.get("tok_s_aggregate_by_round")
        if not isinstance(by_round, list):
            raise BenchError("內部錯誤：order_effect 缺 tok_s_aggregate_by_round")
        rounds_text: list[str] = []
        for round_value in by_round:
            round_rate = _as_mapping(round_value, "tok_s_aggregate_by_round")
            rate = round_rate.get("tok_s_aggregate")
            rate_text = f"{float(rate):.2f}" if _is_number(rate) else "-"
            rounds_text.append(f"R{_int_field(round_rate, 'round', 'tok_s_aggregate_by_round')}={rate_text}")
        spread = effect.get("relative_spread")
        direction = effect.get("direction")
        delta = effect.get("first_to_last_delta_tok_s")
        threshold = effect.get("threshold")
        if (effect.get("available") is True and _is_number(spread) and _is_number(delta)
                and _is_number(threshold)):
            observed = "觀察到" if effect.get("observed") is True else "未觀察到"
            round_count = len(rounds_text)
            limitation = (
                "兩輪無法分辨漂移與雜訊，要下結論需要 --repeat 更多輪"
                if round_count == 2
                else f"{round_count} 輪仍無法分辨漂移與雜訊，要下結論需要 --repeat 更多輪"
            )
            effect_summary.append(
                f"c={concurrency}: {round_count} 輪、{'、'.join(rounds_text)} tok/s；"
                f"relative_spread {float(spread):.1%}（門檻 {float(threshold):.1%}）："
                f"{observed}順序效應；direction={direction} "
                f"(R1→最後輪 {float(delta):+.2f} tok/s)。{limitation}"
            )
        else:
            effect_summary.append(
                f"c={concurrency}: {'、'.join(rounds_text)} tok/s；不可用（{effect.get('reason')}）"
            )
    lines.append("順序效應（同併發跨輪 aggregate tok/s）：" + "; ".join(effect_summary))
    server = _as_mapping(report.get("server"), "server")
    if "error" in server:
        lines.append(f"⚠ SERVER PROVENANCE UNAVAILABLE: {server['error']}")
    warmup = _as_mapping(report.get("warmup", {}), "warmup")
    if warmup and warmup.get("valid") is not True:
        lines.append(
            "⚠ WARM-UP FAILED: "
            f"{warmup.get('error_type')} "
            f"(success {warmup.get('success_n')}/{warmup.get('requests')})"
        )
    determinism = _as_mapping(report.get("determinism"), "determinism")
    lines.append(str(determinism["summary"]))
    lines.append(
        "prefill_tok_s／decode_tok_s 為 server-side pooled rate（Σtokens÷Σms）；"
        "tok_s_aggregate 為牆鐘 aggregate rate，兩者不可互換或相加。"
    )
    lines.append("reference_output 比對僅供參考，不是行為判定。")
    return "\n".join(lines)


def _run_fixture(args: argparse.Namespace, env: Mapping[str, str]) -> None:
    """執行 fixture 子命令並將真實 prompt 題本寫至指定路徑。"""
    output = cast(Path, args.out)
    _ensure_output_available(output, cast(bool, args.force))
    document = _fixture_document(_extract_rows(env, cast(str, args.workspace)),
                                 cast(str, args.workspace), cast(int, args.seed), cast(int, args.n))
    _write_json(output, document)
    print(f"已寫入 {document['n']} 題 fixture：{output}")
    print(f"items sha256：{document['sha256']}")


def _server_props(host: str, api_key: str) -> dict[str, object]:
    """擷取 llama.cpp /props 原始回應；失敗也要寫入 report 作 provenance 警告。"""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        props_request = request.Request(host.rstrip("/") + "/props", headers=headers)
        with request.urlopen(props_request, timeout=REQUEST_TIMEOUT_S) as response:
            decoded: object = json.loads(response.read().decode("utf-8"))
        if not isinstance(decoded, dict) or not all(isinstance(key, str) for key in decoded):
            return {"error": "/props 回應不是 JSON 物件"}
        return cast(dict[str, object], decoded)
    except error.HTTPError as exc:
        with exc:
            return {"error": f"/props HTTP {exc.code}"}
    except TimeoutError:
        return {"error": "/props timeout"}
    except error.URLError as exc:
        return {"error": f"/props network: {exc.reason}"}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {"error": f"/props response: {type(exc).__name__}"}
    except Exception as exc:
        return {"error": f"/props unexpected: {type(exc).__name__}"}


def _warmup(item: _CacheRow, concurrency: int, host: str, model: str, api_key: str,
            seed: int, max_tokens: int, cache_prompt: bool) -> dict[str, object]:
    """以最大受測併發度同時送 synthetic prompt，確保每個 slot 都先被觸及。"""
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(_request_once, item, host, model, api_key, seed, max_tokens, cache_prompt)
            for _ in range(concurrency)
        ]
        results = [future.result() for future in futures]
    error_types: dict[str, int] = {}
    for result in results:
        if result.error_type is not None:
            error_types[result.error_type] = error_types.get(result.error_type, 0) + 1
    success_n = sum(result.error_type is None for result in results)
    error_type = None if not error_types else ",".join(sorted(error_types))
    return {
        "used": True,
        "source": "synthetic",
        "concurrency": concurrency,
        "requests": len(results),
        "success_n": success_n,
        "prompt_sha256": hashlib.sha256(item.prompt.encode("utf-8")).hexdigest(),
        "error_type": error_type,
        "errors": {"total": len(results) - success_n, "by_type": error_types},
        "valid": success_n == len(results),
    }


def _run_benchmark(args: argparse.Namespace) -> bool:
    """執行 run 子命令；有任何 invalid run 時回傳 false。"""
    output = cast(Path | None, args.out)
    if output is not None:
        _ensure_output_available(output, cast(bool, args.force))
    fixture_path = cast(Path, args.fixture)
    fixture = _read_fixture(fixture_path)
    if not fixture.items:
        raise BenchError("題本沒有題目，無法 warm-up 或量測")
    api_key = cast(str | None, args.api_key) or os.environ.get("LLAMA_API_KEY", "")
    if not api_key:
        raise BenchError("run 需要 --api-key 或 LLAMA_API_KEY 環境變數")
    concurrencies = cast(list[int], args.concurrency)
    repeat = cast(int, args.repeat)
    cache_prompt = cast(bool, getattr(args, "cache_prompt", False))
    order_threshold = cast(float, getattr(args, "order_threshold", DEFAULT_ORDER_THRESHOLD))
    orders = _round_concurrency_orders(concurrencies, repeat)
    host = cast(str, args.host).rstrip("/")
    print("警告：這會佔滿伺服器的 slot；跑前確認 dker 沒有在跑索引。"
          f"host={host}、題數={len(fixture.items)}、併發度={','.join(map(str, concurrencies))}、"
          f"輪數={repeat}、cache_prompt={cache_prompt}", file=sys.stderr)
    started_at = time.time()
    server = _server_props(host, api_key)
    warmup_item = _CacheRow(id="synthetic-warmup", prompt=SYNTHETIC_WARMUP_PROMPT,
                            reference_output="", chunk_id="synthetic-warmup")
    if any(item.prompt == warmup_item.prompt for item in fixture.items):
        raise BenchError("合成 warm-up prompt 與題本題目相同，拒絕污染量測")
    warmup = _warmup(warmup_item, max(concurrencies), host, cast(str, args.model), api_key,
                     fixture.seed, cast(int, args.max_tokens), cache_prompt)
    runs: list[_RunResult] = []
    total_runs = len(concurrencies) * repeat
    for round_number, order in enumerate(orders, start=1):
        for concurrency in order:
            drain_after_s = DRAIN_INTERVAL_S if len(runs) < total_runs - 1 else 0.0
            runs.append(_run_once(fixture.items, concurrency, host, cast(str, args.model),
                                  api_key, fixture.seed, cast(int, args.max_tokens), drain_after_s,
                                  round_number, cache_prompt))
            if drain_after_s:
                LOGGER.info("第 %s 輪併發 %s 完成，等待 %.1f 秒讓伺服器排空",
                            round_number, concurrency, drain_after_s)
                time.sleep(drain_after_s)
    report = {"host": host, "model": cast(str, args.model), "server": server,
              "fixture": str(fixture_path.resolve()), "fixture_sha256": fixture.sha256,
              "started_at": started_at, "seed": fixture.seed, "max_tokens": cast(int, args.max_tokens),
              "request_timeout_s": REQUEST_TIMEOUT_S, "concurrency": concurrencies,
              "repeat": repeat,
              "config": {"cache_prompt": cache_prompt, "order_threshold": order_threshold},
              "rate_definitions": {
                  "tok_s_aggregate": "wall-clock aggregate rate: completion_tokens / wall_s",
                  "prefill_tok_s": "server-side pooled rate: Σprompt_n / Σprompt_ms",
                  "decode_tok_s": "server-side pooled rate: Σpredicted_n / Σpredicted_ms",
                  "note": "server-side pooled rates are distinct from wall-clock tok_s_aggregate; do not interchange or add them",
              },
              "warmup": warmup,
              "warmup_error_type": warmup["error_type"],
              "round_orders": [
                  {"round": index, "concurrency": order} for index, order in enumerate(orders, start=1)
              ], "drain_interval_s": DRAIN_INTERVAL_S, "runs": [run.report for run in runs],
              "order_effects": _order_effects(runs, order_threshold),
              "determinism": _determinism(runs, fixture.items)}
    print(_report_table(report))
    if output is not None:
        _write_json(output, report)
        print(f"JSON 報告：{output}")
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return ("error" not in server and warmup["valid"] is True
            and all(run.report.get("valid") is True for run in runs))


def _build_parser(env: dict[str, str]) -> argparse.ArgumentParser:
    """建立不依賴 .env 存在的兩個子命令 parser。"""
    parser = argparse.ArgumentParser(description="以真實抽取快取量測 llama.cpp 吞吐")
    commands = parser.add_subparsers(dest="command", required=True)
    fixture = commands.add_parser("fixture", help="從 extract cache 建立固定題本（僅 dker）")
    fixture.add_argument("--n", type=_positive_int, required=True, help="題數")
    fixture.add_argument("--out", type=Path, required=True, help="輸出 JSON 路徑（不可省略）")
    fixture.add_argument("--force", action="store_true", help="允許覆寫既有 --out")
    fixture.add_argument("--seed", type=int, default=DEFAULT_SEED, help="固定抽樣種子")
    add_workspace_arg(fixture, env)
    run = commands.add_parser(
        "run", help="對 llama.cpp 跑固定題本（僅 coder）",
        description="這會佔滿伺服器的 slot；跑前確認 dker 沒有在跑索引。",
    )
    run.add_argument("--fixture", type=Path, required=True, help="fixture JSON 路徑")
    run.add_argument("--host", default=DEFAULT_HOST, help="llama.cpp server 基底 URL")
    run.add_argument("--api-key", help="優先於 LLAMA_API_KEY 的 API 金鑰")
    run.add_argument("--model", default=DEFAULT_MODEL, help="送入 API 的模型名稱")
    run.add_argument("--concurrency", type=_concurrencies, default=[1, 2, 4, 8],
                     help="逗號分隔併發度，預設 1,2,4,8")
    run.add_argument("--repeat", type=_positive_int, default=2,
                     help="每個併發度重跑輪數；奇數輪正序、偶數輪反序以平衡時間漂移，預設 2")
    run.add_argument("--order-threshold", type=_nonnegative_float, default=DEFAULT_ORDER_THRESHOLD,
                     help="relative_spread 超過此值才標為順序效應，預設 0.05")
    run.add_argument("--max-tokens", type=_positive_int, default=2048, help="每題生成上限")
    run.add_argument("--cache-prompt", action="store_true", default=False,
                     help="允許 llama.cpp prompt cache（預設關閉，量 cold prefill）")
    run.add_argument("--out", type=Path, help="JSON 報告路徑；省略時印到 stdout")
    run.add_argument("--force", action="store_true", help="允許覆寫既有 --out")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """解析 CLI 並執行指定子命令，將可預期錯誤轉成無 traceback 訊息。"""
    env = load_env(REPO)
    parser = _build_parser(env)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        if args.command == "fixture":
            _run_fixture(args, env)
        else:
            return 0 if _run_benchmark(args) else 1
    except BenchError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
