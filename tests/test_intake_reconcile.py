"""把「其實已經進庫」的假失敗撿回來 —— 判準的單元測試。

2026-08-10：一批 89 份進料，84 份被判失敗，而資料庫那側 159 份**全部是
processed**。死因是契約檢查裡的 A-19 斷言「pipeline 現在是閒的」，而同批的
鄰居還在跑。流程那側已經修好（檢查挪到整批抽完之後），這裡處理的是**已經
被誤殺的那些紀錄**。

**不是無條件翻牌。** 兩個獨立來源都說沒事才改：
  1. LightRAG 說這份是 processed
  2. 重跑一次該份的契約檢查，沒有 hard 失敗
少了第 2 條的話，真的有問題的文件會被一起洗白 —— 而那正是這批檢查存在的理由。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "intake_reconcile", ROOT / "scripts" / "intake-reconcile.py")
assert _spec is not None and _spec.loader is not None
reconcile = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reconcile)

FLIP = reconcile.FLIP
KEEP = reconcile.KEEP
SKIP = reconcile.SKIP


def test_a_failure_that_actually_indexed_and_still_passes_gets_flipped() -> None:
    """兩個來源都說沒事 —— 這才是要撿回來的那一種。"""
    verdict, why = reconcile.decide("failed", "processed", verify_ok=True)
    assert verdict is FLIP, why


def test_a_failure_that_indexed_but_fails_its_contract_stays_failed() -> None:
    """**控制組,而且是最重要的一條。**

    沒有它的話，這支工具會退化成「把所有失敗都改成成功」—— 那不是修復，
    是把紅燈關掉。真的有問題的文件必須留在失敗裡。
    """
    verdict, why = reconcile.decide("failed", "processed", verify_ok=False)
    assert verdict is KEEP
    assert "契約" in why, why


def test_a_failure_that_never_reached_the_index_stays_failed() -> None:
    """索引裡沒有這份 —— 那是真的失敗，不是假的。"""
    verdict, why = reconcile.decide("failed", None, verify_ok=True)
    assert verdict is KEEP
    assert "索引" in why, why


def test_a_document_still_being_processed_is_left_alone() -> None:
    """還在跑的不要碰。此刻的契約檢查對它不成立，翻牌只會製造新的假象。"""
    verdict, _ = reconcile.decide("failed", "processing", verify_ok=True)
    assert verdict is KEEP


def test_a_parse_failure_is_never_touched() -> None:
    """解析失敗的從來沒碰過索引 —— 它不在這支工具的管轄範圍。"""
    verdict, _ = reconcile.decide("failed_parse", None, verify_ok=True)
    assert verdict is SKIP


def test_an_already_indexed_job_is_not_rewritten() -> None:
    """已經是 indexed 的不重寫 —— 這支只處理失敗那一堆。"""
    verdict, _ = reconcile.decide("indexed", "processed", verify_ok=True)
    assert verdict is SKIP


def test_status_matching_ignores_case_the_way_lightrag_reports_it() -> None:
    """LightRAG 的狀態字面值實查是小寫，但別靠它 —— 大小寫變了不該讓工具靜靜失效。"""
    verdict, _ = reconcile.decide("failed", "PROCESSED", verify_ok=True)
    assert verdict is FLIP
