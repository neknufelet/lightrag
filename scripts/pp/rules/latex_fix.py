"""三個**機械**的 LaTeX 修補：位置錨定、零例外可驗、不呼叫模型。

三條的共同形狀：MinerU 讀錯的是**排版**，不是內容，而錯法有一個可以精確描述的
位置。位置寫得出來，就不需要模型投票 —— 掃全母體、逐處看過、沒有例外，才准套
（judgement-flow 第 4 節「機械可窮舉」那一類）。

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

## 3. ∂ 誤讀（2026-08-04 定案）

檔頭原本就把 ∂ 誤讀當成 §7.4 的同族拿來對照，現在它自己也在這裡了。
MinerU 把 ∂ 讀成四種寫法，全母體 190 處、零例外、同式混用自證。
第一版只認 `\\hat{\\sigma}`（165 處）就宣稱「零例外」—— 那句話只對搜過的字串
成立。補掃才找到 `\\widehat{\\sigma}` 6、`\\hat{\\partial}` 17、`\\widehat{c}` 2。
**偵測器沒找的東西不會變成「沒有」**（鐵則 4／5）。詳見 `fix_partial`。

## 為什麼這三條放在同一個模組

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


# ∂ 誤讀家族。**逐一量出來的，不是猜的**——第一版只寫 `\hat{\sigma}`，掃全母體
# 之後才發現另外三種寫法：`\widehat` 不等於 `\hat`（正則配不到），而 ∂ 自己也會
# 被加上一頂帽子。四種合計 190 處。
#
#   \hat{\sigma}      165    \widehat{\sigma}    6
#   \hat{\partial}     17    \widehat{c}         2
#
# **刻意不含 `\hat{c}`（9 處）**：那一族有 3 處是真的 ĉ（F #259 的遞迴係數
# `ĉ_n = (1-β²)k₀a/n · ĉ_{n-1}`），而且那一項**同時滿足下面兩條錨點**——
# 擋住它的不是錨點，是「不認 c 這個字元」這個決定。這條線不能動。
HAT_SIGMA = re.compile(
    r"\\(?:wide)?hat\s*\{\s*\\sigma\s*\}"        # σ̂ ／ widehat σ
    r"|\\(?:wide)?hat\s*\{\s*\\partial\s*\}"     # ∂ 頭上多一頂帽子
    r"|\\widehat\s*\{\s*c\s*\}"                  # 只有 widehat 的 c，不含 \hat{c}
)
# 分數／斜線構造。偏微分**必然**寫成分子分母，這是錨點的另一半。
_FRACTION = re.compile(r"\\[Bb]igg?/|\\frac|/")

# **統計估計量的否決記號**（deepseek 2026-08-04 對抗找碴找到的失效模式）。
# 反例是 t 檢定：`\frac{\bar{X}-\mu}{\hat{\sigma}/\sqrt{n}}` —— σ̂ 是樣本標準差，
# 完全符合上面兩條錨點，但改成 ∂ 就是毀資料。Welch's t-test 與 ANOVA 的 MSE
# 展開式會讓 σ̂ 在同一式出現 ≥2 次。
#
# 本語料實測命中 0（'standard deviation'／'estimator'／'confidence interval'／
# 'p-value'／t_{n-1}／μ̂／θ̂ 全部是 0，這 6 份是理論章節），所以**現在**沒有風險。
# 但 /data/rag 裡的期刊論文有量測不確定度與統計分析，拉進來就會咬。
#
# 命中時**不改，而且要出聲**（`LatexPlan.vetoed`）—— 沉默地跳過會讓「規則放過了
# 一個它其實該處理的東西」跟「規則正確地避開了」在畫面上長得一樣。
_STATS_VETO = re.compile(
    r"\\(?:wide)?hat\s*\{\s*\\(?:mu|theta|beta|alpha|gamma)\s*\}"
    r"|\\sqrt\s*\{\s*n\s*\}"
    r"|t\s*_\s*\{\s*n\s*-\s*1\s*\}"
    r"|standard\s+deviation|estimator|confidence\s+interval|p[\s-]value"
    r"|\\bar\s*\{\s*X\s*\}",
    re.I,
)


def fix_partial(text: str) -> tuple[str, int]:
    """`\\hat{\\sigma}` → `\\partial`，只在**偏微分構造**裡動手。

    MinerU 把 ∂ 的字形讀錯成四種寫法（見 `HAT_SIGMA` 的說明），全母體 6 份共
    **190 處，逐處看過，190/190 都是偏微分**，型態涵蓋 ∂/∂n、∂V/∂P、∂²U/∂x²
    （拉普拉斯）、∂(v¹,v²,v³)/∂(u¹,u²,u³)（Jacobi 行列式）、物質導數、
    柱座標的 grad／div／rot 全套（B #680）。

    **自證的證據**：B #816 是 `\\partial k \\big/ \\hat{\\sigma} t + \\hat{\\sigma}
    \\omega \\big/ \\hat{\\sigma} x` —— 同一條式子的同一個分數，分子讀對成
    `\\partial`、分母讀錯成 σ̂。B #273 同型。MinerU 自己證明了 σ̂ 是什麼，
    不必問模型。眼睛（qwen＋luna 各自獨立）也把這些轉錄成 `\\partial`。

    **錨點為什麼不是「看到 σ̂ 就換」**：同族的 `\\hat{c}`（∂ 的另一種誤讀）全母體
    9 處，其中 **F #259 的 3 處是真的 ĉ** —— `ĉ_1=(1-β²)…；ĉ_n=(1-β²)k₀a/n·ĉ_{n-1}`
    是一組遞迴定義的係數，盲目換成 ∂ 會直接毀掉它。認字元會出事，所以認**結構**：

      ① 該項目的家族記號出現 **≥2 次** —— ∂ 成對出現在分子分母，孤零零一個更可能是真的
      ② 該項目有 `\\frac` 或斜線 —— 偏微分的分數構造
      ③ 該項目**沒有**統計估計量的記號（見 `_STATS_VETO`）

    三條都中才動手。190 處全部通過，而 `\\hat{c}` 那一族**這條規則一個都不碰**
    （一次只放寬一條錨點，才知道漂移是誰造成的）。

    **它綁的是 MinerU 這個版本對一個字形的誤讀，不是文件領域的性質。** MinerU 改好
    之後這條會從「修正」變成「破壞」。守它的是兩層，**不是** `model-observations.json`
    ——那個檔自己第一行就寫著「這裡的任何一條都不得寫成流程中的自動裁決規則」，
    而它管的是「哪隻眼睛錯在哪一類」那種判讀觀察。§7.4 的 `\\times` 同樣綁 MinerU，
    走的也是這裡，不是那裡。

      ① **錨點由構造 fail-safe**：MinerU 修好之後就不再產出成對的 σ̂，規則自然
         不再命中；真的 σ̂（單獨出現、或沒有分數構造）本來就在錨點外。
      ② **統計否決**：`_STATS_VETO` 命中就不動手並記一筆（見該常數的說明）。
      ③ **金絲雀**：`plan.partials` 與 `plan.vetoed` 都進了摘要與基準，
         數字變動會出現在 `git diff` 裡。沒說明的數字變動＝未被察覺的漂移。

    回傳 (新文字, 換掉幾處, 是否被統計記號否決)。
    """
    if len(HAT_SIGMA.findall(text)) < 2 or not _FRACTION.search(text):
        return text, 0, False
    if _STATS_VETO.search(text):
        return text, 0, True
    new, n = HAT_SIGMA.subn("\\\\partial", text)
    return new, n, False


def fix_one(text: str) -> tuple[str, int, int, bool, list[str]]:
    """三條規則依序套在同一段文字上。

    回傳 (新文字, \\times 處數, ∂ 處數, 統計否決, 黏出來的詞)。

    `fix_partial` 排在 `unspace` **前面**：σ̂ 的模式含 `\\hat { \\sigma }` 這種
    帶空白的寫法，而 `unspace` 只黏單字母 token、不會動到它 —— 順序其實可交換，
    但擺前面讓「先換符號、再正規化排版」的因果讀得出來。
    """
    t, n = fix_times(text)
    t, d, veto = fix_partial(t)
    t, made = unspace(t)
    return t, n, d, veto, made


@dataclass
class LatexPlan:
    # {(item index, 欄位): (新值, \times 處數, ∂ 處數, 統計否決, 黏出來的詞)}
    edits: dict[tuple[int, str], tuple[str, int, int, bool, list[str]]] = field(default_factory=dict)
    # 命中錨點但被統計記號否決的 (item index, 欄位)。**不改，但要出聲。**
    vetoed: list[tuple[int, str]] = field(default_factory=list)

    @property
    def items(self) -> int:
        return len({i for i, _ in self.edits})

    @property
    def times(self) -> int:
        return sum(e[1] for e in self.edits.values())

    @property
    def partials(self) -> int:
        return sum(e[2] for e in self.edits.values())

    @property
    def glued(self) -> int:
        return sum(len(e[4]) for e in self.edits.values())

    def words(self) -> collections.Counter:
        c: collections.Counter = collections.Counter()
        for e in self.edits.values():
            c.update(e[4])
        return c

    def summary(self) -> str:
        s = (f"LaTeX 正規化 {self.items} 項：\\times→x {self.times} 處、"
             f"∂ 誤讀 {self.partials} 處、逐字母排版黏回 {self.glued} 段")
        if self.vetoed:
            # 沉默地跳過會讓「規則放過了該處理的東西」跟「規則正確地避開了」
            # 在畫面上長得一樣。命中就要報出來，讓人去看那一項到底是什麼。
            s += f"；**統計記號否決 {len(self.vetoed)} 項，需人工確認**"
        return s


def plan(items: list[dict]) -> LatexPlan:
    """只讀不寫。"""
    p = LatexPlan()
    for i, it in enumerate(items):
        for f in FIELDS:
            v = it.get(f)
            if not isinstance(v, str) or "\\" not in v:
                continue
            new, n, d, veto, made = fix_one(v)
            if veto:
                p.vetoed.append((i, f))
            if new != v:
                p.edits[(i, f)] = (new, n, d, veto, made)
    return p


def apply_to_items(items: list[dict], p: LatexPlan, stamp: str) -> int:
    for (i, f), (new, _, _, _, _) in p.edits.items():
        it = items[i]
        # `setdefault`：`_pp_original_*` 只記**第一次**的原文。這條規則跑在人工
        # 裁定之後，裁定過的項目原文早就記好了，不能被這一輪的結果覆蓋掉。
        it.setdefault(f"_pp_original_{f}", it[f])
        it[f] = new
        it["_pp_repaired_at"] = stamp
    return len(p.edits)
