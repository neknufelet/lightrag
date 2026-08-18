"""要人確認的那一段，前後長什麼樣。

**為什麼需要它**：PO 2026-08-18 看著畫面說「只出現一行字就要我確認，這是什麼，
我有點搞不太清楚」。他是對的 —— 給一段孤立的文字問「這是頁眉嗎」，人沒有辦法
判斷。做了一張帶前後文的對照表給他看過之後，PO 裁：**留上下文**。

⚠ 為什麼這個判斷特別重要：全庫實測，要人看的 1053 個「頁首頁尾」裡有 **867 個
（82%）整份只出現一次**。那類看起來像這樣 ——

    'Reverberation and steady-state energy density'   ← 其實是章節標題
    'DOI:10.1201/9781003389873-6'                     ← 這個才真的是頁尾

**兩者差別只看得出來，如果你看得到它前後是什麼。**
"""
from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence

from pp.rules.reference_section import display_text

logger = logging.getLogger(__name__)

#: 前後各取幾段。**折衷**：一段常常還是看不出來（前一段可能也是標題），
#: 三段以上畫面就被前後文淹掉、真正要判斷的那一項反而不明顯。
DEFAULT_SPAN = 2


def _one(item: Mapping[str, object]) -> str:
    """一段的文字。**沒有文字就講出來，不要留空洞。**

    留空的話人會以為那裡本來就什麼都沒有，而實際上可能是圖、表，
    或是被上一輪消音清掉的東西。
    """
    text = display_text(dict(item)).strip()
    if text:
        return text
    return f"（{item.get('type') or '不明型別'}，沒有文字）"


def around(items: Sequence[Mapping[str, object]], index: int,
           span: int = DEFAULT_SPAN) -> tuple[list[str], list[str]]:
    """這一項前後各 ``span`` 段的文字。

    Args:
        items: 解析結果（``content_list.json`` 的內容）。
        index: 這一項在裡面是第幾個。
        span: 前後各取幾段。

    Returns:
        ``(前面幾段, 後面幾段)``。**檔頭檔尾不繞回去** —— 繞回去的話，人會看到
        文件最後一段被當成「前面那段」，而且完全看不出是錯的。

    ⚠ 編號超出範圍就回兩個空的，不丟例外。這會發生在**重新解析之後**：
    計畫是舊的、內容是新的。畫面少一塊上下文可以接受，整頁掛掉不行。
    """
    if not 0 <= index < len(items):
        logger.debug("第 %d 項不在範圍內（共 %d 項），沒有上下文可給", index, len(items))
        return [], []
    before = [_one(it) for it in items[max(0, index - span):index]]
    after = [_one(it) for it in items[index + 1:index + 1 + span]]
    return before, after
