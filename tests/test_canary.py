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
from _plan_skeleton import skeleton

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
        self.with_caption = 0


def _fake_plan() -> dict:
    """假計畫**只有一份**（`tests/_plan_skeleton.py`），這裡只蓋掉要用的幾段。

    ⚠ 2026-08-21 之前這裡是第二份手寫骨架 —— 而骨架自己的檔頭就寫著
    「骨架各寫一份的話，管線多接一條規則時只會有一邊紅，另一邊安靜地繼續測一個
    不存在的形狀」。補 `CANARY_WATCHED` 那九個量時實測踩到：改完骨架測試還是紅，
    因為紅的是**這一份**。
    """
    return skeleton(
        ctx=SimpleNamespace(n_pages=4, items=[0] * 18),
        noise=SimpleNamespace(mutes=[], held=[1, 2], ratio=0.0, distinct={}),
        charts=_FakeChartPlan(),
    )


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
    """真的沒有 bundle 時，canary 不得把「沒有母體」報成規則失敗。

    ⚠ **也不得報成通過。** 這條測試的名字從一開始就寫著「驗不了」，而它
    2026-08-21 之前斷言的是 `== 0` —— 在這套系統裡 0 就是通過
    （`check-levels.py` 的 `level_of`）。**名字寫三態、斷言寫兩態**，
    於是連測試都一起塌了，沒有任何東西攔得住這盞燈變綠。
    """
    module = _module()
    parsed = tmp_path / "parsed"
    parsed.mkdir()
    monkeypatch.setattr(
        module, "_paths",
        lambda: SimpleNamespace(parsed_dir=parsed, inputs_dir=lambda _ws: tmp_path),
    )

    args = argparse.Namespace(workspace="ws", update=False)
    assert module.cmd_canary(args, {}) == module.CANARY_NO_CORPUS
    assert module.CANARY_NO_CORPUS != 0, "「驗不了」回 0 就跟通過長得一樣"
    assert "驗不了" in capsys.readouterr().out


@pytest.mark.proves_red("daily:canary")
def test_canary_empty_baseline_does_not_report_a_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """**本檔最重要的一條。** 基準是 `{}` 時不得回「金絲雀通過」。

    2026-08-21 實測的實際盤面：`tests/canary-baseline.json` 是 `{}`
    （commit 4a6e533 清空舊庫那 319 份幽靈，**那是對的**；沒做後半步
    才是問題），而它每天印：

        金絲雀通過：0 份基準文件的數字都沒變（另有 172 份新文件尚未納入基準）
        canary rc=0

    附了份數、看起來很像有在守 —— 而它守著 0 份。**「守著 0 份」與
    「守住了 172 份」在報告上長得一模一樣**，這就是整輪工單的形狀。
    """
    module = _module()
    raw_dir = tmp_path / "parsed"
    raw_dir.mkdir()
    (raw_dir / "a.pdf.mineru_raw").mkdir()
    monkeypatch.setattr(
        module, "_paths",
        lambda: SimpleNamespace(parsed_dir=raw_dir, inputs_dir=lambda _ws: tmp_path),
    )
    monkeypatch.setattr(module, "plan_one", lambda raw, source_dir=None: _fake_plan())
    monkeypatch.setattr(
        module, "DocContext",
        lambda raw, source_dir=None: SimpleNamespace(doc_name=raw.name.split(".mineru_raw")[0]))

    baseline = tmp_path / "canary-baseline.json"
    baseline.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(module, "CANARY", baseline)

    rc = module.cmd_canary(argparse.Namespace(workspace="ws", update=False), {})
    assert rc == module.CANARY_NO_BASELINE
    assert rc != 0, "守著 0 份不得回 0"
    captured = capsys.readouterr()
    assert "金絲雀通過" not in captured.out, "基準是空的時候不准說通過"
    assert "基準是空的" in captured.err


@pytest.mark.proves_red("daily:canary")
def test_canary_missing_baseline_file_blocks_and_says_what_to_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """沒有基準檔跟基準是空的是同一件事：有人要去跑 `--update`，是做得完的事。"""
    module = _module()
    raw_dir = tmp_path / "parsed"
    raw_dir.mkdir()
    (raw_dir / "a.pdf.mineru_raw").mkdir()
    monkeypatch.setattr(
        module, "_paths",
        lambda: SimpleNamespace(parsed_dir=raw_dir, inputs_dir=lambda _ws: tmp_path),
    )
    monkeypatch.setattr(module, "plan_one", lambda raw, source_dir=None: _fake_plan())
    monkeypatch.setattr(
        module, "DocContext",
        lambda raw, source_dir=None: SimpleNamespace(doc_name=raw.name.split(".mineru_raw")[0]))
    monkeypatch.setattr(module, "CANARY", tmp_path / "不存在.json")

    rc = module.cmd_canary(argparse.Namespace(workspace="ws", update=False), {})
    assert rc == module.CANARY_NO_BASELINE
    assert "canary --update" in capsys.readouterr().err, "要說清楚該跑什麼"


@pytest.mark.proves_red("daily:canary")
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


# ── 計畫多一個量而沒人表態，要當場紅 ────────────────────────────────────────
# **這一組守的是 `0b3319d` 的病根。** 那個 commit 的訊息寫著「在此之前這三條
# 規則完全沒有被金絲雀守著」，而它的處置只是「把漏掉的三格補上去」—— 補完之後
# 下一條新規則還是會漏，事實上 2026-08-21 盤點時又發現九個量沒被守著
# （包括 `refs.ratio`，也就是體檢表 `pp.preflight` 在抓的那個數字）。
#
# 同一個病在本檔記著犯過四次。第五次會被下面這兩條擋下來。

def _real_plan(tmp_path: Path) -> dict:
    """用真的 Plan 物件組一份計畫（空輸入就夠 —— 這裡盤的是形狀不是數值）。"""
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "scripts"))
    from pp.rules import (  # noqa: PLC0415
        chart_type,
        cover_ad_page,
        empty_table,
        latex_fix,
        layout_noise,
        margin_text,
        reference_section,
        title_block,
    )
    return {
        "noise": layout_noise.plan([], 0),
        "refs": reference_section.plan([]),
        "title": title_block.plan([]),
        "tables": empty_table.plan([], 595.0, 842.0),
        "charts": chart_type.plan([], tmp_path),
        "latex": latex_fix.plan([]),
        "cover_ad": cover_ad_page.plan([], claimed=set()),
        "margin": margin_text.plan([], claimed=set()),
    }


def test_every_quantity_in_the_plan_is_either_watched_or_explicitly_not(
    tmp_path: Path,
) -> None:
    """**本檔第二重要的一條。** 計畫裡的每一個量都要表態。

    紅的時候不是「測試壞了」，是「有一條規則多算了一個東西，而沒有人決定
    金絲雀要不要守它」。處置二選一：加進 `CANARY_WATCHED`（同時要在
    `canary_row()` 記下來、重跑 `canary --update`、在 commit 訊息說明），
    或加進 `CANARY_NOT_WATCHED` **並寫下理由** —— 沒有理由的排除跟忘記記
    長得一模一樣。
    """
    module = _module()
    found = module.plan_quantities(_real_plan(tmp_path))
    declared = set(module.CANARY_WATCHED) | set(module.CANARY_NOT_WATCHED)

    unaccounted = sorted(found - declared)
    assert not unaccounted, (
        "計畫多了這些量，但沒有人決定金絲雀要不要守：\n  " + "\n  ".join(unaccounted))

    ghosts = sorted(declared - found)
    assert not ghosts, (
        "對照表上有計畫裡已經不存在的量（改名或刪掉了）：\n  " + "\n  ".join(ghosts))


def test_watched_quantities_all_land_in_the_baseline(tmp_path: Path) -> None:
    """宣告要守的量，`canary_row()` 真的要記下來 —— 宣告不等於記錄。"""
    module = _module()
    row = module.canary_row(_fake_plan())
    missing = sorted(set(module.CANARY_WATCHED.values()) - set(row))
    assert not missing, f"對照表說要守，但基準裡沒有這幾格：{missing}"
    assert set(module._CANARY_KEYS) == set(row), "比對的欄位與記錄的欄位對不起來"


def test_canary_sections_match_what_plan_one_actually_returns() -> None:
    """`CANARY_SECTIONS` 要跟 `plan_one()` 真的回傳的段名一致。

    少一段就整段不被盤點 —— 而「整段沒人盤」跟「盤過沒事」在測試報告上
    長得一樣，那正是這一輪在修的形狀。
    """
    import ast  # noqa: PLC0415

    tree = ast.parse((ROOT / "scripts" / "postprocess.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "plan_one")
    ret = next(n for n in ast.walk(fn) if isinstance(n, ast.Return))
    assert isinstance(ret.value, ast.Dict)
    keys = {k.value for k in ret.value.keys if isinstance(k, ast.Constant)}
    module = _module()
    assert keys - {"ctx"} == set(module.CANARY_SECTIONS), (
        f"plan_one 回傳 {sorted(keys)}，但 CANARY_SECTIONS 是 "
        f"{sorted(module.CANARY_SECTIONS)}")
