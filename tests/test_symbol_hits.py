"""Run with: `uvx --quiet pytest tests/test_symbol_hits.py -q`."""
from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "symbol-hits.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("symbol_hits", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _answer() -> list[dict[str, str]]:
    return [{"name": "Restated", "verdict": "restated"}, {"name": "Correct", "verdict": "correct"},
            {"name": "Wrong", "verdict": "wrong"}]


class _Rag:
    def __init__(self, module: ModuleType, labels: list[str], results: dict[str, object]) -> None:
        self.module, self.labels_out, self.results = module, labels, results

    def labels(self) -> list[str]:
        return self.labels_out

    def popular(self, _count: int) -> list[str]:
        return list(self.results)

    def entities_for(self, query: str, _top_k: int) -> list[str]:
        value = self.results[query]
        if isinstance(value, Exception):
            raise value
        assert isinstance(value, list)
        return value


class _Response:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()


# `Rag` 2026-08-09 從 `entity-merge.py` 搬到 `pp/ragapi.py`（`graph-clean.py` 也要用）。
# 這支測試釘的是「查詢參數的單一來源」，所以跟著搬 —— 留在舊路徑的話它會一直紅，
# 而一直紅的測試遲早會被人 skip 掉。
RAGAPI = ROOT / "scripts" / "pp" / "ragapi.py"


def _merge_query_literals() -> dict[str, object]:
    tree = ast.parse(RAGAPI.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "entities_for":
            for call in ast.walk(node):
                if isinstance(call, ast.Call) and len(call.args) >= 3 and isinstance(call.args[2], ast.Dict):
                    return {key.value: value.value for key, value in zip(call.args[2].keys, call.args[2].values, strict=True)
                            if isinstance(key, ast.Constant) and isinstance(value, ast.Constant)}
    raise AssertionError(f"找不到 {RAGAPI.name} Rag.entities_for 的請求 body")


def test_query_contract_is_read_from_ragapi_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """三個靜態參數必須從 `pp/ragapi.py` 原始碼釘住，不能自行猜。"""
    module, seen = _module(), {}
    literals = _merge_query_literals()

    def fake_urlopen(request: object, **_kwargs: object) -> _Response:
        seen.update(json.loads(request.data.decode()))
        return _Response({"data": {"entities": []}})

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    module._ReadOnlyRag({}).entities_for("seed", 40)
    assert {key: seen[key] for key in ("mode", "only_need_context", "chunk_top_k")} == literals
    assert seen == {"query": "seed", "top_k": 40, **literals}


def test_duplicate_entity_in_one_query_counts_two_slots() -> None:
    module = _module()
    report = module._measure(_Rag(module, ["Restated", "Correct", "Wrong"],
                                  {"q": ["Restated", "Restated", "Correct"]}),
                             _answer(), [{"name": name} for name in ("Restated", "Correct", "Wrong")], 1, 40)
    assert report["entity_slots"] == 3
    assert report["view_1_answer_key"]["groups"]["restated"]["hit_slots"] == 2


def test_unmatched_answer_name_is_reported_separately() -> None:
    module = _module()
    answer = [{"name": "Missing", "verdict": "restated"}, *_answer()[1:]]
    report = module._measure(_Rag(module, ["Correct", "Wrong"], {"q": ["Correct"]}), answer,
                             [{"name": name} for name in ("Missing", "Correct", "Wrong")], 1, 40)
    group = report["view_1_answer_key"]["groups"]["restated"]
    assert report["health_checks"]["answer_key"]["not_in_labels"] == ["Missing"]
    assert group["label_unmatched_names"] == ["Missing"] and group["label_matched_n"] == 0


def test_query_failure_marks_population_incomplete(capsys: pytest.CaptureFixture[str]) -> None:
    module = _module()
    report = module._measure(_Rag(module, ["Restated", "Correct", "Wrong"],
                                  {"q": module.QueryFailure("timeout", "late")}), _answer(),
                             [{"name": name} for name in ("Restated", "Correct", "Wrong")], 1, 40)
    module._print_report(report)
    assert "本次統計母體不完整" in capsys.readouterr().out


def test_existing_output_requires_force(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module, symbolic, answer, output = _module(), tmp_path / "symbolic.json", tmp_path / "answer.json", tmp_path / "out.json"
    # 這條測的是「已有輸出要 --force」，跟 .env 無關。2026-08-07 之前它在 coder 上
    # 能過，是因為 load_env 在檔案不存在時**靜默回空字典**；那個行為已改成丟例外，
    # 所以這裡要顯式給一份空設定，而不是靠副作用。
    monkeypatch.setattr(module, "load_env", lambda _repo, **_kw: {})
    symbolic.write_text('{"entities": [{"name": "Restated"}]}', encoding="utf-8")
    answer.write_text(json.dumps({"items": _answer()}), encoding="utf-8")
    output.write_text("old", encoding="utf-8")
    with pytest.raises(SystemExit):
        module.main(["--symbolic", str(symbolic), "--answer-key", str(answer), "--workspace", "test", "--out", str(output)])
    monkeypatch.setattr(module, "_measure", lambda *_args: {"queries": [], "entity_slots": 0,
                        "query_execution": {"complete": True}, "view_1_answer_key": {"groups": {}},
                        "view_2_symbolic_bucket": {}, "health_checks": {}})
    monkeypatch.setattr(module, "_print_report", lambda _report: None)
    assert module.main(["--symbolic", str(symbolic), "--answer-key", str(answer), "--workspace", "test", "--out", str(output), "--force"]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["generated_from"] == "symbol-hits.py"
