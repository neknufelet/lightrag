"""印在頁面左右邊緣的字，整條丟掉 —— 位置就是答案。

`layout_noise` 那條「頁眉頁尾看位置不看重複次數」的**橫向版本**。PO 2026-08-18
指著 Annual Reviews 那頁的左緣說：

    「第二章左邊也是屬於外面的，可以全部裁掉吧，感覺邊界上的都沒甚麼用」

那條字是直排的下載聲明（`Annu. Rev. Mater. Res. 2017.47:83-114. Downloaded from
www.annualreviews.org. Access provided by Columbia University…`）。它整份只出現
一次、每頁換一個字串，所以永遠過不了「重複夠多次」那道門檻 —— **但它就在正文
框外面**。

## 量到的（dker 全母體 319 份，2026-08-18）

    要人看的 248 項裡 46 項完全落在正文左右緣之外
    誤傷試算：全庫 28,934 段正文型別的段落，落在框外的 80 段

那 80 段**逐段看過**：MDPI 的版權宣告、`Received／Revised／Accepted` 日期、
`Academic Editor`、作者單位、期刊標籤（`acoustics`／`Article`／`Review`／`OPEN`／
`CrossMark`）、掃壞的字（`Chdpte 1`／`wwwwoorg`／`Aps hds prs`）。
**沒有一段是聲學內容。**

⚠ **判準是「整個盒子都在框外」**，不是「起點在框外」。後者會把首行縮排、公式
編號那種正常凸出去一點的東西一起吃掉，而那不會有任何錯誤訊息。
"""
from __future__ import annotations

import logging
import sys
from collections.abc import Container
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pp.rules import layout_noise

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from mineru_common import BODY_TYPES  # noqa: E402

logger = logging.getLogger(__name__)

#: 消掉超過這個比例就要人看一眼。
#:
#: 門檻是量出來的：dker 全母體 319 份實跑 2026-08-18，這條規則在 18 份上消到
#: 東西，**比例最高 1.31%**（`2022 - Broadband impedance modulation`）。設 5%
#: —— 比實測最高值高一個數量級，但一旦某份文件被消掉二十分之一的正文就會叫。
#: ⚠ **不要設成 10% 那種「反正過得了」的數字**：門檻遠高於實測值等於沒有門檻。
SUSPICIOUS_RATIO: Final[float] = 0.05


@dataclass
class MarginMute:
    index: int
    item_type: str
    page: object
    text: str
    signal: str         # "left_margin" | "right_margin"


@dataclass
class MarginPlan:
    mutes: list[MarginMute]
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
        """**沒開火也要報 0 項**（藍桶第 2 條）。"""
        span = "量得出正文框" if self.fired else f"沒開火（{self.reason}）"
        by: dict[str, int] = {}
        for m in self.mutes:
            by[m.signal] = by.get(m.signal, 0) + 1
        detail = "、".join(f"{k} {n}" for k, n in sorted(by.items())) or "無"
        return (f"頁面邊緣：消音 {len(self.mutes)} 項（{detail}）；{span}；"
                f"正文 {self.body_chars_before:,} → {self.body_chars_after:,} "
                f"（{self.ratio * 100:.2f}%）"
                + ("　⚠ 比例異常，請人工確認" if self.suspicious else ""))


def _text_of(item: dict) -> str:
    return (item.get("text") or "").strip()


def side_of(item: dict, left: float, right: float) -> str | None:
    """這一項在框的哪一邊。**整個盒子都要在外面**，否則回 None。"""
    box = item.get("bbox") or []
    if len(box) < 4:
        # 沒有座標就沒有位置可以判。**不判**，留給人看 —— 這條規則的全部把握
        # 都來自位置，沒有位置就沒有把握。
        return None
    if box[2] <= left:
        return "left_margin"
    if box[0] >= right:
        return "right_margin"
    return None


def plan(items: list[dict], *, claimed: Container[int] = frozenset()) -> MarginPlan:
    """算出要丟哪些項目。**只讀，不改 items。**

    Args:
        items: 整份文件的 `content_list.json`。
        claimed: 已經被別條消音規則認領的項目編號。**一定要傳** ——
            消到同一項時 `_pp_original_text` 會被寫兩次、第二次存的是空字串，
            `pp/apply.py` 會直接拒絕整份。
    """
    def body_chars(skip: set[int]) -> int:
        return sum(len(_text_of(it)) for j, it in enumerate(items)
                   if it.get("type") in BODY_TYPES and j not in skip)

    before = body_chars(set())
    left, right = layout_noise.body_hband(items)
    if left is None or right is None:
        # ⚠ **量不出來就不要猜。** 猜一條邊界的後果是把正文當版面消掉，
        # 而那不會有任何錯誤訊息（同 `layout_noise.body_band` 的理由）。
        return MarginPlan([], False, "正文段落太少，量不出正文框", before, before)

    mutes = []
    for i, it in enumerate(items):
        if i in claimed or not _text_of(it):
            continue
        side = side_of(it, left, right)
        if side:
            mutes.append(MarginMute(index=i, item_type=str(it.get("type") or ""),
                                    page=it.get("page_idx"), text=_text_of(it),
                                    signal=side))
    after = body_chars({m.index for m in mutes})
    logger.debug("頁面邊緣：正文框 %s..%s，消音 %d 項", left, right, len(mutes))
    return MarginPlan(mutes, True, "", before, after)


def apply_to_items(items: list[dict], plan_: MarginPlan) -> int:
    """就地消音。原文存進 `_pp_original_text` —— 還原時讀它，查帳時比對它。

    沿用 `layout_noise` 的鍵，所以 `layout_noise.revert_items` 還原得了它。
    """
    n = 0
    for m in plan_.mutes:
        it = items[m.index]
        if it.get("text"):
            it["_pp_original_text"] = it["text"]
            it["text"] = ""
            n += 1
    return n
