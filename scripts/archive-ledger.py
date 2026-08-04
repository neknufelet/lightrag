#!/usr/bin/env python3
"""一次性歸檔不在當前索引裡的舊體檢表。

預設是 dry-run，只列出會被移動的檔案；加 ``--move`` 才會真的移動。
判斷「目前仍在索引」以 Postgres 的 ``lightrag_doc_status`` 為準，因為文件
登記存在但尚未產生 chunk 仍是索引流程中的有意義狀態，不能被當成舊文件。

這支只處理 ``records/ledger/*.pdf.json``，不會掃描或修改 ``records/review/``。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mineru_common import add_workspace_arg, load_env, postgres_container  # noqa: E402
from pp.paths import DEFAULT_DATA_ROOT, DataPaths  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DATE_RE = re.compile(r"^\d{8}$")
README_NAME = "README.md"


class ArchiveError(RuntimeError):
    """歸檔前置條件或移動驗證失敗。"""


def _sql_literal(value: str) -> str:
    """將 workspace 安全地寫成 SQL 字串字面值。"""
    return "'" + value.replace("'", "''") + "'"


def _document_name(file_path: str) -> str:
    """把 DB 的 file_path 正規化成 ledger 使用的 PDF 檔名。"""
    first = file_path.split("<SEP>", 1)[0].strip()
    return Path(first).name if first else ""


def _indexed_query(workspace: str) -> str:
    """建立保留完整檔名的 JSON 聚合查詢。"""
    ws = _sql_literal(workspace)
    return (
        "select coalesce(json_agg(file_path order by file_path), '[]'::json)::text "
        "from (select distinct file_path from lightrag_doc_status "
        f"where workspace = {ws} and file_path is not null) docs;"
    )


def indexed_documents(env: Mapping[str, str], workspace: str) -> set[str]:
    """從當前 workspace 的文件登記讀出已存在於索引流程的檔名。"""
    container = postgres_container(env)
    command = [
        "docker", "exec", container, "psql",
        "-U", env.get("POSTGRES_USER", "deeptutor"),
        "-d", env.get("POSTGRES_DATABASE", "lightrag"),
        "-tAqX", "-c", _indexed_query(workspace),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise ArchiveError(f"psql 失敗（{container}）：{result.stderr.strip()[:400]}")
    try:
        values = json.loads(result.stdout.strip() or "[]")
    except json.JSONDecodeError as exc:
        raise ArchiveError(f"psql 回傳不是 JSON 文件清單：{result.stdout[:200]!r}") from exc
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise ArchiveError("psql 回傳的文件清單格式不符，拒絕猜測")
    return {name for value in values if (name := _document_name(value))}


def ledger_files(root: Path) -> list[Path]:
    """列出 ledger 的體檢表；其他 records 子目錄完全不在範圍。"""
    directory = DataPaths(root).ledger_dir
    if not directory.is_dir():
        raise ArchiveError(f"找不到 ledger 目錄：{directory}")
    return sorted(path for path in directory.glob("*.pdf.json") if path.is_file())


def archive_candidates(root: Path, indexed: set[str]) -> list[Path]:
    """找出 ledger 中不在當前文件登記的體檢表。"""
    return [path for path in ledger_files(root)
            if path.name.removesuffix(".json") not in indexed]


def archive_date(value: str | None) -> str:
    """回傳安全的 YYYYMMDD 目錄日期。"""
    result = value or datetime.now().astimezone().strftime("%Y%m%d")
    if not DATE_RE.fullmatch(result):
        raise ArchiveError("日期必須是 YYYYMMDD，例如 20260804")
    return result


def _readme(archive_day: str, workspace: str, count: int) -> str:
    """產生歸檔目錄的追溯說明。"""
    return (
        f"# ledger archive {archive_day}\n\n"
        "這批對應重建前的文件，已不在索引中，保留供追溯。\n\n"
        f"- workspace: `{workspace}`\n"
        "- 來源：當前 workspace 的 `lightrag_doc_status` 文件登記\n"
        f"- 歸檔體檢表：{count} 份\n"
        "- `records/review/` 的耐久規則證據未移動。\n"
    )


def _check_destinations(candidates: Sequence[Path], archive_dir: Path) -> None:
    """在任何移動前檢查目標，避免覆寫既有歸檔。"""
    if archive_dir.exists() and not archive_dir.is_dir():
        raise ArchiveError(f"歸檔目標不是目錄：{archive_dir}")
    for source in candidates:
        destination = archive_dir / source.name
        if destination.exists():
            raise ArchiveError(f"歸檔目標已存在，拒絕覆寫：{destination}")
    readme = archive_dir / README_NAME
    if readme.exists():
        raise ArchiveError(f"歸檔目標已有 {README_NAME}，請先人工檢查：{archive_dir}")


def move_archive(candidates: Sequence[Path], archive_dir: Path,
                 readme: str) -> None:
    """建立追溯說明、移動檔案，失敗時盡力回滾已移動內容。"""
    _check_destinations(candidates, archive_dir)
    archive_dir.mkdir(parents=True, exist_ok=True)
    readme_path = archive_dir / README_NAME
    moved: list[tuple[Path, Path]] = []
    try:
        readme_path.write_text(readme, encoding="utf-8")
        for source in candidates:
            destination = archive_dir / source.name
            source.rename(destination)
            moved.append((source, destination))
        missing = [destination for _, destination in moved if not destination.is_file()]
        if missing:
            raise ArchiveError(f"移動後找不到目標檔：{missing}")
    except Exception as exc:
        rollback_errors: list[str] = []
        for source, destination in reversed(moved):
            try:
                destination.rename(source)
            except OSError as rollback_exc:
                rollback_errors.append(f"{destination} -> {source}: {rollback_exc}")
        if not rollback_errors:
            readme_path.unlink(missing_ok=True)
        detail = f"；回滾失敗：{'；'.join(rollback_errors)}" if rollback_errors else "；已回滾"
        if isinstance(exc, ArchiveError):
            raise ArchiveError(f"歸檔失敗：{exc}{detail}") from exc
        raise ArchiveError(f"歸檔失敗：{type(exc).__name__}: {exc}{detail}") from exc


def _parser(env: dict[str, str]) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="歸檔不在當前索引裡的舊 ledger（預設 dry-run）",
    )
    add_workspace_arg(parser, env)
    parser.add_argument("--root", type=Path, default=DEFAULT_DATA_ROOT,
                        help="資料根目錄（預設 /data/lightrag）")
    parser.add_argument("--date", help="歸檔目錄日期 YYYYMMDD（預設今天）")
    parser.add_argument("--move", action="store_true",
                        help="真的移動檔案；未指定時只做 dry-run")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """執行 dry-run 或明確要求的歸檔。"""
    env = load_env(REPO)
    args = _parser(env).parse_args(argv)
    try:
        day = archive_date(args.date)
        indexed = indexed_documents(env, args.workspace)
        candidates = archive_candidates(args.root, indexed)
        archive_dir = args.root / "records" / f"ledger-archive-{day}"
    except ArchiveError as exc:
        print(f"archive-ledger: {exc}", file=sys.stderr)
        return 2

    print(f"當前索引文件 {len(indexed)} 份；ledger 體檢表待歸檔 {len(candidates)} 份")
    for candidate in candidates:
        print(f"  {candidate}")
    if not args.move:
        print(f"dry-run：未移動檔案。真的移動請加 --move（目標：{archive_dir}）")
        return 0
    if not candidates:
        print("沒有需要歸檔的體檢表；未建立歸檔目錄。")
        return 0

    try:
        move_archive(candidates, archive_dir, _readme(day, args.workspace, len(candidates)))
    except ArchiveError as exc:
        print(f"archive-ledger: {exc}", file=sys.stderr)
        return 2
    print(f"已移動 {len(candidates)} 份體檢表至 {archive_dir}；README 已寫入。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
