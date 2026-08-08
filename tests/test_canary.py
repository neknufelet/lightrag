"""canary 收集的必須是扁平、可序列化的數字列。

這支測試存在的理由是一次真實的回歸：路徑遷移（commit 51268ac）在 cmd_canary
加 source_dir 參數時，把 `canary_row(plan_one(...))` 寫成了 `plan_one(...)`，
於是 canary_row() 定義著卻沒有人呼叫。後果有兩層，而且第二層更安靜：

  1. `canary --update` 直接崩潰（ChartPlan 不是 JSON 可序列化的）
  2. 比對時 `row.get("pages")` 恆為 None —— **只要基準裡還有同名文件，
     每一個量都會被判成漂移**。當時之所以沒炸，只是因為重建後基準裡的
     20 份文件現況都不存在，迴圈根本沒進到比對那一段。

所以這裡測的是**行為不是字面**：真的呼叫 cmd_canary(--update)，真的把結果寫成
JSON 再讀回來，確認每一份都帶著 _CANARY_KEYS 的全部鍵。忘了呼叫 canary_row
時，這兩條斷言都會紅。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "postprocess.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("postprocess_canary", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeChartPlan:
    """刻意不可 JSON 序列化 —— 真正的 ChartPlan 也不是。

    如果 cmd_canary 把整個 plan 塞進基準檔，json.dumps 會在這裡爆炸，
    測試就抓到了那個回歸。
    """

    def __init__(self) -> None:
        self.convert: list[int] = []
        self.dangling: list[int] = []


def _fake_plan() -> dict:
    return {
        "ctx": SimpleNamespace(n_pages=4, items=[0] * 18),
        "noise": SimpleNamespace(mutes=[], held=[1, 2], ratio=0.0),
        "tables": SimpleNamespace(total=0, repairable=[], review=[]),
        "charts": _FakeChartPlan(),
        "latex": SimpleNamespace(items=0, times=0, partials=0, glued=0, vetoed=[]),
    }


def test_canary_update_writes_flat_serialisable_rows(tmp_path, monkeypatch):
    module = _module()
    baseline = tmp_path / "canary-baseline.json"
    monkeypatch.setattr(module, "CANARY", baseline)
    monkeypatch.setattr(module, "find_bundles",
                        lambda ws, doc, **kwargs: [tmp_path / "示例.pdf.mineru_raw"])
    monkeypatch.setattr(module, "DocContext",
                        lambda raw, source_dir=None: SimpleNamespace(doc_name="示例.pdf"))
    monkeypatch.setattr(module, "plan_one", lambda raw, source_dir=None: _fake_plan())
    monkeypatch.setattr(module, "_paths",
                        lambda: SimpleNamespace(inputs_dir=lambda ws: tmp_path))

    args = argparse.Namespace(workspace="ws", update=True)
    assert module.cmd_canary(args, {}) == 0

    # 忘了呼叫 canary_row 的話，上面那行就會因為 ChartPlan 不可序列化而丟 TypeError。
    written = json.loads(baseline.read_text())
    assert set(written) == {"示例.pdf"}

    row = written["示例.pdf"]
    missing = [k for k in module._CANARY_KEYS if k not in row]
    assert not missing, f"基準列缺少被追蹤的量：{missing}"
    assert row["pages"] == 4 and row["items"] == 18 and row["held"] == 2


def test_canary_row_only_contains_tracked_numbers():
    """基準列不得夾帶物件 —— 夾帶了就代表又把整個 plan 寫進去了。"""
    module = _module()
    row = module.canary_row(_fake_plan())
    assert set(row) == set(module._CANARY_KEYS)
    for key, value in row.items():
        assert isinstance(value, (int, float)), f"{key} 不是數字：{type(value).__name__}"
    json.dumps(row)  # 必須可序列化，否則 --update 會在真實環境崩潰


def test_canary_empty_mother_is_unverifiable_not_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """真的沒有 bundle 時，canary 不得把「沒有母體」報成規則失敗。"""
    module = _module()
    parsed = tmp_path / "parsed"
    parsed.mkdir()
    monkeypatch.setattr(
        module, "_paths",
        lambda: SimpleNamespace(parsed_dir=parsed, inputs_dir=lambda _ws: tmp_path),
    )

    args = argparse.Namespace(workspace="ws", update=False)
    assert module.cmd_canary(args, {}) == 0
    assert "驗不了" in capsys.readouterr().out


def test_canary_new_document_is_info_but_drift_is_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """新增未入基準的文件是資訊；既有文件數字漂移仍是失敗。"""
    module = _module()
    raw_dir = tmp_path / "parsed"
    raw_dir.mkdir()
    raw_base = raw_dir / "base.pdf.mineru_raw"
    raw_new = raw_dir / "new.pdf.mineru_raw"
    raw_base.mkdir()
    raw_new.mkdir()
    monkeypatch.setattr(
        module, "_paths",
        lambda: SimpleNamespace(parsed_dir=raw_dir, inputs_dir=lambda _ws: tmp_path),
    )
    monkeypatch.setattr(module, "plan_one", lambda raw, source_dir=None: _fake_plan())
    monkeypatch.setattr(
        module, "DocContext",
        lambda raw, source_dir=None: SimpleNamespace(doc_name=raw.name.split(".mineru_raw")[0]),
    )

    baseline = tmp_path / "canary-baseline.json"
    monkeypatch.setattr(module, "CANARY", baseline)
    base_row = module.canary_row(_fake_plan())
    drifted_row = {**base_row, "items": 999}
    baseline.write_text(json.dumps({"base.pdf": drifted_row}), encoding="utf-8")
    assert module.cmd_canary(argparse.Namespace(workspace="ws", update=False), {}) == 2
    assert "金絲雀失敗" in capsys.readouterr().out

    monkeypatch.setattr(module, "find_bundles", lambda ws, doc, **kwargs: [raw_base, raw_new])
    baseline.write_text(json.dumps({"base.pdf": base_row}), encoding="utf-8")
    assert module.cmd_canary(argparse.Namespace(workspace="ws", update=False), {}) == 0
    output = capsys.readouterr().out
    assert "新文件尚未納入基準" in output
