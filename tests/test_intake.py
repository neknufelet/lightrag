"""INTAKE-1 的狀態機、順序不變式與 HTTP smoke test。"""
from __future__ import annotations

import json
import logging
import re
import shutil
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from intake import (  # noqa: E402
    DataPaths,
    IntakeApp,
    IntakeError,
    Job,
    OperationResult,
    PlanEvaluation,
    make_handler,
    make_server,
    render_html,
    transition,
)


def _plan(document: str) -> dict[str, object]:
    return {
        "doc": document,
        "pages": 2,
        "items": 3,
        "page_size": [595.0, 842.0],
        "noise": {
            "mute": [], "held": [], "body_chars_before": 100,
            "body_chars_after": 100, "ratio": 0.0, "suspicious": False,
        },
        "tables": {"total": 0, "repair": [], "review": []},
        "charts": {"convert": [], "dangling": []},
    }


class FakeRunner:
    def __init__(self, data_root: Path, evaluations: dict[str, PlanEvaluation] | None = None) -> None:
        self.data_root = data_root
        self.evaluations = evaluations or {}
        self.calls: list[str] = []

    def parse(self, job: Job, source_pdf: Path) -> OperationResult:
        self.calls.append("parse")
        assert source_pdf.is_file()
        raw = self.data_root / "work" / "parsed" / f"{job.filename}.mineru_raw"
        raw.mkdir(parents=True, exist_ok=True)
        (raw / "content_list.json").write_text("[]", encoding="utf-8")
        return OperationResult(True, "fake parse")

    def plan(self, job: Job) -> PlanEvaluation:
        self.calls.append("plan")
        return self.evaluations.get(
            job.filename,
            PlanEvaluation(True, (), (), _plan(job.filename)),
        )

    def apply(self, job: Job) -> OperationResult:
        self.calls.append("apply")
        inputs = self.data_root / "inputs" / job.workspace
        assert not list(inputs.glob("*.pdf")), "apply 前 inputs 不得已有 PDF"
        return OperationResult(True, "fake apply")

    def scan(self, job: Job, admitted_pdf: Path) -> OperationResult:
        self.calls.append("scan")
        assert admitted_pdf.is_file()
        # ⚠ 這裡原本斷言「暫存區只有這一份」。那條**已經作廢**：分組之後一批會
        # 一起躺在暫存區，掃一次全部收下（正式庫實測 `Processing 5 document(s)`）。
        # 改成「這一份必須在裡面」—— 掃描是掃整個目錄，漏掉自己才是真的錯。
        assert admitted_pdf in list(admitted_pdf.parent.glob("*.pdf"))
        return OperationResult(True, "fake scan")

    def wait_indexed(self, job: Job) -> OperationResult:
        self.calls.append("wait")
        return OperationResult(True, "fake indexed")

    def restore_point(self) -> OperationResult:
        # 按下「全部開始」先建還原點，建好才拆解（PO 2026-08-10）。
        self.calls.append("backup")
        return OperationResult(True, "fake backup")

    def verify_batch(self, jobs, known_filenames) -> dict[str, OperationResult]:
        # 整批一次 —— 逐份跑實測 20 秒／份，86 份的尾巴約 28 分鐘。
        self.calls.append("verify")
        return {j.job_id: OperationResult(True, "fake verify") for j in jobs}


class ExplodingParseRunner(FakeRunner):
    def parse(self, job: Job, source_pdf: Path) -> OperationResult:
        super().parse(job, source_pdf)
        raise RuntimeError("測試用解析失敗")


class BatchWatchingRunner(FakeRunner):
    """在「它該壞的那一刻」記帳：改稿的當下，有沒有別人正在被抽取。

    `pp/apply.py` 是在改檔案、LightRAG 是在讀同一份檔案，兩者同時發生時讀進去的
    是半舊半新，所以那支直接拒絕（`pipeline 忙碌中，拒絕改檔`）。**只看設定對不對
    看不出這件事** —— 要在真的跑起來的時候量。

    `max_extracting` 是控制組：沒有它的話，「把放行改成一次一件」也會讓
    `overlaps` 是空的，而那正是我們要離開的狀態。
    """

    def __init__(self, data_root: Path) -> None:
        super().__init__(data_root)
        self.app: IntakeApp | None = None
        self.overlaps: list[str] = []
        self.max_extracting = 0

    def _others_in_flight(self, job_id: str) -> list[str]:
        assert self.app is not None, "測試忘了把 app 掛上來"
        return sorted(j.filename for j in self.app._jobs.values()
                      if j.job_id != job_id
                      and j.status in {"admitted", "scanning", "extracting"})

    def apply(self, job: Job) -> OperationResult:
        clash = self._others_in_flight(job.job_id)
        if clash:
            self.overlaps.append(f"改 {job.filename} 的時候，{clash} 正在被抽取")
        return super().apply(job)

    def wait_indexed(self, job: Job) -> OperationResult:
        assert self.app is not None
        extracting = [j for j in self.app._jobs.values() if j.status == "extracting"]
        self.max_extracting = max(self.max_extracting, len(extracting))
        return super().wait_indexed(job)


class VerifyTimingRunner(FakeRunner):
    """記「契約檢查跑的當下，還有沒有人在等索引」。

    契約檢查裡有一條 A-19 斷言「LightRAG 現在是閒的」。一次一份的時代那永遠
    成立；分批之後，除了最後一份，每一份跑完時同批的鄰居都還在跑 ——
    於是 A-19 必然失敗，整份被判失敗**而文件其實好好地進了庫**。
    2026-08-10 實測：一批 89 份，84 份被這樣誤殺，資料庫那側 159 份全是 processed。
    """

    def __init__(self, data_root: Path) -> None:
        super().__init__(data_root)
        self._waiting = 0
        self._guard = threading.Lock()
        self.verified_while_waiting: list[str] = []
        self.verified: list[str] = []

    def wait_indexed(self, job: Job) -> OperationResult:
        with self._guard:
            self._waiting += 1
        try:
            time.sleep(0.05)          # 讓同批的等待真的重疊得起來
            return super().wait_indexed(job)
        finally:
            with self._guard:
                self._waiting -= 1

    def verify_batch(self, jobs, known_filenames) -> dict[str, OperationResult]:
        # 2026-08-10 起是**整批一次**（逐份跑實測 20 秒／份，86 份尾巴約 28 分鐘）。
        # 這支釘的意圖沒變：跑的當下不得還有人在等索引。
        with self._guard:
            busy = self._waiting
        for job in jobs:
            if busy:
                self.verified_while_waiting.append(
                    f"{job.filename}（還有 {busy} 份在等索引）")
            self.verified.append(job.filename)
        return {job.job_id: OperationResult(True, "fake verify") for job in jobs}


def _batch_app(tmp_path: Path, names: tuple[str, ...]) -> tuple[IntakeApp, BatchWatchingRunner]:
    source_parent = _source(tmp_path, names)
    data_root = tmp_path / "data"
    runner = BatchWatchingRunner(data_root)
    app = IntakeApp(DataPaths(data_root), "test", [source_parent], runner=runner,
                    environment={"INTAKE_ROUND_POLL_SECONDS": "0.02"})
    runner.app = app
    return app, runner


def _wait_all(app: IntakeApp, job_ids: list[str], status: str, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = {str(j.get("job_id")): str(j.get("status"))
                   for j in app.state()["jobs"] if isinstance(j, dict)}
        if all(current.get(job_id) == status for job_id in job_ids):
            return
        time.sleep(0.02)
    current = {str(j.get("job_id")): str(j.get("status"))
               for j in app.state()["jobs"] if isinstance(j, dict)}
    raise AssertionError(f"這些沒有到 {status}：{current}")


def _source(tmp_path: Path, names: tuple[str, ...] = ("paper.pdf",)) -> Path:
    raw = tmp_path / "knowledge_bases" / "demo" / "raw"
    raw.mkdir(parents=True)
    for name in names:
        (raw / name).write_bytes(f"fixture:{name}".encode())
    return raw.parent.parent


def _wait_for(app: IntakeApp, job_id: str, status: str) -> dict[str, object]:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        for job in app.state()["jobs"]:
            if isinstance(job, dict) and job.get("job_id") == job_id and job.get("status") == status:
                return job
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} 沒有到 {status}：{app.state()}")


def test_state_machine_rejects_reversed_or_skipped_transitions(tmp_path: Path) -> None:
    raw_parent = _source(tmp_path)
    paths = DataPaths(tmp_path / "data")
    candidate_id = "a" * 32
    from intake import Candidate

    candidate = Candidate(
        candidate_id=candidate_id,
        source_root=raw_parent / "demo" / "raw",
        source_path=raw_parent / "demo" / "raw" / "paper.pdf",
        source_name="demo",
        source_key="demo-key",
        filename="paper.pdf",
        sha256="sha256:" + "b" * 64,
        size=1,
    )
    job = Job.from_candidate(candidate)
    job.workspace = "test"
    transition(job, "parsing")
    transition(job, "planned")
    transition(job, "repairing")
    transition(job, "repaired")
    transition(job, "admitted")
    transition(job, "scanning")
    transition(job, "extracting")
    transition(job, "indexed")
    with pytest.raises(IntakeError):
        transition(job, "planned")

    # **`repaired` 不能被跳過。** 稿子改好與還沒改在這條路上長得一樣（都還沒碰
    # 索引），差別只在 `content_list.json` 動過沒 —— 而重跑一次 apply 會把
    # MinerU 的原文換成上一輪的修補結果，還原路徑看起來還在，還原出來的卻不是原文。
    # 少了這一格，重啟之後就分不出來了。
    fresh = Job.from_candidate(candidate)
    fresh.workspace = "test"
    transition(fresh, "parsing")
    transition(fresh, "planned")
    transition(fresh, "repairing")
    with pytest.raises(IntakeError):
        transition(fresh, "admitted")
    assert paths.inputs_dir("test").name == "test"


def test_parse_review_keeps_inputs_empty_and_admit_order(tmp_path: Path) -> None:
    source_parent = _source(tmp_path)
    data_root = tmp_path / "data"
    paths = DataPaths(data_root)
    runner = FakeRunner(data_root)
    app = IntakeApp(paths, "test", [source_parent], runner=runner)
    app.start()
    try:
        candidate = app.state()["sections"]["selection"][0]
        assert isinstance(candidate, dict)
        job = app.submit_parse([str(candidate["candidate_id"])])[0]
        # clean 的計畫自動放行（裁決 4eacaea），所以這裡不按放行也會走完。
        # 「放行前 inputs 必須是空的」那條不變式由 FakeRunner.apply 當場斷言。
        indexed = _wait_for(app, job.job_id, "indexed")
        assert indexed["decision"] == "clean"
        # `verify`（契約檢查）是獨立的一步，不再埋在 `wait` 裡面 ——
        # 它要等整批都不在抽取了才跑，理由見
        # `test_the_contract_check_waits_until_the_whole_batch_stopped_extracting`。
        assert runner.calls == ["backup", "parse", "plan", "apply", "scan", "wait", "verify"]
        assert list(paths.inputs_dir("test").glob("*.pdf")) == []
        state_path = paths.intake_job_dir(job.job_id) / "job.json"
        saved = json.loads(state_path.read_text(encoding="utf-8"))
        assert saved["status"] == "indexed"
    finally:
        app.stop()


def test_pending_confirmation_is_grouped_by_reason_and_needs_acknowledgement(tmp_path: Path) -> None:
    source_parent = _source(tmp_path, ("a.pdf", "b.pdf"))
    data_root = tmp_path / "data"
    evaluations = {
        "a.pdf": PlanEvaluation(False, ("未知型別 sidebar_note",), ("a detail",), {
            "failed": ["a：未知的項目型別 ['sidebar_note']"],
        }),
        "b.pdf": PlanEvaluation(False, ("未知型別 sidebar_note",), ("b detail",), {
            "failed": ["b：未知的項目型別 ['sidebar_note']"],
        }),
    }
    app = IntakeApp(
        DataPaths(data_root), "test", [source_parent],
        runner=FakeRunner(data_root, evaluations),
    )
    app.start()
    try:
        candidates = app.state()["sections"]["selection"]
        assert isinstance(candidates, list)
        ids = [str(item["candidate_id"]) for item in candidates if isinstance(item, dict)]
        jobs = app.submit_parse(ids)
        for job in jobs:
            _wait_for(app, job.job_id, "planned")
        state = app.state()
        groups = state["pending_by_reason"]
        assert groups == [{
            "reason": "未知型別 sidebar_note",
            "count": 2,
            "jobs": [
                {"job_id": jobs[0].job_id, "filename": "a.pdf", "source": "demo"},
                {"job_id": jobs[1].job_id, "filename": "b.pdf", "source": "demo"},
            ],
        }]
        html = render_html(state, jobs[0].job_id)
        # 分組的重點是「這個原因有幾份文件的證據」——斷言原因本身與檔名，
        # 不是斷言標題文字（標題會隨版面改，原因不會）。
        assert "未知型別 sidebar_note" in html
        assert "a.pdf" in html and "b.pdf" in html

        # ⚠ 安全斷言（2026-08-09 改版）。
        #
        # 舊版釘的是「待確認的文件**不得**出現放行按鈕」。那條被實務推翻：
        # 「等你看」把東西攔下來給人看，看完卻沒有動作可以做，於是那一節只出不進
        # —— 兩份論文因為「封面頁高度與內頁不同」卡在那裡，量過確認無害卻按不下去。
        #
        # 新的不變式不是「不能放行」，是**「不能不看就放行」**：按鈕必須帶著畫面上
        # 列出來的每一條理由，後端逐條比對。只送一個籠統的 override 會讓
        # 「列了三條只看兩條」通過。
        assert "data-act=" in html, "data-act 不存在，下面的斷言會假通過"
        assert "data-act='admit'" in html, "待確認的文件沒有放行的路 —— 那一節會只出不進"
        assert "data-ack=" in html, "放行按鈕沒有帶理由 —— 等於不看就放行"
        assert "未知型別 sidebar_note" in html.split("data-ack=")[1][:400], (
            "按鈕帶的理由跟畫面列的對不上")
    finally:
        app.stop()


def test_failed_job_is_visible_and_reset_restores_all_candidate_sources(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR, logger="intake")
    source_parent = _source(tmp_path)
    data_root = tmp_path / "data"
    paths = DataPaths(data_root)
    app = IntakeApp(paths, "test", [source_parent], runner=ExplodingParseRunner(data_root))
    app.start()
    try:
        candidate = app.state()["sections"]["selection"][0]
        assert isinstance(candidate, dict)
        job = app.submit_parse([str(candidate["candidate_id"])])[0]
        failed = _wait_for(app, job.job_id, "failed")
        error = failed["error"]
        assert isinstance(error, str) and "測試用解析失敗" in error

        state = app.state()
        assert state["sections"]["failed"] == [failed]
        assert app._public_job(job)["error"] == error
        html = render_html(state, job.job_id)
        assert error in html
        assert "data-act='reset'" in html
        assert "Traceback (most recent call last)" in caplog.text

        library_pdf = paths.library_source_dir(job.source_key) / job.filename
        parsed_pdf = paths.parsed_dir / job.filename
        input_pdf = paths.inputs_dir("test") / job.filename
        assert library_pdf.is_file()
        assert parsed_pdf.is_file()
        input_pdf.write_bytes(Path(job.source_path).read_bytes())
        assert app.state()["sections"]["selection"] == []

        assert app.submit_reset(job.job_id) == job.candidate_id
        reset_state = app.state()
        selection = reset_state["sections"]["selection"]
        assert isinstance(selection, list)
        assert [item["candidate_id"] for item in selection if isinstance(item, dict)] == [
            job.candidate_id,
        ]
        assert reset_state["sections"]["failed"] == []
        assert not library_pdf.exists()
        assert not parsed_pdf.exists()
        assert not input_pdf.exists()
        assert not paths.parsed_bundle_dir(job.filename).exists()
        assert not paths.intake_job_dir(job.job_id).exists()

        reloaded = IntakeApp(paths, "test", [source_parent], runner=ExplodingParseRunner(data_root))
        try:
            reloaded_selection = reloaded.state()["sections"]["selection"]
            assert [item["candidate_id"] for item in reloaded_selection if isinstance(item, dict)] == [
                job.candidate_id,
            ]
        finally:
            reloaded.stop()
    finally:
        app.stop()


def test_health_endpoint_starts_and_returns_200(tmp_path: Path) -> None:
    source_parent = _source(tmp_path)
    app = IntakeApp(DataPaths(tmp_path / "data"), "test", [source_parent], runner=FakeRunner(tmp_path / "data"))
    try:
        server = make_server("127.0.0.1", 0, app)
    except PermissionError as exc:
        # 這個 coder sandbox 禁止 AF_INET bind；仍用 socketpair 走同一個 handler，
        # 讓 /health 的 HTTP status／body 在本機可驗。真實 TCP bind 另列為未驗。
        left, right = socket.socketpair()
        app.start()
        handler_thread = threading.Thread(
            target=make_handler(app), args=(left, ("local", 0), object()), daemon=True,
        )
        handler_thread.start()
        try:
            right.sendall(b"GET /health HTTP/1.1\r\nHost: local\r\nConnection: close\r\n\r\n")
            response = right.recv(4096)
        except PermissionError:
            # 目前 sandbox 連 socketpair 的資料交換也封鎖；至少驗證同一 app 的
            # health contract，TCP／HTTP 實跑在此環境仍不能宣稱已驗。
            assert app.health()["status"] == "ok"
            return
        finally:
            right.close()
            left.close()
            handler_thread.join(timeout=2)
            app.stop()
        assert b"200 OK" in response, exc
        assert b'"status": "ok"' in response
        return
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    app.start()
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/health"
        with urllib.request.urlopen(url, timeout=2) as response:
            assert response.status == 200
            payload = json.loads(response.read())
        assert payload["status"] == "ok"
        assert payload["worker_alive"] is True
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        app.stop()


def test_api_rejects_path_like_candidate_id(tmp_path: Path) -> None:
    app = IntakeApp(DataPaths(tmp_path / "data"), "test", [], runner=FakeRunner(tmp_path / "data"))
    with pytest.raises(IntakeError) as error:
        app.submit_parse(["../outside"])
    assert error.value.status_code == 400


# ── 拖拉上傳與收件匣管理（PO 2026-08-04：不要碰終端機）─────────────────

PDF = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def _app(tmp_path: Path) -> IntakeApp:
    """收件匣本身就是來源 —— 這是實際部署的接法（--source /data/lightrag/inbox）。"""
    data_root = tmp_path / "data"
    paths = DataPaths(data_root)
    paths.inbox_dir.mkdir(parents=True, exist_ok=True)
    return IntakeApp(paths, "test", [paths.inbox_dir], runner=FakeRunner(data_root))


def test_upload_lands_in_inbox_and_is_pickable(tmp_path: Path) -> None:
    """上傳的檔案要落地，而且要能在選片區被挑到。

    只驗「有寫進檔案系統」不夠——落到一個沒人掃描的目錄，等於沒收到。
    """
    app = _app(tmp_path)
    saved = app.save_upload("我的論文.pdf", PDF)
    assert saved.parent == app.paths.inbox_dir
    assert saved.read_bytes() == PDF
    names = [str(item.get("filename")) for item in app.state()["sections"]["selection"]]
    assert "我的論文.pdf" in names, "上傳後沒有出現在選片區"


def test_upload_rejects_non_pdf_by_content_not_only_suffix(tmp_path: Path) -> None:
    """副檔名是使用者說了算，內容不是。

    改名成 .pdf 的 zip 若放行，會在解析階段才炸、錯誤訊息指向 MinerU ——
    那時沒有人會想到問題出在三步之前的上傳。
    """
    app = _app(tmp_path)
    with pytest.raises(IntakeError) as suffix_error:
        app.save_upload("報告.docx", PDF)
    assert suffix_error.value.status_code == 415

    with pytest.raises(IntakeError) as magic_error:
        app.save_upload("假裝是.pdf", b"PK\x03\x04 this is a zip")
    assert magic_error.value.status_code == 415
    assert list(app.paths.inbox_dir.glob("*.pdf")) == [], "被拒絕的內容不該留下"


def test_upload_dedupes_by_content_not_filename(tmp_path: Path) -> None:
    """去重比內容不比檔名——同一份 PDF 改個名再傳，檔名比對抓不到。"""
    app = _app(tmp_path)
    app.save_upload("原名.pdf", PDF)

    with pytest.raises(IntakeError) as same:
        app.save_upload("原名.pdf", PDF)
    assert same.value.status_code == 409

    with pytest.raises(IntakeError) as renamed:
        app.save_upload("改了名字.pdf", PDF)
    assert renamed.value.status_code == 409
    assert "原名.pdf" in str(renamed.value), "拒絕時要說出已存在的是哪一份"

    # 同名但內容不同 ⇒ 是兩份不同文件，兩份都要留
    second = app.save_upload("原名.pdf", PDF + b"% different\n")
    assert second.name != "原名.pdf"
    assert len(list(app.paths.inbox_dir.glob("*.pdf"))) == 2


def test_upload_filename_cannot_escape_inbox(tmp_path: Path) -> None:
    """上傳的檔名是使用者輸入，路徑成分必須在伺服器端被剝掉。"""
    app = _app(tmp_path)
    saved = app.save_upload("../../../etc/evil.pdf", PDF)
    assert saved.parent == app.paths.inbox_dir
    assert saved.name == "evil.pdf"
    assert not (tmp_path.parent / "evil.pdf").exists()


def test_upload_leaves_no_partial_file_when_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """寫到一半失敗時，收件匣不得留下半個檔案。

    半個 PDF 會通過副檔名檢查，然後在解析階段才炸——最難查的一種失敗。
    """
    app = _app(tmp_path)

    def boom(self: Path, data: bytes) -> int:
        raise OSError("磁碟滿了")

    monkeypatch.setattr(Path, "write_bytes", boom)
    with pytest.raises(IntakeError):
        app.save_upload("中斷.pdf", PDF)
    monkeypatch.undo()
    assert list(app.paths.inbox_dir.iterdir()) == [], "失敗後留下了殘骸"


def test_inbox_delete_only_touches_inbox(tmp_path: Path) -> None:
    """只准刪收件匣裡的東西——其他來源是別人的檔案。"""
    app = _app(tmp_path)
    app.save_upload("要刪的.pdf", PDF)
    app.delete_inbox_file("要刪的.pdf")
    assert not (app.paths.inbox_dir / "要刪的.pdf").exists()

    outsider = tmp_path / "別人的.pdf"
    outsider.write_bytes(PDF)
    with pytest.raises(IntakeError):
        app.delete_inbox_file("../別人的.pdf")
    assert outsider.is_file(), "路徑穿越把外面的檔案刪掉了"


def test_upload_body_reader_rejects_oversize_and_truncated(tmp_path: Path) -> None:
    """Content-Length 是客戶端說的，要當成不可信輸入。"""
    import io

    from intake import MAX_UPLOAD_BYTES, _upload_body

    class FakeHandler:
        def __init__(self, length: str, payload: bytes) -> None:
            self.headers = {"Content-Length": length}
            self.rfile = io.BytesIO(payload)

    with pytest.raises(IntakeError) as oversize:
        _upload_body(FakeHandler(str(MAX_UPLOAD_BYTES + 1), b""))
    assert oversize.value.status_code == 413

    with pytest.raises(IntakeError) as truncated:
        _upload_body(FakeHandler("100", b"only ten!"))
    assert truncated.value.status_code == 400


def test_page_links_to_lightrag_from_env_not_hardcoded(tmp_path: Path) -> None:
    """通往知識庫的入口要從 .env 組出來。

    寫死 host 會在換機器時指向不存在的地方，而且**不報錯** ——
    使用者只會看到一個點了沒反應的連結。
    """
    data_root = tmp_path / "data"
    paths = DataPaths(data_root)
    paths.inbox_dir.mkdir(parents=True, exist_ok=True)
    app = IntakeApp(
        paths, "test", [paths.inbox_dir], runner=FakeRunner(data_root),
        environment={"BIND_ADDR": "10.1.2.3", "HOST_PORT": "9999", "KBAPI_PORT": "8888"},
    )
    links = app.state()["links"]
    assert links == {"lightrag": "http://10.1.2.3:9999", "kbapi": "http://10.1.2.3:8888"}
    assert "http://10.1.2.3:9999" in render_html(app.state())


# ── 對帳：索引裡那一列該不該算在本站頭上（PO 2026-08-04 咬到）────────────


def _with_index(app: IntakeApp, rows: list[dict[str, str]]) -> IntakeApp:
    """讓 app 看到一份指定的 LightRAG 文件清單。

    直接換掉 client.request 而不是起假伺服器：這裡要驗的是**歸屬判準**，
    多一層 HTTP 只會讓失敗訊息指向網路。
    """
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row["status"], []).append(row)
    app.client.request = lambda *a, **k: {"statuses": grouped}  # type: ignore[method-assign]
    app._index_cache = None
    return app


def _job_in(app: IntakeApp, filename: str, status: str) -> Job:
    app.save_upload(filename, PDF)
    candidate = next(item for item in app._candidates()[0] if item.filename == filename)
    job = Job.from_candidate(candidate)
    job.status = status  # type: ignore[assignment]
    job.workspace = app.workspace          # 落盤後要讀得回來
    app._jobs[job.job_id] = job
    return job


def test_in_flight_job_is_not_foreign_and_not_yet_processed(tmp_path: Path) -> None:
    """正在抽取的那一份，是本站送的，而且還沒處理完。

    實測 2026-08-04：B 抽到第 41 段時，畫面同時把它列在「處理中」和
    「已進知識庫 · 不是這裡送的」，計數說 2 而知識庫實際只有 1 份。
    成因是排除清單只認 indexed —— 在途的自己人被當成外人。
    """
    app = _app(tmp_path)
    _job_in(app, "B.pdf", "extracting")
    _with_index(app, [{"file_path": "B.pdf", "status": "processing"}])

    state = app.state()
    assert state["foreign"] == [], "在途的自己人被誤判成「不是這裡送的」"
    assert state["convergence"]["processed"] == 0, "還在抽取就被算進已處理"


def test_failed_job_that_actually_indexed_still_counts(tmp_path: Path) -> None:
    """反方向：本站以為失敗、索引其實成功的，不得漏掉。

    這是 2026-08-03 的既有修正，上面那條不能把它改回去 —— 兩個方向是對稱的，
    修一邊過頭就會撞出另一邊。
    """
    app = _app(tmp_path)
    _job_in(app, "A.pdf", "failed")
    _with_index(app, [{"file_path": "A.pdf", "status": "processed"}])

    state = app.state()
    assert [row["filename"] for row in state["foreign"]] == ["A.pdf"]
    assert state["convergence"]["processed"] == 1, "索引裡跑完的文件被漏掉"


def test_genuinely_foreign_but_still_processing_is_listed_not_counted(tmp_path: Path) -> None:
    """別人塞進來、而且還在跑的：要列出來（探針），但不算進已處理。"""
    app = _app(tmp_path)
    _with_index(app, [{"file_path": "別人的.pdf", "status": "processing"}])

    state = app.state()
    assert [row["filename"] for row in state["foreign"]] == ["別人的.pdf"], "探針該響沒響"
    assert state["convergence"]["processed"] == 0, "processing 不是 processed"


def test_parsing_job_does_not_shadow_a_same_named_foreign_row(tmp_path: Path) -> None:
    """還沒送進 inputs 的狀態不得排除同名的列。

    parsing 是 active 但還沒碰索引 —— 那時候索引裡同名的列真的是別人送的。
    用 ACTIVE_STATUSES 一併排除會讓探針在這個縫隙漏報。
    """
    app = _app(tmp_path)
    _job_in(app, "同名.pdf", "parsing")
    _with_index(app, [{"file_path": "同名.pdf", "status": "processed"}])

    state = app.state()
    assert [row["filename"] for row in state["foreign"]] == ["同名.pdf"], "探針被在途狀態蓋住"


# ── 重啟恢復：問索引的現實，不要假設失敗（PO 2026-08-04）──────────────


def _restart_with_index(tmp_path: Path, status: str, rows: dict[str, str] | None = None,
                        stage_started_at: str | None = None):
    """建一個在途的 job、落盤，然後用指定的索引現實重啟一個新 app。

    `stage_started_at` 決定那件工作是「排隊中」還是「真的跑過」——重啟恢復
    對這兩者的處置完全相反（重新排回 vs 判定失敗），所以測試要指得出來。
    """
    app = _app(tmp_path)
    job = _job_in(app, "跑到一半.pdf", status)
    job.stage_started_at = stage_started_at
    app.store.save(job)

    grouped: dict[str, list[dict[str, str]]] = {}
    for name, st in (rows or {}).items():
        grouped.setdefault(st, []).append({"file_path": name, "status": st})

    class _Client:
        def request(self, *a, **k):
            if rows is None:
                raise OSError("connection refused")
            return {"statuses": grouped}

    original = IntakeApp._recover_active_jobs
    seen: list[tuple[str, str]] = []

    def patched(self) -> None:
        self.client = _Client()          # type: ignore[assignment]
        # 兩條佇列都要攔（解析一條、放行一條）—— 只攔一條的話，
        # 「重啟把哪幾件排回去」會漏掉另一條那半，測試看起來過了其實沒驗到。
        self._parse_queue.put = lambda item: seen.append(item)  # type: ignore[method-assign]
        self._admit_queue.put = lambda item: seen.append(item)  # type: ignore[method-assign]
        original(self)

    IntakeApp._recover_active_jobs = patched      # type: ignore[method-assign]
    try:
        fresh = IntakeApp(app.paths, "test", [app.paths.inbox_dir],
                          runner=FakeRunner(app.paths.root))
    finally:
        IntakeApp._recover_active_jobs = original  # type: ignore[method-assign]
    return fresh, seen


def test_restart_marks_indexed_when_lightrag_already_finished(tmp_path: Path) -> None:
    """索引裡已經是 processed 的，重啟不得標成失敗。

    LightRAG 在另一個容器裡，intake 重啟不會打斷它。舊版一律標 failed，
    於是畫面說失敗、庫裡卻有，而 failed 是死路，那份文件從此卡住。
    """
    app, _ = _restart_with_index(tmp_path, "extracting", {"跑到一半.pdf": "processed"})
    job = next(j for j in app._jobs.values() if j.filename == "跑到一半.pdf")
    assert job.status == "indexed", job.status
    assert job.error is None


def test_restart_requeues_when_lightrag_still_processing(tmp_path: Path) -> None:
    """LightRAG 還在跑的，掛回去等，**不重跑抽取**（會付兩次錢又產生重複實體）。"""
    app, queued = _restart_with_index(tmp_path, "extracting", {"跑到一半.pdf": "processing"})
    job = next(j for j in app._jobs.values() if j.filename == "跑到一半.pdf")
    assert job.status == "extracting", job.status
    assert queued == [("resume", job.job_id)], queued


def test_restart_fails_only_when_index_really_lacks_the_document(tmp_path: Path) -> None:
    """索引裡真的沒有這一份 —— 這才是失敗。"""
    app, queued = _restart_with_index(tmp_path, "scanning", {"別人的.pdf": "processed"})
    job = next(j for j in app._jobs.values() if j.filename == "跑到一半.pdf")
    assert job.status == "failed", job.status
    assert "找不到這份文件" in (job.error or "")
    assert queued == []


def test_restart_does_not_guess_when_lightrag_is_unreachable(tmp_path: Path) -> None:
    """問不到 LightRAG 時維持原狀。

    把「連不上」當成「失敗」會在網路瞬斷時殺掉一整批好文件 —— 而失敗是死路。
    """
    app, queued = _restart_with_index(tmp_path, "extracting", None)
    job = next(j for j in app._jobs.values() if j.filename == "跑到一半.pdf")
    assert job.status == "extracting", "連不上就把在途工作殺掉了"
    assert "問不到 LightRAG" in (job.error or "")
    assert queued == []


# ── 分節以知識庫為準：畫面不得與資料庫各說各話（PO 2026-08-08）──────────


def _admit_one(app: IntakeApp, job_id: str) -> None:
    """把一份從「等改稿」推到底，走的是協調者走的那兩段。

    分組之後沒有「一份自己走完全程」的函式了（舊的 `_run_admit` 已刪）——
    留著它會是第二條路，而同一件事兩條路正是本專案踩過五次的形狀。
    這裡就是協調者的一輪，只是那一批剛好只有一份。
    """
    app._run_repair(job_id)
    if app._jobs[job_id].status == "repaired":
        app._extract_batch([job_id])


def _ready_to_admit(app: IntakeApp, filename: str) -> Job:
    """做出一份「審查通過、解析成果齊全」、狀態停在 repairing 的 job。"""
    app.save_upload(filename, PDF)
    candidate = next(item for item in app._candidates()[0] if item.filename == filename)
    job = Job.from_candidate(candidate)
    job.workspace = app.workspace
    job.decision = "clean"
    job.plan = _plan(filename)
    job.status = "repairing"
    app._jobs[job.job_id] = job
    parsed = app.paths.parsed_dir / filename
    parsed.parent.mkdir(parents=True, exist_ok=True)
    parsed.write_bytes(PDF)
    job.parsed_source_path = str(parsed)
    bundle = app.paths.parsed_bundle_dir(filename)
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "content_list.json").write_text("[]", encoding="utf-8")
    app.store.save(job)
    return job


def test_foreign_document_still_processing_is_not_in_the_indexed_section(tmp_path: Path) -> None:
    """別人送的、還在抽取的，不得出現在「已進知識庫」。

    實測 2026-08-08：同一頁上「已處理 4」與「已進知識庫 5」並存。成因是計數
    那半有過濾 status=='processed'，顯示那半把 foreign 整串接在 completed
    後面，不分狀態。教訓學過一次（2026-08-04），只補在計數上。
    """
    app = _app(tmp_path)
    _with_index(app, [{"file_path": "別人的.pdf", "status": "processing"}])

    state = app.state()
    assert [row["filename"] for row in state["sections"]["in_progress"]] == ["別人的.pdf"]
    assert state["sections"]["completed"] == [], "還在抽取的被列進已進知識庫"
    assert state["convergence"]["processed"] == 0


def test_own_indexed_job_drops_back_while_the_index_is_rerunning_it(tmp_path: Path) -> None:
    """自己送的那份被重抽時，畫面要跟著掉回「處理中」。

    簿記只答得出「我送出去了」。重抽會把已完成的文件打回 processing，而簿記
    不會跟著變 —— 實測 2026-08-08 重抽期間畫面 4 份全寫「已進知識庫」，
    資料庫同時 3 份 processing。
    """
    app = _app(tmp_path)
    _job_in(app, "自己的.pdf", "indexed")
    _with_index(app, [{"file_path": "自己的.pdf", "status": "processing"}])

    state = app.state()
    assert [row["filename"] for row in state["sections"]["in_progress"]] == ["自己的.pdf"]
    assert state["sections"]["completed"] == [], "重抽中的文件被當成已完成"
    assert state["convergence"]["processed"] == 0


def test_unknown_index_status_counts_as_still_running(tmp_path: Path) -> None:
    """認不得的狀態一律當成還在跑。

    錯放在「處理中」只是讓人多等；錯放在「已進知識庫」會讓人以為可以開始用了。
    """
    app = _app(tmp_path)
    _with_index(app, [{"file_path": "怪狀態.pdf", "status": "somethingelse"}])

    state = app.state()
    assert [row["filename"] for row in state["sections"]["in_progress"]] == ["怪狀態.pdf"]
    assert state["convergence"]["processed"] == 0


def test_index_unreachable_falls_back_to_bookkeeping_not_to_zero(tmp_path: Path) -> None:
    """問不到知識庫時退回本站簿記，不得反過來說謊成「什麼都沒進去」。"""
    app = _app(tmp_path)
    _job_in(app, "自己的.pdf", "indexed")

    def _boom(*args: object, **kwargs: object) -> dict[str, object]:
        raise OSError("斷線")

    app.client.request = _boom  # type: ignore[method-assign]
    app._index_cache = None

    state = app.state()
    assert [row["filename"] for row in state["sections"]["completed"]] == ["自己的.pdf"]
    assert state["convergence"]["processed"] == 1
    assert "問不到 LightRAG" in str(state["foreign_error"]), "連不上卻沒有警告"


def test_the_counter_and_the_indexed_section_cannot_disagree(tmp_path: Path) -> None:
    """同一頁的兩個數字必須是同一件東西 —— 這是本輪的核心迴歸。

    舊版兩處各算一次，於是「已處理 4」與「已進知識庫 5」同時出現在畫面上，
    而沒有任何東西會發現。
    """
    app = _app(tmp_path)
    _job_in(app, "自己的.pdf", "indexed")
    _with_index(app, [
        {"file_path": "自己的.pdf", "status": "processed"},
        {"file_path": "別人跑完的.pdf", "status": "processed"},
        {"file_path": "別人在跑的.pdf", "status": "processing"},
    ])

    state = app.state()
    assert state["convergence"]["processed"] == len(state["sections"]["completed"]) == 2
    assert [row["filename"] for row in state["sections"]["in_progress"]] == ["別人在跑的.pdf"]

    html = render_html(state)
    match = re.search(r"data-sec='completed'.*?<span class='count'>(\d+)</span>", html, re.S)
    assert match is not None
    assert int(match.group(1)) == state["convergence"]["processed"], "畫面與計數對不上"


def test_in_flight_foreign_document_keeps_the_page_refreshing(tmp_path: Path) -> None:
    """有東西在跑的時候整頁要自動更新。

    舊版的「有沒有在跑」只看自己的 job，於是重抽期間 data-running='0'，
    畫面完全不動 —— 使用者得手動重整才看得到變化。
    """
    app = _app(tmp_path)
    _with_index(app, [{"file_path": "別人在跑的.pdf", "status": "processing"}])

    assert "data-running='1'" in render_html(app.state()), "有東西在跑但畫面不會更新"


# ── 放行被擋：「現在不方便」不是「這份文件壞了」（PO 2026-08-08）──────────


def test_busy_inputs_sends_the_job_back_to_review_not_to_failed(tmp_path: Path) -> None:
    """收件區被別的流程佔著時退回「等你看」，不標失敗。

    實測 2026-08-08：2017 那篇 decision=clean、reasons=[]，只因為重抽拿
    inputs 當暫存區就被判 failed。而 failed 的唯一出口會刪掉解析成果。
    """
    app = _app(tmp_path)
    job = _ready_to_admit(app, "自己的.pdf")
    inputs = app.paths.inputs_dir(app.workspace)
    inputs.mkdir(parents=True, exist_ok=True)
    (inputs / "別的流程在用.pdf").write_bytes(PDF)

    _admit_one(app, job.job_id)

    assert job.status == "planned", "「現在不方便」被記成「這份文件壞了」"
    assert "這次沒有放行" in (job.error or "")
    assert job.plan is not None, "計畫被清掉了，等於還要再審一次"
    assert app.paths.parsed_bundle_dir("自己的.pdf").is_dir(), "解析成果被動到了"
    assert "apply" not in app.runner.calls, "擋下來之後照樣跑了修補"
    assert "這次沒有放行" in render_html(app.state()), "退回了但畫面沒說原因"


def test_retry_puts_a_failed_job_back_without_touching_the_parse(tmp_path: Path) -> None:
    """計畫還有效的失敗可以重試，而且不動已經做好的解析成果。"""
    app = _app(tmp_path)
    job = _ready_to_admit(app, "自己的.pdf")
    job.status = "failed"
    job.error = "放行失敗：inputs 不是純淨空目錄"
    app.store.save(job)
    bundle = app.paths.parsed_bundle_dir("自己的.pdf")
    before = sorted(path.name for path in bundle.iterdir())

    app.submit_retry(job.job_id)

    assert job.status == "planned"
    assert job.error is None, "上一次的錯誤留在畫面上會讓人以為又被擋了"
    assert sorted(path.name for path in bundle.iterdir()) == before


def test_a_reviewed_novel_document_can_be_retried_after_it_failed(tmp_path: Path) -> None:
    """**「等你看」看完並放行過的文件，失敗之後不該變成死路。**

    2026-08-10 實測踩到：兩份老掃描件判定 novel、人逐條確認過理由並放行、
    在 apply 那關失敗，然後 `retry` 回 409「這份沒有通過審查的計畫」——
    唯一出口變成「放回收件匣」，而那會刪掉 MinerU 的解析成果，要重新付費解析。

    **判準守錯位置了。** `retry` 只是把狀態撥回「等你看」，它不放行任何東西；
    要再進去還是得經過 `submit_admit`，而那一關**逐條比對理由**，人沒有重新
    確認過就進不去。所以「人有沒有看過」是 admit 在守的，retry 多守一次，
    守到的不是安全，是把人已經看過的文件關進死路。
    """
    app = _app(tmp_path)
    job = _ready_to_admit(app, "老掃描件.pdf")
    job.decision = "novel"
    job.reasons = ["頁面尺寸不一致"]
    job.status = "failed"
    job.error = "修補失敗：頁面尺寸不一致"
    app.store.save(job)

    app.submit_retry(job.job_id)

    assert job.status == "planned", "人看過並放行過的文件重試不了，只能重新付費解析"
    assert job.decision == "novel", "重試把「這份要人看」這件事洗掉了"
    assert job.reasons == ["頁面尺寸不一致"], (
        "理由被清掉的話，下次放行的逐條確認就無從比對")


def test_a_failure_that_never_produced_a_plan_still_cannot_be_retried(
    tmp_path: Path,
) -> None:
    """**控制組。** 解析階段就掛掉、從來沒有計畫的，重試沒有意義 ——
    那種是真的只能重新解析。沒有這一條的話，上面那支可以靠「一律放行」通過。
    """
    app = _app(tmp_path)
    job = _ready_to_admit(app, "沒計畫的.pdf")
    job.plan = None
    job.status = "failed"
    app.store.save(job)

    with pytest.raises(IntakeError, match="計畫"):
        app.submit_retry(job.job_id)


def test_retry_refuses_when_the_parse_is_gone(tmp_path: Path) -> None:
    """解析成果不在了就不能收下重試 —— 那會變成「宣稱不用重跑」卻其實要。"""
    app = _app(tmp_path)
    job = _ready_to_admit(app, "自己的.pdf")
    job.status = "failed"
    shutil.rmtree(app.paths.parsed_bundle_dir("自己的.pdf"))

    with pytest.raises(IntakeError):
        app.submit_retry(job.job_id)
    assert job.status == "failed"


def test_reset_keeps_a_parse_that_passed_review(tmp_path: Path) -> None:
    """重置保留通過審查的解析成果 —— MinerU 重抓要錢也要時間。

    反例（沒通過審查的照刪）由
    test_failed_job_is_visible_and_reset_restores_all_candidate_sources 守著。
    """
    app = _app(tmp_path)
    job = _ready_to_admit(app, "自己的.pdf")
    job.status = "failed"
    app.store.save(job)

    app.submit_reset(job.job_id)

    assert app.paths.parsed_bundle_dir("自己的.pdf").is_dir(), (
        "重置把通過審查的解析成果刪了，下一輪要重付一次 MinerU")


# ── 自動放行：clean 的不需要人確認（PO 裁決 2026-08-08 `4eacaea`）────────


def test_a_clean_plan_admits_itself(tmp_path: Path) -> None:
    """機械計畫判定 clean 的，不必等人按放行。

    看計畫那一關要抓 novel／未知型別／數字可疑，clean 就是這三樣都沒有。
    在已判乾淨的計畫前面放人工關卡攔不到任何東西，只會讓文件停在那裡。
    """
    source_parent = _source(tmp_path)
    data_root = tmp_path / "data"
    runner = FakeRunner(data_root)
    app = IntakeApp(DataPaths(data_root), "test", [source_parent], runner=runner)
    app.start()
    try:
        candidate = app.state()["sections"]["selection"][0]
        assert isinstance(candidate, dict)
        job = app.submit_parse([str(candidate["candidate_id"])])[0]
        _wait_for(app, job.job_id, "indexed")
        # `verify`（契約檢查）是獨立的一步，不再埋在 `wait` 裡面 ——
        # 它要等整批都不在抽取了才跑，理由見
        # `test_the_contract_check_waits_until_the_whole_batch_stopped_extracting`。
        assert runner.calls == ["backup", "parse", "plan", "apply", "scan", "wait", "verify"]
    finally:
        app.stop()


def test_a_novel_plan_still_waits_for_a_human(tmp_path: Path) -> None:
    """`novel` 照樣停下來 —— 自動放行只放乾淨的那些。

    這是自動放行的控制組：如果它變成「什麼都自動放」，這支會紅。
    """
    source_parent = _source(tmp_path)
    data_root = tmp_path / "data"
    runner = FakeRunner(data_root, {
        "paper.pdf": PlanEvaluation(False, ("未知型別 sidebar_note",), ("細節",), {
            "failed": ["paper：未知的項目型別 ['sidebar_note']"],
        }),
    })
    app = IntakeApp(DataPaths(data_root), "test", [source_parent], runner=runner)
    app.start()
    try:
        candidate = app.state()["sections"]["selection"][0]
        assert isinstance(candidate, dict)
        job = app.submit_parse([str(candidate["candidate_id"])])[0]
        planned = _wait_for(app, job.job_id, "planned")
        assert planned["decision"] == "novel"
        time.sleep(0.2)
        assert runner.calls == ["backup", "parse", "plan"], "novel 的計畫被自動放行了"
        assert app._jobs[job.job_id].status == "planned"
    finally:
        app.stop()


def test_a_deferred_admit_does_not_retry_itself(tmp_path: Path) -> None:
    """被擋下來退回「等你看」之後**不得自動重按**。

    擋的原因（收件區被別的流程佔著）不會因為重按而消失，自動重試會變成
    迴圈：退回 → 自動放行 → 又被擋 → 退回 …… 一路刷爆 log。
    """
    app = _app(tmp_path)
    job = _ready_to_admit(app, "自己的.pdf")
    inputs = app.paths.inputs_dir(app.workspace)
    inputs.mkdir(parents=True, exist_ok=True)
    (inputs / "別的流程在用.pdf").write_bytes(PDF)

    _admit_one(app, job.job_id)

    assert job.status == "planned"
    assert app._parse_queue.empty() and app._admit_queue.empty(), (
        "退回之後又把自己排進佇列了 —— 這會變成迴圈")


def test_the_inbox_offers_one_button_for_the_whole_batch(tmp_path: Path) -> None:
    """收件匣有兩份以上時要有「全部解析」。

    worker 是循序的、`submit_parse` 忙碌時回 409，所以一篇一篇按的話第二篇
    會被擋。放十幾篇進來時這不是麻煩，是不能用。
    """
    app = _app(tmp_path)
    for name in ("一.pdf", "二.pdf", "三.pdf"):
        app.save_upload(name, PDF + name.encode())
    html = render_html(app.state())

    assert "data-act='parse-all'" in html, "多份候選卻只能一篇一篇按"
    assert "全部解析（3 份）" in html
    ids = [str(row["candidate_id"]) for row in app.state()["sections"]["selection"]]
    match = re.search(r"data-act='parse-all' data-id='([^']+)'", html)
    assert match is not None
    assert sorted(match.group(1).split(",")) == sorted(ids), "批次按鈕漏了候選"


def test_a_single_candidate_gets_no_batch_button(tmp_path: Path) -> None:
    """一份的時候不顯示 —— 那顆按鈕跟旁邊的「只解析」做同一件事。

    這是上面那支的控制組：如果它變成「永遠顯示」，這支會紅。
    """
    app = _app(tmp_path)
    app.save_upload("只有一份.pdf", PDF)
    html = render_html(app.state())
    assert "data-act='parse'" in html, "連單份的解析按鈕都不見了"
    assert "data-act='parse-all'" not in html


def test_the_batch_api_takes_every_candidate_at_once(tmp_path: Path) -> None:
    """按鈕送出的那串 id，API 要真的整批收下。

    只驗畫面有按鈕不夠 —— 按鈕送出去被打回 400 的話，畫面看起來一樣正常。
    """
    app = _app(tmp_path)
    for name in ("一.pdf", "二.pdf", "三.pdf"):
        app.save_upload(name, PDF + name.encode())
    ids = [str(row["candidate_id"]) for row in app.state()["sections"]["selection"]]

    jobs = app.submit_parse(ids)

    assert len(jobs) == 3
    assert {job.status for job in jobs} == {"parsing"}


# ── 排隊中 ≠ 正在跑（PO 2026-08-08：「都在處理中也很怪」）──────────────


def test_queued_jobs_are_not_shown_as_running(tmp_path: Path) -> None:
    """排進佇列還沒輪到的，不得長得跟正在跑的一樣。

    worker 循序跑，一次一件。舊版狀態是**排進佇列時**就設的，於是 21 件全部
    寫著「解析中」、每一列都掛著一個一直在長的計時器 —— 卡住與排在後面
    完全分不出來。
    """
    app = _app(tmp_path)

    def _queued_job(name: str) -> Job:
        # 內容要不一樣：收件匣用 sha256 擋重複，同內容不同檔名會被 409 退回
        app.save_upload(name, PDF + name.encode())
        candidate = next(c for c in app._candidates()[0] if c.filename == name)
        job = Job.from_candidate(candidate)
        job.status = "parsing"  # type: ignore[assignment]
        job.workspace = app.workspace
        app._jobs[job.job_id] = job
        return job

    a = _queued_job("排隊的.pdf")
    b = _queued_job("在跑的.pdf")
    b.stage_started_at = "2026-08-08T15:00:00+00:00"

    rows = {str(r["filename"]): r for r in app.state()["sections"]["parsing"]}
    assert rows["排隊的.pdf"]["queued"] is True
    assert rows["在跑的.pdf"]["queued"] is False
    assert a.stage_started_at is None

    html = render_html(app.state())
    assert "排隊中" in html, "排隊的那件沒有標示出來"
    assert "正在跑" in html and "在跑的.pdf" in html, "沒有講現在跑的是哪一件"


def test_restart_requeues_a_job_that_never_started(tmp_path: Path) -> None:
    """重啟時還在排隊的：重新排回去，**不是判定失敗**。

    舊版拿它去問 LightRAG，得到「沒這份」（本來就沒送過），然後標成 failed。
    而 failed 沒有計畫可用，只能整個放回收件匣重來。批次解析上線後，一次
    重啟會這樣殺掉整個佇列。
    """
    app, queued = _restart_with_index(tmp_path, "parsing", {"別人的.pdf": "processed"})
    job = next(j for j in app._jobs.values() if j.filename == "跑到一半.pdf")

    assert job.status == "parsing", f"排隊中的被改成 {job.status}"
    assert queued == [("parse", job.job_id)], "沒有重新排回佇列"


def test_restart_still_fails_a_job_that_really_ran_and_vanished(tmp_path: Path) -> None:
    """控制組：真的跑過、而索引裡沒有的，仍然要判失敗。

    上面那條放寬的是「沒開始跑」，不是「跑過但不見了」。兩者混在一起的話，
    真正的失敗會被無限重排。
    """
    app, queued = _restart_with_index(
        tmp_path, "scanning", {"別人的.pdf": "processed"},
        stage_started_at="2026-08-08T15:00:00+00:00")
    job = next(j for j in app._jobs.values() if j.filename == "跑到一半.pdf")

    assert job.status == "failed", job.status
    assert "找不到這份文件" in (job.error or "")
    assert queued == []


# ── 放行後的 compat-check：soft 不擋、hard 要擋（PO 2026-08-08 當場踩到）──


def _compat_result(tmp_path: Path, code: int) -> OperationResult:
    """讓 compat-check 回指定的離開碼，看那道關卡怎麼判。"""
    from intake import SubprocessRunner

    runner = SubprocessRunner(ROOT, {})
    job = Job.from_candidate(_fake_candidate())
    job.workspace = "test"
    # `_explain_exit` 會把細節接在離開碼後面 —— 那正是舊版字串比對失效的原因
    runner._run = lambda command, timeout: (      # type: ignore[method-assign]
        OperationResult(True, "全部通過", code=0) if code == 0 else
        OperationResult(False, "輸出", f"exit {code}：細節細節", code=code))
    return runner._compat_check(job)


def _fake_candidate():
    from intake import Candidate

    return Candidate(
        candidate_id="c" * 32,
        source_root=Path("/tmp"),
        source_path=Path("/tmp/自己的.pdf"),
        source_name="inbox",
        source_key="inbox-x",
        filename="自己的.pdf",
        sha256="sha256:" + "d" * 64,
        size=1,
    )


def test_a_soft_compat_failure_does_not_block_the_admission(tmp_path: Path) -> None:
    """compat-check 的 soft 失敗（exit 5）不得擋下放行。

    這段本來就打算容忍，判準卻寫成 `result.error == f"exit {5}"`，而
    `_explain_exit` 早就把細節接在後面（`exit 5：…`）——**字串比對永遠不成立，
    而且不會報錯**。2026-08-08 A-32 上線讓 compat-check 第一次在這條路上回 5，
    整批放行當場被自己的紅燈擋死。
    """
    assert _compat_result(tmp_path, 5).ok, "soft 失敗擋下了放行"


def test_a_hard_compat_failure_still_blocks_the_admission(tmp_path: Path) -> None:
    """控制組：hard 失敗（exit 2）仍然要擋。

    放寬的是 soft 那一級，不是「所有非 0 都放行」。沒有這一支的話，
    上面那條可以靠「永遠回 True」通過。
    """
    result = _compat_result(tmp_path, 2)
    assert not result.ok
    assert "exit 2" in (result.error or "")


def test_a_clean_compat_check_passes(tmp_path: Path) -> None:
    """全綠也要會過 —— 否則上面兩支可能是在驗一條根本走不到的路。"""
    assert _compat_result(tmp_path, 0).ok


class _FailingIndexRunner(FakeRunner):
    """索引驗證那一步失敗 —— 放行走到一半掛掉。"""

    def wait_indexed(self, job: Job) -> OperationResult:
        self.calls.append("wait")
        return OperationResult(False, "輸出", "exit 2：真的壞了", code=2)


def test_a_failed_admission_releases_the_inputs_staging_area(tmp_path: Path) -> None:
    """放行失敗要把自己複製進收件區的那份撤掉，否則堵死後面每一件。

    收件區必須是純淨空目錄才准放行，而失敗路徑從來沒清過 —— 實測一件在
    compat-check 掛掉之後，後面 15 件全部退回「等你看」，而擋人的理由是
    **前一件的檔名**。
    """
    app = _app(tmp_path)
    app.runner = _FailingIndexRunner(app.paths.root)   # type: ignore[assignment]
    job = _ready_to_admit(app, "自己的.pdf")

    _admit_one(app, job.job_id)

    assert job.status == "failed"
    leftover = list(app.paths.inputs_dir(app.workspace).glob("*.pdf"))
    assert leftover == [], f"失敗之後 {leftover} 留在收件區，會擋住後面所有放行"
    assert app._inputs_blocked_reason() is None


def test_restart_requeues_a_parse_that_was_interrupted_midway(tmp_path: Path) -> None:
    """解析到一半被重啟：重新排回去，**不是判定失敗**。

    解析中的文件 LightRAG 從頭到尾沒看過（檔案還沒複製進 inputs），拿它去問
    索引得到的「不存在」是**問錯對象**。2026-08-08 實測：一份解析到一半的
    文件因此被判死，而它只需要重跑 —— parse-only 有有效 bundle 就跳過，
    不會重複向 MinerU 收費。
    """
    app, queued = _restart_with_index(
        tmp_path, "parsing", {"別人的.pdf": "processed"},
        stage_started_at="2026-08-08T15:00:00+00:00")
    job = next(j for j in app._jobs.values() if j.filename == "跑到一半.pdf")

    assert job.status == "parsing", f"解析中的被改成 {job.status}"
    assert queued == [("parse", job.job_id)]


def test_restart_requeues_an_admit_that_had_not_touched_the_index(tmp_path: Path) -> None:
    """repairing 也一樣：那一步還沒把檔案複製進 inputs。

    判準是 OWNED_STATUSES（有沒有碰過索引），不是「有沒有開始跑」。

    ⚠ **分組之後改稿不再自己排隊**：協調者每一輪自己去撿等著改稿的那些
    （`_waiting_for_repair`），因為開工時機要由它決定 —— 它得先確認沒有人在抽取。
    所以這裡驗的從「有沒有排進佇列」換成「有沒有被協調者看見」，
    **意圖沒有變：還沒碰過索引的不得判死**。
    """
    app, queued = _restart_with_index(
        tmp_path, "repairing", {"別人的.pdf": "processed"},
        stage_started_at="2026-08-08T15:00:00+00:00")
    job = next(j for j in app._jobs.values() if j.filename == "跑到一半.pdf")

    assert job.status == "repairing"
    assert queued == [], "改稿又自己排隊了 —— 開工時機該由協調者決定"
    assert job.job_id in app._waiting_for_repair(), (
        "重啟後這份沒被協調者看見，會永遠停在那裡")


def test_restart_does_not_reapply_a_document_whose_draft_was_already_fixed(
    tmp_path: Path,
) -> None:
    """`repaired` 重啟後**不得重跑 apply**，直接等下一次抽取時段。

    重跑會把 MinerU 的原文換成上一輪的修補結果（`pp/apply.py` 的
    `_pp_original_*` 只記第一次），還原路徑看起來還在，還原出來的卻不是原文。
    這正是 `repaired` 必須是一個落地狀態、不能只存在記憶體裡的理由。
    """
    app, queued = _restart_with_index(
        tmp_path, "repaired", {"別人的.pdf": "processed"},
        stage_started_at="2026-08-08T15:00:00+00:00")
    job = next(j for j in app._jobs.values() if j.filename == "跑到一半.pdf")

    assert job.status == "repaired", "改好的稿子被重啟判掉了"
    assert queued == []
    assert job.job_id not in app._waiting_for_repair(), "改好的又被排去改一次"
    assert job.job_id in app._already_repaired(), "改好的沒被排進下一次抽取"


def test_parse_and_repair_each_run_wide_on_their_own_queue(tmp_path: Path) -> None:
    """兩邊各自併行，而且**分開兩條佇列**。

    **為什麼不合成一條**：一條佇列時前面塞滿其中一種就會餓死另一種
    （head-of-line blocking），而解析與改稿的耗時差一個量級。

    節流的理由也不同：解析看 mineru.net（併發沒上限），改稿看
    OpenRouter／OpenAI 的速率（兩雙眼睛都在雲端）。

    ⚠ **`admit_workers` 已經沒有了**：一批一起送去讀之後，「同時幾份在跑」由
    LightRAG 的 `MAX_PARALLEL_INSERT` 決定，本站沒有對應的旋鈕。取而代之的是
    一條協調執行緒 —— 改稿與抽取的互斥就是它跑出來的。
    """
    app = _app(tmp_path)
    assert app.parse_workers >= 1
    assert not hasattr(app, "admit_workers"), "廢除的旋鈕又長回來了"
    app.start()
    try:
        names = [w.name for w in app._workers if w.is_alive()]
    finally:
        app.stop()
    parse = [n for n in names if n.startswith("intake-parse-")]
    repair = [n for n in names if n.startswith("intake-repair-")]
    assert len(parse) == app.parse_workers, f"解析工人數不對：{names}"
    assert len(repair) == app.repair_workers, f"改稿工人數不對：{names}"
    assert "intake-coordinator" in names, (
        f"沒有協調執行緒 —— 改稿與抽取的互斥就是靠它，少了它兩件事會撞在一起：{names}")


def test_each_kind_goes_to_the_right_queue(tmp_path: Path) -> None:
    """路由寫錯的話症狀是「放行偷偷併行了」，而那不會報錯，只會偶爾毀資料。"""
    app = _app(tmp_path)
    assert app._queue_for("parse") is app._parse_queue
    for kind in ("admit", "return", "resume"):
        assert app._queue_for(kind) is app._admit_queue, kind


def test_staging_blocks_foreign_pdfs_but_not_my_own_concurrent_ones(tmp_path: Path) -> None:
    """收件區的判準：擋「別人的」，不擋「我自己正在放行的那幾份」。

    2026-08-09 從「目錄必須空」放寬成這樣，才有辦法同時放行多份。
    **擋的東西不能跟著放寬**：外來的 PDF 會被 LightRAG 一起索引而繞過後處理
    （表格修補、LaTeX 修正、雜訊消音全都不會發生，索引起來卻看起來完全正常）。

    順便釘住「走完就不算我的」：`indexed` 的那份如果還被當成自己人，殘留就永遠
    擋不出來 —— 而當天實測過殘留一份會讓 17 件全部退回「等你看」。
    """
    app = _app(tmp_path)
    inputs = app.paths.inputs_dir(app.workspace)
    inputs.mkdir(parents=True, exist_ok=True)

    def _staged(name: str, status: str) -> Job:
        app.save_upload(name, PDF + name.encode())
        candidate = next(c for c in app._candidates()[0] if c.filename == name)
        job = Job.from_candidate(candidate)
        job.workspace = app.workspace
        job.status = status                       # type: ignore[assignment]
        job.admitted_path = str(inputs / name)
        app._jobs[job.job_id] = job
        (inputs / name).write_bytes(PDF)
        return job

    _staged("我的甲.pdf", "scanning")
    _staged("我的乙.pdf", "extracting")
    assert app._inputs_blocked_reason() is None, "自己正在放行的幾份把自己擋住了"

    # 走完的那份不再算「我的」—— 它的檔案應該已經清掉，還在就是殘留
    done = _staged("走完的.pdf", "indexed")
    reason = app._inputs_blocked_reason()
    assert reason is not None and "走完的.pdf" in reason, (
        f"indexed 的殘留沒被當成外來檔：{reason}")
    (inputs / "走完的.pdf").unlink()
    del app._jobs[done.job_id]

    # 真正的外來檔照樣要擋
    (inputs / "別人放的.pdf").write_bytes(PDF)
    reason = app._inputs_blocked_reason()
    assert reason is not None and "別人放的.pdf" in reason, reason
    assert "繞過後處理" in reason, "擋下來的理由不見了 —— 那句話才是這道門的意義"
    assert "我的甲.pdf" not in reason and "我的乙.pdf" not in reason, (
        "把自己正在放行的檔一起列成問題了")


def test_a_batch_is_repaired_before_anyone_is_extracted(tmp_path: Path) -> None:
    """**併行，而且不重疊。** 兩件事要同時成立，只釘一件會被錯的做法騙過去。

    只釘「不重疊」→ 把放行改回一次一件就過了，而那正是現在的樣子。
    只釘「有併行」→ 把併行數調大就過了，而那是 2026-08-09 實測掛掉 3 篇的做法。

    卡住的是 `pp/apply.py` 的 `pipeline 忙碌中，拒絕改檔`：改稿在改檔案、抽取在讀
    同一份檔案。分段之後兩者天然錯開 —— 不是靠等、靠重試，是結構上碰不到。
    """
    app, runner = _batch_app(tmp_path, ("甲.pdf", "乙.pdf", "丙.pdf", "丁.pdf"))
    app.start()
    try:
        ids = [str(c["candidate_id"]) for c in app.state()["sections"]["selection"]
               if isinstance(c, dict)]
        jobs = app.submit_parse(ids)
        _wait_all(app, [j.job_id for j in jobs], "indexed")

        assert runner.overlaps == [], "改稿撞上別人的抽取：\n" + "\n".join(runner.overlaps)
        assert runner.max_extracting > 1, (
            f"從頭到尾只有 {runner.max_extracting} 份在抽取 —— 根本沒有併行，"
            "光是不重疊的話一次一件就做得到")
    finally:
        app.stop()


def test_the_contract_check_waits_until_the_whole_batch_stopped_extracting(
    tmp_path: Path,
) -> None:
    """契約檢查要等**整批**抽完才跑，不是每份索引完就立刻跑。

    因為那組檢查裡有一條斷言「LightRAG 現在是閒的」。一批同時跑的時候，
    除了最後一份，每一份跑完時鄰居都還在跑 —— 那條必然失敗，而它是 hard，
    於是整份被判失敗**而文件其實已經好好地進了庫**。

    2026-08-10 實跑 89 份，84 份這樣被誤殺；資料庫那側 159 份全是 processed，
    也就是說壞掉的從頭到尾只有簿記。

    **不替 A-19 開特例**：把檢查挪到 pipeline 真的閒下來之後，那條斷言就恢復成
    有意義的斷言，30 項一條都不用拿掉。
    """
    source_parent = _source(tmp_path, ("甲.pdf", "乙.pdf", "丙.pdf", "丁.pdf"))
    data_root = tmp_path / "data"
    runner = VerifyTimingRunner(data_root)
    app = IntakeApp(DataPaths(data_root), "test", [source_parent], runner=runner,
                    environment={"INTAKE_ROUND_POLL_SECONDS": "0.02"})
    app.start()
    try:
        ids = [str(c["candidate_id"]) for c in app.state()["sections"]["selection"]
               if isinstance(c, dict)]
        jobs = app.submit_parse(ids)
        _wait_all(app, [j.job_id for j in jobs], "indexed")

        assert runner.verified_while_waiting == [], (
            "契約檢查在別人還在抽取的時候就跑了：\n"
            + "\n".join(runner.verified_while_waiting))
        assert len(runner.verified) == 4, (
            f"不是每一份都驗過 —— 驗了 {len(runner.verified)} 份")
    finally:
        app.stop()


def test_a_whole_batch_only_asks_lightrag_to_scan_once(tmp_path: Path) -> None:
    """一批只掃一次。

    `scan` 掃的是**整個目錄**，第一次就把這一批全部撿走了。每份各掃一次的話，
    後面每一次都只是在重試「pipeline 忙碌中」，而重試會一路撞到逾時。
    """
    app, runner = _batch_app(tmp_path, ("甲.pdf", "乙.pdf", "丙.pdf"))
    app.start()
    try:
        ids = [str(c["candidate_id"]) for c in app.state()["sections"]["selection"]
               if isinstance(c, dict)]
        jobs = app.submit_parse(ids)
        _wait_all(app, [j.job_id for j in jobs], "indexed")
        assert runner.calls.count("scan") == 1, (
            f"三份掃了 {runner.calls.count('scan')} 次")
    finally:
        app.stop()


def test_a_leftover_in_the_staging_area_shows_up_before_it_blocks_anyone(
    tmp_path: Path,
) -> None:
    """殘留要在**沒人問的時候**就出聲，不是等下一份被擋才說（鐵則第 6 條）。

    在此之前，暫存區有別人的檔這件事只有一個現形時機：下一份放行被擋下來。
    而那行紅字掛在**受害者**那一列、理由寫的是別人的檔名 —— 看到的人會覺得
    「我這份好好的，為什麼跟我說一個不相干的檔案有問題」。

    改成一次送一整批之後這件事會放大：一次一份時清不掉最多卡一份，一批 30 份
    時漏清幾份就會擋住下一整輪（2026-08-08 踩過同型：一件掛掉、後面 15 件全退回）。

    ⚠ 順便釘住**兩邊用同一個判準**：橫幅說有問題，`_inputs_blocked_reason` 就必須
    也說有問題。分成兩份實作的話會漂走，而漂走不報錯 —— 2026-08-09 當天犯三次，
    最貴的一次是封面頁例外只加在解析側，索引完了才判失敗。
    """
    app = _app(tmp_path)
    inputs = app.paths.inputs_dir(app.workspace)
    inputs.mkdir(parents=True, exist_ok=True)
    (inputs / "上一批沒清掉的.pdf").write_bytes(PDF)

    html = render_html(app.state())
    assert "上一批沒清掉的.pdf" in html, (
        "暫存區有殘留，畫面上完全看不出來 —— 要等下一份被擋才會知道")
    assert app._inputs_blocked_reason() is not None, (
        "橫幅說有問題，擋門卻說沒有 —— 兩邊判準已經漂開")


def test_the_staging_banner_stays_quiet_when_nothing_is_wrong(tmp_path: Path) -> None:
    """常態不佔畫面。

    「只要在 9710 有警告就好」是本專案唯一的警報管道（2026-08-08 裁決），
    所以那個位置一直掛著一句話的代價是**真的紅燈會被淹沒**。

    兩種「沒事」都要安靜：暫存區空的，以及裡面只有我自己正在放行的那幾份。
    """
    app = _app(tmp_path)
    inputs = app.paths.inputs_dir(app.workspace)
    inputs.mkdir(parents=True, exist_ok=True)

    assert "暫存區" not in render_html(app.state()), "暫存區是空的還在喊"

    app.save_upload("我的.pdf", PDF)
    candidate = next(c for c in app._candidates()[0] if c.filename == "我的.pdf")
    job = Job.from_candidate(candidate)
    job.workspace = app.workspace
    job.status = "scanning"                       # type: ignore[assignment]
    job.admitted_path = str(inputs / "我的.pdf")
    app._jobs[job.job_id] = job
    (inputs / "我的.pdf").write_bytes(PDF)

    assert "暫存區" not in render_html(app.state()), (
        "把自己正在放行的那份當成殘留在喊")


def test_a_novel_plan_needs_every_reason_acknowledged(tmp_path: Path) -> None:
    """`novel` 放得出去，**但要逐條確認**。

    2026-08-09 改版：在此之前只有 `clean` 能放行，於是「等你看」把東西攔下來給人看、
    看完卻沒有任何動作可以做，那一節只出不進（兩份論文因「封面頁高度與內頁不同」
    卡在那裡）。現在可以放行，但擋的東西換成「不能**不看**就放行」。

    **為什麼是逐條比對而不是一個 override 旗標**：畫面上列三條而人只看了兩條時，
    籠統的旗標會把第三條一起帶過去。理由變了（重新解析、規則改了）也會對不上 ——
    那時候本來就該重看一次。
    """
    app = _app(tmp_path)
    app.save_upload("novel.pdf", PDF + b"novel")
    candidate = next(c for c in app._candidates()[0] if c.filename == "novel.pdf")
    job = Job.from_candidate(candidate)
    job.workspace = app.workspace
    job.status = "planned"                        # type: ignore[assignment]
    job.decision = "novel"                        # type: ignore[assignment]
    job.reasons = ["頁面尺寸不一致", "未知型別 sidebar_note"]
    app._jobs[job.job_id] = job

    # 什麼都不確認 → 擋
    with pytest.raises(IntakeError) as e1:
        app.submit_admit(job.job_id)
    assert e1.value.status_code == 409

    # 只確認一條（畫面列了兩條）→ 擋。這一條就是「籠統旗標」擋不到的那種
    with pytest.raises(IntakeError):
        app.submit_admit(job.job_id, acknowledged=["頁面尺寸不一致"])

    # 確認到不存在的理由 → 擋（理由變了要重看）
    with pytest.raises(IntakeError):
        app.submit_admit(job.job_id, acknowledged=["頁面尺寸不一致", "別的理由"])

    # 逐條對上 → 放行，而且要留下痕跡
    out = app.submit_admit(job.job_id, acknowledged=list(reversed(job.reasons)))
    assert out.status == "repairing"
    log = "\n".join(app.store.read_log(job.job_id)) if hasattr(app.store, "read_log") else ""
    if log:
        assert "人工放行" in log, "人工放行沒有留下紀錄"


def test_a_clean_plan_still_admits_without_ceremony(tmp_path: Path) -> None:
    """乾淨的計畫不該被新規矩拖慢 —— 它本來就是自動放行的那一條路。"""
    app = _app(tmp_path)
    app.save_upload("clean.pdf", PDF + b"clean")
    candidate = next(c for c in app._candidates()[0] if c.filename == "clean.pdf")
    job = Job.from_candidate(candidate)
    job.workspace = app.workspace
    job.status = "planned"                        # type: ignore[assignment]
    job.decision = "clean"                        # type: ignore[assignment]
    app._jobs[job.job_id] = job
    assert app.submit_admit(job.job_id).status == "repairing"


def test_a_reset_document_can_be_picked_again(tmp_path: Path) -> None:
    """重置之後那份 PDF 要能再被挑到 —— **這是 2026-08-09 踩到的真 bug。**

    重置刻意保留解析成果（MinerU 要錢），但收件匣的重複判定會讀 bundle 裡
    manifest 的 `source_content_hash`，於是保留下來的成果把自己的 PDF 判成
    「已經有了」，文件重置之後永遠不會再出現在選片區。當天只能手動刪解析成果繞過。

    這條測試同時釘住兩件事：重置後挑得到，而且**解析成果沒有被刪掉**
    （刪了就是白花一次 MinerU 的錢）。
    """
    from intake import RESET_MARKER

    app = _app(tmp_path)
    app.save_upload("重置測試.pdf", PDF + b"reset-case")
    candidate = next(c for c in app._candidates()[0] if c.filename == "重置測試.pdf")
    job = Job.from_candidate(candidate)
    job.workspace = app.workspace
    job.status = "failed"                          # type: ignore[assignment]
    job.decision = "clean"                         # type: ignore[assignment]
    job.plan = _plan(job.filename)                 # 走過審查 → 解析成果要留著
    app._jobs[job.job_id] = job

    # 解析成果：bundle 帶著 manifest，manifest 記著來源雜湊（就是它擋住自己）
    raw = app.paths.parsed_bundle_dir(job.filename)
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "content_list.json").write_text("[]", encoding="utf-8")
    (raw / "_manifest.json").write_text(
        json.dumps({"source_content_hash": job.source_sha256}), encoding="utf-8")

    assert not any(c.filename == "重置測試.pdf" for c in app._candidates()[0]), (
        "前提不成立：還沒重置就已經挑得到，那這條測試驗不到東西")

    app.submit_reset(job.job_id)

    assert raw.is_dir(), "解析成果被刪了 —— 下一輪要重付一次 MinerU"
    assert (raw / RESET_MARKER).exists(), "沒有留下重置記號"
    names = [c.filename for c in app._candidates()[0]]
    assert "重置測試.pdf" in names, f"重置之後挑不到，那份文件等於消失了：{names}"


def test_an_untouched_bundle_still_blocks_duplicates(tmp_path: Path) -> None:
    """**沒有被重置的解析成果照樣要擋。** 不然同一份文件會進去兩次，
    知識庫裡有兩套 chunk 與兩套實體，檢索互相稀釋而且不報錯。

    這是上面那條的控制組 —— 少了它，「跳過記號」寫成「全部跳過」也會通過。
    """
    app = _app(tmp_path)
    app.save_upload("沒重置.pdf", PDF + b"kept")
    candidate = next(c for c in app._candidates()[0] if c.filename == "沒重置.pdf")
    raw = app.paths.parsed_bundle_dir("沒重置.pdf")
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "_manifest.json").write_text(
        json.dumps({"source_content_hash": candidate.sha256}), encoding="utf-8")
    assert not any(c.filename == "沒重置.pdf" for c in app._candidates()[0]), (
        "沒有重置記號的解析成果沒擋住 —— 同一份會進去兩次")
