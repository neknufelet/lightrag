"""兩個**機械**的 LaTeX 修補：位置錨定、零例外可驗、不呼叫模型。

這兩條的共同形狀跟 ∂ 誤讀那一族一樣：MinerU 讀錯的是**排版**，不是內容，而錯法
有一個可以精確描述的位置。位置寫得出來，就不需要模型投票 —— 掃全母體、逐處看過、
沒有例外，才准套（judgement-flow 第 4 節「機械可窮舉」那一類）。

## 1. `\\times` 誤讀（c-tables-disputes §7.4 定案）

MinerU 把**區域羅馬數字下標後面的字母 x** 讀成了乘號：

    現值   Z _ { 0 } \\mathsf { v } _ { \\mathsf { I } \\times } ( \\mathsf { x } )
    裁圖   Z₀ v_{Ix}(x)

同一個 x 在同一行的括號裡被讀對成 `\\mathsf { x }`，只有下標裡那個變成 `\\times`
—— 讀對的那一半直接證明另一半是什麼，跟 ∂ 族「同式混用真 `\\partial`」是同一種證據。

**錨點**：下標 `_{…}` 裡，羅馬數字（I／II／III，含 MinerU 把它們讀成 1／l／| 的
變體，每個字母可能各自被包成 `\\mathsf{…}`）**緊接**一個 `\\times`，然後就收尾。
全母體 20 份掃出 20 處，全部在 C，全部是 `Z_0 v_{…x}(…)` 這個型。三張裁圖
（#520／#529／#373）親眼核對過，20 處零例外。

**刻意不動的一族**：C 另外有 6 處 `e ^ { - \\gamma _ { n , v } \\times }` ——
指數裡的座標 x 同樣被讀成了 `\\times`（裁圖 t373 上寫的是 `e^{-γ_n x}`）。
病因相同但**位置不同**，不在 §7.4 授權的錨點內，所以這裡一個都不碰。
擴大錨點是下一張工單的事：規則要一次只放寬一條，才知道漂移是誰造成的。

## 2. 格內逐字母排版（§7.5 定案）

MinerU 把 `\\mathsf{tanh}`、`\\mathrm{with}` 這類寫成逐字母排開：

    \\mathsf { t a n h }      \\mathrm { w i t h }      \\mathrm { f r o n t }

內容沒有掉，掉的是「這是一個詞」這件事。對索引是實害：檢索 "with" 配不到
`w i t h`，而 `tanh` 是 C 的最大單詞（29 次）。語意上完全無害：命中的 14 個命令
全部是**數學模式**命令（`\\mathrm` 1866、`\\mathbf` 246、`\\mathsf` 233、
`\\operatorname` 18 …），而數學模式**忽略空白**，所以 `\\mathrm{w i t h}` 與
`\\mathrm{with}` 排版結果逐點相同。`\\text` 族（文字模式，空白有意義）命中 0 段
—— 這是套用前必須確認的那一條，因為只有它會改變版面。

**只黏「≥2 個連續單字母 token、彼此只隔空白」的那一段**，其餘位元組原樣不動。
與 coverage-check 的 `latex_unspace` 同語意，但更窄：那支是**量測**用的，可以把
`\\mathrm{ ~ ; ~ }` 壓成 `;`；這支是**寫回資料**，壓掉 `~` 就是改了排版。

2.5 輪的教訓（`~` 是不斷行空白，在這種排版裡當的是**詞**的分隔，一般空白才是
**字母**的分隔）在這裡是**由構造成立**的：`~` 不是單字母 token，所以它自然
中斷一段黏合，而且原樣保留。

    \\mathrm { v e c t o r ~ f r o m ~ o r i g i n ~ o f ~ c o - o r d i n a t e s }
 →  \\mathrm { vector ~ from ~ origin ~ of ~ co - ordinates }

`-` 同理。原文本來就沒有分隔符的（`h a n d s i d e` ← 原文 "hand side"）會黏成
`handside`，救不回來 —— **寧可少救不可亂黏**，而多出來的假詞不會抵銷掉真正的
缺漏（`handside` 配不到 pdf 側的 `hand`／`side`，多重集合差不受影響）。

## 為什麼這兩條放在同一個模組

它們共用同一條寫回路徑（`_pp_original_<欄位>` 只記第一次、`_pp_repaired_at`
蓋時間戳、revert 走既有的還原分支），而且都必須在**人工裁定寫完之後**才跑
—— 裁定檔記的是「圖上寫什麼」，機械正規化記的是「同一件事怎麼寫才對」，
順序反過來的話裁定檔相對於現值就不再是純插入。
"""
from __future__ import annotations

import collections
import re
from dataclasses import dataclass, field

# 這兩條會動的欄位。`table_body` 也在內 —— §7.4／§7.5 的範圍就是「table_body
# 與 equation 文字欄位」，而 C 的 `\times` 20 處全部在 table_body 裡。
FIELDS = ("text", "content", "body", "code_body", "table_body")

# 下標裡的羅馬數字：I / II / III。每個字母可能各自被包成 \mathsf{…}，也可能被
# MinerU 讀成 1 / l / |（domain_facts 記過的「羅馬數字下標難讀」，本規則**不修**
# 那一層，只把 \times 換回 x —— 一次放寬一條）。
_ROMAN = r"(?:\\(?:mathsf|mathrm|mathbf|mathit|text|sf)\s*\{\s*[IlL1|]\s*\}|[IlL1|])"
TIMES = re.compile(r"(_\s*\{\s*" + _ROMAN + r"(?:\s*" + _ROMAN + r")*\s*)\\times(\s*\})")

# `\cmd{…}` 的單層引數。刻意只吃 `[^{}]*`（不含巢狀）—— 正則剖析不了配對括號，
# 硬要吃巢狀只會在別的地方咬錯（judgement-flow 第 3 節記過同一件事）。
CMD_ARG = re.compile(r"(\\[A-Za-z]+\s*\{)([^{}]*)(\})")
TOKEN = re.compile(r"\S+")

# 文字模式命令：空白在裡面**有意義**，黏起來會改變版面，所以一律不碰。
# 目前全母體命中 0 段，這條是防未來的解析產物變樣（斷言而不是註解）。
TEXT_MODE = {"text", "textrm", "textbf", "textit", "textsf", "texttt", "mbox", "textnormal"}


def fix_times(text: str) -> tuple[str, int]:
    """`_{I\\times}` → `_{Ix}`。羅馬數字那一段已經有 `\\mathsf` 包裝時，`x` 也照樣
    包成 `\\mathsf{x}`，跟同一行括號裡那個讀對了的 `( \\mathsf { x } )` 寫法一致；
    沒有包裝的（`_{ 1 1 \\times }` 這種本來就已經讀壞的）就用裸 `x`，不多加東西。"""
    n = 0

    def one(m):
        nonlocal n
        n += 1
        x = "\\mathsf { x }" if "\\mathsf" in m.group(1) else "x"
        return m.group(1) + x + m.group(2)

    return TIMES.sub(one, text), n


def _glue(arg: str) -> tuple[str, list[str]]:
    """把引數裡每一段「≥2 個連續單字母 token、彼此只隔空白」黏成一個詞。

    非單字母的 token（`~`、`-`、標點、多字母片段）原樣留下**並中斷這一段**，
    段與段之間的原始位元組一個不動。回傳 (新引數, 黏出來的詞)。
    """
    toks = list(TOKEN.finditer(arg))
    out: list[str] = []
    made: list[str] = []
    i = last = 0
    while i < len(toks):
        if len(toks[i].group()) == 1 and toks[i].group().isalpha():
            j = i
            while (j + 1 < len(toks)
                   and len(toks[j + 1].group()) == 1 and toks[j + 1].group().isalpha()
                   and set(arg[toks[j].end():toks[j + 1].start()]) <= {" ", "\t"}):
                j += 1
            if j > i:
                word = "".join(t.group() for t in toks[i:j + 1])
                out.append(arg[last:toks[i].start()])
                out.append(word)
                made.append(word)
                last = toks[j].end()
                i = j + 1
                continue
        i += 1
    out.append(arg[last:])
    return "".join(out), made


def unspace(text: str) -> tuple[str, list[str]]:
    """只動 `\\cmd{…}` 引數內的單字母空白序列，一般散文的空白一個都不動。"""
    made: list[str] = []

    def one(m):
        if m.group(1).strip().lstrip("\\").rstrip("{").strip() in TEXT_MODE:
            return m.group(0)                  # 文字模式：空白有意義，不碰
        new, w = _glue(m.group(2))
        made.extend(w)
        return m.group(1) + new + m.group(3)

    return CMD_ARG.sub(one, text), made


def fix_one(text: str) -> tuple[str, int, list[str]]:
    """兩條規則依序套在同一段文字上。回傳 (新文字, \\times 處數, 黏出來的詞)。"""
    t, n = fix_times(text)
    t, made = unspace(t)
    return t, n, made


@dataclass
class LatexPlan:
    # {(item index, 欄位): (新值, \times 處數, 黏出來的詞)}
    edits: dict[tuple[int, str], tuple[str, int, list[str]]] = field(default_factory=dict)

    @property
    def items(self) -> int:
        return len({i for i, _ in self.edits})

    @property
    def times(self) -> int:
        return sum(e[1] for e in self.edits.values())

    @property
    def glued(self) -> int:
        return sum(len(e[2]) for e in self.edits.values())

    def words(self) -> collections.Counter:
        c: collections.Counter = collections.Counter()
        for e in self.edits.values():
            c.update(e[2])
        return c

    def summary(self) -> str:
        return (f"LaTeX 正規化 {self.items} 項：\\times→x {self.times} 處、"
                f"逐字母排版黏回 {self.glued} 段")


def plan(items: list[dict]) -> LatexPlan:
    """只讀不寫。"""
    p = LatexPlan()
    for i, it in enumerate(items):
        for f in FIELDS:
            v = it.get(f)
            if not isinstance(v, str) or "\\" not in v:
                continue
            new, n, made = fix_one(v)
            if new != v:
                p.edits[(i, f)] = (new, n, made)
    return p


def apply_to_items(items: list[dict], p: LatexPlan, stamp: str) -> int:
    for (i, f), (new, _, _) in p.edits.items():
        it = items[i]
        # `setdefault`：`_pp_original_*` 只記**第一次**的原文。這條規則跑在人工
        # 裁定之後，裁定過的項目原文早就記好了，不能被這一輪的結果覆蓋掉。
        it.setdefault(f"_pp_original_{f}", it[f])
        it[f] = new
        it["_pp_repaired_at"] = stamp
    return len(p.edits)
