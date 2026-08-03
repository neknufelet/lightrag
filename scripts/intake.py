#!/usr/bin/env python3
"""收件匣／進料審核台。

這支服務只負責「挑一份、只解析、看機械計畫、放行」的流程編排；解析、後處理與
LightRAG 抽取仍由既有腳本／HTTP 端點執行。審核中的 PDF 放在 ``library/`` 與
``work/parsed/``，``inputs/<workspace>`` 只有在後處理成功後才會短暫出現。

服務本身只用 Python 標準函式庫。HTTP 請求不直接做長時間工作，所有長工作交給
唯一一條序列 worker，job 狀態與事件都落到 DataPaths.root/intake/。
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import logging
import math
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Literal, Mapping, Protocol, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mineru_common import load_env  # noqa: E402
from pp.paths import DataPaths, configured_data_root  # noqa: E402


REPO = Path(__file__).resolve().parent.parent
LOGGER = logging.getLogger("intake")
JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")
PDF_NAME_RE = re.compile(r"^[^/\\\x00]+\.pdf$", re.IGNORECASE)
MAX_BODY_BYTES = 1024 * 1024
MAX_PAGES = 100_000
MAX_ITEMS = 1_000_000
MAX_PAGE_POINTS = 10_000.0

JobStatus = Literal[
    "candidate", "parsing", "planned", "failed_parse", "repairing", "admitted",
    "scanning", "extracting", "indexed", "returned", "failed",
]

TERMINAL_STATUSES: frozenset[str] = frozenset({"indexed", "returned", "failed_parse", "failed"})
ACTIVE_STATUSES: frozenset[str] = frozenset({
    "parsing", "repairing", "admitted", "scanning", "extracting",
})

TRANSITIONS: dict[str, frozenset[str]] = {
    "candidate": frozenset({"parsing"}),
    "parsing": frozenset({"planned", "failed_parse", "failed"}),
    "planned": frozenset({"repairing", "returned", "failed"}),
    "repairing": frozenset({"admitted", "failed"}),
    "admitted": frozenset({"scanning", "failed"}),
    "scanning": frozenset({"extracting", "failed"}),
    "extracting": frozenset({"indexed", "failed"}),
    "failed_parse": frozenset(),
    "indexed": frozenset(),
    "returned": frozenset(),
    "failed": frozenset(),
}


class IntakeError(RuntimeError):
    """服務可以回給 HTTP 呼叫端的錯誤。"""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class StateError(IntakeError):
    """不合法的 job 狀態轉換。"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _safe_pdf_name(name: str) -> bool:
    if not name or not PDF_NAME_RE.fullmatch(name):
        return False
    path = Path(name)
    return not path.is_absolute() and path.name == name and ".." not in path.parts


def _safe_job_id(value: str) -> bool:
    return bool(JOB_ID_RE.fullmatch(value))


def _safe_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return (cleaned or "source")[:64]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _atomic_json_write(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=1, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _string_field(data: Mapping[str, object], name: str) -> str:
    value = data.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"job state 缺少字串欄位 {name}")
    return value


def _string_list(data: Mapping[str, object], name: str) -> list[str]:
    value = data.get(name, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"job state 欄位 {name} 不是字串清單")
    return list(value)


@dataclass(frozen=True)
class SourceRoot:
    path: Path
    label: str
    key: str


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    source_root: Path
    source_path: Path
    source_name: str
    source_key: str
    filename: str
    sha256: str
    size: int

    def public(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "filename": self.filename,
            "source": self.source_name,
            "size": self.size,
            "pages": None,
            "items": None,
            "status": "candidate",
        }


@dataclass
class Job:
    job_id: str
    candidate_id: str
    source_root: str
    source_path: str
    source_name: str
    source_key: str
    filename: str
    source_sha256: str
    status: JobStatus
    decision: str | None
    reasons: list[str]
    details: list[str]
    plan: dict[str, object] | None
    created_at: str
    created_epoch: float
    updated_at: str
    workspace: str = ""
    processed_index: int | None = None
    library_path: str | None = None
    parsed_source_path: str | None = None
    admitted_path: str | None = None
    error: str | None = None

    @classmethod
    def from_candidate(cls, candidate: Candidate) -> "Job":
        now = _now_iso()
        return cls(
            job_id=uuid.uuid4().hex,
            candidate_id=candidate.candidate_id,
            source_root=str(candidate.source_root),
            source_path=str(candidate.source_path),
            source_name=candidate.source_name,
            source_key=candidate.source_key,
            filename=candidate.filename,
            source_sha256=candidate.sha256,
            status="candidate",
            decision=None,
            reasons=[],
            details=[],
            plan=None,
            created_at=now,
            created_epoch=time.time(),
            updated_at=now,
        )

    def public(self, log_tail: str, metrics: dict[str, object]) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "candidate_id": self.candidate_id,
            "filename": self.filename,
            "source": self.source_name,
            "status": self.status,
            "decision": self.decision,
            "reasons": list(self.reasons),
            "details": list(self.details),
            "plan": self.plan,
            "metrics": metrics,
            "processed_index": self.processed_index,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error": self.error,
            "log_tail": log_tail,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "candidate_id": self.candidate_id,
            "source_root": self.source_root,
            "source_path": self.source_path,
            "source_name": self.source_name,
            "source_key": self.source_key,
            "filename": self.filename,
            "source_sha256": self.source_sha256,
            "status": self.status,
            "decision": self.decision,
            "reasons": list(self.reasons),
            "details": list(self.details),
            "plan": self.plan,
            "created_at": self.created_at,
            "created_epoch": self.created_epoch,
            "updated_at": self.updated_at,
            "workspace": self.workspace,
            "processed_index": self.processed_index,
            "library_path": self.library_path,
            "parsed_source_path": self.parsed_source_path,
            "admitted_path": self.admitted_path,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, raw: object) -> "Job":
        if not isinstance(raw, dict):
            raise ValueError("job state 不是 JSON object")
        status = _string_field(raw, "status")
        if status not in TRANSITIONS:
            raise ValueError(f"未知 job 狀態 {status!r}")
        if not _safe_job_id(_string_field(raw, "job_id")):
            raise ValueError("job_id 格式不合法")
        plan = raw.get("plan")
        if plan is not None and not isinstance(plan, dict):
            raise ValueError("plan 不是 JSON object")
        decision = raw.get("decision")
        if decision is not None and not isinstance(decision, str):
            raise ValueError("decision 不是字串")
        processed_index = raw.get("processed_index")
        if processed_index is not None and (
            isinstance(processed_index, bool) or not isinstance(processed_index, int)
        ):
            raise ValueError("processed_index 不是整數")
        created_epoch = raw.get("created_epoch")
        if isinstance(created_epoch, bool) or not isinstance(created_epoch, (int, float)):
            raise ValueError("created_epoch 不是數字")
        return cls(
            job_id=_string_field(raw, "job_id"),
            candidate_id=_string_field(raw, "candidate_id"),
            source_root=_string_field(raw, "source_root"),
            source_path=_string_field(raw, "source_path"),
            source_name=_string_field(raw, "source_name"),
            source_key=_string_field(raw, "source_key"),
            filename=_string_field(raw, "filename"),
            source_sha256=_string_field(raw, "source_sha256"),
            status=cast_job_status(status),
            decision=decision,
            reasons=_string_list(raw, "reasons"),
            details=_string_list(raw, "details"),
            plan=plan,
            created_at=_string_field(raw, "created_at"),
            created_epoch=float(created_epoch),
            updated_at=_string_field(raw, "updated_at"),
            workspace=_string_field(raw, "workspace"),
            processed_index=processed_index,
            library_path=_optional_string(raw.get("library_path")),
            parsed_source_path=_optional_string(raw.get("parsed_source_path")),
            admitted_path=_optional_string(raw.get("admitted_path")),
            error=_optional_string(raw.get("error")),
        )


def cast_job_status(value: str) -> JobStatus:
    return value  # validated by Job.from_dict before this call


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("可選路徑欄位不是字串")
    return value


class JobStore:
    def __init__(self, paths: DataPaths) -> None:
        self.paths = paths
        self.paths.intake_jobs_dir.mkdir(parents=True, exist_ok=True)
        self.load_errors: list[str] = []

    def load(self) -> list[Job]:
        jobs: list[Job] = []
        for state_path in sorted(self.paths.intake_jobs_dir.glob("*/job.json")):
            try:
                jobs.append(Job.from_dict(_read_json(state_path)))
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                message = f"無法讀取 {state_path}: {type(exc).__name__}: {exc}"
                self.load_errors.append(message)
                LOGGER.error(message)
        return jobs

    def save(self, job: Job) -> None:
        job.updated_at = _now_iso()
        path = self.paths.intake_job_dir(job.job_id) / "job.json"
        _atomic_json_write(path, job.to_dict())

    def append_log(self, job_id: str, message: str) -> None:
        path = self.paths.intake_job_dir(job_id) / "run.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(message.rstrip() + "\n")

    def log_tail(self, job_id: str, limit: int = 4000) -> str:
        path = self.paths.intake_job_dir(job_id) / "run.log"
        if not path.is_file():
            return ""
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                return handle.read()[-limit:]
        except OSError as exc:
            LOGGER.warning("讀取 %s 失敗：%s", path, exc)
            return ""


class EventStore:
    def __init__(self, paths: DataPaths) -> None:
        self.path = paths.intake_events_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.read_errors: list[str] = []

    def append(self, event: Mapping[str, object]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            json.dump(dict(event), handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

    def read(self) -> list[dict[str, object]]:
        if not self.path.is_file():
            return []
        events: list[dict[str, object]] = []
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if not line.strip():
                        continue
                    try:
                        value = json.loads(line)
                    except json.JSONDecodeError as exc:
                        message = f"教學事件第 {line_number} 行不是 JSON：{exc}"
                        self.read_errors.append(message)
                        LOGGER.error(message)
                        continue
                    if not isinstance(value, dict):
                        message = f"教學事件第 {line_number} 行不是 object"
                        self.read_errors.append(message)
                        LOGGER.error(message)
                        continue
                    events.append(value)
        except OSError as exc:
            message = f"無法讀取教學事件：{type(exc).__name__}: {exc}"
            self.read_errors.append(message)
            LOGGER.error(message)
        return events


def transition(job: Job, target: JobStatus) -> None:
    if target not in TRANSITIONS.get(job.status, frozenset()):
        raise StateError(f"不合法狀態轉換：{job.status} → {target}", 409)
    job.status = target


def _configured_source_roots(configured: Sequence[Path]) -> list[SourceRoot]:
    roots: list[SourceRoot] = []
    seen: set[Path] = set()
    for configured_path in configured:
        path = configured_path.expanduser().resolve()
        candidates: list[Path] = []
        if path.name == "raw" and path.is_dir():
            candidates = [path]
        elif path.is_dir():
            nested = [item for item in sorted(path.glob("*/raw")) if item.is_dir()]
            candidates = nested or ([path] if any(path.glob("*.pdf")) else [])
        if not candidates:
            LOGGER.warning("來源白名單不存在或沒有 PDF：%s", path)
        for raw_dir in candidates:
            resolved = raw_dir.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            label = resolved.parent.name if resolved.name == "raw" else resolved.name
            key_hash = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:10]
            roots.append(SourceRoot(resolved, label or "source", f"{_safe_component(label)}-{key_hash}"))
    return roots


class CandidateScanner:
    def __init__(self, paths: DataPaths, configured: Sequence[Path]) -> None:
        self.paths = paths
        self.configured = tuple(configured)

    def _known_hashes(self) -> set[str]:
        known: set[str] = set()
        pdfs = list(self.paths.library_dir.rglob("*.pdf"))
        pdfs.extend(self.paths.parsed_dir.glob("*.pdf"))
        pdfs.extend(self.paths.inputs_root.rglob("*.pdf"))
        for pdf in pdfs:
            if pdf.is_file():
                try:
                    known.add(_sha256(pdf))
                except OSError as exc:
                    LOGGER.warning("無法計算既有檔案 sha：%s：%s", pdf, exc)
        for manifest in self.paths.parsed_dir.glob("*.mineru_raw/_manifest.json"):
            try:
                raw = _read_json(manifest)
                if isinstance(raw, dict):
                    value = raw.get("source_content_hash")
                    if isinstance(value, str):
                        known.add(value)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                LOGGER.warning("無法讀取解析 manifest %s：%s", manifest, exc)
        return known

    def scan(self, used_ids: set[str], used_hashes: set[str]) -> tuple[list[Candidate], list[str]]:
        known = self._known_hashes() | used_hashes
        candidates: list[Candidate] = []
        warnings: list[str] = []
        if not self.configured:
            warnings.append("尚未設定 INTAKE_SOURCES；選片清單不代表來源為空。")
        for root in _configured_source_roots(self.configured):
            try:
                files = sorted(root.path.iterdir())
            except OSError as exc:
                warning = f"無法讀取來源 {root.path}: {type(exc).__name__}: {exc}"
                LOGGER.warning(warning)
                warnings.append(warning)
                continue
            for source in files:
                if not source.is_file() or source.suffix.lower() != ".pdf":
                    continue
                resolved = source.resolve()
                if not _is_within(resolved, root.path):
                    warning = f"來源檔案跳過（超出白名單）：{source}"
                    LOGGER.error(warning)
                    warnings.append(warning)
                    continue
                if not _safe_pdf_name(source.name):
                    warning = f"來源檔名不安全，跳過：{source.name!r}"
                    LOGGER.error(warning)
                    warnings.append(warning)
                    continue
                try:
                    digest = _sha256(resolved)
                    size = resolved.stat().st_size
                except OSError as exc:
                    warning = f"無法讀取來源檔案 {resolved}: {type(exc).__name__}: {exc}"
                    LOGGER.warning(warning)
                    warnings.append(warning)
                    continue
                candidate_id = hashlib.sha256(
                    f"{resolved}\x00{digest}".encode("utf-8")
                ).hexdigest()[:32]
                if candidate_id in used_ids or digest in known:
                    continue
                candidates.append(Candidate(
                    candidate_id=candidate_id,
                    source_root=root.path,
                    source_path=resolved,
                    source_name=root.label,
                    source_key=root.key,
                    filename=source.name,
                    sha256=digest,
                    size=size,
                ))
        return candidates, warnings


@dataclass(frozen=True)
class OperationResult:
    ok: bool
    output: str = ""
    error: str | None = None
    payload: dict[str, object] | None = None


@dataclass(frozen=True)
class PlanEvaluation:
    accepted: bool
    reasons: tuple[str, ...]
    details: tuple[str, ...]
    plan: dict[str, object]


class IntakeRunner(Protocol):
    def parse(self, job: Job, source_pdf: Path) -> OperationResult: ...

    def plan(self, job: Job) -> PlanEvaluation: ...

    def apply(self, job: Job) -> OperationResult: ...

    def scan(self, job: Job, admitted_pdf: Path) -> OperationResult: ...

    def wait_indexed(self, job: Job) -> OperationResult: ...


def _as_mapping(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _failure_reason(message: str) -> str:
    if "未知的項目型別" in message:
        tail = message.split("未知的項目型別", 1)[1].split("——", 1)[0].strip(" ：")
        types = re.findall(r"[A-Za-z_][A-Za-z0-9_-]*", tail)
        return "未知型別 " + (", ".join(types) if types else "未列出")
    if "頁面尺寸不一致" in message:
        return "頁面尺寸不一致"
    if "頁序錯位" in message:
        return "頁序錯位"
    if "比例" in message or "數字" in message:
        return "數字異常"
    return "preflight 擋下"


def _numeric_issues(plan: Mapping[str, object]) -> list[str]:
    issues: list[str] = []

    pages = plan.get("pages")
    if isinstance(pages, bool) or not isinstance(pages, int) or not 0 < pages <= MAX_PAGES:
        issues.append(f"pages={pages!r} 不在 1..{MAX_PAGES} 的合理範圍")
    items = plan.get("items")
    if isinstance(items, bool) or not isinstance(items, int) or not 0 < items <= MAX_ITEMS:
        issues.append(f"items={items!r} 不在 1..{MAX_ITEMS} 的合理範圍")
    page_size = plan.get("page_size")
    if not isinstance(page_size, list) or len(page_size) != 2:
        issues.append(f"page_size={page_size!r} 不是兩個數字")
    else:
        for value in page_size:
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(float(value)) or not 0 < float(value) <= MAX_PAGE_POINTS):
                issues.append(f"page_size={page_size!r} 不在合理範圍")
                break

    noise = _as_mapping(plan.get("noise"))
    ratio = noise.get("ratio")
    if (isinstance(ratio, bool) or not isinstance(ratio, (int, float))
            or not math.isfinite(float(ratio)) or not 0 <= float(ratio) <= 1):
        issues.append(f"漏詞／消音比例 ratio={ratio!r} 不在 0..1")
    if noise.get("suspicious"):
        issues.append("postprocess 判定消音比例異常")

    tables = _as_mapping(plan.get("tables"))
    total_tables = tables.get("total")
    if (isinstance(total_tables, bool) or not isinstance(total_tables, int)
            or not 0 <= total_tables <= (items if isinstance(items, int) else MAX_ITEMS)):
        issues.append(f"tables.total={total_tables!r} 不合理")
    for field_name in ("mute", "held"):
        value = noise.get(field_name)
        if not isinstance(value, list) or len(value) > (items if isinstance(items, int) else MAX_ITEMS):
            issues.append(f"noise.{field_name} 數量不合理")
    for field_name in ("repair", "review"):
        value = tables.get(field_name)
        if not isinstance(value, list) or len(value) > (total_tables if isinstance(total_tables, int) else MAX_ITEMS):
            issues.append(f"tables.{field_name} 數量不合理")
    charts = _as_mapping(plan.get("charts"))
    for field_name in ("convert", "dangling"):
        value = charts.get(field_name)
        if not isinstance(value, list) or len(value) > (items if isinstance(items, int) else MAX_ITEMS):
            issues.append(f"charts.{field_name} 數量不合理")
    return issues


def evaluate_plan_payload(payload: object, expected_doc: str) -> PlanEvaluation:
    if not isinstance(payload, dict):
        return PlanEvaluation(False, ("preflight 擋下",), ("plan 沒有回傳 JSON object",), {})
    raw_failed = payload.get("failed", [])
    failed = [item for item in _as_list(raw_failed) if isinstance(item, str)]
    raw_plans = payload.get("plans", [])
    plans = [item for item in _as_list(raw_plans) if isinstance(item, dict)]
    if failed or not plans:
        messages = failed or ["plan 沒有產出文件計畫"]
        reasons: list[str] = []
        for message in messages:
            reason = _failure_reason(message)
            if reason not in reasons:
                reasons.append(reason)
        return PlanEvaluation(False, tuple(reasons), tuple(messages), {
            "failed": messages,
        })
    plan = plans[0]
    reasons = []
    details: list[str] = []
    doc = plan.get("doc")
    if doc != expected_doc:
        reasons.append("preflight 擋下")
        details.append(f"plan 回傳的文件 {doc!r} 與要求的 {expected_doc!r} 不一致")
    numeric = _numeric_issues(plan)
    if numeric:
        reasons.append("數字異常")
        details.extend(numeric)
    return PlanEvaluation(not reasons, tuple(reasons), tuple(details), plan)


class LightRAGClient:
    def __init__(self, environment: Mapping[str, str]) -> None:
        bind = environment.get("BIND_ADDR", "127.0.0.1")
        port = environment.get("HOST_PORT", "9621")
        self.base_url = f"http://{bind}:{port}"
        self.api_key = environment.get("LIGHTRAG_API_KEY", "")

    def request(self, path: str, method: str = "GET", body: dict[str, object] | None = None) -> dict[str, object]:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            self.base_url + path,
            method=method,
            data=data,
            headers={"X-API-Key": self.api_key, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read()
        value = json.loads(raw or b"{}")
        if not isinstance(value, dict):
            raise ValueError(f"LightRAG {path} 回傳不是 object")
        return value


def _contains_value(value: object, needle: str) -> bool:
    if isinstance(value, dict):
        return any(_contains_value(item, needle) for item in value.values())
    if isinstance(value, list):
        return any(_contains_value(item, needle) for item in value)
    return value == needle


class SubprocessRunner:
    def __init__(self, repo: Path, environment: Mapping[str, str]) -> None:
        self.repo = repo
        self.environment = dict(environment)
        self.python = sys.executable
        self.parse_timeout = _positive_float(environment.get("INTAKE_PARSE_TIMEOUT"), 1800.0)
        self.command_timeout = _positive_float(environment.get("INTAKE_COMMAND_TIMEOUT"), 3600.0)
        self.poll_seconds = _positive_float(environment.get("INTAKE_POLL_SECONDS"), 5.0)
        self.index_timeout = _positive_float(environment.get("INTAKE_INDEX_TIMEOUT"), 86400.0)
        self.client = LightRAGClient(environment)

    def _run(self, command: list[str], timeout: float) -> OperationResult:
        try:
            completed = subprocess.run(
                command,
                cwd=self.repo,
                env=self.environment,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            output = str(exc.stdout or "")
            return OperationResult(False, output, f"命令逾時（{timeout:.0f} 秒）")
        except OSError as exc:
            return OperationResult(False, "", f"無法執行命令：{type(exc).__name__}: {exc}")
        output = completed.stdout or ""
        if completed.returncode != 0:
            return OperationResult(False, output, f"exit {completed.returncode}")
        return OperationResult(True, output)

    def parse(self, job: Job, source_pdf: Path) -> OperationResult:
        del source_pdf
        command = [
            self.python, str(self.repo / "scripts" / "parse-only.py"),
            "--workspace", job_workspace(job), "--source-kind", "parsed",
            "--doc", job.filename, "--timeout", str(int(self.parse_timeout)),
        ]
        return self._run(command, self.parse_timeout + 60)

    def plan(self, job: Job) -> PlanEvaluation:
        command = [
            self.python, str(self.repo / "scripts" / "postprocess.py"),
            "plan", "--workspace", job_workspace(job), "--doc", job.filename, "--json",
        ]
        result = self._run(command, self.command_timeout)
        if not result.output.strip():
            message = result.error or "plan 沒有輸出"
            return PlanEvaluation(False, ("preflight 擋下",), (message,), {})
        try:
            payload = json.loads(result.output)
        except json.JSONDecodeError as exc:
            return PlanEvaluation(False, ("preflight 擋下",), (
                f"plan 輸出不是 JSON：{exc}",
            ), {})
        evaluation = evaluate_plan_payload(payload, job.filename)
        if not result.ok and not evaluation.reasons:
            return PlanEvaluation(False, ("preflight 擋下",), (
                result.error or "plan exit 非 0",
            ), evaluation.plan)
        return evaluation

    def apply(self, job: Job) -> OperationResult:
        command = [
            self.python, str(self.repo / "scripts" / "postprocess.py"),
            "apply", "--workspace", job_workspace(job), "--doc", job.filename, "--commit",
        ]
        return self._run(command, self.command_timeout)

    def scan(self, job: Job, admitted_pdf: Path) -> OperationResult:
        del admitted_pdf
        try:
            payload = self.client.request("/documents/scan", "POST")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return OperationResult(False, "", f"scan 失敗：{type(exc).__name__}: {exc}")
        output = json.dumps(payload, ensure_ascii=False)
        if _contains_value(payload, "scanning_skipped_pipeline_busy"):
            return OperationResult(False, output, "scan 沒有排程：pipeline_busy")
        return OperationResult(True, output, payload=payload)

    def wait_indexed(self, job: Job) -> OperationResult:
        deadline = time.monotonic() + self.index_timeout
        while time.monotonic() < deadline:
            try:
                payload = self.client.request(
                    "/documents/paginated", "POST", {"page": 1, "page_size": 200},
                )
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                return OperationResult(False, "", f"讀取文件狀態失敗：{type(exc).__name__}: {exc}")
            rows = payload.get("documents")
            if not isinstance(rows, list):
                return OperationResult(False, json.dumps(payload, ensure_ascii=False),
                                       "文件狀態回應缺少 documents")
            for row in rows:
                if not isinstance(row, dict):
                    continue
                file_path = str(row.get("file_path") or "")
                if Path(file_path).name != job.filename:
                    continue
                status = str(row.get("status") or "").lower()
                if status == "processed":
                    return self._compat_check(job)
                if status in {"failed", "error", "failure"}:
                    return OperationResult(False, json.dumps(row, ensure_ascii=False),
                                           f"文件狀態為 {status}")
            time.sleep(self.poll_seconds)
        return OperationResult(False, "", f"等待 {job.filename} processed 逾時")

    def _compat_check(self, job: Job) -> OperationResult:
        command = [
            self.python, str(self.repo / "scripts" / "compat-check.py"),
            "--doc", job.filename,
        ]
        return self._run(command, self.command_timeout)


def job_workspace(job: Job) -> str:
    if not job.workspace.strip():
        raise RuntimeError("job 缺少 workspace")
    return job.workspace


def _positive_float(value: str | None, default: float) -> float:
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError:
        LOGGER.warning("環境值不是數字，使用預設值 %s：%r", default, value)
        return default
    if not math.isfinite(parsed) or parsed <= 0:
        LOGGER.warning("環境值不是正數，使用預設值 %s：%r", default, value)
        return default
    return parsed


class IntakeApp:
    def __init__(
        self,
        paths: DataPaths,
        workspace: str,
        source_dirs: Sequence[Path],
        *,
        environment: Mapping[str, str] | None = None,
        repo: Path = REPO,
        runner: IntakeRunner | None = None,
    ) -> None:
        if not workspace.strip():
            raise ValueError("workspace 不能是空字串")
        self.paths = paths
        self.workspace = workspace
        self.environment = dict(environment or {})
        self.repo = repo
        self._lock = threading.RLock()
        self._queue: queue.Queue[tuple[str, str] | None] = queue.Queue()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._running_job_id: str | None = None
        self.store = JobStore(paths)
        self.events = EventStore(paths)
        self._jobs: dict[str, Job] = {job.job_id: job for job in self.store.load()}
        self.scanner = CandidateScanner(paths, source_dirs)
        self.runner = runner or SubprocessRunner(repo, self._runner_environment())
        self._ensure_directories()
        self._recover_active_jobs()

    def _runner_environment(self) -> dict[str, str]:
        environment = dict(os.environ)
        environment.update(self.environment)
        environment.setdefault("WORKSPACE", self.workspace)
        return environment

    def _ensure_directories(self) -> None:
        self.paths.intake_dir.mkdir(parents=True, exist_ok=True)
        self.paths.intake_jobs_dir.mkdir(parents=True, exist_ok=True)
        self.paths.library_dir.mkdir(parents=True, exist_ok=True)
        self.paths.parsed_dir.mkdir(parents=True, exist_ok=True)
        self.paths.inputs_dir(self.workspace).mkdir(parents=True, exist_ok=True)

    def _recover_active_jobs(self) -> None:
        for job in self._jobs.values():
            if job.status not in ACTIVE_STATUSES:
                continue
            job.error = "服務重啟時工作仍在執行，未自動重試；請人工檢查後重新選取。"
            job.status = "failed"
            self.store.save(job)
            self.store.append_log(job.job_id, job.error)

    def start(self) -> None:
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._stop.clear()
            self._worker = threading.Thread(
                target=self._worker_loop,
                name="intake-worker",
                daemon=True,
            )
            self._worker.start()

    def stop(self) -> None:
        with self._lock:
            worker = self._worker
            if worker is None:
                return
            self._stop.set()
            self._queue.put(None)
        worker.join(timeout=5)
        if worker.is_alive():
            LOGGER.warning("intake worker 尚未停止；目前工作仍可能在外部命令內執行")
        with self._lock:
            self._worker = None

    def _busy(self) -> bool:
        return self._running_job_id is not None or not self._queue.empty()

    def _jobs_snapshot(self) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())

    def _candidates(self) -> tuple[list[Candidate], list[str]]:
        jobs = self._jobs_snapshot()
        used_ids = {job.candidate_id for job in jobs}
        used_hashes = {job.source_sha256 for job in jobs}
        return self.scanner.scan(used_ids, used_hashes)

    def _candidate_map(self) -> dict[str, Candidate]:
        candidates, _ = self._candidates()
        return {candidate.candidate_id: candidate for candidate in candidates}

    def _get_job(self, job_id: str) -> Job:
        if not _safe_job_id(job_id):
            raise IntakeError("job_id 格式不合法", 400)
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise IntakeError("找不到這份 job", 404)
        return job

    def submit_parse(self, candidate_ids: Sequence[str]) -> list[Job]:
        ids = list(candidate_ids)
        if not ids or any(not _safe_job_id(value) for value in ids):
            raise IntakeError("candidate_id 格式不合法", 400)
        if len(set(ids)) != len(ids):
            raise IntakeError("candidate_id 不得重複", 400)
        with self._lock:
            if self._busy():
                raise IntakeError("已有序列工作進行中，請等待狀態更新", 409)
            existing_candidates = {job.candidate_id for job in self._jobs.values()}
        candidates = self._candidate_map()
        missing = [value for value in ids if value not in candidates]
        if missing:
            raise IntakeError("候選已不存在或已被收件：" + ", ".join(missing), 404)
        selected = [candidates[value] for value in ids]
        if any(candidate.candidate_id in existing_candidates for candidate in selected):
            raise IntakeError("這份候選已有持久化 job，不能重複解析", 409)
        if len({candidate.filename for candidate in selected}) != len(selected):
            raise IntakeError("同一批不能有相同檔名，避免解析 bundle 互相覆蓋", 409)
        jobs: list[Job] = []
        with self._lock:
            for candidate in selected:
                if any(job.filename == candidate.filename for job in self._jobs.values()):
                    raise IntakeError(f"檔名已在 job 紀錄中：{candidate.filename}", 409)
                job = Job.from_candidate(candidate)
                job.workspace = self.workspace
                transition(job, "parsing")
                self._jobs[job.job_id] = job
                self.store.save(job)
                self._queue.put(("parse", job.job_id))
                jobs.append(job)
        return jobs

    def submit_admit(self, job_id: str) -> Job:
        with self._lock:
            if self._busy():
                raise IntakeError("已有序列工作進行中，請等待狀態更新", 409)
        job = self._get_job(job_id)
        with self._lock:
            if job.status != "planned" or job.decision != "clean":
                raise IntakeError("只有機械計畫通過的待審核文件可以放行", 409)
            job.workspace = self.workspace
            transition(job, "repairing")
            self.store.save(job)
            self._queue.put(("admit", job.job_id))
        return job

    def submit_return(self, job_id: str) -> Job:
        with self._lock:
            if self._busy():
                raise IntakeError("已有序列工作進行中，請等待狀態更新", 409)
        job = self._get_job(job_id)
        with self._lock:
            if job.status != "planned":
                raise IntakeError("只有待審核文件可以退回", 409)
            job.workspace = self.workspace
            self._queue.put(("return", job.job_id))
        return job

    def _worker_loop(self) -> None:
        while True:
            task = self._queue.get()
            try:
                if task is None:
                    return
                kind, job_id = task
                with self._lock:
                    self._running_job_id = job_id
                if kind == "parse":
                    self._run_parse(job_id)
                elif kind == "admit":
                    self._run_admit(job_id)
                elif kind == "return":
                    self._run_return(job_id)
                else:
                    raise RuntimeError(f"未知 worker 工作類型 {kind!r}")
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("worker 工作失敗")
                if task is not None:
                    self._mark_failed(task[1], f"worker 例外：{type(exc).__name__}: {exc}")
            finally:
                with self._lock:
                    self._running_job_id = None
                self._queue.task_done()

    def _job_for_worker(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise RuntimeError(f"worker 找不到 job {job_id}")
        job.workspace = self.workspace
        return job

    def _candidate_for_job(self, job: Job) -> Candidate:
        root = Path(job.source_root).resolve()
        source = Path(job.source_path).resolve()
        if not _is_within(source, root) or source.name != job.filename:
            raise RuntimeError(f"來源檔案已超出白名單：{job.filename}")
        if not source.is_file() or _sha256(source) != job.source_sha256:
            raise RuntimeError(f"來源檔案不存在或 sha256 已改變：{job.filename}")
        return Candidate(
            candidate_id=job.candidate_id,
            source_root=root,
            source_path=source,
            source_name=job.source_name,
            source_key=job.source_key,
            filename=job.filename,
            sha256=job.source_sha256,
            size=source.stat().st_size,
        )

    def _copy_library(self, candidate: Candidate) -> Path:
        destination_dir = self.paths.library_source_dir(candidate.source_key)
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / candidate.filename
        if not _safe_pdf_name(destination.name) or destination.parent != destination_dir:
            raise RuntimeError("library 目標檔名不安全")
        if destination.exists():
            if not destination.is_file() or _sha256(destination) != candidate.sha256:
                raise RuntimeError(f"library 既有檔案內容不符：{destination}")
            return destination
        temporary = destination_dir / f".{candidate.candidate_id}.partial"
        temporary.unlink(missing_ok=True)
        shutil.copy2(candidate.source_path, temporary)
        try:
            if _sha256(temporary) != candidate.sha256:
                raise RuntimeError("複製到 library 後 sha256 不一致")
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        return destination

    def _stage_parsed_source(self, job: Job, library_path: Path) -> Path:
        destination = self.paths.parsed_dir / job.filename
        if not _safe_pdf_name(destination.name) or destination.parent != self.paths.parsed_dir:
            raise RuntimeError("work/parsed 目標檔名不安全")
        if destination.exists():
            if not destination.is_file() or _sha256(destination) != job.source_sha256:
                raise RuntimeError(f"work/parsed 既有來源內容不符：{destination}")
            return destination
        temporary = self.paths.parsed_dir / f".{job.job_id}.partial"
        temporary.unlink(missing_ok=True)
        shutil.copy2(library_path, temporary)
        try:
            if _sha256(temporary) != job.source_sha256:
                raise RuntimeError("複製到 work/parsed 後 sha256 不一致")
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        return destination

    def _append_operation(self, job: Job, label: str, result: OperationResult) -> None:
        self.store.append_log(job.job_id, f"[{_now_iso()}] {label}")
        if result.output:
            self.store.append_log(job.job_id, result.output)
        if result.error:
            self.store.append_log(job.job_id, result.error)

    def _run_parse(self, job_id: str) -> None:
        job = self._job_for_worker(job_id)
        try:
            candidate = self._candidate_for_job(job)
            library_path = self._copy_library(candidate)
            parsed_source = self._stage_parsed_source(job, library_path)
            job.library_path = str(library_path)
            job.parsed_source_path = str(parsed_source)
            self.store.save(job)
            result = self.runner.parse(job, parsed_source)
            self._append_operation(job, "只解析", result)
            if not result.ok:
                job.error = result.error or "只解析失敗"
                transition(job, "failed_parse")
                self.store.save(job)
                return
            raw = self.paths.parsed_bundle_dir(job.filename)
            if not (raw / "content_list.json").is_file():
                raise RuntimeError("只解析成功但 work/parsed 缺少 content_list.json")
            evaluation = self.runner.plan(job)
            self._record_plan(job, evaluation)
        except Exception as exc:  # noqa: BLE001
            self._mark_failed(job_id, f"解析／計畫失敗：{type(exc).__name__}: {exc}")

    def _record_plan(self, job: Job, evaluation: PlanEvaluation) -> None:
        with self._lock:
            job.plan = evaluation.plan
            job.reasons = list(evaluation.reasons)
            job.details = list(evaluation.details)
            job.decision = "clean" if evaluation.accepted else "novel"
            max_index = max((item.processed_index or 0 for item in self._jobs.values()), default=0)
            job.processed_index = max_index + 1
            transition(job, "planned")
            self.store.save(job)
        if evaluation.reasons:
            for index, reason in enumerate(evaluation.reasons):
                detail = evaluation.details[index] if index < len(evaluation.details) else reason
                event = {
                    "event_id": uuid.uuid4().hex,
                    "created_at": _now_iso(),
                    "processed_index": job.processed_index,
                    "job_id": job.job_id,
                    "document": job.filename,
                    "reason": reason,
                    "detail": detail,
                }
                self.events.append(event)
                self.store.append_log(job.job_id, f"教學事件：{reason}：{detail}")

    def _inputs_pdf_paths(self) -> list[Path]:
        inputs = self.paths.inputs_dir(self.workspace)
        return sorted(path for path in inputs.glob("*.pdf") if path.is_file())

    def _assert_inputs_empty(self) -> None:
        existing = self._inputs_pdf_paths()
        if existing:
            names = ", ".join(path.name for path in existing)
            raise RuntimeError(f"放行中止：inputs/{self.workspace} 不是純淨空目錄：{names}")

    def _copy_admitted(self, job: Job, source: Path) -> Path:
        inputs = self.paths.inputs_dir(self.workspace)
        destination = inputs / job.filename
        if not _safe_pdf_name(destination.name) or destination.parent != inputs:
            raise RuntimeError("inputs 目標檔名不安全")
        if destination.exists():
            raise RuntimeError(f"inputs 目標已存在：{destination}")
        temporary = inputs / f".{job.job_id}.partial"
        temporary.unlink(missing_ok=True)
        shutil.copy2(source, temporary)
        try:
            if _sha256(temporary) != job.source_sha256:
                raise RuntimeError("複製進 inputs 後 sha256 不一致")
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        return destination

    def _cleanup_admitted(self, job: Job, admitted: Path) -> None:
        if not admitted.exists():
            return
        if not admitted.is_file() or _sha256(admitted) != job.source_sha256:
            raise RuntimeError(f"索引完成但 inputs 檔案內容不符，拒絕刪除：{admitted}")
        admitted.unlink()

    def _run_admit(self, job_id: str) -> None:
        job = self._job_for_worker(job_id)
        admitted: Path | None = None
        try:
            parsed = self.paths.parsed_dir / job.filename
            if (job.parsed_source_path is not None
                    and Path(job.parsed_source_path) != parsed):
                raise RuntimeError("job 的 parsed source 不在既定 work/parsed 路徑")
            if not parsed.is_file() or _sha256(parsed) != job.source_sha256:
                raise RuntimeError("放行前找不到或驗證不了解析來源 PDF")
            self._assert_inputs_empty()
            applied = self.runner.apply(job)
            self._append_operation(job, "修補", applied)
            if not applied.ok:
                self._mark_failed(job_id, applied.error or "修補失敗")
                return
            # 設計 C 的核心順序：apply 成功之後才允許複製進 inputs。
            self._assert_inputs_empty()
            admitted = self._copy_admitted(job, parsed)
            job.admitted_path = str(admitted)
            with self._lock:
                transition(job, "admitted")
                self.store.save(job)
                transition(job, "scanning")
                self.store.save(job)
            scanned = self.runner.scan(job, admitted)
            self._append_operation(job, "開始索引", scanned)
            if not scanned.ok:
                self._mark_failed(job_id, scanned.error or "scan 失敗")
                return
            with self._lock:
                transition(job, "extracting")
                self.store.save(job)
            indexed = self.runner.wait_indexed(job)
            self._append_operation(job, "等待索引完成", indexed)
            if not indexed.ok:
                self._mark_failed(job_id, indexed.error or "索引驗證失敗")
                return
            self._cleanup_admitted(job, admitted)
            with self._lock:
                transition(job, "indexed")
                self.store.save(job)
        except Exception as exc:  # noqa: BLE001
            self._mark_failed(job_id, f"放行失敗：{type(exc).__name__}: {exc}")

    def _run_return(self, job_id: str) -> None:
        job = self._job_for_worker(job_id)
        try:
            raw = self.paths.parsed_bundle_dir(job.filename)
            parsed = self.paths.parsed_dir / job.filename
            if not _is_within(raw, self.paths.parsed_dir) or raw.parent != self.paths.parsed_dir:
                raise RuntimeError("退回目標不在既定 parsed 目錄")
            if raw.is_dir():
                shutil.rmtree(raw)
            parsed.unlink(missing_ok=True)
            with self._lock:
                transition(job, "returned")
                job.error = "已退回；library 複本保留作為稽核備份。"
                self.store.save(job)
            self.store.append_log(job.job_id, job.error)
        except Exception as exc:  # noqa: BLE001
            self._mark_failed(job_id, f"退回失敗：{type(exc).__name__}: {exc}")

    def _mark_failed(self, job_id: str, message: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                LOGGER.error("要標記失敗但找不到 job：%s：%s", job_id, message)
                return
            if job.status not in TERMINAL_STATUSES:
                if "failed" in TRANSITIONS.get(job.status, frozenset()):
                    transition(job, "failed")
                else:
                    job.status = "failed"
            job.error = message
            self.store.save(job)
        self.store.append_log(job_id, message)

    def health(self) -> dict[str, object]:
        with self._lock:
            worker_alive = self._worker is not None and self._worker.is_alive()
            running = self._running_job_id is not None
            jobs = list(self._jobs.values())
        pending = [job for job in jobs if job.status not in TERMINAL_STATUSES]
        oldest = None
        if pending:
            oldest = max(0.0, time.time() - min(job.created_epoch for job in pending))
        return {
            "status": "ok",
            "worker_alive": worker_alive,
            "running": running,
            "oldest_pending_age_s": oldest,
            "workspace": self.workspace,
        }

    def _metrics(self, plan: dict[str, object] | None) -> dict[str, object]:
        if not plan:
            return {"pages": None, "items": None, "mute": 0, "empty_tables": 0,
                    "charts": 0, "item_delta": 0, "leakage_rate": None,
                    "parse_options": "未取得"}
        noise = _as_mapping(plan.get("noise"))
        tables = _as_mapping(plan.get("tables"))
        charts = _as_mapping(plan.get("charts"))
        mute = len(_as_list(noise.get("mute")))
        empty_tables = len(_as_list(tables.get("repair")))
        chart_count = len(_as_list(charts.get("convert"))) + len(_as_list(charts.get("dangling")))
        leakage = plan.get("leakage_rate")
        if not isinstance(leakage, (int, float)) or isinstance(leakage, bool):
            leakage = None
        return {
            "pages": plan.get("pages"),
            "items": plan.get("items"),
            "mute": mute,
            "empty_tables": empty_tables,
            "charts": chart_count,
            "item_delta": 0,
            "leakage_rate": leakage,
            "parse_options": plan.get("parse_options") or "manifest 未提供",
        }

    def _public_job(self, job: Job) -> dict[str, object]:
        return job.public(self.store.log_tail(job.job_id), self._metrics(job.plan))

    def state(self) -> dict[str, object]:
        candidates, warnings = self._candidates()
        jobs = self._jobs_snapshot()
        public_jobs = [self._public_job(job) for job in sorted(jobs, key=lambda item: item.updated_at)]
        sections: dict[str, list[dict[str, object]]] = {
            "selection": [candidate.public() for candidate in candidates],
            "parsing": [item for item in public_jobs if item["status"] == "parsing"],
            "review": [item for item in public_jobs if item["status"] == "planned"],
            "in_progress": [item for item in public_jobs if item["status"] in {
                "repairing", "admitted", "scanning", "extracting",
            }],
            "completed": [item for item in public_jobs if item["status"] == "indexed"],
        }
        grouped: dict[str, dict[str, object]] = {}
        for item in public_jobs:
            if item["status"] == "planned" and item["decision"] != "clean":
                reasons = item["reasons"] if isinstance(item["reasons"], list) else []
            elif item["status"] in {"failed_parse", "failed"}:
                reasons = ["解析失敗" if item["status"] == "failed_parse" else "工作失敗"]
            else:
                reasons = []
            for reason in reasons:
                group = grouped.setdefault(reason, {"reason": reason, "count": 0, "jobs": []})
                group["count"] = int(group["count"]) + 1
                job_list = group["jobs"]
                if isinstance(job_list, list):
                    job_list.append({"job_id": item["job_id"], "filename": item["filename"],
                                     "source": item["source"]})
        events = self.events.read()
        processed = max((job.processed_index or 0 for job in jobs), default=0)
        events = sorted(events, key=lambda event: str(event.get("created_at", "")))
        last_event = events[-1] if events else None
        distance = None
        if last_event is not None and isinstance(last_event.get("processed_index"), int):
            distance = max(0, processed - int(last_event["processed_index"]))
        convergence = {
            "processed": processed,
            "events": events[-20:],
            "distance_since_last_event": distance,
            "warning": "；".join(self.store.load_errors + self.events.read_errors) or None,
        }
        return {
            "sections": sections,
            "jobs": public_jobs,
            "pending_by_reason": sorted(grouped.values(), key=lambda item: str(item["reason"])),
            "convergence": convergence,
            "source_warnings": warnings,
            "health": self.health(),
        }


def _runtime_environment() -> dict[str, str]:
    environment = load_env(REPO)
    environment.update(os.environ)
    if "PP_DATA_ROOT" not in environment and environment.get("DATA_ROOT"):
        environment["PP_DATA_ROOT"] = environment["DATA_ROOT"]
    return environment


def _source_paths(environment: Mapping[str, str], overrides: Sequence[str] | None) -> list[Path]:
    values = list(overrides or [])
    if not values:
        values = [item.strip() for item in environment.get("INTAKE_SOURCES", "").split(",") if item.strip()]
    return [Path(value) for value in values]


def _json_body(handler: BaseHTTPRequestHandler) -> dict[str, object]:
    raw_length = handler.headers.get("Content-Length")
    try:
        length = int(raw_length or "0")
    except ValueError as exc:
        raise IntakeError("Content-Length 不合法", 400) from exc
    if length < 0 or length > MAX_BODY_BYTES:
        raise IntakeError("請求 body 太大", 413)
    try:
        raw = handler.rfile.read(length)
        value = json.loads(raw or b"{}")
    except (OSError, json.JSONDecodeError) as exc:
        raise IntakeError(f"JSON body 不合法：{exc}", 400) from exc
    if not isinstance(value, dict):
        raise IntakeError("JSON body 必須是 object", 400)
    return value


def _candidate_ids(payload: Mapping[str, object]) -> list[str]:
    single = payload.get("candidate_id")
    many = payload.get("candidate_ids")
    if isinstance(single, str):
        return [single]
    if isinstance(many, list) and all(isinstance(item, str) for item in many):
        return list(many)
    raise IntakeError("需要 candidate_id 或 candidate_ids", 400)


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _format_size(value: object) -> str:
    if not isinstance(value, int):
        return "—"
    if value < 1024 * 1024:
        return f"{value / 1024:.1f} KiB"
    return f"{value / (1024 * 1024):.1f} MiB"


def _status_label(status: object, decision: object = None) -> str:
    if status == "planned" and decision == "clean":
        return "待放行"
    labels = {
        "candidate": "選片",
        "parsing": "解析中",
        "planned": "待確認",
        "failed_parse": "解析失敗",
        "repairing": "修補中",
        "admitted": "已准入",
        "scanning": "掃描中",
        "extracting": "抽取中",
        "indexed": "已完成",
        "returned": "已退回",
        "failed": "失敗",
    }
    return labels.get(str(status), str(status))


def _render_candidate_row(candidate: Mapping[str, object]) -> str:
    candidate_id = _esc(candidate.get("candidate_id", ""))
    return (
        "<div class='row candidate-row'>"
        f"<div><strong>{_esc(candidate.get('filename', ''))}</strong>"
        f"<small>{_esc(candidate.get('source', ''))} · {_format_size(candidate.get('size'))}</small></div>"
        f"<span class='chip'>{_status_label('candidate')}</span>"
        f"<button class='secondary' data-action='parse' data-candidate-id='{candidate_id}'>只解析</button>"
        "</div>"
    )


def _render_job_row(job: Mapping[str, object]) -> str:
    metrics = job.get("metrics") if isinstance(job.get("metrics"), dict) else {}
    pages = metrics.get("pages", "—") if isinstance(metrics, dict) else "—"
    items = metrics.get("items", "—") if isinstance(metrics, dict) else "—"
    job_id = _esc(job.get("job_id", ""))
    link = f"?job={job_id}"
    action = ""
    if job.get("status") == "planned" and job.get("decision") == "clean":
        action = f"<a class='secondary' href='{link}'>查看計畫</a>"
    elif job.get("status") == "planned":
        action = f"<a class='secondary' href='{link}'>查看原因</a>"
    return (
        "<div class='row job-row'>"
        f"<div><a href='{link}'><strong>{_esc(job.get('filename', ''))}</strong></a>"
        f"<small>{_esc(job.get('source', ''))} · {pages} 頁／{items} 項</small></div>"
        f"<span class='chip'>{_esc(_status_label(job.get('status'), job.get('decision')))}</span>"
        f"{action}</div>"
    )


def _render_section(title: str, rows: Sequence[Mapping[str, object]], renderer: Callable[[Mapping[str, object]], str]) -> str:
    body = "".join(renderer(row) for row in rows)
    if not body:
        body = "<div class='empty'>目前沒有</div>"
    return f"<section><h2>{_esc(title)}</h2>{body}</section>"


def _render_convergence(convergence: Mapping[str, object]) -> str:
    events = convergence.get("events")
    event_rows: list[str] = []
    if isinstance(events, list):
        for event in reversed(events[-8:]):
            if not isinstance(event, dict):
                continue
            event_rows.append(
                "<li>"
                f"<strong>{_esc(event.get('reason', '教學事件'))}</strong> · "
                f"{_esc(event.get('document', ''))} · {_esc(event.get('created_at', ''))}"
                "</li>"
            )
    event_body = "<ul>" + "".join(event_rows) + "</ul>" if event_rows else "<p>尚無教學事件。</p>"
    distance = convergence.get("distance_since_last_event")
    distance_text = "尚無事件" if distance is None else f"{distance} 份"
    warning = convergence.get("warning")
    warning_html = f"<p class='warning'>⚠ {_esc(warning)}</p>" if warning else ""
    return (
        "<section class='convergence'>"
        "<div><p class='eyebrow'>收斂列</p><h1>這批還在教我們東西嗎</h1></div>"
        "<div class='convergence-stats'>"
        f"<span>已處理份數<strong>{_esc(convergence.get('processed', 0))}</strong></span>"
        f"<span>距上次事件<strong>{_esc(distance_text)}</strong></span>"
        "</div>"
        f"<div class='events'><h3>教學事件</h3>{event_body}</div>{warning_html}"
        "</section>"
    )


def _render_pending_groups(groups: object) -> str:
    if not isinstance(groups, list) or not groups:
        return "<section class='pending-groups'><h2>待確認（按原因）</h2><div class='empty'>目前沒有待確認原因</div></section>"
    rows: list[str] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        jobs = group.get("jobs")
        names = []
        if isinstance(jobs, list):
            names = [str(item.get("filename", "")) for item in jobs if isinstance(item, dict)]
        rows.append(
            "<div class='reason-row'>"
            f"<strong>✗ {_esc(group.get('reason', '未分類'))}</strong>"
            f"<span>{_esc(group.get('count', 0))} 份</span>"
            f"<small>{_esc('、'.join(names))}</small>"
            "</div>"
        )
    return "<section class='pending-groups'><h2>待確認（按原因）</h2>" + "".join(rows) + "</section>"


def _render_plan(job: Mapping[str, object] | None) -> str:
    if job is None:
        return (
            "<section class='plan-card'><p class='eyebrow'>處理計畫</p>"
            "<h2>先從左側選一份已解析文件</h2>"
            "<p>只解析完成並產生機械計畫後，這裡才會出現放行動作。</p></section>"
        )
    metrics = job.get("metrics") if isinstance(job.get("metrics"), dict) else {}
    if not isinstance(metrics, dict):
        metrics = {}
    reasons = job.get("reasons") if isinstance(job.get("reasons"), list) else []
    details = job.get("details") if isinstance(job.get("details"), list) else []
    if reasons:
        things = []
        for index, reason in enumerate(reasons):
            detail = details[index] if index < len(details) else reason
            things.append(
                "<li><strong>"
                f"{_esc(reason)}</strong><small>{_esc(detail)}</small>"
                "<em>決定會變成規則，套用到之後所有文件</em></li>"
            )
        thing_body = "<ul class='new-things'>" + "".join(things) + "</ul>"
    else:
        thing_body = "<p class='clean-message'>沒有。全部命中既有規則</p>"
    plan_action = ""
    if job.get("status") == "planned" and job.get("decision") == "clean":
        job_id = _esc(job.get("job_id", ""))
        plan_action = (
            f"<button class='primary' data-action='admit' data-job-id='{job_id}'>"
            "放行 · 修補並索引</button>"
            f"<button class='secondary' data-action='return' data-job-id='{job_id}'>退回</button>"
        )
    elif job.get("status") == "planned":
        job_id = _esc(job.get("job_id", ""))
        plan_action = f"<button class='secondary' data-action='return' data-job-id='{job_id}'>退回並保留理由</button>"
    else:
        plan_action = f"<p class='status-note'>目前狀態：{_esc(_status_label(job.get('status'), job.get('decision')))}</p>"
    leakage = metrics.get("leakage_rate")
    leakage_text = "未量測" if leakage is None else f"{float(leakage):.2%}"
    return (
        "<section class='plan-card'><p class='eyebrow'>處理計畫</p>"
        f"<h2>{_esc(job.get('filename', ''))}</h2>"
        "<div class='teaching-card'><h3>這份有沒有教我們新東西</h3>"
        f"{thing_body}</div>"
        "<h3>打算怎麼處理</h3><div class='metrics'>"
        f"<span>消音<strong>{_esc(metrics.get('mute', 0))}</strong>處</span>"
        f"<span>空表格<strong>{_esc(metrics.get('empty_tables', 0))}</strong>個</span>"
        f"<span>chart<strong>{_esc(metrics.get('charts', 0))}</strong>（只登記）</span>"
        f"<span>項目數變化<strong>{_esc(metrics.get('item_delta', 0))}</strong>（不得改變）</span>"
        "</div>"
        "<table class='details'><tbody>"
        f"<tr><th>來源</th><td>{_esc(job.get('source', ''))}</td></tr>"
        f"<tr><th>解析選項</th><td>{_esc(metrics.get('parse_options', '未取得'))}</td></tr>"
        f"<tr><th>狀態</th><td>{_esc(_status_label(job.get('status'), job.get('decision')))}</td></tr>"
        f"<tr><th>漏詞率</th><td>{_esc(leakage_text)}</td></tr>"
        "</tbody></table><div class='actions'>"
        f"{plan_action}</div>"
        "<p class='hint'>放行會寫入磁碟並開始抽取（約 12 分鐘）。寫入前原始檔會自動備份，可 revert；"
        "但抽取進索引之後，撤銷是「刪掉重跑」不是「還原」。</p>"
        "</section>"
    )


def render_html(state: Mapping[str, object], selected_job_id: str | None = None) -> str:
    sections = state.get("sections") if isinstance(state.get("sections"), dict) else {}
    jobs = state.get("jobs") if isinstance(state.get("jobs"), list) else []
    selected: Mapping[str, object] | None = None
    if selected_job_id and isinstance(jobs, list):
        for item in jobs:
            if isinstance(item, dict) and item.get("job_id") == selected_job_id:
                selected = item
                break
    selection = sections.get("selection", []) if isinstance(sections, dict) else []
    parsing = sections.get("parsing", []) if isinstance(sections, dict) else []
    review = sections.get("review", []) if isinstance(sections, dict) else []
    in_progress = sections.get("in_progress", []) if isinstance(sections, dict) else []
    completed = sections.get("completed", []) if isinstance(sections, dict) else []
    convergence = state.get("convergence") if isinstance(state.get("convergence"), dict) else {}
    source_warnings = state.get("source_warnings")
    warning_html = ""
    if isinstance(source_warnings, list) and source_warnings:
        warning_html = "<div class='source-warning'>⚠ " + _esc("；".join(str(item) for item in source_warnings)) + "</div>"
    return """<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="5">
<title>收件匣／進料審核台</title>
<style>
:root { color-scheme: light; --ink:#29233d; --muted:#716b82; --line:#e7e1ed;
  --purple:#7454c6; --pale:#f5f0ff; --green:#26765a; --red:#b74953; --bg:#fbfafc; }
* { box-sizing:border-box; } body { margin:0; background:var(--bg); color:var(--ink);
  font:15px/1.5 system-ui,-apple-system,"Noto Sans TC",sans-serif; }
main { max-width:1440px; margin:0 auto; padding:24px; }
.convergence { background:#29233d; color:#fff; border-radius:18px; padding:22px 26px;
  display:grid; grid-template-columns:1.1fr .9fr 1.4fr; gap:24px; align-items:start; }
.convergence h1 { margin:0; font-size:28px; } .eyebrow { margin:0 0 5px; color:#a991ed;
  font-size:12px; letter-spacing:.08em; text-transform:uppercase; }
.convergence-stats { display:flex; gap:20px; padding-top:18px; } .convergence-stats span { color:#c8c0d7; }
.convergence-stats strong { display:block; color:#fff; font-size:26px; } .events h3 { margin:0; }
.events ul { margin:7px 0 0; padding-left:18px; color:#ddd7e7; max-height:110px; overflow:auto; }
.warning { color:#ffcf8a; } .source-warning { margin-top:14px; padding:10px 13px; border-radius:9px; background:#fff5dd; color:#795b15; }
.layout { display:grid; grid-template-columns:minmax(430px, .95fr) minmax(500px,1.05fr);
  gap:22px; margin-top:22px; align-items:start; } .left,.right { min-width:0; }
section { background:#fff; border:1px solid var(--line); border-radius:14px; padding:17px; margin-bottom:14px; }
h2 { margin:0 0 10px; font-size:17px; } h3 { margin:14px 0 8px; font-size:15px; }
.row { display:grid; grid-template-columns:minmax(0,1fr) auto auto; gap:10px; align-items:center;
  border-top:1px solid var(--line); padding:11px 0; } .row:first-of-type { border-top:0; }
.row strong { display:block; overflow-wrap:anywhere; } small { display:block; color:var(--muted); font-size:12px; }
a { color:var(--purple); text-decoration:none; } .chip { white-space:nowrap; border-radius:999px; padding:3px 9px;
  background:#eeeaf5; color:#5e526e; font-size:12px; } button,.secondary { border:0; border-radius:8px;
  padding:8px 11px; cursor:pointer; font:inherit; white-space:nowrap; text-decoration:none; }
button.primary { background:var(--purple); color:#fff; } button.secondary,.secondary { background:#eeeaf5; color:var(--ink); }
.empty { color:var(--muted); padding:7px 0; } .pending-groups { border-color:#ead6d8; }
.reason-row { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:2px 12px; border-top:1px solid var(--line); padding:9px 0; }
.reason-row:first-of-type { border-top:0; } .reason-row strong { color:var(--red); } .reason-row small { grid-column:1 / -1; }
.plan-card { border-color:#cfc1f4; box-shadow:0 8px 24px rgba(80,54,137,.08); }
.teaching-card { background:var(--pale); border-left:4px solid var(--purple); padding:13px 15px; border-radius:8px; }
.teaching-card h3 { margin-top:0; } .new-things { margin:0; padding-left:20px; } .new-things li { margin:7px 0; }
.new-things em { display:block; color:var(--purple); font-size:12px; font-style:normal; }
.clean-message { margin:0; color:var(--green); font-weight:600; } .metrics { display:grid; grid-template-columns:repeat(4,1fr);
  gap:9px; } .metrics span { background:#f7f5fa; border-radius:8px; padding:10px; color:var(--muted); font-size:12px; }
.metrics strong { display:block; color:var(--ink); font-size:22px; } table { width:100%; border-collapse:collapse; margin-top:15px; }
th,td { text-align:left; border-top:1px solid var(--line); padding:8px 4px; vertical-align:top; }
th { color:var(--muted); width:25%; font-weight:500; } .actions { display:flex; gap:9px; margin-top:17px; }
.hint { margin:16px 0 0; color:#625b70; font-size:13px; background:#faf7ec; padding:11px 12px; border-radius:8px; }
.status-note { color:var(--muted); } @media (max-width:900px) { .convergence,.layout { grid-template-columns:1fr; }
  .metrics { grid-template-columns:repeat(2,1fr); } main { padding:12px; } }
</style></head><body><main>
""" + _render_convergence(convergence) + warning_html + "<div class='layout'><div class='left'>" + \
        _render_section("選片", selection if isinstance(selection, list) else [], _render_candidate_row) + \
        _render_section("解析中", parsing if isinstance(parsing, list) else [], _render_job_row) + \
        _render_section("待審核", review if isinstance(review, list) else [], _render_job_row) + \
        _render_section("進行中", in_progress if isinstance(in_progress, list) else [], _render_job_row) + \
        _render_section("已完成", completed if isinstance(completed, list) else [], _render_job_row) + \
        _render_pending_groups(state.get("pending_by_reason")) + \
        "</div><div class='right'>" + _render_plan(selected) + "</div></div>" + \
        "<script>\n" + \
        "async function postJson(path, body) { const r = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)}); const d = await r.json(); if (!r.ok) { alert(d.error || '操作失敗'); return; } location.reload(); }\n" + \
        "document.querySelectorAll('[data-action=\"parse\"]').forEach(b => b.onclick = () => postJson('/api/parse', {candidate_id:b.dataset.candidateId}));\n" + \
        "document.querySelectorAll('[data-action=\"admit\"]').forEach(b => b.onclick = () => postJson('/api/admit', {job_id:b.dataset.jobId}));\n" + \
        "document.querySelectorAll('[data-action=\"return\"]').forEach(b => b.onclick = () => postJson('/api/return', {job_id:b.dataset.jobId}));\n" + \
        "</script></main></body></html>"


def make_handler(app: IntakeApp) -> type[BaseHTTPRequestHandler]:
    class IntakeHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _send(self, status_code: int, body: bytes, content_type: str) -> None:
            self.send_response(status_code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload: Mapping[str, object], status_code: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(status_code, body, "application/json; charset=utf-8")

        def _html(self, body: str, status_code: int = 200) -> None:
            self._send(status_code, body.encode("utf-8"), "text/html; charset=utf-8")

        def log_message(self, format_string: str, *args: object) -> None:
            LOGGER.info("http %s - %s", self.address_string(), format_string % args)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            try:
                if parsed.path == "/health":
                    self._json(app.health())
                    return
                if parsed.path == "/api/state":
                    self._json(app.state())
                    return
                if parsed.path == "/api/candidates":
                    state = app.state()
                    sections = state.get("sections") if isinstance(state.get("sections"), dict) else {}
                    candidates = sections.get("selection", []) if isinstance(sections, dict) else []
                    self._json({"candidates": candidates, "warnings": state.get("source_warnings", [])})
                    return
                if parsed.path == "/api/jobs":
                    self._json({"jobs": app.state().get("jobs", [])})
                    return
                if parsed.path.startswith("/api/jobs/"):
                    job_id = urllib.parse.unquote(parsed.path.rsplit("/", 1)[-1])
                    job = app._get_job(job_id)
                    self._json(app._public_job(job))
                    return
                if parsed.path == "/":
                    query = urllib.parse.parse_qs(parsed.query)
                    selected = (query.get("job") or [None])[0]
                    self._html(render_html(app.state(), selected))
                    return
                self._json({"error": "unknown path"}, 404)
            except IntakeError as exc:
                self._json({"error": str(exc)}, exc.status_code)
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("GET 處理失敗")
                self._json({"error": f"服務內部錯誤：{type(exc).__name__}"}, 500)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            try:
                payload = _json_body(self)
                if parsed.path == "/api/parse":
                    jobs = app.submit_parse(_candidate_ids(payload))
                    self._json({"jobs": [app._public_job(job) for job in jobs]}, 202)
                    return
                job_id = payload.get("job_id")
                if not isinstance(job_id, str):
                    raise IntakeError("需要 job_id", 400)
                if parsed.path == "/api/admit":
                    job = app.submit_admit(job_id)
                    self._json({"job": app._public_job(job)}, 202)
                    return
                if parsed.path == "/api/return":
                    job = app.submit_return(job_id)
                    self._json({"job": app._public_job(job)}, 202)
                    return
                self._json({"error": "unknown path"}, 404)
            except IntakeError as exc:
                self._json({"error": str(exc)}, exc.status_code)
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("POST 處理失敗")
                self._json({"error": f"服務內部錯誤：{type(exc).__name__}"}, 500)

    return IntakeHandler


def make_server(bind_addr: str, port: int, app: IntakeApp) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((bind_addr, port), make_handler(app))


def main(argv: Sequence[str] | None = None) -> int:
    environment = _runtime_environment()
    parser = argparse.ArgumentParser(description="收件匣／進料審核台")
    parser.add_argument("--port", type=int, default=9710)
    parser.add_argument("--workspace", default=environment.get("WORKSPACE"))
    parser.add_argument("--source", action="append", dest="sources",
                        help="來源白名單目錄，可重複；未指定時讀 INTAKE_SOURCES")
    parser.add_argument("--log-level", default="INFO",
                        choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    args = parser.parse_args(argv)
    if not isinstance(args.workspace, str) or not args.workspace.strip():
        parser.error("請以 --workspace 或 WORKSPACE 指定知識庫")
    logging.basicConfig(level=getattr(logging, args.log_level),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    paths = DataPaths(configured_data_root(environment))
    app = IntakeApp(
        paths,
        args.workspace,
        _source_paths(environment, args.sources),
        environment=environment,
    )
    bind_addr = environment.get("BIND_ADDR", "127.0.0.1")
    server = make_server(bind_addr, args.port, app)
    app.start()
    LOGGER.info("intake 監聽 %s:%s，DATA_ROOT=%s", bind_addr, args.port, paths.root)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("收到中斷，停止 intake")
    finally:
        app.stop()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
