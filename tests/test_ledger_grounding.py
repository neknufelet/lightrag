"""接地率 → 體檢表的三態。**分母只算「字串比對有鑑別力」的那些。**

`extract-check.py` 的原理：每個抽出的實體名字，應該在它來源的那個 chunk 裡
找得到；模型編出來的不會。確定性、不呼叫任何模型、不花錢。

⚠ 但有一整類實體**驗不了**：來源 chunk 全是表格或公式時，字串比對沒有鑑別力。
那既不是幻覺也不是通過 —— 把它算進分母會稀釋比例、算成失敗會誤殺。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))

from _scripts import load  # noqa: E402

bf = load("ledger_backfill", "ledger-backfill.py")

T = 0.10


def test_a_clean_document_passes() -> None:
    """40 個實體、37 個接得回原文、3 個符號型 → 可疑 0，過。"""
    state, note, value = bf.grounding_entry(
        {"total": 40, "ok": 37, "missing_chunk": 0, "symbolic": 3}, T)
    assert state == "pass"
    assert value == 0.0
    assert "符號型 3" in note, note


def test_symbolic_entities_are_not_in_the_denominator() -> None:
    """**這條是整支的重點。** 10 個有鑑別力的裡 1 個可疑 = 10%，不是 1/110。

    拿符號型稀釋分母的話，一份幾乎全是公式的文件永遠不會超標 —— 而那正是
    最需要被看的那種。
    """
    _, _, value = bf.grounding_entry(
        {"total": 110, "ok": 9, "missing_chunk": 0, "symbolic": 100}, T)
    assert abs(value - 0.10) < 1e-9, value


def test_over_the_threshold_is_a_fail() -> None:
    """超過 10% 就是 fail，而且理由要帶得出分子分母。"""
    state, note, value = bf.grounding_entry(
        {"total": 20, "ok": 15, "missing_chunk": 0, "symbolic": 0}, T)
    assert state == "fail"
    assert abs(value - 0.25) < 1e-9
    assert "5" in note and "20" in note, note


def test_a_document_made_only_of_symbols_is_unverifiable() -> None:
    """全部都是符號型 ⇒ **沒得驗**，不是通過。

    分母 0 時比例算不出來。記 `pass` 等於宣稱驗過了，而字串比對對這份文件
    從頭到尾沒有鑑別力。
    """
    state, note, value = bf.grounding_entry(
        {"total": 12, "ok": 0, "missing_chunk": 0, "symbolic": 12}, T)
    assert state == "unverifiable"
    assert value is None
    assert "鑑別力" in note, note


def test_a_document_with_no_entities_is_unverifiable() -> None:
    """一個實體都沒抽出來 —— 那也不是「通過」，是沒東西可驗。"""
    state, _, value = bf.grounding_entry(
        {"total": 0, "ok": 0, "missing_chunk": 0, "symbolic": 0}, T)
    assert state == "unverifiable"
    assert value is None


def test_entities_whose_source_chunk_vanished_are_not_counted_as_suspect() -> None:
    """來源 chunk 找不到 ⇒ 不是幻覺，是簿記問題。**不進分子也不進分母。**

    算成可疑的話，索引重建期間的一次不一致會在表上看起來像模型在編東西。
    """
    state, note, value = bf.grounding_entry(
        {"total": 20, "ok": 10, "missing_chunk": 10, "symbolic": 0}, T)
    assert state == "pass"
    assert value == 0.0
    assert "10" in note, note
