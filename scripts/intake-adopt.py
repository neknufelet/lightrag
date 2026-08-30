#!/usr/bin/env python3
"""把「索引裡有、審核台卻不認」的文件收回簿記。**預設乾跑，`--commit` 才寫。**

## 為什麼需要這支

2026-08-30：`intake.py` 的 `_run` 把 stderr 併進 stdout，而 `compat-check --json`
刻意把 `#scope N` 走 stderr 以保持 stdout 整份是 JSON。那行字黏在收尾的 `]` 後面，
於是整批 12 份被判「契約檢查的輸出讀不出來」——**而它們其實已經抽完進庫了**。
判失敗觸發 rollback 撤掉 `inputs/` 的副本，PO 在畫面上按了重置，job 目錄被
`shutil.rmtree` 刪掉。結果：LightRAG 說 184 份 processed，審核台只認 172 份，
另外 12 份變成「不是這裡送進去的」。

根因已修（`fix(intake): 要餵給 json.loads 的輸出不准併 stderr`）。這支處理的是
**已經壞掉的那些紀錄**，一次性補救，不是常設流程。

⚠ **`intake-reconcile.py` 救不了這一種。** 那支管的是 `status == "failed"` 的 job，
而這裡的文件**連 job 都沒有**——重置把整個目錄刪了。兩支的形狀不同，不要合併。

⚠ **不重放。** 這 12 份在 LightRAG 裡是 `processed`，當成新檔再放行一次會在圖譜裡
長出重複的實體與關係，比現在難收拾得多。這支不碰 LightRAG，不重抽，只補回
檔案位置與 job 紀錄。

## 判準：三個獨立來源都點頭才收

    1. LightRAG 說這份是 `processed`
    2. `work/parsed` 下有它的 `.mineru_raw` bundle，manifest 讀得出 source_content_hash
    3. 收件匣裡有一份原檔，內容雜湊與 manifest 記的**相符**

少一條就不收。收錯的代價是「畫面說進去了、其實沒有」——那比不收嚴重得多，
因為不收看得見，收錯看不見。

## 用法

    python3 scripts/intake-adopt.py --source /data/lightrag/inbox            # 乾跑
    python3 scripts/intake-adopt.py --source /data/lightrag/inbox --commit   # 真的寫

⚠ **乾跑不用停服務**（它只讀）。**`--commit` 之前才要停** —— intake 把 job 抱在
記憶體裡、只在自己改動時存檔，在它底下建 `job.json` 不會被讀到，重啟之後還會
被舊值蓋回去（與 `intake-reconcile.py` 同一個理由）。

    sudo systemctl stop lightrag-intake.service
    python3 scripts/intake-adopt.py --source /data/lightrag/inbox --commit
    sudo systemctl start lightrag-intake.service
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import shutil
import sys
from pathlib import Path
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parent))

from intake import (  # noqa: E402
    REPO,
    Candidate,
    CandidateScanner,
    DataPaths,
    Job,
    JobStore,
    LightRAGClient,
    configured_data_root,
    index_status_by_filename,
    load_env,
)

LOGGER = logging.getLogger("intake-adopt")

ADOPT: Final = "收回"
SKIP: Final = "不收"

RESET_NOTE: Final = (
    "簿記修正（intake-adopt）：這份其實已經進庫（LightRAG 回報 processed）。"
    "原本的失敗是 compat-check 的 stdout 被 stderr 的 #scope 污染造成的假訊號，"
    "不是文件的問題；重置把 job 目錄刪掉之後它就變成「不是這裡送進去的」。"
    "解析成果與原檔的雜湊都比對過才收回。**計畫（plan）救不回來了**——"
    "重置刪掉的東西沒有備份，所以這一列的頁數／項目數會顯示「未取得」。"
)


def adopt_verdict(index_status: str | None, *,
                  has_bundle: bool, source_matches: bool) -> tuple[str, str]:
    """這一份該不該收回簿記。**純函式，沒有 I/O** —— 判準要能單獨被測。

    `index_status` 是 LightRAG 回報的狀態，`None` 代表索引裡根本沒有這份。
    """
    if index_status is None:
        return SKIP, "索引裡沒有這份 —— 它不是被誤殺的，是真的沒進去"
    if index_status.lower() != "processed":
        return SKIP, f"索引說它現在是 {index_status}，還沒定案"
    if not has_bundle:
        return SKIP, "找不到解析成果（.mineru_raw），沒有東西可以佐證這份是誰"
    if not source_matches:
        return SKIP, "收件匣的原檔對不上 manifest 的 source_content_hash —— 檔案被換過"
    return ADOPT, "索引是 processed、解析成果在、原檔雜湊相符"


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _manifest_source_hash(bundle: Path) -> str | None:
    """bundle 記的來源雜湊。讀不出來就回 None —— **不要猜**。"""
    try:
        return str(json.loads((bundle / "_manifest.json").read_text(encoding="utf-8"))
                   ["source_content_hash"])
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        LOGGER.warning("讀不到 %s 的 _manifest.json：%s: %s", bundle.name, type(exc).__name__, exc)
        return None


def _restore(source: Path, destination: Path, want: str) -> None:
    """把原檔複製到它該在的位置，**複製完再驗一次雜湊**。

    先寫暫存再 rename：中途斷掉不會留下一個長得像成品的半截檔案，而半截檔案
    會被 `CandidateScanner._known_hashes` 當成「已經有了」。
    """
    if destination.exists():
        if _sha256_of(destination) != want:
            raise RuntimeError(f"既有檔案內容不符，不覆蓋：{destination}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.adopt-partial"
    temporary.unlink(missing_ok=True)
    shutil.copy2(source, temporary)
    try:
        if _sha256_of(temporary) != want:
            raise RuntimeError(f"複製到 {destination} 後 sha256 不一致")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _adopted_job(candidate: Candidate, workspace: str,
                 library_path: Path, parsed_path: Path) -> Job:
    """做一份對應這份文件的 job 紀錄，狀態直接是 `indexed`。

    ⚠ **不走 `transition()`。** 狀態機管的是流程往前走，而這裡是在補一段
    **已經發生過**的歷史 —— 把 candidate→parsing→…→indexed 假裝走一遍只會在
    run.log 留下沒發生過的事。`intake-reconcile.py` 的翻牌也是直接指派。
    """
    job = Job.from_candidate(candidate)
    job.workspace = workspace
    job.status = "indexed"                              # type: ignore[assignment]
    job.library_path = str(library_path)
    job.parsed_source_path = str(parsed_path)
    job.details = ["簿記由 intake-adopt 補回，解析計畫已隨重置刪除"]
    return job


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument("--commit", action="store_true", help="真的寫入；預設只列出判定")
    parser.add_argument("--source", action="append", default=[],
                        help="收件匣目錄，可重複；未指定時讀 INTAKE_SOURCES")
    parser.add_argument("--workspace", default=None,
                        help="寫進 job 的 workspace；未指定時讀 .env 的 WORKSPACE")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    environment = load_env(REPO)
    paths = DataPaths(configured_data_root(environment))
    workspace = args.workspace or environment.get("WORKSPACE", "")
    if not workspace:
        LOGGER.error("不知道 workspace：給 --workspace，或讓 .env 有 WORKSPACE。")
        return 2

    sources = [Path(value) for value in args.source] or [
        Path(item.strip()) for item in environment.get("INTAKE_SOURCES", "").split(",")
        if item.strip()]
    if not sources:
        LOGGER.error("沒有來源目錄：給 --source，或讓 .env 有 INTAKE_SOURCES。")
        return 2

    store = JobStore(paths)
    jobs = store.load()
    if store.load_errors:
        LOGGER.error("有 job 讀不起來，先處理它們再跑這支：\n  %s",
                     "\n  ".join(store.load_errors))
        return 2

    index, error = index_status_by_filename(LightRAGClient(environment))
    if error is not None:
        # **問不到就停，不要猜。** 空的索引清單會讓每一份都判成「不收」，
        # 而那個結論看起來完全正常。
        LOGGER.error("問不到 LightRAG 的文件清單，停下來：%s", error)
        return 2

    mine = {job.filename for job in jobs}
    orphans = sorted(name for name in index if name not in mine)
    LOGGER.info("job 總數 %d、索引裡 %d 份、沒有 job 的 %d 份",
                len(jobs), len(index), len(orphans))
    if not orphans:
        LOGGER.info("每一份索引裡的文件都有 job，不用做事。")
        return 0

    # **先掃再補。** 掃描靠「這個雜湊在 library/work/parsed/inputs 出現過沒」判重複，
    # 補完檔案之後這些文件就掃不出來了，拿不到 candidate_id 與 source_key。
    candidates, warnings = CandidateScanner(paths, sources).scan(set(), set())
    for warning in warnings:
        LOGGER.warning("掃描：%s", warning)
    by_name = {candidate.filename: candidate for candidate in candidates}

    picked: list[Candidate] = []
    for name in orphans:
        bundle = paths.parsed_bundle_dir(name)
        want = _manifest_source_hash(bundle) if bundle.is_dir() else None
        candidate = by_name.get(name)
        matches = bool(want) and candidate is not None and candidate.sha256 == want
        verdict, why = adopt_verdict(index.get(name), has_bundle=want is not None,
                                     source_matches=matches)
        if verdict is ADOPT and candidate is not None:
            picked.append(candidate)
            LOGGER.info("  收回  %s", name)
        else:
            extra = "" if candidate is not None else "（收件匣裡也找不到原檔）"
            LOGGER.info("  不收  %s　—— %s%s", name, why, extra)

    LOGGER.info("\n可以收回 %d 份、不收 %d 份", len(picked), len(orphans) - len(picked))
    if not args.commit:
        LOGGER.info("乾跑，沒有寫任何東西。確認上面的判定之後加 --commit。")
        return 0

    for candidate in picked:
        library = paths.library_source_dir(candidate.source_key) / candidate.filename
        parsed = paths.parsed_dir / candidate.filename
        _restore(candidate.source_path, library, candidate.sha256)
        _restore(library, parsed, candidate.sha256)
        job = _adopted_job(candidate, workspace, library, parsed)
        store.save(job)
        store.append_log(job.job_id, RESET_NOTE)
        LOGGER.info("已收回 %s（job %s）", candidate.filename, job.job_id)
    LOGGER.info("\n已寫入 %d 份。記得把 intake 服務重新啟動。", len(picked))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
