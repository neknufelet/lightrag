"""要人確認的那一段，前後長什麼樣。

PO 2026-08-18 看著畫面說「只出現一行字就要我確認，這是什麼，我有點搞不太清楚」
—— 他是對的。給一段孤立的文字問「這是頁眉嗎」，人沒有辦法判斷。
看過前後文對照之後 PO 裁：**留上下文**。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from pp.confirm_context import around  # noqa: E402

ITEMS = [
    {"type": "text", "text": "第 0 段"},
    {"type": "text", "text": "第 1 段"},
    {"type": "text", "text": "第 2 段"},
    {"type": "text", "text": "第 3 段"},
    {"type": "text", "text": "第 4 段"},
]


def test_it_gives_what_comes_before_and_after() -> None:
    """前後各兩段。**兩段是量出來的折衷**：一段常常還是看不出來
    （前一段可能也是標題），三段以上畫面就被前後文淹掉了。
    """
    before, after = around(ITEMS, 2, span=2)

    assert before == ["第 0 段", "第 1 段"]
    assert after == ["第 3 段", "第 4 段"]


def test_the_first_item_does_not_borrow_from_nowhere() -> None:
    """第 0 項前面沒有東西 —— 回空的，不要繞到結尾去拿。

    繞回去的話，人會看到文件最後一段被當成「前面那段」，而且完全看不出是錯的。
    """
    before, after = around(ITEMS, 0, span=2)

    assert before == []
    assert after == ["第 1 段", "第 2 段"]


def test_the_last_item_is_the_same_story() -> None:
    """最後一項後面也沒有東西。"""
    before, after = around(ITEMS, 4, span=2)

    assert before == ["第 2 段", "第 3 段"]
    assert after == []


def test_an_index_that_is_out_of_range_gives_nothing_instead_of_crashing() -> None:
    """編號超出範圍就回空的，不要炸。

    ⚠ 這會發生在**重新解析之後**：計畫是舊的、內容是新的，編號可能指到範圍外。
    畫面少一塊上下文可以接受，整頁掛掉不行。
    """
    assert around(ITEMS, 99) == ([], [])
    assert around([], 0) == ([], [])


def test_a_reference_list_still_shows_its_words() -> None:
    """參考清單的型別是 `list`，內容在 `list_items` 裡而 `text` 是空的。

    ⚠ 用既有的 `reference_section.display_text` —— 這個坑這個碼庫踩過兩次
    （`item_chars` 只數 text 報出假比例；`refs.mute` 少 text 讓 382 段變空白）。
    第三次還自己寫一份就太過分了。
    """
    items = [{"type": "list", "text": "", "list_items": ["[1] Toole 1986.", "[2] Olive 2004."]},
             {"type": "text", "text": "正文"}]

    before, _ = around(items, 1, span=1)

    assert "Toole" in before[0]


def test_an_empty_neighbour_says_so_rather_than_leaving_a_hole() -> None:
    """前後那段是空的（圖片、已被消音）要**講出來**，不要留一個看不出來的空洞。

    留空的話，人會以為那裡本來就什麼都沒有 —— 而實際上可能是被上一輪消音清掉的。
    """
    items = [{"type": "image", "text": ""}, {"type": "text", "text": "這一段"}]

    before, _ = around(items, 1, span=1)

    assert before == ["（image，沒有文字）"]
