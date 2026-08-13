r"""公式的比對鍵：把一條式子壓成「骨架 ＋ 常數序列」。

## 這支在解什麼問題

同一條公式在不同論文裡**變數名字完全不同**，但結構一樣。2026-08-12 手動查到
一個實例：同一條 Maa 的微穿孔板電阻公式出現在庫裡三篇，其中一篇的係數差 4 倍。

```
2017 …  k_r = [1 + k²/32]^{1/2} + (√2/32)·k·(l/t)
2020 …  k_r = √(1 + χ²/32)     + (√2/32)·(χd/h)
2026 …  R = …(√(1+k₁²/32)      + (√2/8) ·k₁·(d₁/t₁))·ρ₀c₀    ← 8 不是 32
```

⇒ **骨架**（變數抹成 `#`、數字抽走）用來認「這是同一條」；
   **常數序列**用來看「第幾位差開」。

⚠ **常數必須移出骨架。** 留在裡面的話 `√2/32` 與 `√2/8` 會被判成兩條不同的
公式，正好違背這支存在的理由。

## 為什麼不直接用 `crosscheck.eq_normalize`

那支最後會 `.lower()`，而**判斷「哪個字母是變數」必須在小寫化之前** ——
`\Gamma` 與 `\gamma`、`T` 與 `t` 在物理裡不是同一個東西。
所以這裡重用它的三張表（`_EQ_DELIM`／`_EQ_STRIP`／`_ALIAS`），**不呼叫那支函式**。
⚠ 不要「順手改成呼叫 eq_normalize」—— 那會讓大寫小寫的區別消失。

## 這支不做的事

判斷誰對誰錯。**產出是「這裡有分歧」，不是「這裡有錯」** ——
分歧可能來自 MinerU 讀錯、原文本來就不同（不同的端點修正）、
或兩篇用了不同的假設。
"""
from __future__ import annotations

import re

from .crosscheck import _ALIAS, _EQ_DELIM, _EQ_STRIP

# 當常數用的希臘字母：抹成 `#` 的話 `2πr` 與 `2xr` 會混在一起。
_CONST_GREEK = frozenset({"pi", "infty"})

# 結構命令原樣留著 —— 它們是骨架本身。變數是名字，結構不是。
_STRUCTURE = frozenset({
    "frac", "sqrt", "sum", "int", "iint", "iiint", "oint", "prod", "lim",
    "partial", "nabla", "times", "cdot", "pm", "mp", "leq", "geq", "neq",
    "approx", "equiv", "propto", "in", "exp", "log", "ln", "sin", "cos", "tan",
    "sinh", "cosh", "tanh", "cot", "sec", "csc", "arctan", "arcsin", "arccos",
    "overline", "hat", "bar", "tilde", "vec", "dot", "ddot", "prime",
    "begin", "end", "array", "cases", "matrix", "pmatrix", "bmatrix",
})

_CMD = re.compile(r"\\([A-Za-z]+)")
_NUM = re.compile(r"\d+(?:\.\d+)?")


def _glue_digits(t: str) -> str:
    r"""MinerU 逐位吐數字：`3 2` → `32`、`0 . 8 5` → `0.85`。

    **不黏回去的話常數序列整串是錯的** —— `32` 會變成 `3` 與 `2` 兩個常數。
    """
    t = re.sub(r"(?<=\d)\s+(?=\d)", "", t)
    t = re.sub(r"(?<=\d)\s*\.\s*(?=\d)", ".", t)
    return re.sub(r"(?<=\d)\s+(?=\d)", "", t)


def _prepare(latex: str) -> str:
    """剝定界符、字體指令、套別名、黏數字。**不小寫化。**"""
    t = _EQ_DELIM.sub(" ", latex or "")
    t = _EQ_STRIP.sub("", t)
    for a, b in _ALIAS.items():
        if a.startswith("\\"):
            t = t.replace(a, b)
    return _glue_digits(t)


def _tokens(t: str) -> list[str]:
    """切成 token：`\\命令`、數字、上下標記號、單一字元。"""
    out: list[str] = []
    i = 0
    while i < len(t):
        ch = t[i]
        if ch.isspace():
            i += 1
            continue
        if ch in "{}":
            # **括號要留。** 丟掉的話 `\frac{a}{b+c}` 與 `\frac{b+c}{a}` 壓成同一串
            # —— 而順序在數學裡有意義（`eq_similar` 的說明就寫著這句）。
            out.append(ch)
            i += 1
            continue
        if ch == "\\":
            m = re.match(r"\\[A-Za-z]+|\\.", t[i:])
            out.append(m.group())
            i += len(m.group())
            continue
        m = _NUM.match(t, i)
        if m:
            out.append(m.group())
            i = m.end()
            continue
        out.append(ch)
        i += 1
    return out


def _drop_redundant_braces(toks: list[str]) -> list[str]:
    """把只包一個 token 的括號拆掉：`{ p }` → `p`。

    MinerU 的括號很隨性（`{ \bf p }` 剝掉字體指令之後剩 `{ p }`，而兩眼寫 `p`），
    留著會讓同一條式子對不上。**但包住多個 token 的括號要留** —— 那是 `\frac`
    的上下之分。
    """
    out: list[str] = []
    for tok in toks:
        if tok == "}" and len(out) >= 2 and out[-2] == "{":
            inner = out.pop()
            out.pop()
            out.append(inner)
            continue
        out.append(tok)
    return out


def _is_variable(tok: str) -> bool:
    """單一拉丁字母，或當變數用的希臘字母。`\\pi` 不算（它是常數）。"""
    if len(tok) == 1 and tok.isalpha():
        return True
    if tok.startswith("\\"):
        name = tok[1:]
        return name.isalpha() and name not in _STRUCTURE and name not in _CONST_GREEK
    return False


def _strip_subscripts(toks: list[str]) -> list[str]:
    r"""下標整段丟掉：`k_r` → `k`、`\rho_0` → `\rho`。

    下標是**名字的一部分**，不是結構 —— 三篇論文寫 `k_r`／`k_r`／`k_1`
    指的是同一個量。⚠ 上標**要留**：`k²` 與 `k³` 是真的差異。
    """
    out: list[str] = []
    i = 0
    while i < len(toks):
        if toks[i] == "_":
            i += 1
            # ⚠ 下標可能是**一整組**（`_{si}`），要整段跳過。
            # 只跳一個 token 的話會留下 `si}` 那種殘骸 —— 而殘骸會讓同一條式子對不上。
            if i < len(toks) and toks[i] == "{":
                depth = 0
                while i < len(toks):
                    if toks[i] == "{":
                        depth += 1
                    elif toks[i] == "}":
                        depth -= 1
                        if depth == 0:
                            i += 1
                            break
                    i += 1
            elif i < len(toks):
                i += 1
            continue
        out.append(toks[i])
        i += 1
    return out


def _walk(toks: list[str]) -> list[tuple[str, bool]]:
    """（token, 是不是指數裡的）。指數要跟一般常數分開對待。

    ⚠ 指數可能是**一整組**（`^{1/2}`）。只算一個 token 的話，組裡其餘的數字
    會被當成一般常數，兩篇寫法不同的同一條公式常數序列就對不上。
    """
    out: list[tuple[str, bool]] = []
    exp_until = -1
    i = 0
    while i < len(toks):
        if toks[i] == "^":
            j = i + 1
            if j < len(toks) and toks[j] == "{":
                depth = 0
                while j < len(toks):
                    if toks[j] == "{":
                        depth += 1
                    elif toks[j] == "}":
                        depth -= 1
                        if depth == 0:
                            break
                    j += 1
            exp_until = j
        out.append((toks[i], i <= exp_until))
        i += 1
    return out


def _half_power_to_sqrt(toks: list[str]) -> list[str]:
    r"""`[X]^{1/2}` 與 `(X)^{1/2}` → `\sqrt{X}`。

    同一條公式兩篇一個寫 `\sqrt{…}`、一個寫 `[…]^{1/2}`（實測：Maa 那條在
    2017 與 2020 兩篇就是這樣），不收斂的話認不出是同一條。
    """
    PAIR = {"]": "[", ")": "("}
    out = list(toks)
    i = 0
    while i < len(out) - 5:
        if (out[i] == "^" and out[i + 1] == "{" and out[i + 2] == "1"
                and out[i + 3] == "/" and out[i + 4] == "2" and out[i + 5] == "}"
                and i > 0 and out[i - 1] in PAIR):
            opener = PAIR[out[i - 1]]
            depth = 0
            k = i - 1
            while k >= 0:
                if out[k] == out[i - 1]:
                    depth += 1
                elif out[k] == opener:
                    depth -= 1
                    if depth == 0:
                        break
                k -= 1
            if k < 0:
                i += 1
                continue
            del out[i:i + 6]
            out[i - 1] = "}"
            out[k] = "{"
            out.insert(k, "\\sqrt")
            i = k
            continue
        i += 1
    return out


def constants(latex: str) -> list[str]:
    """數字常數，**按出現順序**。骨架認出「同一條」之後，用它看第幾位差開。"""
    toks = _half_power_to_sqrt(_strip_subscripts(_drop_redundant_braces(_tokens(_prepare(latex)))))
    return [t for t, is_exp in _walk(toks) if _NUM.fullmatch(t) and not is_exp]


def skeleton(latex: str) -> str:
    r"""抹掉變數名與數字之後的結構。同一條公式在不同論文裡應該得到同一串。

    ⚠ 連續的 `#` 壓成一個：`\rho_0 c_0` 與 `\rho c` 是同一個「一團係數」。
    不壓的話，同一條公式在兩篇裡因為多寫一個符號就對不上。
    """
    out: list[str] = []
    for tok, is_exp in _walk(_half_power_to_sqrt(_strip_subscripts(_drop_redundant_braces(_tokens(_prepare(latex)))))):
        if _NUM.fullmatch(tok):
            # **指數保留原值**：`k²` 與 `k³` 是真的差異，抹成 N 就分不開了。
            out.append(tok if is_exp else "N")
        elif _is_variable(tok):
            if out and out[-1] == "#":
                continue
            out.append("#")
        else:
            out.append(tok)
    return "".join(out)


def structure_profile(latex: str) -> tuple[tuple[str, int], ...]:
    """結構命令的多重集合 ＋ 常數個數。**Tier B 的分塊鍵**，用來避免兩兩全比。"""
    toks = _half_power_to_sqrt(_strip_subscripts(_drop_redundant_braces(_tokens(_prepare(latex)))))
    counts: dict[str, int] = {}
    for tok in toks:
        m = _CMD.fullmatch(tok)
        if m and m.group(1) in _STRUCTURE:
            counts[m.group(1)] = counts.get(m.group(1), 0) + 1
    counts["#nums"] = sum(1 for t in toks if _NUM.fullmatch(t))
    return tuple(sorted(counts.items()))
