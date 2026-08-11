"""intake 自動寫體檢表：計畫一判完就記，不等收尾。

**為什麼不是收尾。** `pp.preflight` 與 `pp.tables` 的判定在「計畫」那一刻就有了。
寫在批次收尾只會記錄到**活下來的那些** —— 而被 preflight 擋下的文件永遠進不了
批次，也就永遠不會有紀錄。那正是最該被記下來的一批。

**為什麼要自動。** `ledger.py` 設計得很完整（三態、強制附理由、pdf_sha256），
但它是手動的 —— 2026-08-10 實測：知識庫 257 份，體檢表只有 20 份舊語料的紀錄。
鐵則第 6 條：探針要在沒人問的時候會響。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import ledger  # noqa: E402
from intake import DataPaths, IntakeApp, PlanEvaluation  # noqa: E402

sys.path.insert(0, str(ROOT / "tests"))
from test_intake import FakeRunner, _source, _wait_for  # noqa: E402


def _plan_payload(doc: str, *, tables: dict | None = None) -> dict:
    return {
        "doc": doc, "pages": 2, "items": 3, "page_size": [595.0, 842.0],
        "noise": {"mute": [], "held": [], "body_chars_before": 100,
                  "body_chars_after": 100, "ratio": 0.0, "suspicious": False},
        "tables": tables if tables is not None else {"total": 0, "repair": [], "review": []},
        "charts": {"convert": [], "dangling": []},
    }


def _run_one(tmp_path: Path, evaluation: PlanEvaluation | None) -> tuple[IntakeApp, str]:
    source_parent = _source(tmp_path, ("paper.pdf",))
    data_root = tmp_path / "data"
    evals = {"paper.pdf": evaluation} if evaluation else {}
    app = IntakeApp(DataPaths(data_root), "test", [source_parent],
                    runner=FakeRunner(data_root, evals),
                    environment={"INTAKE_ROUND_POLL_SECONDS": "0.02"})
    app.start()
    candidate = app.state()["sections"]["selection"][0]
    job = app.submit_parse([str(candidate["candidate_id"])])[0]
    return app, job.job_id


def test_a_clean_plan_records_both_gates_it_knows(tmp_path: Path) -> None:
    """判乾淨的：preflight 過、表格沒有待辦 —— 兩格都寫 pass。"""
    app, job_id = _run_one(tmp_path, None)
    try:
        _wait_for(app, job_id, "indexed")
        rec = ledger.load(app.paths.root, app.workspace, "paper.pdf")
        assert rec["gates"]["pp.preflight"]["state"] == "pass"
        assert rec["gates"]["pp.tables"]["state"] == "pass"
    finally:
        app.stop()


def test_a_document_stopped_by_preflight_still_gets_a_record(tmp_path: Path) -> None:
    """**這條是整支的理由。**

    被擋下的文件永遠進不了批次。寫在收尾的話它不會有任何紀錄，
    而「停在等你看的那些」正是最需要有人回頭看的一批。
    """
    app, job_id = _run_one(tmp_path, PlanEvaluation(
        False, ("未知型別 sidebar_note",), ("細節",), _plan_payload("paper.pdf")))
    try:
        _wait_for(app, job_id, "planned")
        rec = ledger.load(app.paths.root, app.workspace, "paper.pdf")
        assert rec["gates"]["pp.preflight"]["state"] == "fail"
        assert "未知型別" in rec["gates"]["pp.preflight"]["note"]
    finally:
        app.stop()


def test_tables_needing_a_look_are_recorded_as_unverifiable(tmp_path: Path) -> None:
    """待查的表是「沒得驗」不是「壞了」—— 三態的中間那一格，而且必須附理由。

    這正是 PO 要的二次檢查名單：`ledger.py summary --problems` 就是它。
    """
    app, job_id = _run_one(tmp_path, PlanEvaluation(
        True, (), (), _plan_payload("paper.pdf",
                                    tables={"total": 5, "repair": [1], "review": [2, 3]})))
    try:
        _wait_for(app, job_id, "indexed")
        entry = ledger.load(app.paths.root, app.workspace, "paper.pdf")["gates"]["pp.tables"]
        assert entry["state"] == "unverifiable"
        assert entry["note"], "驗不了沒有理由，跟沒檢查在表上長得一樣"
        assert "2" in entry["note"] and "1" in entry["note"], entry["note"]
    finally:
        app.stop()


def test_a_plan_with_no_tables_section_must_not_be_recorded_as_pass(tmp_path: Path) -> None:
    """**假通過的洞**（2026-08-11 找到，workflow 指出、我讀碼實測確認）。

    計畫沒有產出 `tables` 那一段時（例如計畫本身半路失敗），
    `_as_mapping(None)` 回 `{}` → `total=None`、`repair=[]`、`review=[]`
    → 走 else → 寫下 `pp.tables = pass`，備註「共 **None** 張，沒有待修或待查的」。

    實測那個分支：

        _as_mapping(None) = {}
        total = None　repair = []　review = []
        → 走哪個分支: pass

    dker 上 259 個 job 裡有 4 個是這個形狀（計畫失敗但文件已入庫）。
    它們現在還沒有體檢表紀錄，**但照原本的程式回填就會當場產生 4 個假通過**。

    諷刺的是同一個函式的說明往上 12 行自己寫著「沒跑過的閘門填 `pass`
    就是說謊」—— 規則寫對了，程式沒跟上。

    「空的表格清單」與「根本沒有表格這一段」是兩件事：前者是真的沒有待辦，
    後者是**不知道**。三態設計存在的理由就是不讓後者偽裝成前者。
    """
    plan = _plan_payload("paper.pdf")
    del plan["tables"]
    app, job_id = _run_one(tmp_path, PlanEvaluation(True, (), (), plan))
    try:
        _wait_for(app, job_id, "indexed")
        entry = ledger.load(app.paths.root, app.workspace, "paper.pdf")["gates"]["pp.tables"]
        assert entry["state"] != "pass", f"沒有表格資料卻寫了 pass：{entry}"
        assert entry["state"] == "unverifiable", entry
        assert entry["note"], "驗不了沒有理由，跟沒檢查在表上長得一樣"
        assert "None" not in entry["note"], f"備註把 None 當數字印出來了：{entry['note']}"
    finally:
        app.stop()


def test_an_empty_table_list_is_still_a_pass(tmp_path: Path) -> None:
    """控制組：真的**有**表格那一段而且是空的 —— 那是「查過了，沒有待辦」。

    修上面那條的時候最容易把這條一起改壞，變成所有文件都寫「驗不了」。
    """
    app, job_id = _run_one(tmp_path, PlanEvaluation(
        True, (), (), _plan_payload("paper.pdf",
                                    tables={"total": 0, "repair": [], "review": []})))
    try:
        _wait_for(app, job_id, "indexed")
        entry = ledger.load(app.paths.root, app.workspace, "paper.pdf")["gates"]["pp.tables"]
        assert entry["state"] == "pass", entry
    finally:
        app.stop()


def test_writing_the_ledger_never_kills_the_worker(tmp_path: Path) -> None:
    """**體檢表寫不進去不得影響進料。**

    它是紀錄不是閘門。磁碟滿了、目錄權限錯了都會讓寫入失敗，而那不該讓一份
    好文件停在半路 —— 那會把「記帳的東西」變成「擋路的東西」。
    """
    app, job_id = _run_one(tmp_path, None)
    try:
        app.paths.ledger_dir.parent.mkdir(parents=True, exist_ok=True)
        app.paths.ledger_dir.write_text("我不是目錄", encoding="utf-8")
        _wait_for(app, job_id, "indexed")
    finally:
        app.stop()
