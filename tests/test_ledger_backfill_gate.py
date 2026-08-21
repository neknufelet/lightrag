r"""回填體檢表時只補指定欄位 —— **不覆蓋人工查證過的格子**。

**為什麼有這一檔。** `ledger-backfill.py` 是機械回填：它從 `job.json` 與
`scan-partial` 重算判定，**不知道哪一格是人看過之後才改的**。

2026-08-21 實測（dker，172 份）不加 `--gate` 直接跑會寫 516 格，其中：

    pp.equations   172 格　← 真的空著，要補的就是這些
    pp.preflight   172 格　← 已經有值，而且其中 3 格會從 pass 改回 unverifiable
    pp.tables      172 格　← 已經有值

那 3 格 `pp.preflight` 正是當天有人逐項看過原文（確認消音拿掉的全是頁首頁尾、
期刊招牌、參考文獻，沒有一項是正文）之後才改成通過的。機械回填會把那個結論
抹掉，而且**畫面上只會顯示「寫入 516 格」**，看不出剛剛毀掉了什麼。

⇒ 「補上空白欄位」與「重算全部欄位」是兩件事。之前只有後者。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

_spec = importlib.util.spec_from_file_location(
    "ledger_backfill", ROOT / "scripts" / "ledger-backfill.py")
assert _spec and _spec.loader
bf = importlib.util.module_from_spec(_spec)
sys.modules["ledger_backfill"] = bf
_spec.loader.exec_module(bf)

# 一份縮小版的計畫，欄位順序與 `main()` 裡 `planned` 的元素一致：
# (文件, 欄位, 狀態, 備註, 數值)
PLAN = [
    ("A", "pp.equations", "pass", "命中 0 處", 0.0),
    ("A", "pp.preflight", "unverifiable", "機械判定：消音比例超標", None),
    ("A", "pp.tables", "pass", "共 3 張", None),
    ("B", "pp.equations", "pass", "命中 0 處", 0.0),
    ("B", "pp.preflight", "pass", "機械計畫判定 clean", None),
]


def test_without_the_flag_everything_is_written() -> None:
    """不指定就是全寫 —— 這是舊行為，也是危險所在，要留著才看得出差別。"""
    assert bf.select_gates(PLAN, None) == PLAN
    assert bf.select_gates(PLAN, []) == PLAN


def test_only_the_named_gate_survives() -> None:
    """**本檔的重點。** 只補 `pp.equations`，人工查證過的那格原封不動。"""
    got = bf.select_gates(PLAN, ["pp.equations"])
    assert [row[1] for row in got] == ["pp.equations", "pp.equations"]
    assert not any(row[1] == "pp.preflight" for row in got), (
        "人工查證過的 pp.preflight 被排進回填了")


def test_several_gates_can_be_named() -> None:
    got = bf.select_gates(PLAN, ["pp.equations", "pp.tables"])
    assert sorted({row[1] for row in got}) == ["pp.equations", "pp.tables"]


def test_a_typo_in_the_gate_name_is_refused_not_silently_empty() -> None:
    """**打錯字要當場拒絕。**

    靜靜回空清單的話，`--gate pp.equation`（少個 s）會印「寫入 0 格」然後
    rc=0 —— 看起來跟做完了一模一樣。鐵則 1：拒絕，不猜。
    """
    with pytest.raises(ValueError, match="不認得的欄位"):
        bf.select_gates(PLAN, ["pp.equation"])
    # 一對一錯也要整批拒絕，不能只做對的那半邊。
    with pytest.raises(ValueError, match="不認得的欄位"):
        bf.select_gates(PLAN, ["pp.equations", "pp.equation"])
