r"""一批抽完就量接地率 —— **不能靠人記得跑**。

判定本身早就寫好了（`grounding_entry`），三態、分母、理由都驗過。
缺的只有一條線：**生產路徑零呼叫點**，只有手動回填工具在叫它。
「寫好的檢查沒被呼叫等於沒寫」——這支測的就是那條線接上了。

⚠ **不擋這一批**：接地率要等抽取做完才量得到，那時文件已經在圖譜裡。
擋下整批等於用一件量測結果去否定一件已經發生的事。判 fail 就記進體檢表、
讓審核台顯示紅，人回頭處理（PO 2026-08-16 裁決）。

⚠ **拿不到報告就一格都不寫。** 沒跑過的閘門填 `pass` 就是說謊 —— 那正是
`ledger` 三態存在的理由。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# ⚠ 一般 import，不要自己 exec 一份 —— 見 test_intake_graph_clean.py 的說明。
import intake  # noqa: E402
import ledger  # noqa: E402

DOC = "2024 - A Compact Low-Frequency Acoustic Perfect Absorber.pdf"
CLEAN = {"total": 81, "ok": 79, "missing_chunk": 0, "symbolic": 2}
DIRTY = {"total": 60, "ok": 40, "missing_chunk": 0, "symbolic": 10}   # 可疑 10/50 = 20%
SYMBOLIC_ONLY = {"total": 12, "ok": 0, "missing_chunk": 0, "symbolic": 12}


class _Runner(intake.SubprocessRunner):
    """只換掉 `_run`，其餘照原樣 —— 測的是編排不是子行程。"""

    def __init__(self, results: list) -> None:                        # noqa: ANN001
        self.calls: list[list[str]] = []
        self._results = results
        self.python, self.repo = "python3", ROOT
        self.command_timeout = 1.0

    def _run(self, command: list[str], timeout: float,
             *, merge_stderr: bool = True) -> intake.OperationResult:
        self.calls.append(command)
        # extract-check 的 stdout 要餵給 `json.loads`，併了 stderr 就會被污染
        # （2026-08-30 compat-check 走過同一個坑）。
        assert not merge_stderr, "要解析的輸出不能併 stderr"
        return self._results.pop(0)


def _payload(per_doc: dict) -> str:
    return json.dumps({"per_doc": per_doc, "ungrounded": []})


# ── 判定本身：搬家之後仍然只有一份 ─────────────────────────────────────────

def test_the_judgement_lives_in_ledger_not_in_the_backfill_tool() -> None:
    """判準只能有一個家。`ledger.py` import 得動，帶連字號的腳本不行。"""
    assert hasattr(ledger, "grounding_entry")


def test_the_backfill_tool_reuses_it_instead_of_keeping_a_copy() -> None:
    """**控制組。** 兩份判準會漂移 —— 這個專案被「兩條路」咬過不只一次。"""
    sys.path.insert(0, str(ROOT / "tests"))
    from _scripts import load
    bf = load("ledger_backfill", "ledger-backfill.py")
    assert bf.grounding_entry is ledger.grounding_entry


# ── 跑報告 ────────────────────────────────────────────────────────────────

def test_a_report_comes_back_as_per_document_stats() -> None:
    r = _Runner([intake.OperationResult(True, _payload({DOC: CLEAN}))])
    out, stats = r.grounding_report("ws")
    assert out.ok and stats == {DOC: CLEAN}
    assert "extract-check.py" in " ".join(r.calls[0]) and "--json" in r.calls[0]


def test_a_failed_subprocess_yields_no_stats_and_does_not_raise() -> None:
    """**不擋這一批。** 量不到就是量不到，不能讓已經進庫的文件卡住。"""
    r = _Runner([intake.OperationResult(False, "", "psql 掛了")])
    out, stats = r.grounding_report("ws")
    assert not out.ok and stats == {}


def test_unreadable_json_is_reported_not_guessed() -> None:
    """讀不到要說出來，不能當成「這批都很乾淨」—— 那會靜靜地填滿一排 pass。"""
    r = _Runner([intake.OperationResult(True, "{ 這不是 JSON")])
    out, stats = r.grounding_report("ws")
    assert not out.ok and stats == {}
    assert "讀不到" in (out.error or "")


# ── 寫進體檢表 ────────────────────────────────────────────────────────────

def _record_calls(monkeypatch) -> list:                               # noqa: ANN001
    seen: list = []
    monkeypatch.setattr(ledger, "record",
                        lambda *a, **k: seen.append((a, k)) or ("d", {}, None))
    return seen


def test_a_clean_document_is_written_as_pass(monkeypatch) -> None:    # noqa: ANN001
    seen = _record_calls(monkeypatch)
    intake.record_grounding(Path("/tmp"), "ws", [DOC], {DOC: CLEAN})
    assert len(seen) == 1
    assert seen[0][0][3:5] == ("extract.grounding", "pass")


def test_a_document_over_the_threshold_is_written_as_fail(monkeypatch) -> None:  # noqa: ANN001
    seen = _record_calls(monkeypatch)
    intake.record_grounding(Path("/tmp"), "ws", [DOC], {DOC: DIRTY})
    assert seen[0][0][3:5] == ("extract.grounding", "fail")
    assert seen[0][1].get("value") is not None, "量到的比率要寫進表，不能只留一個 FAIL"


def test_a_document_made_only_of_symbols_is_unverifiable(monkeypatch) -> None:  # noqa: ANN001
    """字串比對對它沒有鑑別力。**既不是幻覺也不是通過。**"""
    seen = _record_calls(monkeypatch)
    intake.record_grounding(Path("/tmp"), "ws", [DOC], {DOC: SYMBOLIC_ONLY})
    assert seen[0][0][3:5] == ("extract.grounding", "unverifiable")


def test_a_document_missing_from_the_report_gets_no_row(monkeypatch) -> None:  # noqa: ANN001
    """**沒跑到的不填。** 填 pass 是說謊，填 fail 是誣賴。"""
    seen = _record_calls(monkeypatch)
    intake.record_grounding(Path("/tmp"), "ws", [DOC], {"別份.pdf": CLEAN})
    assert seen == []


def test_an_empty_report_writes_nothing(monkeypatch) -> None:         # noqa: ANN001
    """**控制組。** 報告拿不到時整批留空，而不是整批 pass。"""
    seen = _record_calls(monkeypatch)
    intake.record_grounding(Path("/tmp"), "ws", [DOC], {})
    assert seen == []


def test_a_broken_ledger_write_never_stops_the_batch(monkeypatch) -> None:  # noqa: ANN001
    """紀錄不是閘門。磁碟滿了不該讓一份好文件停在半路。"""
    def boom(*a: object, **k: object) -> None:
        raise OSError("磁碟滿了")
    monkeypatch.setattr(ledger, "record", boom)
    intake.record_grounding(Path("/tmp"), "ws", [DOC], {DOC: CLEAN})   # 不得拋出
