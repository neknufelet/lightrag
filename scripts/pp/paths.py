"""LightRAG 資料目錄的單一路徑契約。

宿主資料根的內容分成三類：LightRAG 入口、不可再生紀錄，以及工作快取。
所有腳本都從這裡取得它們的子目錄，避免搬家時各自重新拼出不同路徑。
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

DEFAULT_DATA_ROOT: Final[Path] = Path("/data/lightrag")
CONTAINER_DATA_ROOT: Final[Path] = Path("/app/data")


def configured_data_root(
    environment: Mapping[str, str] | None = None,
    *,
    variable: str = "PP_DATA_ROOT",
) -> Path:
    """回傳腳本用的資料根；未設定時使用乾淨環境的預設值。"""
    values = environment if environment is not None else os.environ
    return Path(values.get(variable) or DEFAULT_DATA_ROOT)


@dataclass(frozen=True)
class DataPaths:
    """宿主上的 LightRAG、後處理與體檢資料路徑。"""

    root: Path

    @property
    def inbox_dir(self) -> Path:
        return self.root / "inbox"

    @property
    def library_dir(self) -> Path:
        return self.root / "library"

    @property
    def intake_dir(self) -> Path:
        """審核台自己的狀態根；不與 LightRAG 的輸入或解析快取混用。"""
        return self.root / "intake"

    @property
    def intake_jobs_dir(self) -> Path:
        return self.intake_dir / "jobs"

    @property
    def intake_events_path(self) -> Path:
        return self.intake_dir / "teaching-events.jsonl"

    def intake_job_dir(self, job_id: str) -> Path:
        return self.intake_jobs_dir / job_id

    def library_source_dir(self, source_key: str) -> Path:
        """單一來源庫的審核台複本目錄。"""
        return self.library_dir / source_key

    @property
    def work_dir(self) -> Path:
        return self.root / "work"

    @property
    def parsed_dir(self) -> Path:
        return self.work_dir / "parsed"

    @property
    def crops_dir(self) -> Path:
        return self.work_dir / "crops"

    @property
    def equations_dir(self) -> Path:
        return self.crops_dir / "_equations"

    @property
    def records_dir(self) -> Path:
        return self.root / "records"

    @property
    def ledger_dir(self) -> Path:
        return self.records_dir / "ledger"

    @property
    def checks_dir(self) -> Path:
        return self.root / "checks"

    @property
    def inputs_root(self) -> Path:
        return self.root / "inputs"

    @property
    def rag_storage_dir(self) -> Path:
        return self.root / "rag_storage"

    @property
    def backup_stamp(self) -> Path:
        return self.root / ".backup-cold.stamp"

    def inputs_dir(self, workspace: str) -> Path:
        """LightRAG 掃描入口；workspace 子目錄不可省略。"""
        return self.inputs_root / workspace

    def parsed_bundle_dir(self, document: str) -> Path:
        return self.parsed_dir / f"{document}.mineru_raw"

    def crop_document_dir(self, document: str) -> Path:
        return self.crops_dir / document


@dataclass(frozen=True)
class ContainerPaths:
    """容器內的 LightRAG 路徑，對應 compose 的 bind mounts。"""

    root: Path = CONTAINER_DATA_ROOT

    def inputs_dir(self, workspace: str) -> Path:
        return self.root / "inputs" / workspace

    def parsed_dir(self, workspace: str) -> Path:
        return self.inputs_dir(workspace) / "__parsed__"

    def parsed_bundle_dir(self, workspace: str, document: str) -> Path:
        return self.parsed_dir(workspace) / f"{document}.mineru_raw"
