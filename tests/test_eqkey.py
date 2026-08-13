r"""公式的「骨架 ＋ 常數序列」：把同一條公式從不同論文裡認出來。

**這支解決的問題**（2026-08-12 手動做過一次）：同一條 Maa 的微穿孔板電阻公式
出現在庫裡三篇論文，其中一篇的係數差了 4 倍：

```
2017 - Optimal sound-absorbing structures #148
  k_r = [1 + k²/32]^{1/2} + (√2/32)·k·(l/t)
2020 - Ultra-broadband acoustic absorption #87
  k_r = √(1 + χ²/32) + (√2/32)·(χd/h)
2026 - Low-frequency broadband absorber #104
  R = 32μt₁/(δcd₁²)(√(1+k₁²/32) + (√2/8)·k₁·(d₁/t₁))·ρ₀c₀     ← √2/8
```

**三篇的變數名字完全不同**（k／χ／k₁、l／d／d₁、t／h／t₁），所以比對鍵不能靠名字。
做法：把變數抹成 `#`、把數字抽進一個序列，**骨架用來認「是同一條」，
常數序列用來看「哪一位差開」**。

⚠ 常數**必須**移出骨架。留在裡面的話 `√2/32` 與 `√2/8` 會被判成兩條不同的公式，
正好違背這支存在的理由。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from pp.eqkey import constants, skeleton  # noqa: E402

# 三條都取自 dker 上的原文（`content_list.json`），不是我改寫的。
MAA_2017 = (r"$$ r = \frac { 3 2 \eta _ { 0 } t } { \sigma \rho _ { 0 } \nu _ { 0 } l } k _ { r } ,"
            r" k _ { r } = \left[ 1 + \frac { k ^ { 2 } } { 3 2 } \right] ^ { 1 / 2 }"
            r" + \frac { \sqrt { 2 } } { 3 2 } k \frac { l } { t } , $$")
MAA_2020 = (r"$$ r _ { s p } = \frac { 3 2 \mu h } { \rho _ { 0 } c _ { 0 } \sigma \eta d ^ { 2 } }"
            r" k _ { r } , k _ { r } = \sqrt { 1 + \frac { \chi ^ { 2 } } { 3 2 } }"
            r" + \frac { \sqrt { 2 } } { 3 2 } \frac { \chi d } { h } ,\tag{11a} $$")
MAA_2026 = (r"$$ \mathrm { Here } { : } \quad R = \frac { 3 2 \mu t _ { 1 } }"
            r" { \delta c d _ { 1 } ^ { 2 } } \left( \sqrt { 1 + \frac { k _ { 1 } ^ { 2 } } { 3 2 } }"
            r" + \frac { \sqrt { 2 } } { 8 } k _ { 1 } \frac { d _ { 1 } } { t _ { 1 } } \right)"
            r" \rho _ { 0 } c _ { 0 } ,\tag{11} $$")


def test_the_three_papers_are_near_matches_not_exact() -> None:
    """**三條的骨架不完全相同 —— 而那是對的，它們真的不一樣。**

    ```
    2017  …\frac{N#}{#}…      前置因子 σρ₀ν₀l，沒有平方
    2020  …\frac{N#}{#^2}…    前置因子 ρ₀c₀σηd²，有平方
    2026  …(…)…               整段包在括號裡，前面還有 `Here:`
    ```

    它們共用的是**中間那個括號裡的因子**，不是整條式子。
    硬要骨架相同就得把括號結構抹掉，而那會讓 `a/(b+c)` 與 `(b+c)/a` 混成一條
    —— 用一個真的假併，換一個假的真併。

    ⇒ 所以 Tier A（骨架逐字相同）抓不到它們，**Tier B（相近）才是它們的位置**。
    相似度 0.86～0.95。
    """
    from difflib import SequenceMatcher
    a, b, c = skeleton(MAA_2017), skeleton(MAA_2020), skeleton(MAA_2026)
    assert a != b, "骨架被抹得太平了 —— 前置因子的平方是真差異"
    for x, y, who in ((a, b, "2017-2020"), (b, c, "2020-2026"), (a, c, "2017-2026")):
        r = SequenceMatcher(None, x, y, autojunk=False).ratio()
        assert r >= 0.85, f"{who} 只有 {r:.3f}，Tier B 撈不到它們"


def test_the_constants_show_where_they_disagree() -> None:
    """骨架認出「同一條」，常數序列指出「第幾位差開」。

    2017／2020 的常數序列必須相同；2026 在最後一位是 8 而不是 32。
    """
    n2017, n2020, n2026 = constants(MAA_2017), constants(MAA_2020), constants(MAA_2026)
    assert n2017 == n2020, (n2017, n2020)
    assert n2026 != n2017, "係數差 4 倍卻沒被看出來"
    diff = [i for i, (x, y) in enumerate(zip(n2017, n2026, strict=False)) if x != y]
    assert diff, (n2017, n2026)
    assert n2017[diff[0]] == "32" and n2026[diff[0]] == "8", (n2017, n2026)


# ── 不變性：MinerU 實際會吐的變體，骨架不得改變 ────────────────────────────


def test_spacing_does_not_matter() -> None:
    r"""MinerU 逐 token 吐出來，空白位置完全不可靠。"""
    assert skeleton(r"\frac{a}{b}") == skeleton(r"\frac { a } { b }")


def test_digits_split_across_tokens_are_glued_back() -> None:
    r"""`3 2` 與 `32` 是同一個數；`0 . 8 5` 也是。**不黏回去的話常數序列全是錯的。**"""
    assert constants(r"$x = 3 2 y$") == ["32"]
    assert constants(r"$x = 0 . 8 5 y$") == ["0.85"]


def test_font_and_alias_commands_are_stripped() -> None:
    r"""`\dfrac`／`\frac`、`\varepsilon`／`\epsilon`、字體指令 —— 都是同一條式子。"""
    assert skeleton(r"$\dfrac{\varepsilon}{2}$") == skeleton(r"$\frac{\epsilon}{2}$")
    assert skeleton(r"$\mathrm{p}_{1}$") == skeleton(r"$p_1$")


def test_variable_names_are_erased() -> None:
    r"""變數名字抹掉 —— 那正是三篇論文各寫各的地方。"""
    assert skeleton(r"$\frac{k}{t}$") == skeleton(r"$\frac{\chi}{h}$")


# ── 差異性：抹太多比抹太少危險，而且不會有人發現 ──────────────────────────


def test_powers_are_kept() -> None:
    r"""`k²` 與 `k³` 是真的差異，不能一起抹掉。"""
    assert skeleton(r"$k^{2}$") != skeleton(r"$k^{3}$")


def test_order_matters() -> None:
    r"""`a/b` 與 `b/a` 不是同一回事 —— `eq_similar` 的說明就寫著這句。"""
    assert skeleton(r"$\frac{a}{b+c}$") != skeleton(r"$\frac{b+c}{a}$")


def test_structure_commands_survive() -> None:
    r"""`\int`／`\sum`／`\partial` 是結構不是名字，抹掉就什麼都認成同一條。"""
    assert skeleton(r"$\int f$") != skeleton(r"$\sum f$")
    assert r"\int" in skeleton(r"$\int f$")


def test_greek_used_as_a_constant_is_not_a_variable() -> None:
    r"""`\pi` 是常數不是變數，抹成 `#` 會讓 `2\pi r` 與 `2xr` 混在一起。"""
    assert skeleton(r"$2 \pi r$") != skeleton(r"$2 x r$")
