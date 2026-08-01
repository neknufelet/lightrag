"""兩雙眼睛的逐格比對。

為什麼要逐格：袋裝記號相似度已經到極限。同一張跨頁續表的相鄰片段內容近乎重複
（交叉相似度 0.72–0.80），整張表的分數再怎麼算都分不開。但**具體到某一格**，
兩個獨立模型讀出來的東西要嘛一樣要嘛不一樣，不受整體詞彙重疊稀釋。

輸出也從「這個分數沒有鑑別力」變成「第 3 列第 2 格兩邊不一樣」—— 人工複查
從讀整張表變成看一格。

為什麼比對數學：兩邊都是 VLM 輸出，都能正確寫出 Z_{Mi}、\\eta_n、S_{0,n}。
先前拿文字層當基準時必須丟掉數學（文字層表示不了），那套過濾器不能沿用到這裡 ——
實測沿用會把每張表濾到只剩 5 個共用散文詞，任兩張表的相似度都變成 1.00。
基準換了，可比對的符號集合就換了。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from html.parser import HTMLParser

# 一格算「兩邊一致」的門檻。取 0.80 是因為兩個模型的 LaTeX 寫法會有無害差異
# （\mathrm 的有無、{} 的鬆緊），norm() 收斂掉大部分但不是全部。
T_CELL_AGREE = 0.80

# 整張表要自動採用，必須所有格都一致，且至少有這麼多格 —— 一張只有兩格的表
# 「全部一致」不構成證據。
MIN_CELLS = 4

# 下標前只取**單一**字母。數學變數是單字母，`\Gamma_iZ_i`（luna 不留空格）
# 用 [A-Za-z]+_ 會抓成 iZ_i，跟 qwen 的 `\Gamma_i Z_i` 抓出的 Z_i 對不上 ——
# 純粹是空格造成的斷詞假象，不是內容差異。
TOK = re.compile(r"\\[a-zA-Z]+|[A-Za-z]_\{[^}]*\}|[A-Za-z]_[A-Za-z0-9]|"
                 r"[A-Za-z]{3,}|\d+(?:\.\d+)?")

# LaTeX 環境名。\begin{cases} 與 \begin{array} 在這裡表達同一件事（分段定義），
# 兩個模型各挑一種寫法。環境名不帶內容，整批剝掉。
_ENV = {"begin", "end", "cases", "array", "matrix", "pmatrix", "bmatrix",
        "vmatrix", "aligned", "align", "split", "gathered"}

# 只影響外觀、不改變內容的 LaTeX 指令。兩個模型對這些的用法差異很大
# （luna 愛加 \displaystyle，qwen 愛用 \text{}），全部剝掉才看得到真差異。
# 較長的寫在前面，否則 text 會先吃掉 textstyle。結尾用 (?![a-zA-Z]) 保住指令邊界。
_FORMAT_ONLY = re.compile(
    r"\\(?:displaystyle|textstyle|scriptstyle|mathrm|mathit|mathbf|mathsf|"
    r"qquad|quad|underline|overline|nolimits|limits|left|right|"
    r"Bigg|bigg|Big|big|text|rm|it|bf|underset|overset|substack)(?![a-zA-Z])")

# 同一個符號的不同寫法。這些是排版慣例差異，不是讀錯。
_ALIAS = {
    "\\varepsilon": "\\epsilon", "\\vartheta": "\\theta", "\\varphi": "\\phi",
    "\\varrho": "\\rho", "\\varsigma": "\\sigma", "\\geq": "\\ge",
    "\\leq": "\\le", "\\longrightarrow": "\\to", "\\rightarrow": "\\to",
    "\\Longrightarrow": "\\to", "\\dfrac": "\\frac", "\\tfrac": "\\frac",
    # 只別名「同義」的寫法。\iint 與 \int、\notin 與 \neq 意思不同，
    # 別名掉等於主動隱藏真差異 —— 那正是這支程式存在要防的事。
    "\\xrightarrow": "\\to", "\\xlongrightarrow": "\\to", "\\ne": "\\neq",
    "\\ldots": "\\dots", "\\cdots": "\\dots",
    # 兩邊表達「這格是圖」的方式不同：prompt 要求寫 [FIGURE]，qwen 改吐 <img>。
    # 語意相同，不該算成不一致。
    "img": "figure",
}


def _norm(s: str) -> str:
    """收斂掉排版差異。Z_{Mi} / Z_Mi / Z_{\\mathrm{Mi}} / \\displaystyle Z_{Mi}
    全部變成同一個鍵。別名查兩次：剝符號前（指令形式 \\varepsilon）與剝之後
    （純文字形式 img）。"""
    s = _FORMAT_ONLY.sub("", s)
    s = _ALIAS.get(s, s)
    s = re.sub(r"[{}\\ ]", "", s).lower()
    return _ALIAS.get(s, s)


def tokens(text: str) -> set[str]:
    """不要在斷詞前把大括號拆開。`X_{...}` 這條規則靠括號緊貼著才配得到，
    先 replace("{", " { ") 會讓 J_{0} 變成 J { 0 }，下標整個抓不到 ——
    結果是「愛用大括號的那個模型」的下標記號全部消失，兩邊憑空產生大量假分歧。
    實測 luna 寫 J_{0}、qwen 寫 J_0，#390 就是這樣被誤判成不一致的。
    括號本來就會被 _norm 剝掉，這裡什麼都不用做。"""
    return {n for x in TOK.findall(text) if (n := _norm(x)) and n not in _ENV}


class _Grid(HTMLParser):
    """把 <table> 讀成 list[list[str]]。不處理 rowspan/colspan —— 這類表格
    實測沒有跨格，真的遇到會表現為列長度不一致，被 structural 分支擋下。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = []
        elif tag == "img" and self._cell is not None:
            # <img> 在儲存格裡代表模型放棄了那格的內容。標記出來，
            # 不要讓它變成空字串跟另一邊的空格「一致」。
            self._cell.append("[IMG]")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(" ".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def grid(html: str) -> list[list[str]]:
    p = _Grid()
    p.feed(html)
    if p._row:                      # 沒有 </tr> 收尾時補上
        p.rows.append(p._row)
    return [r for r in p.rows if any(c.strip() for c in r)]


@dataclass
class CellDiff:
    row: int
    col: int
    a: str
    b: str
    sim: float


@dataclass
class TableCheck:
    key: str
    rows_a: int
    rows_b: int
    cells: int = 0
    agree: int = 0
    diffs: list[CellDiff] = field(default_factory=list)
    structural: str | None = None      # 列數/欄數對不上，無法逐格比

    @property
    def ok(self) -> bool:
        return (self.structural is None and not self.diffs
                and self.cells >= MIN_CELLS)

    def line(self) -> str:
        if self.structural:
            return f"結構不符（{self.structural}）→ 人工"
        if self.cells < MIN_CELLS:
            return f"格數不足（{self.cells} < {MIN_CELLS}），一致也不構成證據 → 人工"
        if self.diffs:
            return f"{self.agree}/{self.cells} 格一致，{len(self.diffs)} 格不一致 → 人工看這幾格"
        return f"{self.cells}/{self.cells} 格一致 → 自動採用"


def _sig(row: list[str]) -> frozenset:
    s = set()
    for c in row:
        s |= tokens(c)
    return frozenset(s)


def compare(key: str, html_a: str, html_b: str) -> TableCheck:
    ga, gb = grid(html_a), grid(html_b)
    chk = TableCheck(key, len(ga), len(gb))
    if not ga or not gb:
        chk.structural = f"解析不出表格（A {len(ga)} 列、B {len(gb)} 列）"
        return chk

    # 列數可能不同（某一邊把兩列併成一列）。用列的記號集合做序列對齊，
    # 只比對得上的列 —— 硬按索引對會把整張表往後錯一格，產出一堆假差異。
    sa, sb = [_sig(r) for r in ga], [_sig(r) for r in gb]
    sm = SequenceMatcher(None, sa, sb, autojunk=False)
    pairs: list[tuple[int, int]] = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            pairs += [(i1 + d, j1 + d) for d in range(i2 - i1)]
        elif op == "replace" and (i2 - i1) == (j2 - j1):
            pairs += [(i1 + d, j1 + d) for d in range(i2 - i1)]

    if not pairs:
        chk.structural = f"列對不起來（A {len(ga)} 列、B {len(gb)} 列）"
        return chk
    if len(pairs) < max(len(ga), len(gb)) * 0.6:
        chk.structural = (f"只有 {len(pairs)} 列對得上"
                          f"（A {len(ga)}、B {len(gb)}）")
        return chk

    for i, j in pairs:
        ra, rb = ga[i], gb[j]
        if len(ra) != len(rb):
            chk.structural = f"第 {i+1} 列欄數不同（A {len(ra)}、B {len(rb)}）"
            return chk
        for c, (ca, cb) in enumerate(zip(ra, rb)):
            ta, tb = tokens(ca), tokens(cb)
            if not ta and not tb:
                continue                      # 兩邊都空，不算一格
            chk.cells += 1
            s = len(ta & tb) / max(len(ta | tb), 1)
            if s >= T_CELL_AGREE:
                chk.agree += 1
            else:
                chk.diffs.append(CellDiff(i + 1, c + 1, ca, cb, s))
    return chk
