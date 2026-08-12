r"""∂ 誤讀探針的判準。**這支之前一個測試都沒有** —— 血淚全寫在註解裡。

`scan-partial.py` 的註解記著兩代失敗換來的判斷（枚舉清單 → 白名單 → 上下同形），
但沒有任何東西守著它們。2026-08-12 抓到第一個真誤報之後補上這支：
每一條判準一個案例，改判準時它們會說話。

判準是「上下同形」：`∂p/∂z` 誤讀後分子分母會變成同一個 token，
而真的 c̄、ρ̄ 不會長成 `c̄x / c̄y`。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("scan_partial", ROOT / "scripts" / "scan-partial.py")
assert _spec and _spec.loader
sp = importlib.util.module_from_spec(_spec)
sys.modules["scan_partial"] = sp
_spec.loader.exec_module(sp)


def hits(latex: str) -> list[str]:
    """把一個 `\\frac{...}{...}` 丟進判準，回傳它認定的誤讀 token。"""
    m = sp.FRAC.search(latex)
    assert m, f"這串裡沒有 frac：{latex}"
    sides = sp.frac_sides(latex, m.end())
    assert sides, f"剖析不了：{latex}"
    return sp.hit_tokens(*sides)


def test_a_misread_derivative_is_a_hit() -> None:
    r"""正例：`∂p/∂n` 被讀成 `ô p / ô n` —— 上下同形，兩側都有被微分量。"""
    assert hits(r"\frac { \hat { o } \mathrm { p } } { \hat { o } \mathrm { n } }") \
        == [r"\hat{o}"]


def test_a_second_derivative_is_still_a_hit() -> None:
    r"""正例：`∂²/∂t²`。分子是 `ô^2`，後面接的是次方不是被微分量 —— 仍然是算子。

    （`canon` 的說明寫著上標要剝：`∂²` 寫成 `\hat{\sigma}^{2}` 是同一個算子。）
    """
    assert hits(r"\frac { \hat { o } ^ { 2 } } { \hat { o } \mathrm { t } ^ { 2 } }") \
        == [r"\hat{o}"]


def test_a_bare_operator_over_dt_is_a_hit() -> None:
    r"""**正例，而且是最常見的寫法**：`∂/∂t`，被微分的量寫在分數外面。

    ⚠ 2026-08-12 我第一版把判準寫成「**兩側**都要有被微分量」，
    當場殺掉 20 處這個形狀的真誤讀（只留下 41／62）。

    判準是**不對稱**的：分母一定有被微分量（∂t、∂x_i、∂n），分子可以只有算子。
    """
    assert hits(r"\frac { \hat { o } } { \hat { o } \mathbf { t } }") == [r"\hat{o}"]


def test_favre_averaging_is_not_a_derivative(tmp_path: Path) -> None:
    r"""**這是 2026-08-12 抓到的第一個真誤報。**

    `N Flow Acoustics` 第 149 項：

        f̃ᶠ = (ρ̄ f̄) / ρ̄      「filtered part of f」

    那是**密度加權平均（Favre averaging）的定義式**，ρ̄ 是真的平均密度。
    上下同形成立（兩側都是 ρ̄），所以舊判準把它當成誤讀 —— 而改掉它就是毀資料。

    分辨的關鍵：**真導數的兩側都有被微分量**（`∂p` 對 `∂n`），
    而這裡分母只有孤零零一個 ρ̄，後面什麼都沒有。

    ⚠ 探針的說明寫著「對今天的合法符號誤報 0」—— 那句話在 2026-08-12 之後
    不再成立，這支測試就是那個反例。
    """
    latex = (r"\frac { \overline { { { \rho } } } \overline { { { \bf f } } } } "
             r"{ \overline { { { \rho } } } }")
    assert hits(latex) == [], "把 Favre 平均的定義式當成 ∂ 了"


def test_a_named_ratio_with_subscripts_is_not_a_hit() -> None:
    r"""控制組：`ρ̃_ss / ρ̃_ff` 是 Biot 參數的比值，不是導數。

    2026-08-03 的血淚：剝下標會讓這兩個變成同一個 token，
    **那一個錯誤就製造了 15 處誤報中的 13 處**。改判準時最容易把它弄回來。
    """
    assert hits(r"\frac { \tilde { \rho } _ { ss } } { \tilde { \rho } _ { ff } }") == []


def test_different_tokens_on_each_side_are_not_a_hit() -> None:
    r"""控制組：上下不同形就不是這條規則的事。

    （同一個 ∂ 在同一行被讀成兩個不同字母是真的存在 —— `σ̂p / ĉn` ——
    但那要另一條規則抓，不能靠放寬這一條。放寬會把真的比值一起吃進來。）
    """
    assert hits(r"\frac { \hat { \sigma } \mathrm { p } } { \hat { c } \mathrm { n } }") == []
