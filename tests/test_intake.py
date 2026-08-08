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
        assert list(admitted_pdf.parent.glob("*.pdf")) == [admitted_pdf]
        return OperationResult(True, "fake scan")

    def wait_indexed(self, job: Job) -> OperationResult:
        self.calls.append("wait")
        return OperationResult(True, "fake indexed")


class ExplodingParseRunner(FakeRunner):
    def parse(self, job: Job, source_pdf: Path) -> OperationResult:
        super().parse(job, source_pdf)
        raise RuntimeError("測試用解析失敗")


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
    transition(job, "admitted")
    transition(job, "scanning")
    transition(job, "extracting")
    transition(job, "indexed")
    with pytest.raises(IntakeError):
        transition(job, "planned")
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
        planned = _wait_for(app, job.job_id, "planned")
        assert planned["decision"] == "clean"
        assert list(paths.inputs_dir("test").glob("*.pdf")) == []

        app.submit_admit(job.job_id)
        _wait_for(app, job.job_id, "indexed")
        assert runner.calls == ["parse", "plan", "apply", "scan", "wait"]
        assert list(paths.inputs_dir("test").glob("*.pdf")) == []
        state_path = paths.intake_job_dir(job.job_id) / "job.json"
        saved = json.loads(state_path.read_text(encoding="utf-8"))
        assert saved["status"] == "indexed"
    finally:
        app.stop()


def test_pending_confirmation_is_grouped_by_reason_and_has_no_admit_button(tmp_path: Path) -> None:
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

        # ⚠ 這是安全斷言：待確認的文件**不得**出現放行按鈕。
        # not-in 形式必須有控制組——否則按鈕屬性一改名，這行會從「守住安全」
        # 默默變成「永遠說沒事」，找的是一個已經不存在的字串。鐵則 7 那一族。
        assert "data-act=" in html, "data-act 不存在，下面的 not-in 斷言會假通過"
        assert "data-act='admit'" not in html
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


def _restart_with_index(tmp_path: Path, status: str, rows: dict[str, str] | None = None):
    """建一個在途的 job、落盤，然後用指定的索引現實重啟一個新 app。"""
    app = _app(tmp_path)
    job = _job_in(app, "跑到一半.pdf", status)
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
        self._queue.put = lambda item: seen.append(item)  # type: ignore[method-assign]
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

    app._run_admit(job.job_id)

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
