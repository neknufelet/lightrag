r"""Tier B 的排序：**證據強度優先於相似度**。

2026-08-13 實跑全庫（229 份、8680 條），Tier B 係數不一致 465 對的常數個數分佈：

```
   0 個常數 :  132 對
   1 個常數 :  299 對      ← 431/465（93%）在這兩格
   2 個常數 :   24 對
   3 個常數 :    6 對
   4 個常數 :    1 對
   5 個常數 :    3 對
```

**只按相似度排的話，前排全被那 93% 佔滿。** 而 08-12 手動驗收過的那條
（Maa 微穿孔板電阻，五個常數只差最後一位 `32` vs `8`）相似度只有 0.897，
排在一堆「只有一個數字對不上」的 0.98 後面 —— 而那些一個數字的匹配，
根本分不清是同一條公式的係數分歧，還是兩條不同的公式碰巧長得像。

⇒ 排序鍵改成 `(係數一致, -常數個數, -相似度)`。

⚠ **常數個數取兩邊的小值。** 一邊 5 個、一邊 1 個不是強證據 —— 只有 1 個位置
可比，而且長度不同本身就說明它們可能不是同一條。取大值會把這種弱匹配捧上來。

⚠ **這只改排序，不改判準。** 465 對一條都沒少（BASELINE 第 2 條），
`--min-ratio` 仍然是排序起點不是門檻。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

_spec = importlib.util.spec_from_file_location("eq_dup", ROOT / "scripts" / "eq-dup.py")
assert _spec and _spec.loader
eqdup = importlib.util.module_from_spec(_spec)
sys.modules["eq_dup"] = eqdup
_spec.loader.exec_module(eqdup)

from pp.eqkey import constants, skeleton  # noqa: E402

# ── 素材全部取自 dker 上的 `content_list.json` 原文，不是改寫的 ──────────────

# 強證據：五個常數、只差最後一位。**這是 08-12 手動查到、08-12 自動抓到的驗收案例。**
STRONG_A = (r"$$ r _ { s p } = \frac { 3 2 \mu h } { \rho _ { 0 } c _ { 0 } \sigma \eta d ^ { 2 } }"
            r" k _ { r } , k _ { r } = \sqrt { 1 + \frac { \chi ^ { 2 } } { 3 2 } }"
            r" + \frac { \sqrt { 2 } } { 3 2 } \frac { \chi d } { h } ,\tag{11a} $$")
STRONG_B = (r"$$ \mathrm { Here } { : } \quad R = \frac { 3 2 \mu t _ { 1 } }"
            r" { \delta c d _ { 1 } ^ { 2 } } \left( \sqrt { 1 + \frac { k _ { 1 } ^ { 2 } } { 3 2 } }"
            r" + \frac { \sqrt { 2 } } { 8 } k _ { 1 } \frac { d _ { 1 } } { t _ { 1 } } \right)"
            r" \rho _ { 0 } c _ { 0 } ,\tag{11} $$")

# 弱證據：只有一個常數（`64` vs `4`），但相似度比上面那對還高。
# **改排序之前，這一對排在報告第一名。**
WEAK_A = ("$$\n\\rho _ { \\mathrm { eq } } = \\rho _ { 0 } \\frac { \\nu w _ { i } ^ { 2 } a ^ { 2 } }"
          " { 6 4 i \\omega } \\left\\{ \\sum _ { k = 0 } ^ { \\infty } \\sum _ { n = 0 } ^ { \\infty }"
          " \\bigg [ \\alpha _ { k } ^ { 2 } \\beta _ { k } ^ { 2 } \\bigg ( \\alpha _ { k } ^ { 2 }"
          " + \\beta _ { k } ^ { 2 } + \\frac { i \\omega } { \\nu } \\bigg ) \\bigg ] ^ { - 1 }"
          " \\right\\} ^ { - 1 } ,\\tag{7}\n$$")
WEAK_B = ("$$\n\\rho _ { i } ^ { e } = \\rho _ { 0 } \\frac { \\nu a ^ { 2 } d ^ { 2 } }"
          " { 4 j \\omega } \\left\\{ \\sum _ { m = 0 } ^ { \\infty } \\sum _ { n = 0 } ^ { \\infty }"
          " \\left[ \\alpha _ { m } ^ { 2 } \\beta _ { n } ^ { 2 } \\bigg ( \\alpha _ { m } ^ { 2 }"
          " + \\beta _ { n } ^ { 2 } + \\frac { j \\omega } { \\nu } \\bigg ) \\right] ^ { - 1 }"
          " \\right\\} ^ { - 1 } ,\\tag{5}\n$$")


def _eq(doc: str, item: int, latex: str) -> dict:
    """`collect()` 產出的那個形狀 —— 一份文件一個來源，這樣才會跨來源配對。"""
    return {"doc": doc, "item": item, "latex": latex, "skeleton": skeleton(latex),
            "nums": constants(latex), "source": f"doc:{doc}"}


CORPUS = [
    _eq("strong-a", 1, STRONG_A), _eq("strong-b", 2, STRONG_B),
    _eq("weak-a", 3, WEAK_A), _eq("weak-b", 4, WEAK_B),
]


def test_the_material_is_what_the_docstring_says() -> None:
    """先確認素材本身沒被我看錯 —— 弱的那對相似度**比較高**，這才是問題所在。"""
    from difflib import SequenceMatcher

    def ratio(x: str, y: str) -> float:
        return SequenceMatcher(None, skeleton(x), skeleton(y), autojunk=False).ratio()

    assert constants(STRONG_A) == ["32", "1", "32", "2", "32"], constants(STRONG_A)
    assert constants(STRONG_B) == ["32", "1", "32", "2", "8"], constants(STRONG_B)
    assert constants(WEAK_A) == ["64"], constants(WEAK_A)
    assert constants(WEAK_B) == ["4"], constants(WEAK_B)
    assert ratio(WEAK_A, WEAK_B) > ratio(STRONG_A, STRONG_B), (
        "弱的那對相似度不再比較高 —— 這個測試就失去意義了，換素材")


def test_five_constants_outrank_one_constant() -> None:
    """**這條是本檔的理由。** 五個常數只差一位，要排在一個常數之前。"""
    pairs = eqdup.tier_b(CORPUS, 0.80)
    disagree = [p for p in pairs if not p["constants_agree"]]
    docs = [(p["a"]["doc"], p["b"]["doc"]) for p in disagree]
    assert ("strong-a", "strong-b") in docs, f"驗收案例整個沒被撈到：{docs}"
    assert ("weak-a", "weak-b") in docs, f"弱匹配整個沒被撈到：{docs}"
    assert docs.index(("strong-a", "strong-b")) < docs.index(("weak-a", "weak-b")), (
        f"五個常數的強匹配排在一個常數的弱匹配後面：{docs}")


def test_agreeing_pairs_still_sort_after_disagreeing_ones() -> None:
    """原本的第一順位不能被擠掉：**係數不一致的永遠排在前面。**"""
    pairs = eqdup.tier_b(CORPUS, 0.80)
    agree_flags = [p["constants_agree"] for p in pairs]
    assert agree_flags == sorted(agree_flags), agree_flags


def test_a_lopsided_pair_is_not_treated_as_strong() -> None:
    """一邊 5 個常數、一邊 1 個 —— 只有一個位置可比，不算強證據。

    取大值的話這種配對會被捧到前排，而它比「兩邊都 1 個」更可疑不是更可信。
    """
    lopsided = {"a": {"nums": ["32", "1", "32", "2", "32"]}, "b": {"nums": ["4"]}}
    both_weak = {"a": {"nums": ["64"]}, "b": {"nums": ["4"]}}
    assert eqdup.pair_evidence(lopsided) == eqdup.pair_evidence(both_weak) == 1
