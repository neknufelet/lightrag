"""拆章勾選清單 —— 純算層。

吃 :func:`chapters.split_plan.plan_pdf_split` 算好的計畫，回一份**給人勾**的清單。

**這一層不開畫面、不切檔、不寫檔。** 它只回答兩件事：這本書有哪幾列可以勾、
規則先幫你勾成什麼樣。算錯了在這裡發現最便宜 —— 等畫面做好才發現，畫面也得重做。

設計與裁決在 `docs/chapter-selection-record-20260817.md`。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from chapters.naming import MAX_FILENAME_LENGTH, sanitize_filename
from chapters.split_plan import PdfChapterPlan, is_appendix_title, is_preamble_title

logger = logging.getLogger(__name__)

#: `decided_by` 的兩個值。分開記是為了讓「哪些是人判的」永遠看得出來 ——
#: 少了它，下一個人無法區分「規則剛好也這樣勾」與「有人特地改成這樣」。
DECIDED_BY_RULE = "rule"
DECIDED_BY_HUMAN = "human"


@dataclass
class SelectionRow:
    """勾選清單的一列。

    Attributes:
        title: 目錄原標題（未清理）。
        level: TOC 層級（1＝章、2＝節）。
        page_range: 1-indexed 含頭含尾頁範圍。
        serial: 兩位流水號的數值。**配在完整計畫上，包含沒勾的列** —— 見
            :func:`build_selection`。
        filename: 切出來的檔名 ``<KEY>_<NN> <尾巴>.pdf``。
        selected: 這一列要不要切出來。
        decided_by: 誰決定的 —— :data:`DECIDED_BY_RULE` 或 :data:`DECIDED_BY_HUMAN`。
        note: 人改這一列的理由。**選填**（PO 2026-08-17 裁：不強迫）。
    """

    title: str
    level: int
    page_range: tuple[int, int]
    serial: int
    filename: str
    selected: bool
    decided_by: str
    note: str = ""


def build_selection(plans: list[PdfChapterPlan], *, key: str, tail: str) -> list[SelectionRow]:
    """把拆章計畫變成一份給人勾的清單，規則先勾好。

    Args:
        plans: :func:`plan_pdf_split` 的輸出，順序即書的順序。
        key: 這本書的 8 碼 Zotero item key。
        tail: 檔名尾巴（``年份 - 標題``），沿用進料台既有的形狀。

    Returns:
        與 ``plans`` 等長、同序的清單。**沒勾的列也在裡面**（藍桶第 2 條）。

    ⚠ **流水號配在完整計畫上，不是配在勾好的那幾列上。** 跳過沒勾的列去配號的話，
    取消勾第 3 列會讓第 4 列從 ``_04`` 遞補成 ``_03``，檔名就跟著勾選浮動 ——
    那違背 PO 2026-08-17 的裁決（「照舊的切、檔名不變」），而且下游的 MinerU
    解析與 DeepSeek 抽取會整批重跑。取消勾選因此在號碼上留下空隙，那是刻意的。
    """
    rows: list[SelectionRow] = []
    for serial, plan in enumerate(plans, start=1):
        skip = is_preamble_title(plan.title) or is_appendix_title(plan.title)
        body = sanitize_filename(f"{tail}_{plan.title}", max_length=MAX_FILENAME_LENGTH)
        rows.append(SelectionRow(
            title=plan.title,
            level=plan.level,
            page_range=plan.page_range,
            serial=serial,
            filename=f"{key}_{serial:02d} {body}.pdf",
            selected=not skip,
            decided_by=DECIDED_BY_RULE,
        ))
    logger.debug("勾選清單 %d 列，規則預設勾 %d 列",
                 len(rows), sum(r.selected for r in rows))
    return rows
