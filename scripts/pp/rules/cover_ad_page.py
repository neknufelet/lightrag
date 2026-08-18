"""出版商夾在 PDF 最前面那一頁（廣告＋別人的論文）整頁丟掉。

`title_block` 的檔頭早就把這一頁列成「救不了的」：

    期刊封面頁（IOP 那種「You may also like」列別人論文的版面）—— 它的第一項
    不是 lvl=1 標題，本規則不開火。**那是另一種版面，另一條規則的事**

這裡就是那一條。PO 2026-08-18 看著兩張截圖說「出現好多份這種期刊一開始的廣告
頁面上的廣告字典被抽出來」，量完發現他講的不是幾個字，是**一整頁**。那一頁上
只有三種東西：

    這篇自己的標題（後面的頁上還會再出現一次）
    「Articles you may be interested in」＋**別人論文的標題與卷期**
    廣告（LakeShore、Zurich Instruments、Get the whitepaper、Lock-in Amplifiers）

⚠ **害處在中間那項**，不在廣告。別人的論文標題被當成這篇的內容吃進去，抽取出來
的圖譜就會把兩篇不相干的論文接在一起，而且不會有任何錯誤訊息。

**為什麼敢整頁丟**：全庫實測 2026-08-18，26 份有這一頁；逐份查過**每一份自己的
標題在後面的頁上都還在**（其中 `2019 - Broadband near-perfect absorption` 是
連字號斷字才比對不到，打開看過，第 1 頁確實有）。
"""
from __future__ import annotations

import logging
import re
import sys
from collections.abc import Container
from dataclasses import dataclass
from pathlib import Path
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from mineru_common import BODY_TYPES  # noqa: E402

logger = logging.getLogger(__name__)

#: 只認第 0 頁。**這道關不是保險，是必要條件。**
#: `2021 - A low-frequency sound absorber` 的廣告字出現在第 1 頁，而那一頁有
#: 807 字的真正文 —— 少了這道關，整段內容會被刪掉而且不報錯。
WRAPPER_PAGE_IDX: Final[int] = 0

#: 招牌字。兩種訊號，任一即可：
#:
#: ① 「Articles you may be interested in」—— 那一行底下列的是**別人的論文**
#: ② 廣告詞 —— 儀器商與期刊自己的推銷
#:
#: ⚠ 判準是「這一頁上出現過」，不是「這一段就是它」。整頁丟的規則要的是
#: **這一頁是什麼版面**，不是逐段判斷；逐段判斷正是上一輪做過而漏掉一半的做法。
AD_MARKERS: Final[re.Pattern[str]] = re.compile(
    r"articles?\s+you\s+may\s+be\s+interested\s+in"
    r"|learn\s+more|get\s+the\s+whitepaper|lake\s?shore|zurich\s+instruments"
    r"|advance\s+your\s+science|potential\s+to\s+shape\s+the\s+future"
    r"|save\s+your\s+money\s+for\s+your\s+research|belongs\s+in"
    r"|challenge\s+us|lock-in\s+amplifiers|whitepaper", re.I)

#: 這一頁上只要有一段比這個長，就不當廣告頁。
#:
#: **真正文都很長，廣告與別人的標題都很短。** 全庫實測 2026-08-18：26 個廣告頁
#: 上**沒有任何一段超過 300 字**，而誤判的那一頁（第 1 頁那份）最長的一段是
#: 807 字。這道關與 `WRAPPER_PAGE_IDX` 是互相獨立的兩張網，刻意都留著。
BODY_PARAGRAPH_MIN_CHARS: Final[int] = 300

#: 消掉超過這個比例就要人看一眼。
#:
#: ⚠ **這個門檻比另外三條鬆，是量出來的不是拍的。** 廣告頁常常出現在 APL 那種
#: 4 頁的短論文前面，一整頁佔全文的比重本來就高 —— 全庫實測 2026-08-18 開火的
#: 26 份，比例中位 2.5%、**最高 8.93%**（`2017 - Single-channel labyrinthine`）。
#: 設 8% 的話那一份會被比例守衛擋下來，而它完全正常。設 15% 留餘裕。
SUSPICIOUS_RATIO: Final[float] = 0.15


@dataclass
class CoverAdMute:
    index: int
    item_type: str
    page: object
    text: str
    signal: str         # "wrapper_page"


@dataclass
class CoverAdPlan:
    mutes: list[CoverAdMute]
    fired: bool
    reason: str                 # 沒開火的話，為什麼
    body_chars_before: int
    body_chars_after: int

    @property
    def ratio(self) -> float:
        b = self.body_chars_before
        return (b - self.body_chars_after) / b if b else 0.0

    @property
    def suspicious(self) -> bool:
        return self.ratio > SUSPICIOUS_RATIO

    def summary(self) -> str:
        """**沒開火也要報 0 項。** 數字不見的話，「這份沒有廣告頁」與「規則沒跑」
        在畫面上長得一模一樣（藍桶第 2 條）。
        """
        span = "有封面廣告頁" if self.fired else f"無封面廣告頁（{self.reason}）"
        return (f"封面廣告頁：消音 {len(self.mutes)} 項；{span}；"
                f"正文 {self.body_chars_before:,} → {self.body_chars_after:,} "
                f"（{self.ratio * 100:.2f}%）"
                + ("　⚠ 比例異常，請人工確認" if self.suspicious else ""))


def _text_of(item: dict) -> str:
    return (item.get("text") or "").strip()


def _on_wrapper_page(items: list[dict]) -> list[int]:
    return [i for i, it in enumerate(items)
            if it.get("page_idx") == WRAPPER_PAGE_IDX]


def plan(items: list[dict], *, claimed: Container[int] = frozenset()) -> CoverAdPlan:
    """算出要丟哪些項目。**只讀，不改 items。**

    Args:
        items: 整份文件的 `content_list.json`。
        claimed: 已經被別條消音規則認領的項目編號。**一定要傳。**
            三條規則消到同一項時 `_pp_original_text` 會被寫兩次、第二次存進去的
            是空字串，於是計數說消了兩項而還原只還原得了一項（`pp/apply.py`
            會直接拒絕整份）。這裡先讓開，不靠「記得不要重疊」。
    """
    def body_chars(skip: set[int]) -> int:
        return sum(len(_text_of(it)) for j, it in enumerate(items)
                   if it.get("type") in BODY_TYPES and j not in skip)

    before = body_chars(set())
    page = _on_wrapper_page(items)
    if not page:
        return CoverAdPlan([], False, f"沒有第 {WRAPPER_PAGE_IDX} 頁", before, before)

    if not any(AD_MARKERS.search(_text_of(items[i])) for i in page):
        return CoverAdPlan([], False, "第一頁沒有出版商招牌", before, before)

    longest = max((len(_text_of(items[i])) for i in page), default=0)
    if longest >= BODY_PARAGRAPH_MIN_CHARS:
        # ⚠ **不要因為「招牌字很明確」就放行。** 招牌字明確的那一頁正是有 807 字
        # 正文的那一份 —— 明確的招牌加上真正文，代表版面判斷錯了，不是廣告更明顯。
        return CoverAdPlan([], False, f"第一頁有 {longest} 字的長段落，不像廣告頁",
                           before, before)

    mutes = [CoverAdMute(index=i, item_type=str(items[i].get("type") or ""),
                         page=items[i].get("page_idx"), text=_text_of(items[i]),
                         signal="wrapper_page")
             for i in page if _text_of(items[i]) and i not in claimed]
    after = body_chars({m.index for m in mutes})
    logger.debug("封面廣告頁：消音 %d 項", len(mutes))
    return CoverAdPlan(mutes, True, "", before, after)


def apply_to_items(items: list[dict], plan_: CoverAdPlan) -> int:
    """就地消音。原文存進 `_pp_original_text` —— 還原時讀它，查帳時比對它。

    沿用 `layout_noise` 的鍵，所以 `layout_noise.revert_items` 還原得了它。
    本規則不碰 `list_items`，所以不需要自己的 revert。
    """
    n = 0
    for m in plan_.mutes:
        it = items[m.index]
        if it.get("text"):
            it["_pp_original_text"] = it["text"]
            it["text"] = ""
            n += 1
    return n
