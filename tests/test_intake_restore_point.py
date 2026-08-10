"""按下「全部開始」先建還原點，建好才開始拆解。

**PO 怕的是圖譜**（2026-08-10）：實體與關係一旦合併進圖譜，放錯的檔案很難只
拿掉它那一份。LightRAG 的刪除其實會**重建**還有其他來源的實體
（`lightrag.py:4734` 的 delete-outright／rebuild 分支），但那條路沒有人實測過，
而還原點是確定可行的那條：停掉、換回目錄、啟動。

**為什麼在解析之前而不是抽取之前。** 解析會寫 `work/parsed`；還原點落在解析
之前，這一批才是真的「什麼都還沒發生」——連放錯的那份 PDF 都還沒被解析過。

**不帶 `--force`。** 備份腳本比的是「現在的資料庫」對「上次備份成功時的」，
沒變就跳過而且不停機 —— 而那時上一份備份本來就已經是這一批的還原點了。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from intake import DataPaths, IntakeApp, Job, OperationResult  # noqa: E402

sys.path.insert(0, str(ROOT / "tests"))
from test_intake import FakeRunner, _source, _wait_for  # noqa: E402


class BackupRunner(FakeRunner):
    """記錄還原點與解析的先後，並且可以讓備份失敗。"""

    def __init__(self, data_root: Path, *, ok: bool = True) -> None:
        super().__init__(data_root)
        self.ok = ok
        self.order: list[str] = []

    def restore_point(self) -> OperationResult:
        self.order.append("backup")
        self.calls.append("backup")
        return (OperationResult(True, "fake backup") if self.ok
                else OperationResult(False, "", "備份失敗：停不掉容器"))

    def parse(self, job: Job, source_pdf: Path) -> OperationResult:
        self.order.append("parse")
        return super().parse(job, source_pdf)


def _app(tmp_path: Path, *, ok: bool = True) -> tuple[IntakeApp, BackupRunner]:
    source_parent = _source(tmp_path, ("甲.pdf", "乙.pdf"))
    data_root = tmp_path / "data"
    runner = BackupRunner(data_root, ok=ok)
    app = IntakeApp(DataPaths(data_root), "test", [source_parent], runner=runner,
                    environment={"INTAKE_ROUND_POLL_SECONDS": "0.02"})
    return app, runner


def test_the_restore_point_is_made_before_anything_is_parsed(tmp_path: Path) -> None:
    """**順序就是這支的全部。** 還原點要落在連解析都還沒發生之前。"""
    app, runner = _app(tmp_path)
    app.start()
    try:
        ids = [str(c["candidate_id"]) for c in app.state()["sections"]["selection"]
               if isinstance(c, dict)]
        jobs = app.submit_parse(ids)
        for job in jobs:
            _wait_for(app, job.job_id, "indexed")

        assert runner.order[0] == "backup", f"解析先跑了：{runner.order[:4]}"
        assert runner.order.count("backup") == 1, "一批只該建一個還原點"
    finally:
        app.stop()


def test_a_failed_restore_point_stops_the_batch(tmp_path: Path) -> None:
    """**控制組，而且是最重要的一條。**

    備份失敗還照抽，等於明知沒有安全網還往前走。這個備份存在的唯一理由就是
    「出事要能回去」—— 建不起來就不該開始。
    """
    app, runner = _app(tmp_path, ok=False)
    app.start()
    try:
        ids = [str(c["candidate_id"]) for c in app.state()["sections"]["selection"]
               if isinstance(c, dict)]
        jobs = app.submit_parse(ids)
        for job in jobs:
            _wait_for(app, job.job_id, "failed")
        assert "parse" not in runner.order, "備份失敗了還是去解析了"
        for job in jobs:
            assert "還原點" in str(app._jobs[job.job_id].error), app._jobs[job.job_id].error
    finally:
        app.stop()


def test_the_screen_says_a_restore_point_is_being_made(tmp_path: Path) -> None:
    """畫面要說得出「現在在做什麼」。

    停機窗實測 77 秒（2026-08-10，排除 models 之後；之前是 92 秒）—— 沒有這一句
    的話，那 77 秒裡使用者看到的是「按了沒反應」，而查詢也剛好在那段時間失敗。
    """
    app, _ = _app(tmp_path)
    assert "restore_point" in app.state(), "state() 沒有還原點的欄位"


def test_the_restore_point_does_not_wait_for_the_offsite_upload() -> None:
    """還原點只等本機複本 —— **不等 restic 上傳**。

    2026-08-10 實測：上傳 11G 到 Google Drive 要 38 分鐘。等它等於讓人盯著
    「還原點建立中」半小時而解析完全不動，**而那半小時買到的東西（異地副本）
    對「我放錯檔案想退回去」一點用都沒有** —— 那個用途要的是本機那份複本，
    還原方式是停掉、換回目錄、啟動。

    讀原始碼而不是跑：`SubprocessRunner` 需要 .env，coder 上沒有。
    """
    src = (ROOT / "scripts" / "intake.py").read_text(encoding="utf-8")
    # 只看真正組指令的那一行 —— 說明文字裡本來就會提到 `--force` 為什麼不帶。
    line = next(ln for ln in src.splitlines() if "backup-cold.sh" in ln and "command = " in ln)
    assert "--stage-only" in line, f"還原點會等 restic 上傳完才回來：{line}"
    assert "--force" not in line, f"不該帶 --force —— 指紋沒變時本來就不必再備一次：{line}"
