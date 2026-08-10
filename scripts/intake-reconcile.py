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

⚠ **乾跑不用停服務**（它只讀）。**`--commit` 之前才要停** —— intake 把 job 抱在
記憶體裡、只在自己改動時存檔，在它底下改 `job.json` 不會被讀到，重啟之後還會
被舊值蓋回去。

    sudo systemctl stop lightrag-intake.service
    python3 scripts/intake-reconcile.py --commit
    sudo systemctl start lightrag-intake.service
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
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
    configured_data_root,
    hard_failing_documents,
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


def _hard_failing_documents(filenames: set[str]) -> tuple[set[str], list[str]]:
    """跑一次全庫契約檢查，把結果交給共用的判準去分。

    ⚠ **解析那段不寫在這裡。** `intake.py` 的批次驗證用同一支
    `hard_failing_documents()` —— 兩份實作只要有人改一邊就會靜靜地不一致，
    而這個專案已經踩過五次「同一件事兩個地方」。
    """
    completed = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "compat-check.py"), "--json"],
        cwd=REPO, capture_output=True, text=True, check=False, timeout=3600)
    try:
        return hard_failing_documents(completed.stdout, filenames)
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"compat-check --json 的輸出不是 JSON（exit {completed.returncode}）："
            f"{exc}；stderr 前 300 字：{completed.stderr[:300]}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument("--commit", action="store_true", help="真的寫入；預設只列出判定")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    environment = load_env(REPO)
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

    # **跑一次全庫的契約檢查，不是逐份跑。** 逐份跑 84 次要十幾分鐘而且會把
    # Postgres 打滿（2026-08-10 實測，中途只好停掉）；而那 84 次問的是同一個
    # 母體，一次就答得完。
    bad_docs, fatal = _hard_failing_documents({job.filename for job in jobs})
    if fatal:
        LOGGER.error("契約檢查有**不屬於任何一份文件**的 hard 失敗，先處理它們：\n  %s\n"
                     "整庫層級的紅燈沒排除之前翻牌是不負責任的。", "\n  ".join(fatal))
        return 2
    LOGGER.info("全庫契約檢查跑完：%d 份有 hard 失敗", len(bad_docs))

    flipped: list[Job] = []
    kept: list[tuple[Job, str]] = []
    for job in candidates:
        status = index.get(job.filename)
        verify_ok = job.filename not in bad_docs
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
