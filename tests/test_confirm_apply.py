"""人勾的「這段不要」，要真的被消音。

⚠ 沒有這一層的話，確認清單是**假的**：人勾完、畫面說存好了、抽取照樣把那幾段
送進去。那比沒有確認清單更糟 —— 人以為自己做了決定。

做法刻意是「把人勾的那幾項從 `held` 搬進 `mutes`」，而不是另外寫一條消音路徑：
搬過去之後就走既有的 `apply_to_items`，還原（`_pp_original_text`）、計數、
守衛全部一致。**同一件事不要有兩條路。**
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from pp.confirm_apply import honour  # noqa: E402


@dataclass
class Row:
    index: int


@dataclass
class Plan:
    mutes: list
    held: list


def _plans() -> tuple[Plan, Plan]:
    noise = Plan(mutes=[Row(3)], held=[Row(41), Row(42)])
    title = Plan(mutes=[Row(0)], held=[Row(1)])
    return noise, title


def test_what_the_person_ticked_gets_muted() -> None:
    """人勾了 noise:41 → 它要從「待決定」變成「要消掉」。"""
    noise, title = _plans()

    moved = honour(noise, title, {"noise:41"})

    assert moved == 1
    assert [m.index for m in noise.mutes] == [3, 41]
    assert [h.index for h in noise.held] == [42], "搬走的不能還留在待決定裡"


def test_what_the_person_left_alone_stays_out_of_the_way() -> None:
    """沒勾的**維持原狀**（＝留著）。這是 PO 第三條：不確定的留著。"""
    noise, title = _plans()

    honour(noise, title, set())

    assert [m.index for m in noise.mutes] == [3], "沒勾的不能被消掉"
    assert len(noise.held) == 2


def test_both_sections_are_honoured() -> None:
    """兩段各有各的 index，**要靠 `section:index` 分辨**。

    只看 index 的話，`noise:1` 與 `title:1` 會撞在一起，勾了一個消掉兩個。
    """
    noise, title = _plans()

    moved = honour(noise, title, {"noise:41", "title:1"})

    assert moved == 2
    assert [m.index for m in title.mutes] == [0, 1]
    assert title.held == []


def test_a_key_that_matches_nothing_is_reported_not_swallowed() -> None:
    """勾的東西找不到對應項目 → **要講出來**，不要安靜忽略。

    這會發生在重新解析之後：紀錄是舊的、項目換了。安靜忽略的話，人的決定
    無聲消失（藍桶第 2 條），而且畫面上什麼都看不出來。
    """
    noise, title = _plans()

    moved, missing = honour(noise, title, {"noise:41", "noise:999"}, report_missing=True)

    assert moved == 1
    assert missing == ["noise:999"]


def test_running_it_twice_does_not_double_count() -> None:
    """同一份跑兩次 apply 不能把同一項算兩次。

    `pp/apply.py` 本來就可以重跑（協調者會重試），而 `_pp_original_text`
    只記第一次 —— 重複搬會讓計數說謊。
    """
    noise, title = _plans()

    first = honour(noise, title, {"noise:41"})
    second = honour(noise, title, {"noise:41"})

    assert (first, second) == (1, 0)
    assert [m.index for m in noise.mutes] == [3, 41]
