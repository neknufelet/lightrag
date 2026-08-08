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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Literal, Protocol

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

# 「索引裡那一列是本站負責的」——從 admitted 起算，因為那一步才把檔案複製進
# inputs，在那之前索引裡不可能有本站造成的列。
#
# 這個集合單獨存在而不是複用 ACTIVE_STATUSES，是因為兩者問的問題不同：
# ACTIVE 問「重啟時這個 job 有沒有做到一半」，這個問「索引裡那一列該不該
# 算在本站頭上」。parsing 與 repairing 是 active 但還沒碰索引 —— 那時候索引
# 裡同名的列**真的是別人送的**，不能一起排除掉，否則探針會漏報。
OWNED_STATUSES: frozenset[str] = frozenset({
    "admitted", "scanning", "extracting", "indexed",
})

TRANSITIONS: dict[str, frozenset[str]] = {
    "candidate": frozenset({"parsing"}),
    "parsing": frozenset({"planned", "failed_parse", "failed"}),
    "planned": frozenset({"repairing", "returned", "failed"}),
    # repairing → planned：收件區被別的流程佔著時退回「等你看」。那是時機問題
    # 不是文件問題，不該走 failed（見 _defer_to_review）。
    "repairing": frozenset({"admitted", "planned", "failed"}),
    "admitted": frozenset({"scanning", "failed"}),
    "scanning": frozenset({"extracting", "failed"}),
    "extracting": frozenset({"indexed", "failed"}),
    "failed_parse": frozenset(),
    "indexed": frozenset(),
    "returned": frozenset(),
    # failed → planned：**唯一的出口不該是「整份丟掉重來」。**
    # 舊版這裡是空集合，於是失敗的唯一處置是重置為候選，而重置會刪掉
    # MinerU 的解析成果（要錢、要時間）。計畫還有效時應該能直接重試 ——
    # 守門是在動任何東西之前擋的，沒有東西需要回滾。
    "failed": frozenset({"planned"}),
}


class IntakeError(RuntimeError):
    """服務可以回給 HTTP 呼叫端的錯誤。"""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class StateError(IntakeError):
    """不合法的 job 狀態轉換。"""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


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
    # 這一階段**真的輪到了**的時刻。排進佇列時清成 None，worker 撿起來才填。
    # worker 是循序的，所以同時間只有一件不是 None —— 沒有這個欄位的話
    # 「卡住」與「排在後面」在畫面上長得一樣，重啟恢復也分不出來（見
    # `_recover_active_jobs`）。
    stage_started_at: str | None = None

    @classmethod
    def from_candidate(cls, candidate: Candidate) -> Job:
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
            "stage_started_at": self.stage_started_at,
            # 在佇列裡等、還沒輪到。worker 循序跑，所以絕大多數「在途」的其實是這種。
            "queued": self.status in ACTIVE_STATUSES and self.stage_started_at is None,
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
            "stage_started_at": self.stage_started_at,
        }

    @classmethod
    def from_dict(cls, raw: object) -> Job:
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
            # 舊紀錄沒有這個欄位 ⇒ None ⇒ 「還沒輪到」。對升級當下**還在佇列裡**
            # 的工作，這正是我們要的判定：重新排回去，不要判成失敗。
            stage_started_at=_optional_string(raw.get("stage_started_at")),
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
                    f"{resolved}\x00{digest}".encode()
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
    # 子行程的離開碼。**判斷失敗種類要用它，不要比對訊息字串** ——
    # 訊息會為了給人看而加細節，而字串比對不會因此報錯，只會安靜地永遠不成立
    # （2026-08-08：soft 失敗的容忍就是這樣壞掉的，見 `_compat_check`）。
    code: int | None = None


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

    def request(self, path: str, method: str = "GET", body: dict[str, object] | None = None,
                timeout: float = 120.0) -> dict[str, object]:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            self.base_url + path,
            method=method,
            data=data,
            headers={"X-API-Key": self.api_key, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
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
            return OperationResult(False, output,
                                   _explain_exit(completed.returncode, output),
                                   code=completed.returncode)
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

    # compat-check.py:550 的退出碼語義：2 = hard 失敗、5 = soft 失敗、0 = 全過。
    # soft 的定義就是「值得知道但不該擋」，把它當成流程失敗會讓
    # 「文件其實已經索引成功」被報成 failed。實際咬過：第一份文件進來時
    # A-25 因為整庫只有 1 個 chunk 而 soft FAIL，於是整個 job 變成 failed。
    _COMPAT_SOFT_FAIL = 5

    def _compat_check(self, job: Job) -> OperationResult:
        command = [
            self.python, str(self.repo / "scripts" / "compat-check.py"),
            "--doc", job.filename,
        ]
        result = self._run(command, self.command_timeout)
        # ⚠ 比離開碼，不要比訊息。舊版比的是 `f"exit {5}"`，而 `_explain_exit`
        # 早就把細節接在後面（`exit 5：…`），於是這個容忍**永遠不成立**而且
        # 不會有人知道。2026-08-08 A-32 上線讓 compat-check 第一次在這條路上
        # 回 5，整批放行當場被自己的紅燈擋死。
        if not result.ok and result.code == self._COMPAT_SOFT_FAIL:
            LOGGER.warning("compat-check 有 soft 失敗（不擋流程）：%s", job.filename)
            return OperationResult(True, result.output, code=result.code)
        return result


def _explain_exit(code: int, output: str) -> str:
    """把子行程的失敗講成人看得懂的話。

    只回「exit 2」等於沒說 —— 真正的原因一直只在 run.log 裡，使用者得去翻
    磁碟才知道發生什麼事。取輸出的最後幾行有內容的，那通常就是結論。
    """
    lines = [line.strip() for line in (output or "").splitlines() if line.strip()]
    tail = " ／ ".join(lines[-3:])[:400]
    return f"exit {code}：{tail}" if tail else f"exit {code}（沒有輸出可說明原因）"


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
        self.client = LightRAGClient(self.environment)
        # 與 LightRAG 對帳的結果快取；state() 會被輪詢，每次都打 API 太吵。
        self._index_cache: tuple[float, dict[str, str], str | None] | None = None
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
        """重啟時的在途工作：**問索引的現實，不要假設失敗。**

        舊版一律標成 failed。那是錯的處置——LightRAG 在**另一個容器**裡，
        intake 重啟不會打斷它，文件照樣會被抽完。於是畫面說失敗、庫裡卻有，
        而且 failed 是死路，那份文件從此卡住。實測會踩到：一次 dker 重開機
        就會把正在抽取的那份誤殺。

        與 `_foreign_documents()` 同一個形狀：**兩個獨立來源不一致時，
        以跑著的系統為準，不以本站的記憶為準。**

        三種處置，對應索引裡的三種現實：

            processed   → indexed，本來就成功了
            processing  → 放回佇列繼續等（LightRAG 還在跑）
            查不到      → 這才是真的失敗

        問不到 LightRAG 時**不猜**：維持在途、標記待確認。把「連不上」當成
        「失敗」會在網路瞬斷時殺掉一整批好文件。
        """
        active = [job for job in self._jobs.values() if job.status in ACTIVE_STATUSES]
        if not active:
            return

        # 還沒輪到就重啟的：**那不是失敗，是排隊。** 它們沒有跑過任何外部命令、
        # 沒有產生任何檔案，重新排回佇列就好。拿它們去問 LightRAG 只會得到
        # 「沒這份」，而下面那段把那個答案當成「真的失敗」——一次重啟就會殺掉
        # 整批還在排隊的工作（2026-08-08：批次解析上線後佇列裡一度有 19 件）。
        #
        # 只救 parsing／repairing：那兩個是「排進佇列但還沒開始」唯一會停的狀態。
        # admitted 之後的每一步都在 worker 裡面走，不可能沒開始。
        requeued: set[str] = set()
        for job in active:
            if job.stage_started_at is not None or job.status not in {"parsing", "repairing"}:
                continue
            kind = "parse" if job.status == "parsing" else "admit"
            self._queue.put((kind, job.job_id))
            requeued.add(job.job_id)
            message = f"服務重啟時這份還在排隊（沒有開始跑），原樣重新排回 {kind}。"
            self.store.append_log(job.job_id, message)
            LOGGER.info("job %s %s", job.job_id, message)
        if requeued:
            LOGGER.info("重啟恢復：%d 件排隊中的工作重新排回佇列", len(requeued))
        active = [job for job in active if job.job_id not in requeued]
        if not active:
            return

        rows: dict[str, str] = {}
        error: str | None = None
        try:
            payload = self.client.request("/documents", timeout=10.0)
            statuses = payload.get("statuses")
            if isinstance(statuses, dict):
                for status_name, documents in statuses.items():
                    for item in documents if isinstance(documents, list) else []:
                        if not isinstance(item, dict):
                            continue
                        name = Path(str(item.get("file_path") or "")).name
                        if name:
                            rows[name] = str(item.get("status") or status_name).lower()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            error = f"{type(exc).__name__}: {exc}"
            LOGGER.warning("重啟恢復：問不到 LightRAG（%s），在途工作維持原狀待確認", error)

        for job in active:
            if error is not None:
                job.error = (f"服務重啟時這份仍在執行，而且問不到 LightRAG（{error}）——"
                             "狀態未變更。等 LightRAG 回來後重新整理，或人工確認索引現況。")
                self.store.save(job)
                self.store.append_log(job.job_id, job.error)
                continue

            reality = rows.get(job.filename)
            if reality == "processed":
                # 已經成功了。狀態機不允許從 scanning 直接跳 indexed，所以直接落值。
                job.status = "indexed"
                job.error = None
                message = "服務重啟時這份已經索引完成，直接標為已進知識庫。"
            elif reality in {"processing", "pending"}:
                job.error = None
                message = (f"服務重啟時 LightRAG 仍在處理這份（{reality}），"
                           "重新掛回等待，不重跑抽取。")
                self._queue.put(("resume", job.job_id))
            else:
                job.status = "failed"
                message = ("服務重啟時工作仍在執行，而且索引裡找不到這份文件"
                           f"（LightRAG 回報 {reality or '不存在'}）——判定為真的失敗。")
                job.error = message
            self.store.save(job)
            self.store.append_log(job.job_id, message)

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
                job.stage_started_at = None          # 排進佇列，還沒輪到
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
            # 上一次退回的原因不要留到這一次 —— 舊訊息掛在畫面上會讓人
            # 以為又被擋了一次。
            job.error = None
            transition(job, "repairing")
            job.stage_started_at = None              # 排進佇列，還沒輪到
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

    def submit_retry(self, job_id: str) -> Job:
        """失敗但計畫還有效的，放回「等你看」，**不動任何已經做好的東西**。

        與「重置為候選」的差別就是代價：重置會刪掉解析成果，下一輪得再送一次
        MinerU（要錢、要時間）；重試只是把狀態撥回去，解析成果原封不動。

        擋在前面的三個條件都是**可驗的事實**，不是推測：計畫通過過、解析來源
        PDF 還在而且內容沒變、解析成果還在。任何一項不成立就只能走重置 ——
        那時候「已經做好的東西」本來就不完整了。

        撥回 planned 而不是直接重跑放行：擋下來的原因（例如收件區被佔用）可能
        還在，讓人再按一次是唯一能確認「現在方便了」的方式。
        """
        with self._lock:
            if self._busy():
                raise IntakeError("已有序列工作進行中，請等待狀態更新", 409)
        job = self._get_job(job_id)
        if job.status != "failed":
            raise IntakeError("只有失敗的 job 可以重試", 409)
        if job.decision != "clean" or job.plan is None:
            raise IntakeError("這份沒有通過審查的計畫，只能用「放回收件匣」重來", 409)
        parsed = self.paths.parsed_dir / job.filename
        if not parsed.is_file() or _sha256(parsed) != job.source_sha256:
            raise IntakeError("解析來源 PDF 不見了或內容已變，只能用「放回收件匣」重來", 409)
        bundle = self.paths.parsed_bundle_dir(job.filename)
        if not (bundle / "content_list.json").is_file():
            raise IntakeError("解析成果不在了，只能用「放回收件匣」重來", 409)
        with self._lock:
            job.workspace = self.workspace
            transition(job, "planned")
            job.error = None
            self.store.save(job)
        LOGGER.info("job %s 重試：計畫仍有效，撥回待審核", job_id)
        self.store.append_log(job_id, "重試：計畫仍有效，解析成果保留，撥回待審核")
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
                self._mark_stage_started(job_id)
                if kind == "parse":
                    self._run_parse(job_id)
                elif kind == "admit":
                    self._run_admit(job_id)
                elif kind == "return":
                    self._run_return(job_id)
                elif kind == "resume":
                    self._run_resume(job_id)
                else:
                    raise RuntimeError(f"未知 worker 工作類型 {kind!r}")
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("worker 工作失敗")
                if task is not None:
                    self._mark_failed(
                        task[1], f"worker 例外：{type(exc).__name__}: {exc}", exception=exc,
                    )
            finally:
                with self._lock:
                    self._running_job_id = None
                self._queue.task_done()

    def _mark_stage_started(self, job_id: str) -> None:
        """這一件真的輪到了。

        **「排隊中」與「正在跑」必須分得開。** worker 是循序的，一次只跑一件，
        所以佇列裡二十件全部標成「解析中」時，只有一件是真的。不分開的話：

          畫面  每一列都掛著一個一直在長的計時器 ⇒ 卡住與排在後面長得一樣
          重啟  `_recover_active_jobs` 拿還沒跑的去問 LightRAG，得到「沒這份」，
                然後判定為真的失敗 —— 一次重啟殺掉整批（2026-08-08 差點踩到，
                當時佇列裡有 19 件）
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.stage_started_at = _now_iso()
            self.store.save(job)

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
            self._mark_failed(
                job_id, f"解析／計畫失敗：{type(exc).__name__}: {exc}", exception=exc,
            )

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
        if evaluation.accepted:
            self._auto_admit(job)

    def _auto_admit(self, job: Job) -> None:
        """機械計畫判定 clean 的自動放行（PO 裁決 2026-08-08 `4eacaea`）。

        看計畫那一關要抓的是 novel／未知型別／數字可疑，而 `clean` 就是
        「這三樣都沒有」。**在已判乾淨的計畫前面放人工關卡攔不到任何東西**
        —— PO 本來就無法判讀機械計畫。`novel` 照樣停在「等你看」。

        **不加 LLM 複查**（同一個裁決）：機械規則是確定性、位置錨定的，加模型
        會把可重現的東西變成不可重現；真正需要模型判斷的地方（表格轉錄、
        方程式）已經有兩雙眼睛＋第三隻眼。

        **只在解析剛跑完時觸發一次。** 放行被擋下來會退回 `planned`
        （`_defer_to_review`），那時候不再自動重按 —— 擋的原因（收件區被別的
        流程佔著）可能還在，自動重試會變成迴圈。那一次要人按，或走
        `submit_retry`。
        """
        with self._lock:
            transition(job, "repairing")
            job.stage_started_at = None              # 排進佇列，還沒輪到
            self.store.save(job)
            self._queue.put(("admit", job.job_id))
        LOGGER.info("job %s 計畫判定 clean，自動放行", job.job_id)
        self.store.append_log(job.job_id, "計畫判定 clean，自動放行（裁決 4eacaea）")

    def _inputs_pdf_paths(self) -> list[Path]:
        inputs = self.paths.inputs_dir(self.workspace)
        return sorted(path for path in inputs.glob("*.pdf") if path.is_file())

    def _inputs_blocked_reason(self) -> str | None:
        """放行前 `inputs/<ws>` 不得有任何 PDF。擋得住就回原因，乾淨就回 None。

        **為什麼擋**：放行時 LightRAG 會掃描整個 `inputs/<ws>`，多出來的檔會被
        一起索引，**而且繞過後處理** —— 表格修補、LaTeX 修正、雜訊消音全都不會
        發生，索引起來卻看起來完全正常。

        **為什麼不自動清掉**：這支服務沒辦法知道那個檔是別的流程正在用的，還是
        殘留。刪錯的代價是「某份文件在這台的唯一副本沒了」。所以擋下來並**把處置
        指令直接印出來** —— 與 `ledger.py` 在體檢表脫節時的做法同一個模式：
        擋住不等於把問題丟給人，要給可以直接跑的下一步。

        **為什麼回字串而不是一律丟例外**：呼叫端要能分辨「這份文件有問題」與
        「現在不方便」。後者不該進 failed，見 `_defer_to_review`。

        （2026-08-08 實測兩次：先是手動跑管線把 PDF `scp` 進 inputs、跑完沒清，
        四篇一放行全部撞到這裡；當天稍晚重抽拿 inputs 當暫存區，2017 放行撞上，
        被判 failed 而它自己 decision=clean、reasons=[]。）
        """
        existing = self._inputs_pdf_paths()
        if not existing:
            return None
        names = ", ".join(path.name for path in existing)
        inputs = self.paths.inputs_dir(self.workspace)
        stamp = time.strftime("%Y%m%d")
        archive = self.paths.library_dir / f"manual-{stamp}"
        return (
            f"放行中止：inputs/{self.workspace} 不是純淨空目錄：{names}\n"
            f"  為什麼擋：放行時 LightRAG 會掃描整個 {inputs}，"
            f"多出來的檔會被一起索引且**繞過後處理**。\n"
            f"  如果是重抽／手動跑管線正在用它當暫存區，等那邊跑完再放行就好。\n"
            f"  如果是殘留（intake 自己走的流程會清），處置：\n"
            f"    mkdir -p '{archive}'\n"
            f"    mv '{inputs}'/*.pdf '{archive}'/\n"
            f"  **搬到 library 不要直接刪** —— 那可能是某份文件在這台的唯一副本。")

    def _assert_inputs_empty(self) -> None:
        reason = self._inputs_blocked_reason()
        if reason is not None:
            raise RuntimeError(reason)

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

    def _remove_reset_pdf(self, path: Path, root: Path, expected_sha256: str, label: str) -> None:
        resolved_root = root.resolve()
        resolved_path = path.resolve()
        if resolved_path.parent != resolved_root:
            raise RuntimeError(f"重置目標不在既定 {label} 目錄：{path}")
        if not path.exists():
            return
        if not path.is_file() or _sha256(path) != expected_sha256:
            raise RuntimeError(f"重置拒絕刪除未驗證的 {label} 檔案：{path}")
        path.unlink()

    def _remove_reset_artifacts(self, job: Job) -> bool:
        """清掉重置要清的東西。回傳「解析成果有沒有留下」。

        **解析成果預設留著。** MinerU 要錢也要時間，而 `parse-only.py` 本來就會
        跳過已有的有效 bundle（「重抓要錢」），所以留著等於下一輪免費。
        `is_bundle_valid` 比對的是來源檔的大小與內容雜湊，不是檔案身分，
        所以這裡照樣刪掉 work/parsed 的 PDF 副本 —— 下一輪重新複製一份出來，
        雜湊一樣就仍然有效；換成別的同名 PDF 則會失效並重抓，兩邊都對。

        **什麼時候該刪**：這份解析成果**沒有通過審查**的時候（`plan is None`）。
        那表示它連被看過都還沒有 —— 解析途中就掛了、或計畫算不出來，內容值不值得
        信任沒有人知道。反過來，走到過審查就代表這份解析成果被檢查過了，留著安全。

        判準用「有沒有計畫」而不是「失敗代號是不是 failed_parse」：解析階段有好
        幾條路會丟例外（bundle 缺 content_list、plan 算不出來），那些都會落成
        `failed` 而不是 `failed_parse`，用代號分會把它們一起留下來。
        """
        if not _safe_pdf_name(job.filename):
            raise RuntimeError("重置拒絕使用不安全的文件檔名")
        source_key_path = Path(job.source_key)
        if (not job.source_key or source_key_path.name != job.source_key
                or ".." in source_key_path.parts):
            raise RuntimeError("重置拒絕使用不安全的來源鍵")
        workspace = job.workspace or self.workspace
        workspace_path = Path(workspace)
        if not workspace or workspace_path.name != workspace or ".." in workspace_path.parts:
            raise RuntimeError("重置拒絕使用不安全的 workspace")

        library_root = self.paths.library_source_dir(job.source_key)
        parsed_root = self.paths.parsed_dir
        inputs_root = self.paths.inputs_dir(workspace)
        library_pdf = library_root / job.filename
        parsed_pdf = parsed_root / job.filename
        inputs_pdf = inputs_root / job.filename
        expected_paths = (
            ("library", library_pdf, library_root),
            ("parsed", parsed_pdf, parsed_root),
            ("inputs", inputs_pdf, inputs_root),
        )
        for field_name, expected in (
            ("library_path", library_pdf),
            ("parsed_source_path", parsed_pdf),
            ("admitted_path", inputs_pdf),
        ):
            stored = getattr(job, field_name)
            if stored is not None and Path(stored).resolve() != expected.resolve():
                raise RuntimeError(f"job 的 {field_name} 不在預期重置路徑")
        for label, path, root in expected_paths:
            self._remove_reset_pdf(path, root, job.source_sha256, label)

        raw = self.paths.parsed_bundle_dir(job.filename)
        if job.plan is not None:
            return raw.is_dir()
        if raw.exists():
            if raw.parent.resolve() != parsed_root.resolve() or not raw.is_dir():
                raise RuntimeError(f"重置拒絕刪除未驗證的 parsed bundle：{raw}")
            shutil.rmtree(raw)
        return False

    def submit_reset(self, job_id: str) -> str:
        with self._lock:
            if self._busy():
                raise IntakeError("已有序列工作進行中，請等待狀態更新", 409)
        job = self._get_job(job_id)
        with self._lock:
            if job.status not in {"failed", "failed_parse", "returned"}:
                raise IntakeError("只有失敗的 job 可以重置為候選", 409)
            try:
                kept_bundle = self._remove_reset_artifacts(job)
                job_dir = self.paths.intake_job_dir(job.job_id)
                if (job_dir.resolve().parent != self.paths.intake_jobs_dir.resolve()
                        or job_dir.name != job.job_id):
                    raise RuntimeError("重置拒絕刪除不安全的 job 目錄")
                if job_dir.exists():
                    if not job_dir.is_dir():
                        raise RuntimeError(f"job 目錄不是目錄：{job_dir}")
                    shutil.rmtree(job_dir)
                self._jobs.pop(job.job_id, None)
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("重置 job %s 為候選失敗", job.job_id)
                raise IntakeError(f"重置失敗：{type(exc).__name__}: {exc}", 409) from exc
        LOGGER.info(
            "job %s 已重置為候選：candidate_id=%s，解析成果%s",
            job.job_id, job.candidate_id,
            "保留（下一輪不必重抓）" if kept_bundle else "已刪除",
        )
        return job.candidate_id

    def _run_admit(self, job_id: str) -> None:
        job = self._job_for_worker(job_id)
        admitted: Path | None = None
        settled = False
        try:
            parsed = self.paths.parsed_dir / job.filename
            if (job.parsed_source_path is not None
                    and Path(job.parsed_source_path) != parsed):
                raise RuntimeError("job 的 parsed source 不在既定 work/parsed 路徑")
            if not parsed.is_file() or _sha256(parsed) != job.source_sha256:
                raise RuntimeError("放行前找不到或驗證不了解析來源 PDF")
            blocked = self._inputs_blocked_reason()
            if blocked is not None:
                self._defer_to_review(job_id, blocked)
                return
            applied = self.runner.apply(job)
            self._append_operation(job, "修補", applied)
            if not applied.ok:
                self._mark_failed(job_id, applied.error or "修補失敗")
                return
            # 設計 C 的核心順序：apply 成功之後才允許複製進 inputs。
            #
            # 這一次擋下來也是退回而不是失敗：apply 走的是「同內容不重寫、
            # `_pp_original_*` 只記第一次」（pp/apply.py），重跑安全。
            blocked = self._inputs_blocked_reason()
            if blocked is not None:
                self._defer_to_review(job_id, blocked)
                return
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
            settled = True
            with self._lock:
                transition(job, "indexed")
                self.store.save(job)
        except Exception as exc:  # noqa: BLE001
            self._mark_failed(
                job_id, f"放行失敗：{type(exc).__name__}: {exc}", exception=exc,
            )
        finally:
            if not settled and admitted is not None:
                self._release_inputs(job, admitted)

    def _release_inputs(self, job: Job, admitted: Path) -> None:
        """放行沒走完時，把暫存在收件區的那份撤掉。

        **一件失敗會堵死整條佇列。** 收件區必須是純淨空目錄才准放行
        （`_inputs_blocked_reason`），而失敗路徑從來沒有清掉自己複製進去的那份，
        於是後面每一件放行都被擋 —— 2026-08-08 實測：一件在 compat-check 掛掉，
        後面 15 件全部退回「等你看」，而擋人的理由是**前一件的檔名**。

        清不掉就只記 log 不再往上丟：這裡已經在失敗處理路徑上，
        再丟一個例外只會把真正的死因蓋掉。
        """
        try:
            self._cleanup_admitted(job, admitted)
        except (OSError, RuntimeError) as exc:
            LOGGER.error("放行失敗後清不掉 inputs 的 %s：%s —— "
                         "後續放行會被擋，需要人工搬走", admitted, exc)
            self.store.append_log(
                job.job_id,
                f"⚠ 放行失敗後 {admitted} 沒清掉（{type(exc).__name__}），"
                "後面的放行會被擋住，要人工處理")
        else:
            LOGGER.info("放行沒走完，已撤掉 inputs 的 %s", admitted)

    def _run_resume(self, job_id: str) -> None:
        """重啟後掛回一份 LightRAG 還在處理的文件。

        **只等，不重跑。** 抽取在另一個容器裡好好地跑著，這裡重跑一次等於
        付兩次錢還會產生重複實體。所以直接進 `wait_indexed`，走完既有的
        「等 processed → compat-check → 收尾」那段。

        `admitted_path` 可能已經被上一輪清掉了（或根本沒記到），
        `_cleanup_admitted` 對不存在的路徑要能安靜跳過，這裡不另外處理。
        """
        job = self._job_for_worker(job_id)
        try:
            with self._lock:
                if job.status != "extracting":
                    # scanning／admitted 停在半路的，掛回抽取這一段等它結束。
                    job.status = "extracting"
                    self.store.save(job)
            indexed = self.runner.wait_indexed(job)
            self._append_operation(job, "重啟後接回等待索引", indexed)
            if not indexed.ok:
                self._mark_failed(job_id, indexed.error or "重啟後等待索引失敗")
                return
            if job.admitted_path:
                self._cleanup_admitted(job, Path(job.admitted_path))
            with self._lock:
                job.status = "indexed"
                job.error = None
                self.store.save(job)
        except Exception as exc:  # noqa: BLE001
            self._mark_failed(
                job_id, f"重啟後接回失敗：{type(exc).__name__}: {exc}", exception=exc,
            )

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
            self._mark_failed(
                job_id, f"退回失敗：{type(exc).__name__}: {exc}", exception=exc,
            )

    def _defer_to_review(self, job_id: str, reason: str) -> None:
        """「現在不方便」退回「等你看」，不標失敗。

        擋下放行的理由分兩種，處置完全不同：

          這份文件有問題      → failed，要人去看它
          現在不方便          → 退回待審核，等一下再按一次就好

        收件區被別的流程佔著屬於後者：文件本身 decision=clean、計畫還有效、
        守門是在動任何東西**之前**擋的，沒有東西需要回滾。舊版把它標成 failed，
        而 failed 的唯一出口是「重置為候選」，那條路會刪掉 MinerU 的解析成果
        （2026-08-08 的 2017：4.0MB、要錢也要時間，而且它從頭到尾沒有錯）。

        錯誤訊息留在 job 上讓畫面顯示 —— 退回而不說原因，使用者只會看到
        按了沒反應。
        """
        message = f"這次沒有放行：{reason}"
        LOGGER.warning("job %s 退回待審核：%s", job_id, message)
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                LOGGER.error("要退回待審核但找不到 job：%s：%s", job_id, message)
                return
            if job.status == "repairing":
                transition(job, "planned")
            job.error = message
            self.store.save(job)
        self.store.append_log(job_id, message)

    def _mark_failed(
        self,
        job_id: str,
        message: str,
        *,
        exception: BaseException | None = None,
    ) -> None:
        if exception is None:
            LOGGER.error("job %s 失敗：%s", job_id, message)
        else:
            LOGGER.error(
                "job %s 失敗：%s",
                job_id,
                message,
                exc_info=(type(exception), exception, exception.__traceback__),
            )
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

    def save_upload(self, raw_name: str, data: bytes) -> Path:
        """把拖進來的 PDF 存進 inbox。

        三道檢查，缺一不可：

        1. **檔名只取 basename 並過濾**——上傳的檔名是使用者輸入，
           `../../etc/foo` 或絕對路徑都必須在這裡被剝掉，不能相信前端。
        2. **副檔名只收 .pdf**——收件匣的下游是 MinerU，別的格式進來只會
           在解析階段才炸，而且錯誤訊息會指向錯的地方。
        3. **驗 magic bytes**——副檔名是使用者說了算，內容不是。改名成 .pdf
           的 zip 進來會讓解析失敗得莫名其妙。

        同名檔不覆蓋而是加序號：覆蓋會讓「我剛剛傳的那份呢」變成無解的問題，
        而磁碟比困惑便宜。
        """
        name = Path(raw_name.replace("\\", "/")).name.strip()
        if not name or name.startswith("."):
            raise IntakeError("檔名不合法", 400)
        if Path(name).suffix.lower() != ".pdf":
            raise IntakeError(f"只收 PDF，收到的是 {Path(name).suffix or '沒有副檔名'}", 415)
        if not data.startswith(b"%PDF-"):
            raise IntakeError("內容不是 PDF（檔頭對不上），請確認檔案沒有被改過副檔名", 415)

        # 去重比的是**內容**不是檔名。同一份 PDF 改個名再傳，檔名比對抓不到，
        # 而重複的內容進索引會產生兩組指向同一份文件的實體與關係。
        # 這個專案本來就是內容定址的（manifest 的 source_content_hash、
        # candidate_id 也是內容雜湊），去重跟著同一把尺才不會兩套標準。
        digest = hashlib.sha256(data).hexdigest()
        inbox = self.paths.inbox_dir
        inbox.mkdir(parents=True, exist_ok=True)

        for existing in sorted(inbox.glob("*.pdf")):
            try:
                if hashlib.sha256(existing.read_bytes()).hexdigest() == digest:
                    raise IntakeError(f"這份已經在收件匣裡了：{existing.name}", 409)
            except OSError:
                continue

        for known, where in self._indexed_digests().items():
            if known == digest:
                raise IntakeError(f"這份已經進知識庫了：{where}", 409)

        target = inbox / name
        if target.exists():
            # 走到這裡代表**同名但內容不同** —— 那是兩份不同的文件，兩份都要留。
            stem, suffix = Path(name).stem, Path(name).suffix
            for serial in range(2, 1000):
                candidate = inbox / f"{stem} ({serial}){suffix}"
                if not candidate.exists():
                    target = candidate
                    break
            else:
                raise IntakeError("同名檔太多，請先整理 inbox", 409)

        # 先寫暫存再改名：寫到一半失敗時，收件匣裡不會出現半個檔案 ——
        # 而半個 PDF 會通過副檔名檢查、在解析階段才炸。
        staging = target.with_name(f".{target.name}.part")
        try:
            staging.write_bytes(data)
            staging.replace(target)
        except OSError as exc:
            staging.unlink(missing_ok=True)
            raise IntakeError(f"寫入失敗：{exc}", 500) from exc
        LOGGER.info("收到上傳 %s（%d bytes）", target.name, len(data))
        return target

    def _indexed_digests(self) -> dict[str, str]:
        """已經走過流程的內容雜湊 → 給人看的出處。

        兩個來源，因為「已處理」不是單一狀態：job 紀錄涵蓋經過本站的，
        磁碟上的 manifest 涵蓋用 CLI 跑的。只看其中一邊，另一條路徑進來的
        文件就會被當成新的再收一次。
        """
        digests: dict[str, str] = {}
        with self._lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            raw = getattr(job, "source_sha256", None)
            if isinstance(raw, str) and raw:
                digests.setdefault(raw.removeprefix("sha256:"),
                                   f"{job.filename}（{_status_label(job.status, job.decision)}）")
        for manifest_path in sorted(self.paths.parsed_dir.glob("*.mineru_raw/_manifest.json")):
            try:
                manifest = json.loads(manifest_path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            raw = manifest.get("source_content_hash")
            if isinstance(raw, str) and raw:
                name = manifest_path.parent.name.removesuffix(".mineru_raw")
                digests.setdefault(raw.removeprefix("sha256:"), f"{name}（已解析）")
        return digests

    def delete_inbox_file(self, filename: str) -> None:
        """刪掉收件匣裡的一份檔案。**只准刪 inbox** —— 其他來源不是我們的東西。"""
        name = Path(filename.replace("\\", "/")).name.strip()
        if not name or name.startswith("."):
            raise IntakeError("檔名不合法", 400)
        target = self.paths.inbox_dir / name
        if not target.is_file():
            raise IntakeError(f"收件匣裡沒有這個檔案：{name}", 404)
        # resolve 之後再確認父目錄，擋掉 symlink 指到外面的情況。
        if target.resolve().parent != self.paths.inbox_dir.resolve():
            raise IntakeError("只能刪收件匣裡的檔案", 400)
        target.unlink()
        LOGGER.info("刪除收件匣檔案 %s", name)

    # daily-check 的結果超過這麼久沒更新，就當成「沒有在檢查」而不是「通過」。
    # 24 小時是排程週期的兩倍——留一次失敗的餘裕，但不留到「停了一週還在顯示綠燈」。
    CHECKS_STALE_AFTER_S = 24 * 3600

    def daily_checks(self) -> dict[str, object]:
        """把 daily-check 的紅綠燈拉到審核台上。

        **這是這個專案的警報管道**（2026-08-08 PO 裁決）：「只要在 9710 有警告就好，
        我都會透過那個」。ntfy 於 2026-08-07 拆除之後，紅綠狀態一直只落在
        `${DATA_ROOT}/checks/latest.json`，**而沒有任何人會經過那裡**。

        ⚠ **過期比紅燈更危險**：排程停掉之後 `latest.json` 會停在最後一次的結果，
        於是「一週前通過」看起來跟「剛剛通過」一模一樣。所以一律回報 `age_s`，
        並在超過 `CHECKS_STALE_AFTER_S` 時把 `state` 改成 `stale` —— 那不是通過，
        是「沒有在檢查」。
        """
        path = self.paths.checks_dir / "latest.json"
        if not path.is_file():
            return {"state": "missing", "reason": f"{path} 不存在——daily-check 從來沒跑過？"}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {"state": "unreadable", "reason": f"{path} 讀不了：{exc}"}

        age = max(0.0, time.time() - path.stat().st_mtime)
        stamp = str(raw.get("at") or "")
        status = str(raw.get("status") or "unknown")
        state = "stale" if age > self.CHECKS_STALE_AFTER_S else status
        failing = sorted(k for k, v in raw.items()
                         if k.endswith("_rc") and isinstance(v, int) and v != 0)
        return {
            "state": state,          # ok / fail / stale / missing / unreadable
            "reported": status,      # 檔案裡寫的原值，stale 時仍要看得到
            "at": stamp,
            "age_s": age,
            "failing": failing,      # 哪幾項非零，例如 ["scan_rc", "tests_rc"]
            "detail": raw.get("detail"),
            # 產生這筆結果的 commit。沒有它，「這條檢查後來被修好了」與
            # 「這個問題還在」在畫面上無法區分 —— 讀者會照著一份舊碼的判斷去處置。
            # daily-check.sh 寫入；舊的結果檔沒有這個欄位，所以要容許缺席。
            "commit": raw.get("commit"),
        }

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
        foreign_rows, foreign_error = self._foreign_documents()
        index_status, _ = self._index_documents()

        # 「進知識庫了沒」問的是**知識庫的現實**，不是本站的簿記。兩者會脫節，
        # 而且兩個方向都實測踩過：
        #   ① 簿記說 indexed、知識庫正在重抽那一份 → 畫面說完成，其實還在跑
        #      （2026-08-08：重抽期間畫面 4 份全寫「已進知識庫」，資料庫 3 份
        #       processing）
        #   ② 簿記說 failed、知識庫其實跑完了 → 兩邊都不算，那份文件憑空消失
        # 所以分節一律以知識庫的狀態為準，而且**本站送的與別人送的走同一條規則**
        # —— 舊版只對「別人送的」做過濾，計數那半修好了、顯示那半沒有，於是
        # 同一頁上出現「已處理 4」與「已進知識庫 5」。
        def bucket(filename: str, fallback: str) -> str:
            """知識庫怎麼說。問不到、或它根本沒這一列，才退回本站的簿記。"""
            status = index_status.get(filename)
            if status is None:
                return fallback
            if status == "processed":
                return "completed"
            if status == "failed":
                return "failed"
            # 認不得的狀態一律當成還在跑。**寧可錯放在「處理中」也不要錯放在
            # 「已進知識庫」** —— 前者只是讓人多等，後者會讓人以為可以開始用了。
            return "in_progress"

        sections: dict[str, list[dict[str, object]]] = {
            "selection": [candidate.public() for candidate in candidates],
            "parsing": [item for item in public_jobs if item["status"] == "parsing"],
            "review": [item for item in public_jobs if item["status"] == "planned"],
            "in_progress": [item for item in public_jobs if item["status"] in {
                "repairing", "admitted", "scanning", "extracting",
            }],
            "completed": [],
            "skipped": [item for item in public_jobs if item["status"] == "returned"],
            "failed": [item for item in public_jobs if item["status"] in {
                "failed_parse", "failed",
            }],
        }
        for item in public_jobs:
            if item["status"] == "indexed":
                sections[bucket(str(item["filename"]), "completed")].append(item)
        for row in foreign_rows:
            sections[bucket(str(row["filename"]), "in_progress")].append(row)
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
        # **數的和列的必須是同一件東西。** 舊版這裡自己算一次、畫面那邊自己
        # 算一次，於是同一頁的兩個數字互相矛盾而沒有任何東西會發現。現在
        # 「已處理」就是「已進知識庫」那一節的長度，兩者不可能再對不上。
        #
        # 字面值實查為小寫 processing／processed（GET /documents 的 statuses
        # 鍵與 item.status 同值）。
        processed = len(sections["completed"])
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
            "checks": self.daily_checks(),
            "health": self.health(),
            "links": self.links(),
            "foreign": foreign_rows,
            "foreign_error": foreign_error,
        }

    def _index_documents(self) -> tuple[dict[str, str], str | None]:
        """索引裡每份文件的現況：檔名 → 狀態。**「它現在怎麼樣」的唯一真相來源。**

        本站的簿記只答得出「我送出去了」，答不出「它現在怎麼樣」——
        重抽會把已經完成的文件打回 processing，而簿記不會跟著變。

        連不上時回報**錯誤訊息**而不是空字典：一個安靜的 0 會讓人以為
        「沒有別的東西」，那比看到警告危險。
        """
        now = time.monotonic()
        if self._index_cache is not None and now - self._index_cache[0] < 30.0:
            return self._index_cache[1], self._index_cache[2]

        rows: dict[str, str] = {}
        error: str | None = None
        try:
            # 用 GET /documents 而不是 /documents/paginated：後者的 page_size
            # 上限是 200（實測傳 500 回 HTTP 422），而這裡要的是**全部**，
            # 分頁只會讓「有沒有漏」多一個要驗的東西。
            payload = self.client.request("/documents", timeout=4.0)
            statuses = payload.get("statuses")
            if isinstance(statuses, dict):
                for status_name, documents in statuses.items():
                    if not isinstance(documents, list):
                        continue
                    for item in documents:
                        if not isinstance(item, dict):
                            continue
                        name = str(item.get("file_path") or item.get("id") or "")
                        if name:
                            rows[name] = str(item.get("status") or status_name)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            error = f"問不到 LightRAG 的文件清單（{type(exc).__name__}），下面的份數可能不完整"

        self._index_cache = (now, rows, error)
        return rows, error

    def _foreign_documents(self) -> tuple[list[dict[str, object]], str | None]:
        """索引裡有、但本站沒有紀錄的文件。

        審核台只記得自己經手過的。用 CLI 或別的方式進去的文件它不知道，
        於是畫面顯示 1 份而資料庫其實有 2 份 —— 而使用者會照畫面做決定。
        """
        index, error = self._index_documents()

        # 排除的是「本站**負責那一列**的」：在途（已經送進 inputs）或已完成。
        #
        # 兩個方向都踩過，而且是對稱的：
        # ① 排除「本站有紀錄的」太寬 —— 文件已索引成功但 job 因誤判卡在
        #    failed，於是它既不算 completed 也不算 foreign，兩邊都漏掉。
        # ② 排除「本站 indexed 的」太窄 —— 正在抽取的那一份不算成功處理，
        #    於是自己送的文件被貼上「不是這裡送的」，而且被計進「已處理」。
        #    2026-08-04 實測：B 抽到第 41 段時畫面說「已進知識庫 2」，實際 1 份。
        #
        # 正確的界線是 OWNED_STATUSES：**本站碰過索引，且還沒放手**。
        # failed／returned／planned 不排除 —— 那是 ① 要救的情況。
        mine = {job.filename for job in self._jobs.values() if job.status in OWNED_STATUSES}
        rows: list[dict[str, object]] = [
            {"filename": name, "status": status, "source": "不是這裡送進去的"}
            for name, status in index.items() if name not in mine
        ]
        return rows, error

    def links(self) -> dict[str, str]:
        """外部服務的位址，從 .env 組出來給畫面用。

        寫死 host 會讓這頁在換機器時指向不存在的地方，而且不會報錯 ——
        使用者只會看到一個點了沒反應的連結。
        """
        host = self.environment.get("BIND_ADDR", "127.0.0.1")
        return {
            "lightrag": f"http://{host}:{self.environment.get('HOST_PORT', '9621')}",
            "kbapi": f"http://{host}:{self.environment.get('KBAPI_PORT', '9700')}",
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


MAX_UPLOAD_BYTES = 512 * 1024 * 1024


def _upload_body(handler: BaseHTTPRequestHandler) -> bytes:
    """讀上傳的原始位元組。

    刻意不解析 multipart：`cgi` 在 3.13 被移除，自己寫 multipart 解析器則是
    典型的踩雷面（邊界字串、編碼、巢狀）。前端直接把 File 當 body 送，
    檔名走 `X-Filename` 標頭，這樣伺服器端只要讀 N 個位元組就好。
    """
    raw_length = handler.headers.get("Content-Length")
    try:
        length = int(raw_length or "0")
    except ValueError as exc:
        raise IntakeError("Content-Length 不合法", 400) from exc
    if length <= 0:
        raise IntakeError("沒有收到檔案內容", 400)
    if length > MAX_UPLOAD_BYTES:
        raise IntakeError(f"檔案超過上限 {MAX_UPLOAD_BYTES // (1024 * 1024)} MB", 413)
    try:
        data = handler.rfile.read(length)
    except OSError as exc:
        raise IntakeError(f"讀取上傳內容失敗：{exc}", 400) from exc
    if len(data) != length:
        raise IntakeError("上傳內容不完整（可能中斷）", 400)
    return data


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
        return "可以放行"
    labels = {
        "candidate": "還沒處理",
        "parsing": "解析中",
        "planned": "要你決定",
        "failed_parse": "解析失敗",
        # 修補→准入→掃描→抽取這四步是系統內部的分工，使用者在這段
        # 除了等沒有別的事可做。細分只會讓人以為每一步都需要他判斷。
        "repairing": "處理中",
        "admitted": "處理中",
        "scanning": "處理中",
        "extracting": "處理中",
        "indexed": "已進知識庫",
        "returned": "已跳過",
        "failed": "失敗",
    }
    return labels.get(str(status), str(status))


_BUSY_STATUSES = frozenset({"parsing", "repairing", "admitted", "scanning", "extracting"})

_BUSY_NOTE = {
    "parsing": "送去 MinerU 解析",
    "repairing": "套用修補規則",
    "admitted": "準備送進索引",
    "scanning": "LightRAG 掃描中",
    "extracting": "抽取實體與關係",
}


def _render_now_running(jobs: Sequence[Mapping[str, object]]) -> str:
    """**現在真的在跑的是哪一件**，還有多少在排隊。

    worker 是循序的，一次一件。沒有這一列的話，畫面上二十件都寫著「處理中」，
    而每一列的計時器都在長 —— 使用者無從得知是卡住了還是排在後面。
    2026-08-08 放 21 篇進來時當場被 PO 抓到：「都在處理中也很怪」。
    """
    running = [job for job in jobs
               if job.get("status") in _BUSY_STATUSES and not job.get("queued")]
    queued = [job for job in jobs if job.get("queued")]
    if not running and not queued:
        return ""

    if running:
        job = running[0]
        note = _busy_note(job.get("status"), job.get("stage_started_at"))
        head = (f"▶ <b>正在跑</b>　{_esc(str(job.get('filename'))[:62])}"
                f"　<span class='stamp'>{_esc(note)}</span>")
    else:
        head = "▶ <b>正在跑</b>　（沒有——佇列空了，或 worker 停了）"

    waiting = ""
    if queued:
        parse_n = sum(1 for job in queued if job.get("status") == "parsing")
        admit_n = len(queued) - parse_n
        bits = []
        if parse_n:
            bits.append(f"解析 {parse_n}")
        if admit_n:
            bits.append(f"放行 {admit_n}")
        waiting = (f"<div class='sub'><span>排隊中 {len(queued)} 件"
                   f"（{'、'.join(bits)}）</span>"
                   f"<span>一次跑一件，排隊的不會同時動</span></div>")
    return f"<div class='banner'>{head}{waiting}</div>"


def _busy_note(status: object, updated_at: object) -> str:
    """正在跑的工作要說「在做什麼、跑多久了」。

    MinerU 與抽取都是黑箱（送出去等回應），拿不到百分比。**能誠實講的只有
    走到哪一步、以及過了多久** —— 假的進度條比沒有進度條更糟，因為它會讓
    「卡住了」看起來像「快好了」。
    """
    note = _BUSY_NOTE.get(str(status), "處理中")
    if not isinstance(updated_at, str) or not updated_at:
        return note
    try:
        started = datetime.fromisoformat(updated_at)
    except ValueError:
        return note
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    seconds = int((datetime.now(UTC) - started).total_seconds())
    if seconds < 0:
        return note
    if seconds < 60:
        return f"{note} · {seconds} 秒"
    return f"{note} · {seconds // 60} 分 {seconds % 60} 秒"


def _chip_class(status: object, decision: object = None) -> str:
    """狀態 → 顏色。顏色本身要帶資訊，不是裝飾。"""
    if status == "planned":
        return "clean" if decision == "clean" else "novel"
    if status in {"failed", "failed_parse"}:
        return "blocked"
    if status == "indexed":
        return "clean"
    if status in {"parsing", "repairing", "scanning", "extracting", "admitted"}:
        return "review"
    return "idle"


def _render_candidate_row(candidate: Mapping[str, object]) -> str:
    candidate_id = _esc(candidate.get("candidate_id", ""))
    source = str(candidate.get("source", ""))
    filename = str(candidate.get("filename", ""))
    # 只有收件匣裡的檔案給刪 —— 別的來源不是我們的東西。
    remove = ""
    if source == "inbox":
        remove = (f"<button class='danger' data-act='rm' data-id='{_esc(filename)}'"
                  f" title='從收件匣刪除'>刪除</button>")
    return (
        "<div class='row'>"
        f"<span class='nm' title='{_esc(filename)}'>{_esc(filename)}</span>"
        f"<span style='display:flex;gap:6px'>{remove}"
        f"<button data-act='parse' data-id='{candidate_id}'>只解析</button></span>"
        f"<span class='sub'><span>{_esc(source)}</span>"
        f"<span>{_format_size(candidate.get('size'))}</span></span>"
        "</div>"
    )


def _render_parse_all(candidates: Sequence[Mapping[str, object]]) -> str:
    """整批送去解析。

    **為什麼需要**：worker 是循序的，一次只跑一件，而 `submit_parse` 在忙碌時
    直接回 409。所以一篇一篇按的話，第二篇會被擋 —— 使用者得守在旁邊等每一篇
    跑完（解析＋自動放行＋抽取，一篇好幾分鐘）再按下一篇。放 14 篇進來時
    這不是「有點麻煩」，是不能用。

    API（`_candidate_ids`）本來就收得下 `candidate_ids` 複數，缺的只是按鈕。

    兩份以下不顯示：一顆「全部解析（1 份）」跟旁邊那顆「只解析」做的是同一件事，
    只是多佔一行。
    """
    if len(candidates) < 2:
        return ""
    ids = ",".join(str(row.get("candidate_id", "")) for row in candidates)
    return (
        "<div class='row'>"
        "<span class='nm'>這一批全部送去解析</span>"
        f"<button data-act='parse-all' data-id='{_esc(ids)}'>"
        f"全部解析（{len(candidates)} 份）</button>"
        "<span class='sub'><span>一次排隊、依序跑</span>"
        "<span>計畫乾淨的會自動放行，要你看的會停在「等你看」</span></span>"
        "</div>"
    )


def _render_job_row(job: Mapping[str, object], current: str | None = None) -> str:
    metrics = job.get("metrics") if isinstance(job.get("metrics"), dict) else {}
    if not isinstance(metrics, dict):
        metrics = {}
    job_id = _esc(job.get("job_id", ""))
    status = job.get("status")
    decision = job.get("decision")
    is_current = current is not None and job.get("job_id") == current
    action = ""
    if status in {"failed", "failed_parse", "returned"}:
        # 計畫還通過著的失敗給「重試」，而且排在「放回收件匣」前面 ——
        # 並排的兩顆按鈕裡，先看到的那顆會被當成建議做法，而重試不會刪掉
        # 已經做好的解析成果（重抓要錢、要時間）。
        if status == "failed" and decision == "clean":
            action = (f"<button data-act='retry' data-id='{job_id}'"
                      f" title='計畫還有效，解析成果保留'>重試</button>")
        action += f"<button data-act='reset' data-id='{job_id}'>放回收件匣</button>"
    elif status == "planned":
        action = f"<a class='btn' href='?job={job_id}'>看計畫</a>"
    pages = metrics.get("pages")
    items = metrics.get("items")
    size_bits = []
    if pages not in (None, "—"):
        size_bits.append(f"<span>{_esc(pages)} 頁</span>")
    if items not in (None, "—"):
        size_bits.append(f"<span>{_esc(items)} 項</span>")
    # 正在跑的要說出「在做什麼、跑多久了」。沒有這個，使用者只看得到
    # 檔案從收件匣消失，不知道它是在跑還是壞了。
    if status in _BUSY_STATUSES:
        # 計時器從**這一階段真的開始**算起，不是從排進佇列算起。
        # 排隊中的完全不給計時器 —— 一個一直在長的數字就是「卡住」的樣子。
        note = ("排隊中，還沒輪到" if job.get("queued")
                else _busy_note(status, job.get("stage_started_at") or job.get("updated_at")))
        size_bits.append(f"<span>{_esc(note)}</span>")
    error = job.get("error")
    err_html = ""
    # planned 也要顯示：放行被擋下來會把文件退回這一節並留下原因，不顯示的話
    # 使用者只看得到「按了沒反應」。
    if status in {"failed", "failed_parse", "planned"} and isinstance(error, str) and error:
        err_html = f"<span class='err'>⚠ {_esc(error)}</span>"
    chip = (f"<span class='chip {'idle' if job.get('queued') else _chip_class(status, decision)}'>"
            f"{_esc('排隊中' if job.get('queued') else _status_label(status, decision))}</span>")
    return (
        f"<div class='row{" current" if is_current else ""}'>"
        f"<a class='nm' href='?job={job_id}' title='{_esc(job.get("filename", ""))}'>"
        f"{_esc(job.get('filename', ''))}</a>"
        f"<span style='display:flex;gap:6px;align-items:center'>{chip}{action}</span>"
        f"<span class='sub'><span>{_esc(job.get('source', ''))}</span>{''.join(size_bits)}</span>"
        f"{err_html}</div>"
    )


def _index_status_label(status: object) -> str:
    """知識庫回的狀態 → 人話。**明說是知識庫講的**，因為這一列的可信度來自它，
    不是來自本站的簿記。認不得的原樣顯示 —— 翻譯不出來就不要假裝看得懂。
    """
    return {
        "processed": "知識庫說已完成",
        "processing": "知識庫說正在抽取",
        "pending": "知識庫說排隊中",
        "failed": "知識庫說失敗",
    }.get(str(status), str(status))


def _render_foreign_row(row: Mapping[str, object]) -> str:
    """索引裡有、但本站沒紀錄的文件。沒有 job 就沒有動作可做，只標明它存在。

    不列出來的話，畫面會顯示「已進知識庫 1 份」而資料庫其實有 2 份 ——
    而使用者會照畫面做決定。
    """
    return (
        "<div class='row'>"
        f"<span class='nm' title='{_esc(row.get("filename", ""))}'>"
        f"{_esc(row.get('filename', ''))}</span>"
        "<span class='chip idle'>不是這裡送的</span>"
        f"<span class='sub'><span>{_esc(_index_status_label(row.get('status')))}</span>"
        "<span>用 CLI 或其他方式進去的</span></span>"
        "</div>"
    )


def _render_section(key: str, title: str, rows: Sequence[Mapping[str, object]],
                    renderer: Callable[[Mapping[str, object]], str],
                    open_default: bool = False, prefix: str = "") -> str:
    """一節佇列。預設收起來 —— 攤開全部等於沒有分節。

    內容區限高捲動（CSS 的 .sec-body），所以 387 份的選片區不會把畫面撐爆。

    `prefix` 是整節的動作列（例如「全部解析」），只在**這節有東西**時出現 ——
    空的佇列上掛一顆按不動的按鈕，只會讓人以為壞了。
    """
    body = "".join(renderer(row) for row in rows)
    body = prefix + body if body else "<div class='empty'>沒有</div>"
    attr = " open" if open_default else ""
    return (
        f"<details data-sec='{_esc(key)}'{attr}>"
        f"<summary><span class='caret'>▶</span>"
        f"<span class='sec-name'>{_esc(title)}</span>"
        f"<span class='count'>{len(rows)}</span></summary>"
        f"<div class='sec-body'>{body}</div></details>"
    )


def _render_convergence(convergence: Mapping[str, object], links: Mapping[str, object]) -> str:
    """收斂列：這批還在教我們東西嗎。

    ⚠ 樣本太小時**明說樣本太小**，不畫趨勢圖。用 3 份文件畫出來的「出現率」
    是噪音，而畫成圖表會讓它看起來像結論 —— 那正是這個專案一路在防的東西。
    """
    processed = convergence.get("processed", 0)
    try:
        n = int(processed)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        n = 0
    events = convergence.get("events")
    event_count = len([e for e in events if isinstance(e, dict)]) if isinstance(events, list) else 0
    distance = convergence.get("distance_since_last_event")
    distance_text = "—" if distance is None else str(distance)

    if n < 10:
        verdict = (f"樣本還太小（{n} 份），現在談收斂沒有意義。"
                   f"先累積到 10 份以上，出現率才讀得出趨勢。")
    elif event_count == 0:
        verdict = f"連續 {n} 份沒有出現新型態 —— 規則可能已經涵蓋這批文件。"
    else:
        verdict = (f"最近一次新型態出現在 {distance_text} 份之前。"
                   f"距離拉長代表規則在收斂。")

    warning = convergence.get("warning")
    banner = f"<div class='banner'>⚠ {_esc(warning)}</div>" if warning else ""
    lightrag = _esc(links.get("lightrag", "")) if isinstance(links, Mapping) else ""
    kbapi = _esc(links.get("kbapi", "")) if isinstance(links, Mapping) else ""
    return (
        "<div class='topbar'>"
        "<div class='topbar-main'><p class='eyebrow'>收斂狀態</p>"
        "<h1>這批還在教我們東西嗎</h1>"
        f"<p>{_esc(verdict)}</p></div>"
        "<div class='stats'>"
        f"<div><div class='k'>已處理</div><div class='v'>{n}</div></div>"
        f"<div><div class='k'>沒見過的</div><div class='v'>{event_count}</div></div>"
        f"<div><div class='k'>距上次</div><div class='v'>{_esc(distance_text)}</div></div>"
        "</div>"
        "<div class='links'>"
        f"<a href='{lightrag}' target='_blank' rel='noopener'>知識庫 ↗</a>"
        f"<a href='{kbapi}/health' target='_blank' rel='noopener'>kbapi ↗</a>"
        "</div></div>" + banner
    )


def _render_pending_groups(groups: object) -> str:
    """待確認**按原因分組**，不是按文件。

    判準是「這個現象有幾份文件的證據」——按文件分組看不到跨文件的模式，
    而那正是決定要不要寫成規則的唯一依據。
    """
    if not isinstance(groups, list) or not groups:
        return ""
    rows: list[str] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        jobs = group.get("jobs")
        names = []
        if isinstance(jobs, list):
            names = [str(item.get("filename", "")) for item in jobs if isinstance(item, dict)]
        rows.append(
            "<div class='row'>"
            f"<span class='nm'>{_esc(group.get('reason', '未分類'))}</span>"
            f"<span class='chip novel'>{_esc(group.get('count', 0))} 份</span>"
            f"<span class='sub'><span>{_esc('、'.join(names))}</span></span>"
            "</div>"
        )
    return (
        "<details data-sec='reasons'>"
        "<summary><span class='caret'>▶</span>"
        "<span class='sec-name'>卡住的 · 按原因</span>"
        f"<span class='count'>{len(rows)}</span></summary>"
        f"<div class='sec-body'>{''.join(rows)}</div></details>"
    )


def _render_plan(job: Mapping[str, object] | None) -> str:
    if job is None:
        return (
            "<div class='stage-body'><p class='eyebrow'>處理計畫</p>"
            "<h2>左邊挑一份，先只解析</h2>"
            "<p class='meta'>解析完會在這裡列出它打算怎麼處理，"
            "確認過才會有放行動作。</p>"
            "<p class='hint'>先花小錢解析看清楚，再花十幾分鐘抽取的大錢 ——"
            "這一步不能跳過。</p></div>"
        )
    metrics = job.get("metrics") if isinstance(job.get("metrics"), dict) else {}
    if not isinstance(metrics, dict):
        metrics = {}
    status = job.get("status")
    decision = job.get("decision")
    reasons = job.get("reasons") if isinstance(job.get("reasons"), list) else []
    details = job.get("details") if isinstance(job.get("details"), list) else []
    error = job.get("error")
    job_id = _esc(job.get("job_id", ""))

    if status in {"failed", "failed_parse"} and isinstance(error, str) and error:
        teach = ("<div class='teach bad'><b>這一份失敗了</b>"
                 f"<ul><li>{_esc(error)}</li></ul></div>")
    elif reasons:
        items = []
        for index, reason in enumerate(reasons):
            detail = details[index] if index < len(details) else ""
            extra = f"<small>{_esc(detail)}</small>" if detail else ""
            items.append(f"<li>{_esc(reason)}{extra}"
                         "<em>決定會變成規則，套用到之後所有文件</em></li>")
        teach = (f"<div class='teach'><b>有 {len(reasons)} 件沒見過的</b>"
                 f"<ul>{''.join(items)}</ul></div>")
    else:
        teach = ("<div class='teach ok'><b>沒有。全部命中既有規則</b>"
                 "<ul><li>處理方式與前面幾份相同，沒有需要你決定的事。</li></ul></div>")

    if status == "planned" and decision == "clean":
        acts = (f"<button class='go' data-act='admit' data-id='{job_id}'>放行 · 修補並索引</button>"
                f"<button data-act='return' data-id='{job_id}'>跳過</button>")
    elif status == "planned":
        acts = f"<button data-act='return' data-id='{job_id}'>跳過並保留理由</button>"
    elif status in {"failed", "failed_parse"}:
        acts = f"<button data-act='reset' data-id='{job_id}'>重置為候選</button>"
    else:
        acts = (f"<span class='chip {_chip_class(status, decision)}'>"
                f"{_esc(_status_label(status, decision))}</span>")

    leakage = metrics.get("leakage_rate")
    leakage_text = "未量測" if leakage is None else f"{float(leakage):.2%}"
    pages = metrics.get("pages")
    items_n = metrics.get("items")
    head = []
    if pages not in (None, "—"):
        head.append(f"{_esc(pages)} 頁")
    if items_n not in (None, "—"):
        head.append(f"{_esc(items_n)} 個項目")
    head.append(_esc(_status_label(status, decision)))

    return (
        "<div class='stage-body'><p class='eyebrow'>處理計畫</p>"
        f"<h2>{_esc(job.get('filename', ''))}</h2>"
        f"<p class='meta'>{' · '.join(head)}</p>"
        "<h3>這份有沒有教我們新東西</h3>"
        f"{teach}"
        "<h3>打算怎麼處理</h3><div class='grid'>"
        f"<div class='cell'><div class='k'>消音</div>"
        f"<div class='v'>{_esc(metrics.get('mute', 0))}<small>處</small></div></div>"
        f"<div class='cell'><div class='k'>空表格</div>"
        f"<div class='v'>{_esc(metrics.get('empty_tables', 0))}<small>個</small></div></div>"
        f"<div class='cell'><div class='k'>chart</div>"
        f"<div class='v'>{_esc(metrics.get('charts', 0))}<small>只登記</small></div></div>"
        f"<div class='cell'><div class='k'>項目數變化</div>"
        f"<div class='v'>{_esc(metrics.get('item_delta', 0))}<small>不得改變</small></div></div>"
        "</div>"
        "<h3>細節</h3><table><tbody>"
        f"<tr><td>來源</td><td class='val'>{_esc(job.get('source', ''))}</td></tr>"
        f"<tr><td>解析選項</td><td class='val'>{_esc(metrics.get('parse_options', '未取得'))}</td></tr>"
        f"<tr><td>漏詞率</td><td class='val'>{_esc(leakage_text)}</td></tr>"
        "</tbody></table>"
        f"<div class='acts'>{acts}</div>"
        "<p class='hint'>放行會寫入磁碟並開始抽取。寫入前原始檔會自動備份，可以還原；"
        "<b>但抽取進索引之後，撤銷是「刪掉重跑」不是「還原」。</b></p>"
        "</div>"
    )


CSS = """:root{
  --ground:#E9EDEF; --panel:#F8FAFB; --sunk:#DDE4E7; --rail:#E1E7E9;
  --ink:#0E161A; --ink-2:#46585F; --ink-3:#6D8189;
  --line:#C2CDD2; --line-soft:#D6DEE1;
  --accent:#14566E; --accent-ink:#F8FAFB;
  --clean:#2C6A51; --review:#9A6B15; --blocked:#8F352C; --novel:#5B3E8C;
  --mono:ui-monospace,"SF Mono","JetBrains Mono",Menlo,Consolas,monospace;
  --sans:ui-sans-serif,-apple-system,"Segoe UI","PingFang TC","Noto Sans TC",sans-serif;
}
@media (prefers-color-scheme:dark){
  :root{
    --ground:#090F12; --panel:#111A1E; --sunk:#0C1316; --rail:#0E1619;
    --ink:#E2EAED; --ink-2:#93A6AE; --ink-3:#6B7F86;
    --line:#223035; --line-soft:#1A252A;
    --accent:#68AEC8; --accent-ink:#08131A;
    --clean:#6EBE94; --review:#D6A448; --blocked:#D2786D; --novel:#A98BD6;
  }
}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--sans);
  font-size:15px;line-height:1.6;-webkit-font-smoothing:antialiased}
main{max-width:1340px;margin:0 auto;padding:18px 16px 64px}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}

/* ── 頂列：收斂狀態 ───────────────────────────────── */
.topbar{background:var(--panel);border:1px solid var(--line);border-radius:2px;
  padding:14px 18px;display:flex;gap:22px;align-items:flex-start;flex-wrap:wrap}
.topbar-main{flex:1 1 320px;min-width:0}
.eyebrow{margin:0 0 2px;font-family:var(--mono);font-size:10.5px;letter-spacing:.12em;
  text-transform:uppercase;color:var(--ink-3)}
.topbar h1{margin:0;font-size:17px;font-weight:640;letter-spacing:-.01em}
.topbar p{margin:4px 0 0;color:var(--ink-2);font-size:13.5px}
.stats{display:flex;gap:20px;flex:0 0 auto}
.stats div{min-width:72px}
.stats .k{font-family:var(--mono);font-size:10.5px;letter-spacing:.06em;
  text-transform:uppercase;color:var(--ink-3)}
.stats .v{font-size:22px;font-weight:600;font-variant-numeric:tabular-nums;
  letter-spacing:-.02em;font-family:var(--mono)}
.links{display:flex;gap:8px;flex:0 0 auto;align-items:center}
.links a{font-family:var(--mono);font-size:12px;border:1px solid var(--line);
  border-radius:2px;padding:5px 10px;color:var(--ink-2)}
.links a:hover{border-color:var(--accent);color:var(--accent);text-decoration:none}
.banner{margin-top:2px;padding:9px 14px;border-radius:2px;font-size:13px;
  background:var(--sunk);border-left:3px solid var(--review);color:var(--ink-2)}
/* 紅燈分兩種，處置完全不同，所以顏色也要分：
   .bad   新鮮的失敗 —— 現在就有東西壞了，去看 detail。
   .stale 結果凍住了 —— **你不知道現在是好是壞**，先去救排程，不要讀那個值。
   灰色是刻意的：過期的結果不該用警示色搶注意力，那會讓人以為問題在被檢查的
   東西上，而實際上問題在檢查本身沒有在跑。 */
.banner.bad{border-left-color:var(--blocked)}
.banner.stale{border-left-color:var(--line);color:var(--ink-3)}
.banner .stamp{font-family:var(--mono);font-size:12px;color:var(--ink-3)}

/* ── 版面：佇列 ｜ 判斷 ────────────────────────────── */
.layout{display:grid;grid-template-columns:minmax(300px,360px) minmax(0,1fr);
  gap:2px;margin-top:2px;align-items:start}
@media (max-width:900px){.layout{grid-template-columns:1fr}}
.queue,.stage{background:var(--panel);border:1px solid var(--line);border-radius:2px}
.queue{overflow:hidden}

/* ── 佇列的摺疊節 ─────────────────────────────────── */
details{border-bottom:1px solid var(--line-soft)}
details:last-of-type{border-bottom:0}
summary{list-style:none;cursor:pointer;padding:10px 16px;display:flex;
  align-items:center;gap:9px;background:var(--sunk);user-select:none}
summary::-webkit-details-marker{display:none}
summary:hover{background:var(--rail)}
summary:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
.caret{font-family:var(--mono);font-size:10px;color:var(--ink-3);
  transition:transform .12s ease;flex:0 0 auto}
details[open] .caret{transform:rotate(90deg)}
.sec-name{font-size:12px;font-family:var(--mono);letter-spacing:.1em;
  text-transform:uppercase;color:var(--ink-3);font-weight:500;flex:1}
.count{font-family:var(--mono);font-size:12px;font-variant-numeric:tabular-nums;
  color:var(--ink-2);background:var(--panel);border:1px solid var(--line-soft);
  border-radius:2px;padding:1px 7px}
.sec-body{max-height:16.5rem;overflow-y:auto;overscroll-behavior:contain}

/* ── 佇列的列 ─────────────────────────────────────── */
.row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:4px 10px;
  align-items:center;padding:10px 16px;border-bottom:1px solid var(--line-soft);
  border-left:3px solid transparent}
.row:last-child{border-bottom:0}
.row:hover{background:var(--sunk)}
.row.current{background:var(--rail);border-left-color:var(--accent)}
.row .nm{font-size:13.5px;font-weight:560;overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap;min-width:0}
.row .sub{grid-column:1/-1;font-family:var(--mono);font-size:11.5px;color:var(--ink-3);
  display:flex;gap:8px;flex-wrap:wrap}
.row .err{grid-column:1/-1;font-size:12px;color:var(--blocked);overflow-wrap:anywhere}
.empty{padding:14px 16px;color:var(--ink-3);font-size:13px}

/* ── 狀態標籤 ─────────────────────────────────────── */
.chip{font-family:var(--mono);font-size:10.5px;letter-spacing:.05em;padding:1px 7px;
  border-radius:2px;border:1px solid;white-space:nowrap}
.chip.clean{color:var(--clean);border-color:var(--clean)}
.chip.review{color:var(--review);border-color:var(--review)}
.chip.blocked{color:var(--blocked);border-color:var(--blocked)}
.chip.novel{color:var(--novel);border-color:var(--novel)}
.chip.idle{color:var(--ink-3);border-color:var(--line)}

/* ── 按鈕 ─────────────────────────────────────────── */
button,.btn{font:inherit;font-size:12.5px;font-family:var(--mono);padding:5px 11px;
  border-radius:2px;border:1px solid var(--line);background:var(--panel);
  color:var(--ink-2);cursor:pointer;white-space:nowrap}
button:hover,.btn:hover{border-color:var(--accent);color:var(--accent);text-decoration:none}
button:focus-visible,.btn:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
button.go{background:var(--accent);border-color:var(--accent);color:var(--accent-ink);
  font-size:14px;font-family:var(--sans);font-weight:600;padding:9px 18px}
button.go:hover{filter:brightness(1.12);color:var(--accent-ink)}
button.danger:hover{border-color:var(--blocked);color:var(--blocked)}
button[disabled]{opacity:.4;cursor:not-allowed}

/* ── 判斷卡片 ─────────────────────────────────────── */
.stage-body{padding:22px 26px 26px}
.stage h2{margin:0 0 3px;font-size:20px;font-weight:640;letter-spacing:-.015em;
  text-wrap:balance;overflow-wrap:anywhere}
.stage .meta{font-family:var(--mono);font-size:12px;color:var(--ink-3);margin:0 0 20px}
.stage h3{margin:22px 0 8px;font-family:var(--mono);font-size:11px;letter-spacing:.11em;
  text-transform:uppercase;color:var(--ink-3);font-weight:500}
.stage h3:first-child{margin-top:0}
.teach{border:1px solid var(--novel);border-left-width:3px;background:var(--sunk);
  padding:14px 16px}
.teach b{color:var(--novel)}
.teach ul{margin:8px 0 0;padding-left:1.15em}
.teach li{margin-bottom:7px;font-size:14px}
.teach li small{display:block;color:var(--ink-2);font-size:12.5px;margin-top:2px}
.teach li em{display:block;color:var(--novel);font-size:11.5px;font-style:normal;margin-top:3px}
.teach.ok{border-color:var(--clean)}
.teach.ok b{color:var(--clean)}
.teach.bad{border-color:var(--blocked)}
.teach.bad b{color:var(--blocked)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(116px,1fr));gap:2px}
.cell{background:var(--sunk);padding:11px 13px}
.cell .k{font-family:var(--mono);font-size:10.5px;letter-spacing:.05em;color:var(--ink-3)}
.cell .v{font-family:var(--mono);font-size:19px;font-weight:600;margin-top:2px;
  font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.cell .v small{font-family:var(--sans);font-size:12px;font-weight:400;color:var(--ink-3);
  letter-spacing:0;margin-left:3px}
table{border-collapse:collapse;width:100%;font-size:13.5px;margin-top:4px}
td{padding:7px 0;border-bottom:1px solid var(--line-soft);vertical-align:top}
td:first-child{color:var(--ink-2);width:34%;font-size:13px}
td.val{font-family:var(--mono);font-size:12.5px;overflow-wrap:anywhere}
tr:last-child td{border-bottom:0}
.acts{display:flex;gap:9px;flex-wrap:wrap;margin-top:24px;padding-top:18px;
  border-top:1px solid var(--line)}
.hint{font-size:12.5px;color:var(--ink-3);margin:12px 0 0;line-height:1.55}
.hint b{color:var(--ink-2)}

/* ── 拖拉上傳 ─────────────────────────────────────── */
.dropzone{margin:2px 0 0;background:var(--panel);border:1px dashed var(--line);
  border-radius:2px;padding:16px;text-align:center;color:var(--ink-3);font-size:13px}
.dropzone b{color:var(--ink-2);font-weight:560}
.dropzone input{display:none}
.dropzone label{color:var(--accent);cursor:pointer;text-decoration:underline}
#veil{position:fixed;inset:0;background:color-mix(in srgb,var(--ground) 88%,transparent);
  border:3px dashed var(--accent);display:none;place-items:center;z-index:50;
  font-size:19px;font-weight:600;color:var(--accent)}
#veil.on{display:grid}
#uplog{margin-top:8px;font-family:var(--mono);font-size:12px;text-align:left}
#uplog div{padding:2px 0}
#uplog .bad{color:var(--blocked)}
#uplog .ok{color:var(--clean)}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}"""


JS = r"""const post = async (path, body) => {
  const r = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'},
                              body:JSON.stringify(body)});
  const d = await r.json().catch(() => ({}));
  if (!r.ok) { alert(d.error || '操作失敗'); return false; }
  location.reload(); return true;
};
document.querySelectorAll('[data-act]').forEach(b => b.onclick = () => {
  const a = b.dataset.act;
  if (a === 'parse')  return post('/api/parse',  {candidate_id: b.dataset.id});
  if (a === 'parse-all') return post('/api/parse', {candidate_ids: b.dataset.id.split(',')});
  if (a === 'admit')  return post('/api/admit',  {job_id: b.dataset.id});
  if (a === 'return') return post('/api/return', {job_id: b.dataset.id});
  if (a === 'retry')  return post('/api/retry',  {job_id: b.dataset.id});
  if (a === 'reset')  return post('/api/reset',  {job_id: b.dataset.id});
  if (a === 'rm') {
    if (!confirm('從收件匣刪除 ' + b.dataset.id + '？')) return;
    return post('/api/inbox/delete', {filename: b.dataset.id});
  }
});

/* 記住哪幾節是開的 —— reload 之後不該把使用者剛展開的東西關回去 */
const OPEN = 'intake.open';
const opened = new Set(JSON.parse(sessionStorage.getItem(OPEN) || '[]'));
document.querySelectorAll('details[data-sec]').forEach(d => {
  if (opened.size) d.open = opened.has(d.dataset.sec);
  d.addEventListener('toggle', () => {
    const now = [...document.querySelectorAll('details[data-sec]')]
      .filter(x => x.open).map(x => x.dataset.sec);
    sessionStorage.setItem(OPEN, JSON.stringify(now));
  });
});

/* 上傳：拖到頁面任何地方都收 */
const veil = document.getElementById('veil');
const uplog = document.getElementById('uplog');
let depth = 0;
const say = (msg, cls) => {
  const el = document.createElement('div');
  el.textContent = msg; if (cls) el.className = cls;
  uplog.prepend(el);
};
const send = async (files) => {
  let ok = 0;
  for (const f of files) {
    try {
      const r = await fetch('/api/upload', {method:'POST', body:f,
        headers:{'X-Filename': encodeURIComponent(f.name),
                 'Content-Type':'application/octet-stream'}});
      const d = await r.json().catch(() => ({}));
      if (r.ok) { say('收下 ' + (d.filename || f.name), 'ok'); ok++; }
      else say(f.name + '：' + (d.error || '失敗'), 'bad');
    } catch (e) { say(f.name + '：' + e.message, 'bad'); }
  }
  if (ok) setTimeout(() => location.reload(), 700);
};
['dragenter','dragover'].forEach(ev => document.addEventListener(ev, e => {
  if (!e.dataTransfer || ![...e.dataTransfer.types].includes('Files')) return;
  e.preventDefault(); depth++; veil.classList.add('on');
}));
['dragleave','drop'].forEach(ev => document.addEventListener(ev, e => {
  e.preventDefault(); depth = Math.max(0, depth - (ev === 'drop' ? depth : 1));
  if (!depth) veil.classList.remove('on');
}));
document.addEventListener('drop', e => {
  if (e.dataTransfer && e.dataTransfer.files.length) send(e.dataTransfer.files);
});
const picker = document.getElementById('picker');
if (picker) picker.onchange = () => { if (picker.files.length) send(picker.files); };

/* 只在真的有工作在跑時才輪詢。閒著的時候整頁不動 ——
   原本那個 <meta refresh 5> 會在你看東西看到一半把畫面抽掉。 */
if (document.body.dataset.running === '1') {
  const seen = document.body.dataset.sig;
  setInterval(async () => {
    try {
      const s = await (await fetch('/api/state')).json();
      const sec = s.sections || {};
      const sig = [s.health && s.health.running ? 1 : 0,
                   ...['selection','parsing','review','in_progress','completed','failed']
                     .map(k => (sec[k] || []).length)].join('.');
      if (sig !== seen) location.reload();
    } catch (_) { /* 網路瞬斷不該把畫面弄壞，下一輪再試 */ }
  }, 3000);
}"""


def render_html(state: Mapping[str, object], selected_job_id: str | None = None) -> str:
    sections = state.get("sections") if isinstance(state.get("sections"), dict) else {}
    if not isinstance(sections, dict):
        sections = {}
    jobs = state.get("jobs") if isinstance(state.get("jobs"), list) else []
    selected: Mapping[str, object] | None = None
    if selected_job_id and isinstance(jobs, list):
        for item in jobs:
            if isinstance(item, dict) and item.get("job_id") == selected_job_id:
                selected = item
                break

    def sec(name: str) -> list[Mapping[str, object]]:
        value = sections.get(name, [])
        return value if isinstance(value, list) else []

    review, parsing, failed = sec("review"), sec("parsing"), sec("failed")
    in_progress, completed, selection = sec("in_progress"), sec("completed"), sec("selection")
    skipped = sec("skipped")

    # foreign 的列已經在 state() 依知識庫狀態分進各節了，這裡只取錯誤訊息。
    foreign_error = state.get("foreign_error")
    health = state.get("health") if isinstance(state.get("health"), dict) else {}
    running = bool(health.get("running")) or bool(parsing) or bool(in_progress)
    signature = ".".join(str(x) for x in [
        1 if health.get("running") else 0,
        len(selection), len(parsing), len(review),
        len(in_progress), len(completed), len(failed), len(skipped)])

    links = state.get("links") if isinstance(state.get("links"), dict) else {}
    warnings = state.get("source_warnings")
    warn_html = ""
    if isinstance(warnings, list) and warnings:
        warn_html = ("<div class='banner'>⚠ "
                     + _esc("；".join(str(item) for item in warnings)) + "</div>")
    if isinstance(foreign_error, str) and foreign_error:
        warn_html += f"<div class='banner'>⚠ {_esc(foreign_error)}</div>"

    # daily-check 的紅綠燈。**這是本專案唯一的警報管道**（2026-08-08 裁決：
    # 「只要在 9710 有警告就好」）。ok 不顯示 —— 常態不該佔畫面，否則真的紅燈
    # 會被淹沒；其餘四種狀態都要出現在最上面。
    checks = state.get("checks") if isinstance(state.get("checks"), dict) else {}
    cs = str(checks.get("state") or "")
    if cs and cs != "ok":
        age = checks.get("age_s")
        age_txt = f"{age / 3600:.0f} 小時前" if isinstance(age, (int, float)) else "時間不明"
        tone = ""
        if cs == "stale":
            tone = " stale"
            msg = (f"每日檢查已經 {age_txt}沒有更新（最後一次寫的是 "
                   f"{checks.get('reported')}）——**這不是通過，是沒有在檢查**。"
                   "排程可能停用了：systemctl status lightrag-daily-check.timer")
        elif cs == "missing":
            msg = str(checks.get("reason") or "每日檢查沒有結果檔")
        elif cs == "unreadable":
            msg = str(checks.get("reason") or "每日檢查的結果檔讀不了")
        else:
            tone = " bad"
            failing = checks.get("failing")
            which = "、".join(str(x) for x in failing) if isinstance(failing, list) and failing else "未指明"
            msg = (f"每日檢查 {cs}（{age_txt}）：{which}。"
                   f"細節 {checks.get('detail') or '（無）'}")
        # 產生它的 commit 跟著顯示：一筆紅燈是哪一版的碼判的，決定了它還算不算數。
        commit = checks.get("commit")
        stamp_html = (f" <span class='stamp'>由 {_esc(str(commit))} 產生</span>"
                      if commit else
                      " <span class='stamp'>（這筆結果沒有記版本，是舊格式）</span>")
        warn_html += f"<div class='banner{tone}'>🔔 {_esc(msg)}{stamp_html}</div>"

    # 預設只展開「待審核」—— 那是唯一需要你動腦的一節。其餘收起來，
    # 使用者展開過的會被 sessionStorage 記住（見 JS）。
    # 由上而下就是一份文件實際會走的路：
    #   收件匣 → 解析 → 等你看 → （卡住的）→ 處理 → 進知識庫 →（失敗）
    # 預設只展開「等你看」——那是唯一需要你動腦的一節。
    job_row = lambda row: _render_job_row(row, selected_job_id)  # noqa: E731
    # 三節可能同時裝著本站的 job 與別人送的列（見 state() 的分節規則），
    # 用同一個 renderer 分辨：有 job_id 就是本站的。
    any_row = lambda row: (_render_job_row(row, selected_job_id)  # noqa: E731
                           if row.get("job_id") else _render_foreign_row(row))
    queue = (
        _render_section("selection", "收件匣", selection, _render_candidate_row,
                        prefix=_render_parse_all(selection))
        + _render_section("parsing", "解析中", parsing, job_row,
                          open_default=bool(parsing))
        + _render_section("review", "等你看", review, job_row, open_default=True)
        + _render_pending_groups(state.get("pending_by_reason"))
        + _render_section("in_progress", "處理中", in_progress, any_row,
                          open_default=bool(in_progress))
        + _render_section("completed", "已進知識庫", completed, any_row)
        + _render_section("skipped", "已跳過", skipped, job_row,
                          open_default=bool(skipped))
        + _render_section("failed", "失敗", failed, any_row,
                          open_default=bool(failed))
    )

    return (
        "<!doctype html>\n"
        "<html lang='zh-Hant'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>進料審核台</title><style>" + CSS + "</style></head>"
        f"<body data-running='{1 if running else 0}' data-sig='{_esc(signature)}'>"
        "<div id='veil'>放開就收下</div><main>"
        + _render_convergence(
            state.get("convergence") if isinstance(state.get("convergence"), dict) else {},
            links)
        + _render_now_running(jobs)
        + warn_html
        + "<div class='layout'>"
        + f"<div class='queue'>{queue}</div>"
        + f"<div class='stage'>{_render_plan(selected)}</div>"
        + "</div>"
        + "<div class='dropzone'>把 PDF <b>拖到這一頁的任何地方</b>，或"
          "<label for='picker'>選擇檔案</label>"
          "<input id='picker' type='file' accept='application/pdf' multiple>"
          "<div id='uplog'></div></div>"
        + "</main><script>" + JS + "</script></body></html>"
    )


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
                # 上傳走 raw body，不是 JSON —— 必須在 _json_body 之前分流，
                # 否則會拿 PDF 的位元組去餵 json.loads。
                if parsed.path == "/api/upload":
                    name = self.headers.get("X-Filename", "")
                    saved = app.save_upload(urllib.parse.unquote(name), _upload_body(self))
                    self._json({"status": "ok", "filename": saved.name}, 201)
                    return
                payload = _json_body(self)
                if parsed.path == "/api/parse":
                    jobs = app.submit_parse(_candidate_ids(payload))
                    self._json({"jobs": [app._public_job(job) for job in jobs]}, 202)
                    return
                if parsed.path == "/api/inbox/delete":
                    filename = payload.get("filename")
                    if not isinstance(filename, str):
                        raise IntakeError("需要 filename", 400)
                    app.delete_inbox_file(filename)
                    self._json({"status": "ok"})
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
                if parsed.path == "/api/retry":
                    job = app.submit_retry(job_id)
                    self._json({"job": app._public_job(job)}, 202)
                    return
                if parsed.path == "/api/reset":
                    candidate_id = app.submit_reset(job_id)
                    self._json({"status": "ok", "candidate_id": candidate_id})
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
