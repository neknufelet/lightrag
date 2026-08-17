"""確認清單的純算層：從處理計畫挑出「要人看的段落」。

**規則只做確定的，其餘進清單**（PO 2026-08-16 裁決）。這一層不開畫面、不寫檔，
只回答三件事：這份文件有哪幾項要人確認、規則預設怎麼勾、**為什麼**。

設計與四條裁決在 `docs/confirm-list-design-20260817.md`：

1. 打勾 ＝ 不要
2. 一份一份，確認一份放行一份（沒確認的不會被抽取 —— 先抽再改要重抽，花兩次錢）
3. 不確定的預設不勾（＝留著）：寧可多留垃圾，不要誤刪正文
4. **每一項都要有一句白話理由** —— 少了它，人得自己重新判斷每一項，
   「規則先幫你勾好」就白幫了

2026-08-17 在 dker 全母體實測：要確認的 1,232 項散在 218 份（平均 5.7 項），
規則有把握直接丟的 7,586 項。
"""
from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DECIDED_BY_RULE = "rule"
DECIDED_BY_HUMAN = "human"


@dataclass(frozen=True)
class ConfirmItem:
    """確認清單的一列。

    Attributes:
        section: 來自計畫的哪一段（``noise`` / ``title``）。與 ``index`` 合起來
            才是穩定的識別 —— 兩段的 index 各自從 0 起算，會撞。
        index: 這一項在解析結果裡是第幾項。
        category: 給人看的分類（「頁首頁尾」「標題區塊」）。
        reason: **白話理由**，說「機器憑什麼這樣勾」，不是只說分類。
        text: 原文片段。不給原文，人沒辦法判斷。
        page: 第幾頁。不給頁碼，人回不去查。
        suppress: 要不要丟掉。**沒把握的一律 False（留著）。**
        decided_by: :data:`DECIDED_BY_RULE` 或 :data:`DECIDED_BY_HUMAN`。
        note: 人改這一項的理由。選填。
    """

    section: str
    index: int
    category: str
    reason: str
    text: str
    page: int
    suppress: bool
    decided_by: str = DECIDED_BY_RULE
    note: str = ""

    @property
    def key(self) -> str:
        """穩定識別。存檔與回填都用它。"""
        return f"{self.section}:{self.index}"


def _require(plan: Mapping[str, object], name: str) -> Mapping[str, object]:
    """計畫裡必須有這一段。**缺了就丟，不要回空的假裝乾淨。**

    這個碼庫記過同型事故：`pp.tables` 因為缺鍵而回 `{}`，一路走到
    「共 None 張，沒有待修的」，在 dker 上產生 4 個假通過。
    """
    section = plan.get(name)
    if not isinstance(section, Mapping):
        raise KeyError(f"處理計畫缺少 `{name}` 那一段 —— 多半是計畫半路失敗，"
                       "這時候不知道有沒有要確認的項目，不能當成沒有")
    return section


def _rows(section: Mapping[str, object], key: str) -> Sequence[Mapping[str, object]]:
    value = section.get(key) or []
    return value if isinstance(value, list) else []


def items_from_plan(plan: Mapping[str, object]) -> list[ConfirmItem]:
    """挑出要人確認的項目。**規則有把握的不進來**（那些走 :func:`muted_count`）。

    有把握的也塞進來的話，實測會從 1,232 列變成 8,818 列 —— 人看不完，
    而「規則先幫你勾好」這個設計就失去意義。

    Raises:
        KeyError: 計畫缺段（見 :func:`_require`）。
    """
    noise = _require(plan, "noise")
    title = _require(plan, "title")

    items: list[ConfirmItem] = []
    for row in _rows(noise, "held"):
        repeat = row.get("repeat")
        items.append(ConfirmItem(
            section="noise", index=int(row["index"]), category="頁首頁尾",
            reason=(f"重複 {repeat} 次，像頁首頁尾，但次數不夠多、不敢確定"
                    if repeat is not None else "像頁首頁尾，但不敢確定"),
            text=str(row.get("text") or ""), page=int(row.get("page") or 0),
            suppress=False,
        ))
    for row in _rows(title, "held"):
        items.append(ConfirmItem(
            section="title", index=int(row["index"]), category="標題區塊",
            reason="在第一頁的標題區，可能是期刊封面資訊，也可能是正文開頭",
            text=str(row.get("text") or ""), page=int(row.get("page") or 0),
            suppress=False,
        ))

    logger.debug("%s：要確認 %d 項", plan.get("doc"), len(items))
    return items


def muted_count(plan: Mapping[str, object]) -> int:
    """規則有把握、直接丟掉的項數。

    **要報個數，不能安靜消失**（藍桶第 2 條）。數字不見的話，人分不出
    「這份很乾淨」與「規則把半份文件丟了」。
    """
    total = 0
    for name in ("noise", "refs", "title"):
        section = plan.get(name)
        if isinstance(section, Mapping):
            total += len(_rows(section, "mute"))
    return total
