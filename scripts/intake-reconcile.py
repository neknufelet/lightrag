#!/usr/bin/env python3
"""把「其實已經進庫」的假失敗撿回來。**預設乾跑，`--commit` 才寫。**

## 為什麼需要這支

2026-08-10 一批 89 份進料，審核台報 84 份失敗，而資料庫那側 **159 份全部是
processed**。死因是契約檢查裡的一條斷言「pipeline 現在是閒的」（A-19，hard），
而分批之後同批的鄰居還在跑 —— 於是除了最後一份，每一份都被自己的鄰居判死。
**壞掉的從頭到尾只有簿記，資料全部是對的。**

流程那側已經修好（契約檢查挪到整批抽完之後，見 `intake.py` 的 `verify`）。
這支處理的是**已經被誤殺的那些紀錄**，是一次性的補救，不是常設流程。

## 判準：兩個獨立來源都說沒事才翻牌

    1. LightRAG 說這份是 processed
    2. 重跑一次該份的契約檢查，沒有 hard 失敗

**第 2 條是這支工具不會退化成「把紅燈關掉」的唯一保障。** 少了它，真的有問題
的文件會跟著一起洗白 —— 而那正是這批檢查存在的理由。
（`tests/test_intake_reconcile.py` 有一條控制組專門釘住這件事。）

## 用法

    python3 scripts/intake-reconcile.py                 # 乾跑，只列出判定
    python3 scripts/intake-reconcile.py --commit        # 真的寫

⚠ **跑之前先把 intake 服務停掉。** 它把 job 抱在記憶體裡、只在自己改動時存檔；
在它底下改 `job.json` 不會被讀到，重啟之後還會被舊值蓋回去。

    sudo systemctl stop lightrag-intake.service
    python3 scripts/intake-reconcile.py --commit
    sudo systemctl start lightrag-intake.service
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parent))

from intake import (  # noqa: E402
    REPO,
    DataPaths,
    Job,
    JobStore,
    LightRAGClient,
    SubprocessRunner,
    configured_data_root,
    index_status_by_filename,
    load_env,
)

LOGGER = logging.getLogger("intake-reconcile")

FLIP: Final = "翻牌"
KEEP: Final = "留著"
SKIP: Final = "不管"


def decide(job_status: str, index_status: str | None, *, verify_ok: bool) -> tuple[str, str]:
    """這一筆該怎麼處置。**純函式，沒有 I/O** —— 判準要能單獨被測。

    `index_status` 是 LightRAG 那邊回報的狀態，`None` 代表索引裡根本沒有這份。
    """
    if job_status != "failed":
        return SKIP, f"狀態是 {job_status}，不在管轄範圍"
    if index_status is None:
        return KEEP, "索引裡沒有這份 —— 這是真的失敗"
    if index_status.lower() != "processed":
        return KEEP, f"索引說它現在是 {index_status}，還沒定案"
    if not verify_ok:
        return KEEP, "契約檢查仍然沒過 —— 這一份是真的有問題"
    return FLIP, "索引裡是 processed，契約也重驗過了"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument("--commit", action="store_true", help="真的寫入；預設只列出判定")
    parser.add_argument("--workspace", default=None, help="預設讀 .env 的 WORKSPACE")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    environment = load_env(REPO)
    workspace = args.workspace or environment.get("WORKSPACE") or "acoustics_v2"
    paths = DataPaths(configured_data_root(environment))
    store = JobStore(paths)
    jobs = store.load()
    if store.load_errors:
        LOGGER.error("有 job 讀不起來，先處理它們再跑這支：\n  %s",
                     "\n  ".join(store.load_errors))
        return 2

    client = LightRAGClient(environment)
    index, error = index_status_by_filename(client)
    if error is not None:
        # **問不到就停，不要猜。** 空的索引清單會讓每一筆都判成「真的失敗」，
        # 而那個結論看起來完全正常。
        LOGGER.error("問不到 LightRAG 的文件清單，停下來：%s", error)
        return 2

    candidates = [job for job in jobs if job.status == "failed"]
    LOGGER.info("job 總數 %d、其中失敗 %d、索引裡 %d 份",
                len(jobs), len(candidates), len(index))
    if not candidates:
        LOGGER.info("沒有失敗的 job，不用做事。")
        return 0

    runner = SubprocessRunner(REPO, {**environment, "WORKSPACE": workspace})
    flipped: list[Job] = []
    kept: list[tuple[Job, str]] = []
    for job in candidates:
        status = index.get(job.filename)
        verify_ok = False
        if status is not None and status.lower() == "processed":
            result = runner.verify(job)
            verify_ok = result.ok
        verdict, why = decide(job.status, status, verify_ok=verify_ok)
        if verdict is FLIP:
            flipped.append(job)
            LOGGER.info("  翻牌  %s", job.filename)
        elif verdict is KEEP:
            kept.append((job, why))
            LOGGER.info("  留著  %s　—— %s", job.filename, why)

    LOGGER.info("\n可以翻牌 %d 筆、留在失敗 %d 筆", len(flipped), len(kept))
    if not args.commit:
        LOGGER.info("乾跑，沒有寫任何東西。確認上面的判定之後加 --commit。")
        return 0

    for job in flipped:
        job.status = "indexed"          # type: ignore[assignment]
        job.error = None
        store.save(job)
        store.append_log(
            job.job_id,
            "簿記修正：這份其實已經進庫（LightRAG 回報 processed，契約重驗通過）。"
            "原本的失敗是分批抽取時契約檢查撞上「鄰居還在跑」造成的，不是文件的問題。")
    LOGGER.info("已寫入 %d 筆。記得把 intake 服務重新啟動。", len(flipped))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
