"""「還有哪幾份要確認、現在輪到哪一份」——確認清單的排隊。

PO 2026-08-17 第二條：一份一份，做到哪算到哪，關掉再回來從下一份接著。
這一層只回答順序，不碰檔案、不算計畫，所以在 coder 上就驗得完。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from pp.confirm_queue import next_after, pending, position_of  # noqa: E402

DOCS = ["c.pdf", "a.pdf", "b.pdf"]


def test_the_order_never_moves_between_page_loads() -> None:
    """排隊順序**必須穩定**，否則「第 12 / 165 份」是騙人的。

    ⚠ 用檔名排序，不用檔案系統給的順序 —— `glob` 的順序沒有保證，換一台機器
    或多一個檔就可能不一樣。順序一變，人重新整理一次就看到自己「倒退」了。
    """
    assert pending(DOCS, recorded=set()) == ["a.pdf", "b.pdf", "c.pdf"]
    assert pending(list(reversed(DOCS)), recorded=set()) == ["a.pdf", "b.pdf", "c.pdf"]


def test_what_is_already_done_drops_out_of_the_queue() -> None:
    """確認過的就不再排隊 —— 這就是「確認一份、放行一份」的一半。"""
    assert pending(DOCS, recorded={"a.pdf"}) == ["b.pdf", "c.pdf"]
    assert pending(DOCS, recorded=set(DOCS)) == []


def test_position_is_counted_from_one_because_people_read_it() -> None:
    """「第 0 份」沒有人看得懂。這個數字是給人看的，不是陣列索引。"""
    queue = pending(DOCS, recorded=set())

    assert position_of("a.pdf", queue) == 1
    assert position_of("c.pdf", queue) == 3


def test_a_document_that_is_not_queued_reports_zero_not_a_crash() -> None:
    """已經確認過的那份被重新整理到 —— 回 0，不要炸掉。

    人按了「存起來，下一份」之後按瀏覽器的上一頁，就會走到這裡。
    炸掉的話他會以為自己把東西弄壞了。
    """
    assert position_of("已經做完.pdf", pending(DOCS, recorded=set())) == 0


def test_skipping_lands_on_the_next_one_not_back_at_the_start() -> None:
    """「跳過這份」要落在下一份，不是回到第一份。

    回到開頭的話，被跳過的那份永遠排在前面，人會一直看到同一份。
    """
    queue = pending(DOCS, recorded=set())

    assert next_after("a.pdf", queue) == "b.pdf"
    assert next_after("b.pdf", queue) == "c.pdf"


def test_the_last_one_says_there_is_no_next() -> None:
    """做到最後一份要回 None，讓畫面講「做完了」而不是繞回開頭。"""
    queue = pending(DOCS, recorded=set())

    assert next_after("c.pdf", queue) is None
    assert next_after("不在隊伍裡.pdf", queue) is None
