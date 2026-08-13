r"""收斂列的三個數字：**數的是「幾種」就不能拿「幾次」來數**。

2026-08-14 PO 看畫面問「新型態 9 種，跟旁邊的『152 份之前』不是矛盾嗎」。
兩個數字都對，錯的是標籤：

```
畫面寫   新型態 9 種（最近 20 筆內）
實際是   9 **次**事件、只有 2 **種**型態；而那個 20 是顯示上限不是時間窗口
```

於是它讀起來像「最近 20 份文件裡冒出 9 種新型態」，跟「最近一次在 152 份之前」
正面衝突。**同一頁的兩個數字互相矛盾而沒有東西會發現** —— 這支的程式碼註解
早就寫過同一句話（舊版「已處理」也曾兩邊各算一次）。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import intake  # noqa: E402

# 取自 dker 上 `intake/teaching-events.jsonl` 的真實形狀（2026-08-14）：
# 9 筆事件、兩種 reason。
REAL = {
    "processed": 259,
    "event_kinds": ["參考文獻消音比例異常", "頁面尺寸不一致"],
    "event_occurrences": 9,
    "distance_since_last_event": 152,
}


def _html(**over: object) -> str:
    return intake._render_convergence({**REAL, **over}, {})


def test_the_headline_number_counts_kinds_not_occurrences() -> None:
    """**本檔的理由。** 標題數字是「幾種」，所以要是 2 不是 9。"""
    html = _html()
    assert "<div class='v'>2</div>" in html, html[html.find("新型態"):][:200]


def test_the_occurrence_count_is_still_shown() -> None:
    """次數不能消失（藍桶第 2 條）—— 它換了位置，不是被丟掉。"""
    assert "共 9 次" in _html()


def test_the_window_claim_is_gone() -> None:
    """**控制組。** 「最近 20 筆內」是假的窗口，那個 20 是顯示上限。

    留著它，讀者會把一個累計數當成近期數，而那正是 PO 當場撞到的矛盾。
    """
    assert "最近 20 筆內" not in _html()


def test_a_small_sample_still_refuses_to_talk_about_convergence() -> None:
    """既有行為不能被我改壞：樣本太小就明說太小，不談收斂。"""
    assert "樣本還太小" in _html(processed=3)


def test_no_events_reads_as_covered() -> None:
    """一次都沒出現過 ≠ 出現過但很久沒出現。兩句話要不一樣。"""
    html = _html(event_kinds=[], event_occurrences=0)
    assert "沒有出現新型態" in html


# ── 型態的識別字裡不能有量測值 ────────────────────────────────────────────


def test_the_same_kind_with_different_measurements_is_one_kind() -> None:
    """**同一種型態量到不同數字，不是兩種型態。**

    2026-08-14 實機撞到：畫面顯示 3 種，實際只有 2 種 —— 因為兩筆的 `reason`
    是 `參考文獻消音比例異常（31.6%）` 與 `（49.0%）`，字串不同。
    ⚠ 這是專案反覆出現的同一個病：把會變的量測值塞進識別字裡。
    """
    a = intake._event_kind({"reason": "參考文獻消音比例異常（31.6%）"})
    b = intake._event_kind({"reason": "參考文獻消音比例異常（49.0%）"})
    assert a == b == "參考文獻消音比例異常"


def test_a_kind_without_numbers_is_left_alone() -> None:
    """**控制組。** 只剝尾端帶數字的括號，別的一個字都不准動。"""
    assert intake._event_kind({"reason": "頁面尺寸不一致"}) == "頁面尺寸不一致"
    assert intake._event_kind({"reason": "未知型別 foo, bar"}) == "未知型別 foo, bar"


def test_an_internal_parenthesis_is_not_stripped() -> None:
    """句中的括號不是量測值尾巴，剝掉會改變型態的意思。"""
    assert intake._event_kind({"reason": "頁序錯位（第 3 頁）之後還有內容"}) == \
        "頁序錯位（第 3 頁）之後還有內容"
