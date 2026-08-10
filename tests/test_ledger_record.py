"""體檢表的寫入判準：CLI 與 intake 自動寫入必須走**同一支**。

**為什麼要抽出來。** 守衛原本全在 `cmd_set` 裡（閘門白名單、三態白名單、
「驗不了必須附理由」）。intake 要自動寫體檢表時如果直接呼叫 `load`／`save`，
那些守衛就被繞過了 —— 而繞過的症狀是「表上多出一個沒人認得的閘門」或
「一堆沒有理由的驗不了」，兩者都不會報錯，只會讓表慢慢失去意義。

同一件事兩個地方是本專案踩過五次的形狀。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import ledger  # noqa: E402


def test_a_verdict_lands_in_the_document_record(tmp_path: Path) -> None:
    ledger.record(tmp_path, "ws", "甲.pdf", "pp.preflight", "pass", note="計畫判定 clean")

    rec = ledger.load(tmp_path, "ws", "甲.pdf")
    assert rec["gates"]["pp.preflight"]["state"] == "pass"
    assert rec["gates"]["pp.preflight"]["note"] == "計畫判定 clean"
    assert rec["gates"]["pp.preflight"]["at"], "沒有記下時間，之後分不出新舊"


def test_an_unknown_gate_is_refused(tmp_path: Path) -> None:
    """**白名單不是提示。** 打錯字的閘門名會安靜地長出第八個欄位，
    而總表少一格沒有人會發現（鐵則 1：拒絕，不猜）。"""
    with pytest.raises(ValueError, match="閘門"):
        ledger.record(tmp_path, "ws", "甲.pdf", "pp.preflght", "pass")


def test_unverifiable_without_a_reason_is_refused(tmp_path: Path) -> None:
    """**這條是三態存在的理由。**

    沒有理由的「驗不了」跟「沒檢查」在表上長得一模一樣。把它收下來，
    等於讓「不知道」偽裝成「查過了」。
    """
    with pytest.raises(ValueError, match="理由"):
        ledger.record(tmp_path, "ws", "甲.pdf", "pp.tables", "unverifiable")

    ledger.record(tmp_path, "ws", "甲.pdf", "pp.tables", "unverifiable",
                  note="2 張表待查")
    assert ledger.load(tmp_path, "ws", "甲.pdf")["gates"]["pp.tables"]["state"] == "unverifiable"


def test_writing_the_same_gate_twice_keeps_the_latest(tmp_path: Path) -> None:
    """重跑會覆寫 —— 體檢表記的是「現在的判定」，不是歷史。"""
    ledger.record(tmp_path, "ws", "甲.pdf", "pp.tables", "pass")
    ledger.record(tmp_path, "ws", "甲.pdf", "pp.tables", "fail", note="重跑後變了")

    entry = ledger.load(tmp_path, "ws", "甲.pdf")["gates"]["pp.tables"]
    assert entry["state"] == "fail"
    assert entry["note"] == "重跑後變了"


def test_the_cli_goes_through_the_same_judgement() -> None:
    """CLI 不得自己再寫一份守衛 —— 兩份只要有人改一邊就會靜靜地不一致。"""
    src = (ROOT / "scripts" / "ledger.py").read_text(encoding="utf-8")
    body = src[src.index("def cmd_set("):src.index("def cmd_show(")]
    assert "record(" in body, "cmd_set 沒有走共用的 record()"
    assert "unverifiable 必須" not in body, "CLI 裡還留著第二份守衛"
