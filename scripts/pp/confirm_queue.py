"""確認清單的排隊：還有哪幾份要確認、現在輪到哪一份。

PO 2026-08-17 第二條：**一份一份，做到哪算到哪**，關掉再回來從下一份接著。

這一層刻意只回答順序 —— 不碰檔案、不算計畫、不知道資料根在哪，所以在 coder 上
就驗得完（coder 沒有 LightRAG 的 `.env` 也沒有它的 docker）。真正去找檔案、
算計畫的是 `intake.py`，它只做接線。
"""
from __future__ import annotations

import logging
from collections.abc import Container, Sequence

logger = logging.getLogger(__name__)


def pending(docs: Sequence[str], recorded: Container[str]) -> list[str]:
    """還沒確認過的那些，**依檔名排好**。

    ⚠ **順序必須穩定**，否則畫面上的「第 12 / 165 份」是騙人的。用檔名排序而不是
    沿用檔案系統給的順序 —— `glob` 的順序沒有保證，換一台機器或多一個檔就可能
    不一樣，而順序一變，人重新整理一次就看到自己「倒退」了。

    Args:
        docs: 所有有東西要確認的文件檔名。
        recorded: 已經有確認紀錄的那些。
    """
    queue = sorted(d for d in docs if d not in recorded)
    logger.debug("待確認 %d 份（總共 %d 份有項目）", len(queue), len(docs))
    return queue


def position_of(doc: str, queue: Sequence[str]) -> int:
    """這一份排第幾（**1 起算**，因為這個數字是給人看的）。

    不在隊伍裡就回 0 —— 人按了「存起來，下一份」再按瀏覽器的上一頁就會走到
    這裡。**回 0 不要丟例外**：炸掉的話他會以為自己把東西弄壞了。
    """
    try:
        return queue.index(doc) + 1
    except ValueError:
        logger.debug("%s 不在待確認隊伍裡（可能剛確認完）", doc)
        return 0


def next_after(doc: str, queue: Sequence[str]) -> str | None:
    """下一份是誰。做到最後一份、或這一份不在隊伍裡，都回 ``None``。

    ⚠ **不要繞回第一份。** 繞回去的話，被跳過的那份永遠排在前面，
    人會一直看到同一份。
    """
    index = position_of(doc, queue)
    if index == 0 or index >= len(queue):
        return None
    return queue[index]
