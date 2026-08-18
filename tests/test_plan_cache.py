"""算過的計畫記起來，檔案沒變就不重算。

2026-08-18 PO 實際感覺到：「為什麼覺得登入網路的反應變好慢」——因為
「還有幾份要確認」這個數字被加進審核台首頁，而它每次都要重算全部 317 份的
處理計畫。dker 實測 **4.71 秒**，跟頁面變慢的秒數一模一樣。

⚠ 之前的碼裡刻意寫著「不做快取，因為快取要處理失效」。那個判斷在**只有
確認清單那一頁會用到**的前提下是對的；一旦它上了首頁，前提就變了。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from pp.plan_cache import PlanCache  # noqa: E402

A = Path("/x/a.mineru_raw")
B = Path("/x/b.mineru_raw")


def test_the_same_unchanged_file_is_only_computed_once() -> None:
    """同一份、檔案沒變 → 只算一次。這就是省下那 4.7 秒的地方。"""
    cache, calls = PlanCache(), []

    for _ in range(3):
        cache.get(A, (111, 222), lambda: (calls.append(1), {"doc": "a"})[1])

    assert len(calls) == 1


def test_a_changed_file_is_computed_again() -> None:
    """檔案變了就重算 —— **這是快取唯一可以接受的失效方式**。

    用「改動時間 ＋ 大小」當指紋，不用檔名。只看檔名的話，重新解析同一份文件
    之後畫面會給人看舊的清單，而人完全不會發現。
    """
    cache, calls = PlanCache(), []

    def compute() -> dict:
        calls.append(1)
        return {"n": len(calls)}

    first = cache.get(A, (111, 222), compute)
    second = cache.get(A, (999, 222), compute)          # 改動時間變了

    assert len(calls) == 2
    assert first != second, "回的必須是重算後的，不是舊的"


def test_size_alone_is_enough_to_invalidate() -> None:
    """大小變了也要重算 —— 有些檔案系統的時間戳解析度很粗，同一秒內改兩次
    只靠時間戳看不出來。兩個一起看才擋得住。
    """
    cache, calls = PlanCache(), []
    cache.get(A, (111, 222), lambda: (calls.append(1), {})[1])
    cache.get(A, (111, 333), lambda: (calls.append(1), {})[1])

    assert len(calls) == 2


def test_different_files_do_not_share_an_entry() -> None:
    """兩份不同的文件各記各的。撞在一起的話畫面會拿 A 的清單去問 B。"""
    cache = PlanCache()

    cache.get(A, (1, 1), lambda: {"doc": "a"})
    cache.get(B, (1, 1), lambda: {"doc": "b"})

    assert cache.get(A, (1, 1), lambda: {"不該被叫到": True}) == {"doc": "a"}
    assert cache.get(B, (1, 1), lambda: {"不該被叫到": True}) == {"doc": "b"}


def test_files_that_went_away_stop_taking_up_room() -> None:
    """不見的檔案要從快取裡清掉。

    ⚠ 這一條是為了**整顆碟被清空**那天 —— 舊庫刪掉之後，快取如果還抱著 317 份
    的計畫，畫面就會繼續顯示已經不存在的文件。
    """
    cache = PlanCache()
    cache.get(A, (1, 1), lambda: {"doc": "a"})
    cache.get(B, (1, 1), lambda: {"doc": "b"})

    cache.keep_only({A})

    assert cache.size == 1
    calls: list[int] = []
    cache.get(B, (1, 1), lambda: (calls.append(1), {"doc": "b"})[1])
    assert calls == [1], "被清掉的那份要重算"
