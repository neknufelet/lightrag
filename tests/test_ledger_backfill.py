"""回填體檢表：同一份文件有好幾個 job 時，取哪一個。

2026-08-11 實測：2072 格裡 1940 格未設定。材料本來就在磁碟上（每個 job 的
`job.json` 都留著當時的 `plan`），這支把它讀回來 —— 但**同一份文件可能有好幾個
job**（重試、重置過的），取錯的話會拿一次失敗的重試蓋掉成功那次的判定，
而表上看不出來。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

_spec = importlib.util.spec_from_file_location(
    "ledger_backfill", ROOT / "scripts" / "ledger-backfill.py")
assert _spec and _spec.loader
bf = importlib.util.module_from_spec(_spec)
sys.modules["ledger_backfill"] = bf
_spec.loader.exec_module(bf)


def test_the_latest_job_wins() -> None:
    """重試過的文件取**最後更新**那次，不是第一次。"""
    jobs = [
        {"filename": "a.pdf", "updated_at": "2026-08-01T00:00:00", "decision": "novel"},
        {"filename": "a.pdf", "updated_at": "2026-08-09T00:00:00", "decision": "clean"},
    ]
    assert bf.latest_job_per_document(jobs)["a.pdf"]["decision"] == "clean"


def test_a_job_without_a_timestamp_never_wins() -> None:
    """缺 `updated_at` 的當成最舊 —— **不讓缺欄位的意外勝出**。

    缺欄位多半是舊格式或半路壞掉的紀錄，拿它蓋掉有時間戳的那份是最難察覺的
    那種錯：表上會有一個值，只是來源不對。
    """
    jobs = [
        {"filename": "a.pdf", "decision": "novel"},
        {"filename": "a.pdf", "updated_at": "2026-08-09T00:00:00", "decision": "clean"},
    ]
    assert bf.latest_job_per_document(jobs)["a.pdf"]["decision"] == "clean"


def test_a_job_without_a_filename_is_dropped() -> None:
    """沒有檔名就對不到文件。**丟掉，不要猜**（鐵則 1：拒絕，不猜）。"""
    assert bf.latest_job_per_document([{"updated_at": "2026-08-09T00:00:00"}]) == {}


def test_each_document_appears_once() -> None:
    """三個 job 兩份文件 → 兩筆。回填是逐份寫的，重複會互相覆蓋。"""
    jobs = [
        {"filename": "a.pdf", "updated_at": "2026-08-01T00:00:00"},
        {"filename": "a.pdf", "updated_at": "2026-08-02T00:00:00"},
        {"filename": "b.pdf", "updated_at": "2026-08-01T00:00:00"},
    ]
    assert sorted(bf.latest_job_per_document(jobs)) == ["a.pdf", "b.pdf"]
