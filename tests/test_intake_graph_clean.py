r"""一批抽完就清位置標記 —— **不能靠人記得**。

規則 2a（不要把 Figure N／Equation N 抽成節點）寫在抽取提示詞裡，實測三次都沒
守住，而且守不住的程度隨模型而變。所以每抽一批就會長出一批新的 ——
2026-08-13 手動清掉 376 個，而那些本來就不該需要人發現。

⚠ **清不掉不能擋這一批**：文件已經進索引了。擋下整批等於用一件可以晚點做的事
去否定一件已經做完的事。`compat-check` A-33 會在沒清乾淨時亮燈。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# ⚠ **用一般 import，不要自己 exec 一份。** 第一版用 `spec_from_file_location`
# 另建了一個 module 物件又塞回 `sys.modules["intake"]`，於是 `test_intake.py`
# 拿到的是我這一份 —— 它 monkeypatch 的模組層常數落在另一個物件上，
# 那支的 `MAX_UPLOAD_BYTES` 測試當場變紅。**同一個模組兩個物件**，
# 正是這個專案反覆記著的那個形狀，連測試也不例外。
import intake  # noqa: E402


class _Runner(intake.SubprocessRunner):
    """只換掉 `_run`，其餘照原樣 —— 測的是編排不是子行程。"""

    def __init__(self, results: list) -> None:                    # noqa: ANN001
        self.calls: list[list[str]] = []
        self._results = results
        self.python, self.repo = "python3", ROOT
        self.command_timeout = 1.0

    def _run(self, command: list[str], timeout: float) -> intake.OperationResult:
        self.calls.append(command)
        return self._results.pop(0)


def _plan(tmp: Path, names: list[str]) -> Path:
    p = tmp / "graph-clean" / "intake-plan.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"certain": names}), encoding="utf-8")
    return p


def test_nothing_to_clean_does_not_call_apply(tmp_path: Path) -> None:
    """沒東西可清就不要動圖譜。**apply 是不可逆的,不該在沒事時被叫。**"""
    r = _Runner([intake.OperationResult(True, "planned")])
    out = r.clean_graph_labels("ws", _plan(tmp_path, []))
    assert out.ok and len(r.calls) == 1 and r.calls[0][2] == "plan"


def test_labels_found_triggers_apply(tmp_path: Path) -> None:
    """有東西就清,而且回報清了幾個。"""
    r = _Runner([intake.OperationResult(True, "planned"), intake.OperationResult(True, "applied")])
    out = r.clean_graph_labels("ws", _plan(tmp_path, ["Chapter 1", "Eq. 4.43"]))
    assert out.ok and "2" in out.output
    assert [c[2] for c in r.calls] == ["plan", "apply"] and "--yes" in r.calls[1]


def test_a_failed_plan_never_reaches_apply(tmp_path: Path) -> None:
    """**控制組。** 計畫都拿不到就去刪,是拿沒驗過的清單動不可逆的東西。"""
    r = _Runner([intake.OperationResult(False, "", "psql 掛了")])
    out = r.clean_graph_labels("ws", _plan(tmp_path, ["Chapter 1"]))
    assert not out.ok and [c[2] for c in r.calls] == ["plan"]


def test_an_unreadable_plan_is_reported_not_guessed(tmp_path: Path) -> None:
    """讀不到計畫要說出來,不能當成「沒東西可清」—— 那會靜靜地跳過清除。"""
    bad = tmp_path / "graph-clean" / "intake-plan.json"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("{ 這不是 JSON", encoding="utf-8")
    r = _Runner([intake.OperationResult(True, "planned")])
    out = r.clean_graph_labels("ws", bad)
    assert not out.ok and "讀不到清除計畫" in (out.error or "")
