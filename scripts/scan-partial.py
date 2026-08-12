#!/usr/bin/env python3
r"""∂ 誤讀的常駐探針：以**上下同形**判定，不靠白名單。

## 這支在防什麼

MinerU 會把 `∂` 的曲線讀成「某個字母戴帽子」——`\hat{\sigma}`、`\hat{\alpha}`、
`\widehat{\mathcal{D}}`…。它**不刪字、不改型別**，所以漏字檢查（覆蓋率永遠
100%）與 preflight（型別沒變）都抓不到，可以完全安靜地進索引。

## 判準的演進（三代，每一代都是被前一代的失敗逼出來的）

1. **枚舉符號**（`scan_partial.py`）：列一張 TOKENS 清單去找。
   失敗方式：族還會不會再長，它答不出來。清單從 4 個長到 9 個再到 14 個。
2. **位置封閉 ＋ 白名單**（`scan_partial_closed.py`）：改以「站在算子位置上」
   為錨，再用一張「已定案真符號」清單排除誤報。
   失敗方式：**白名單是枚舉換了個方向。** 實測 2026-08-03，白名單用完整字串
   比對，於是 `\bar{c}` 與 `\overline{\mathsf{c}}`、`\tilde{\rho}` 與
   `\widetilde{\rho}` 被當成不同條目；27 種「未定案」裡有一半只是同一個符號的
   不同寫法。擴到 390 份只會更長，而**永遠很長的殘留清單就不是殘留清單**。
3. **位置 ＋ 上下同形**（本檔）：不需要任何清單。

## 為什麼「上下同形」抓得到而且不誤報

誤讀來自 `∂p/∂z` 這種導數式，而 MinerU 是**整份一致地**讀錯——實測 1,044 筆
歷史誤讀裡 927 筆是同一個 `\hat{\sigma}`。所以兩個 ∂ 會變成**同一個** token，
分子分母各一個。真的 c̄、ρ̄、D̄ 不會長成這樣：沒有人寫 `c̄x / c̄y`。

實測（拿修補前的 `partial-hits.json` 1,044 筆真誤讀當正例，
今天已修補資料的 105 筆合法符號當負例）：

    同一 token 出現在【兩側】        召回 868/1044 (83.1%)
    同一 token 在 pattern 出現 ≥2 次  召回 962/1044 (92.1%)
    對今天的合法符號                  誤報 0

**先前的白名單知識沒有丟**，改成本檔末尾的註解——那是花時間換來的判斷，
但不再參與判定。

## 試過又撤回的規則（別再想一次）

- **「被微分量不能又是 accent」**：本來想用它濾掉 `\frac{ρ̄f̄}{ρ̄}`（Favre 平均
  的比值，ρ̄ 合法地上下同形）。實測誤報確實歸零，但**代價是把 `∂v̄_j/∂x`、
  `∂²𝔭/∂x_i` 這類「對平均量或花體量微分」整片變成盲區**——而那正是 N Flow
  紊流章節最常見的寫法，也是最容易出錯的地方。1 個誤報換一個盲區，不划算。
  正例從 425 掉到 410、少了一整種 token，就是這麼掉的。
- **「分數對面那側有真 `\partial`」**：實測召回只有 5.1%。因為 MinerU 是
  **整份一致地**讀錯，兩側的 ∂ 會變成同一個錯 token，「對面留著真 ∂」幾乎
  不發生。

## 2026-08-12 的兩個更新

- **「對今天的合法符號誤報 0」那句話不再成立。** `N Flow Acoustics` 第 149 項的
  `(ρ̄f̄)/ρ̄` 是 Favre 平均的定義式，上下同形成立但 ρ̄ 是真的平均密度。
  補上「**分母那側要有被微分量**」之後歸零。⚠ 判準**不對稱**：分子可以是光禿禿
  的算子（`∂/∂t`），寫成「兩側都要」會殺掉三分之一的真誤讀（實測 62 → 41）。
- **行內除法已覆蓋**（原本列在「已知未覆蓋」）。實測 11 處候選、逐處看過原文，
  10 真 1 假；判準沿用 `hit_tokens`，新增的只有「怎麼找到兩側」。
  ⚠ 分子必須**剛好剖析完**到斜線為止 —— 往左找跨過 `\approx` 就會抓成
  `x̄ ≈ x`（那個假的就是這樣來的）。

## 已知未覆蓋

- 單側重複（同一 token 在同一側出現兩次、另一側沒有）：規則放寬到「≥2 次」
  可多抓 94 筆，但那會讓「同側兩個獨立導數」型的合法式子進來。目前取嚴。
- **同一個 ∂ 被讀成兩個不同字母**（分子 `D̂`、分母 `Ô`）：上下同形永遠看不到。
  ⚠ 不要靠放寬這條規則去抓 —— 放寬等於「任何 accent 對 accent 的分數都算導數」，
  而真的比值就是長那樣（Favre 與 Biot 兩個誤報都是這個形狀）。
  已知案例記在 `docs/partial-review-20260812.md`，量還沒數過。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mineru_common import add_workspace_arg, load_env  # noqa: E402
from pp.paths import DEFAULT_DATA_ROOT, DataPaths  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
FIELDS = ("text", "content", "body", "code_body", "table_body")
FRAC = re.compile(r"\\[cdt]?frac\b")

# 錨點是**類別**不是符號清單。類別的邊界由**觀察到的誤讀**決定，不是「所有可能
# 的命令」：兩輪下來 MinerU 把 ∂ 讀成的東西一律是「accent 蓋在某個字母上」或
# 「裸的花體大寫」。`\dot`／`\vec`／裸 `\boldsymbol`／`\pmb` **不在**這一族
# （沒有任何一處觀察到），而它們是常見的合法記號（Ṁ 質量流率、p⃗、粗體向量）。
ACCENT = ("hat", "widehat", "bar", "overline", "tilde", "widetilde")
SCRIPT = ("mathcal", "mathfrak", "mathscr")
CAND = re.compile(r"^\\(" + "|".join(ACCENT + SCRIPT) + r")\s*\{")

# 寫法正規化：`\overline{\mathsf{c}}` 與 `\bar{c}` 是同一個符號。上下同形要比的
# 是「同一個符號」，不是「同一串字元」——不正規化的話 MinerU 在分子分母用了
# 不同字體命令就會被判成不同 token，規則直接失效。
_SYNONYM = {"overline": "bar", "widetilde": "tilde", "widehat": "hat"}
_FONT = re.compile(r"\\(math(rm|sf|bf|it|tt|frak|cal|scr)|bf|rm|sf|it|boldsymbol|pmb)\s*")


# accent 底下必須是**單一原子**（一個字母或一個 \命令），才可能是被讀錯的 ∂
# ——∂ 是一個字形，讀錯之後也只會是一個字形戴帽子。accent 蓋在整段運算式上
# （`\overline{v_1' v_2'}`、`\overline{[∂²T/∂t²]…}`）是**系綜平均**，不同族。
_ATOM = re.compile(r"^(\\[A-Za-z]+|[A-Za-z0-9])$")


def canon(tok: str) -> str | None:
    r"""正規化成可比較的形式；不是「accent 蓋單一原子」就回 None（不是候選）。

    **不剝下標。** 剝了會讓 `ρ̃_ss` 與 `ρ̃_ff` 變成同一個 token，於是
    `\frac{ρ̃_ss}{ρ̃_ff}`（Biot 參數的比值）被誤判成上下同形。
    實測 2026-08-03：這一個錯誤就製造了 15 處誤報中的 13 處。
    上標則要剝——`∂²` 寫成 `\hat{\sigma}^{2}`，那是同一個算子。
    """
    t = re.sub(r"\s+", "", tok)
    m = re.match(r"^\\([A-Za-z]+)\{(.*)\}$", t, re.S)
    if not m:
        return None
    cmd, inner = m.group(1), m.group(2)
    cmd = _SYNONYM.get(cmd, cmd)
    inner = _FONT.sub("", inner)
    inner = re.sub(r"^\{+|\}+$", "", inner).strip()
    if not _ATOM.match(inner):
        return None                      # 蓋在運算式上 → 系綜平均，不是候選
    return f"\\{cmd}{{{inner}}}"


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


def match_brace(s: str, i: int) -> int:
    d = 0
    while i < len(s):
        if s[i] == "\\":
            i += 2
            continue
        if s[i] == "{":
            d += 1
        elif s[i] == "}":
            d -= 1
            if d == 0:
                return i + 1
        i += 1
    return -1


def read_unit(s: str, i: int) -> tuple[str, int]:
    r"""讀一個 top-level 單元：`\cmd` ＋其後緊接的 `{…}`，或一個 `{…}` 群組，
    或單一字元。"""
    while i < len(s) and s[i].isspace():
        i += 1
    if i >= len(s):
        return "", i
    start = i
    if s[i] == "\\":
        m = re.match(r"\\[A-Za-z]+|\\.", s[i:])
        i += len(m.group())
        j = i
        while j < len(s) and s[j].isspace():
            j += 1
        if j < len(s) and s[j] == "{":
            e = match_brace(s, j)
            if e > 0:
                i = e
    elif s[i] == "{":
        e = match_brace(s, i)
        i = e if e > 0 else i + 1
    else:
        i += 1
    return s[start:i], i


def skip_scripts(s: str, i: int) -> int:
    while True:
        j = i
        while j < len(s) and s[j].isspace():
            j += 1
        if j < len(s) and s[j] in "^_":
            _, i = read_unit(s, j + 1)
            continue
        return i


def frac_sides(s: str, k: int) -> tuple[str, str] | None:
    r"""從 `\frac` 的結尾位置讀出兩側。兩側都可以是 `{…}` 或裸單元
    （截斷式的尾巴不會有 `{`，配對括號掃描原本在那裡直接放棄）。"""
    a, i = read_unit(s, k)
    if not a:
        return None
    i = skip_scripts(s, i)
    b, _ = read_unit(s, i)
    if not b:
        return None
    return (a[1:-1] if a.startswith("{") else a,
            b[1:-1] if b.startswith("{") else b)


class Op(NamedTuple):
    """一個站在算子位置上的候選：正規化後的 token、後面有沒有被微分量、原字串的範圍。

    範圍是**修補**要用的：判斷與修補共用同一個剖析，兩邊才不會各自漂移。
    """

    token: str
    has_operand: bool
    start: int
    end: int


def side_operators(side: str) -> list[tuple[str, bool]]:
    """站在算子位置上的候選 token（不管剖析到哪裡為止）。見 `parse_side`。"""
    return [(o.token, o.has_operand) for o in parse_side(side)[0]]


def parse_side(side: str) -> tuple[list[Op], int]:
    r"""這一側站在算子位置上的候選 token、它後面有沒有被微分量，**以及剖析到哪裡為止**。

    「剖析到哪裡」是斜線那條路要用的：行內的 `A / B` 沒有括號界定分子從哪裡開始，
    所以要能判斷「我抓的這一段是不是剛好就是分子」。剖不完代表抓過頭了
    —— `x̄ ≈ x` 那個誤報就是跨過 `\approx` 抓來的。

    「後面有沒有東西」是 2026-08-12 補的，用來擋這個誤報（`N Flow Acoustics` 第 149 項）：

        f̃ᶠ = (ρ̄ f̄) / ρ̄      「filtered part of f」——密度加權平均的定義式

    上下同形成立（兩側都是 ρ̄），但那是真的平均密度，改掉就是毀資料。
    分辨的關鍵是**真導數的兩側都有被微分量**（`∂p` 對 `∂n`），
    而這裡分母只有孤零零一個 ρ̄。

    ⚠ 上標算數：`∂²/∂t²` 的分子是 `ô^2`，後面接的是次方不是被微分量，
    但它仍然是算子（`canon` 的說明也寫著上標要剝）。
    """
    out: list[Op] = []
    i = 0
    # ⚠ **`consumed` 只在整輪成功之後才前進。** 直接回傳 `i` 是錯的：
    # 迴圈一開頭就把 `i` 推到那個單元後面，於是「因為它不是算子而中斷」的那個
    # 單元也被算成剖析完了。`x̄ ≈ x` 那個誤報就是這樣溜過去的 —— 中斷在 `x`，
    # 但回報的位置已經越過 `x`，看起來剛好剖析完。
    consumed = 0
    while i < len(side):
        u, ni = read_unit(side, i)
        if not u:
            break
        after = skip_scripts(side, ni)
        had_script = after != ni
        token: str | None = None
        if norm(u) == r"\partial":
            pass                        # 真算子：吃掉被微分量，下一格仍是算子位
        elif CAND.match(u):
            # **帶下標的 accent 不是算子**：算子不帶下標，`ρ̃_ss` 那種是具名的量。
            j = ni
            while j < len(side) and side[j].isspace():
                j += 1
            if j < len(side) and side[j] == "_":
                break
            token = canon(u)
            if token is None:
                break                   # 蓋在運算式上（系綜平均）→ 不是這一族
        else:
            break                       # 其餘（一般變數、\rho、\left…）不是這一族
        i = after
        operand, i2 = read_unit(side, i)
        i = skip_scripts(side, i2)
        consumed = i
        if token is not None:
            out.append(Op(token, bool(operand) or had_script, ni - len(u), ni))
    return out, consumed


# ── 行內斜線（2026-08-12 加）────────────────────────────────────────────────
# `∂p/∂n` 不一定寫成 `\frac`，很多時候是行內的斜線。原本只看 `\frac`，於是
# 這一整族**完全看不見**，而且掃描結果不會提醒你它漏了什麼。
# 全庫實跑 11 處候選，逐處看過：10 處真、1 處假。
SLASH = re.compile(r"(?:\\(?:bigg?|Bigg?)\s*)?/")
ACC_START = re.compile(r"\\(?:" + "|".join(ACCENT) + r")\s*\{")


def slash_sides(s: str, start: int, after: int) -> tuple[str, str] | None:
    r"""行內斜線的分子與分母；抓不到分子就回 None。

    ⚠ **分子必須剛好剖析完。** 行內斜線沒有括號界定分子從哪裡開始，只能往左找；
    找過頭就會抓到別的式子。`$1 + x / \bar{x} \approx x / \bar{x}$` 就是這樣被
    誤判的 —— 往左抓成 `x̄ ≈ x`，而真正的分子只有 `x`（那是比值不是導數）。
    """
    base = max(0, start - 90)
    window = s[base:start]
    for m in reversed(list(ACC_START.finditer(window))):
        left = window[m.start():]
        toks, used = parse_side(left)
        if len(toks) != 1:
            continue                    # 分子只該有一個算子
        if left[used:].strip(" {}$"):
            continue                    # 剖不完 ⇒ 抓過頭了，這不是它的分子
        return left, s[after:after + 90]
    return None


def slash_findings(s: str) -> list[tuple[int, str]]:
    """（斜線位置, 誤讀 token）。判準完全沿用 `hit_tokens`，只有找兩側的方式不同。"""
    out: list[tuple[int, str]] = []
    for m in SLASH.finditer(s):
        sides = slash_sides(s, m.start(), m.end())
        if sides:
            out.extend((m.start(), tok) for tok in hit_tokens(*sides))
    return out


def slash_hits(s: str) -> list[str]:
    return [tok for _, tok in slash_findings(s)]


def hit_tokens(num: str, den: str) -> list[str]:
    r"""兩側都站在算子位置、**而且分母那一側有被微分量**的 token —— 那才是誤讀的 ∂。

    **判準是不對稱的，這一點很容易寫錯。** 分母一定有被微分量（`∂t`、`∂x_i`、`∂n`），
    分子可以只有一個光禿禿的算子 —— `∂/∂t` 就是這樣，被微分的量寫在分數外面，
    而那是最常見的寫法。

    ⚠ 2026-08-12 第一版寫成「**兩側**都要有被微分量」，當場殺掉 20 處真誤讀
    （62 → 41）。那 20 處全是 `∂/∂t`、`∂/∂x_i` 這個形狀。

    要擋的只有分母光禿禿的那種：`(ρ̄ f̄) / ρ̄` 是 Favre 平均的定義，不是導數。
    """
    def collect(side: str) -> dict[str, bool]:
        seen: dict[str, bool] = {}
        for tok, has_operand in side_operators(side):
            seen[tok] = seen.get(tok, False) or has_operand
        return seen

    left, right = collect(num), collect(den)
    return sorted(t for t in left.keys() & right.keys() if right[t])


def _content_spans(s: str, k: int) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """`frac_sides` 的位置版：兩側**內容**在原字串裡的範圍（外層大括號不算）。"""
    def inner(span: tuple[int, int], text: str) -> tuple[int, int]:
        return (span[0] + 1, span[1] - 1) if text.startswith("{") else span

    a, i = read_unit(s, k)
    if not a:
        return None
    a_span = (i - len(a), i)
    i = skip_scripts(s, i)
    b, j = read_unit(s, i)
    if not b:
        return None
    return inner(a_span, a), inner((j - len(b), j), b)


def repair_text(s: str) -> tuple[str, int]:
    r"""把**被判定為誤讀的那些位置**換成 `\partial`；回傳（新文字, 換了幾處）。

    **判斷與修補共用同一個剖析**（`parse_side` 回報 token 的位置），所以修補
    動到的就是探針報出來的那些格子，一個不多一個不少。

    ⚠ **這裡刻意不認字元。** `pp/rules/latex_fix.py` 的 `fix_partial` 認的是一張
    token 清單，而它自己的說明寫著「`\hat{c}` 全母體 9 處裡有 3 處是真的遞迴係數
    ĉ_n，盲目換成 ∂ 會直接毀掉它」—— 所以**不能把別的 token 加進那張清單**。
    這裡改的是位置不是字元：同一段文字裡的 `ĉ_n` 不會被波及，因為它沒有站在
    算子位置上。

    ⚠ `\bar{\partial}` 也走這條：整個 token 被換成 `\partial`，效果就是
    「把多出來的那條槓拿掉」（原圖上 ∂ 頭上是乾淨的）。
    """
    spans: set[tuple[int, int]] = set()

    def collect(base: int, side: str, toks: set[str]) -> None:
        for op in parse_side(side)[0]:
            if op.token in toks:
                spans.add((base + op.start, base + op.end))

    if "frac" in s:
        for m in FRAC.finditer(s):
            got = _content_spans(s, m.end())
            if not got:
                continue
            (a0, a1), (b0, b1) = got
            num, den = s[a0:a1], s[b0:b1]
            toks = set(hit_tokens(num, den))
            if toks:
                collect(a0, num, toks)
                collect(b0, den, toks)
    if "/" in s:
        for m in SLASH.finditer(s):
            sides = slash_sides(s, m.start(), m.end())
            if not sides:
                continue
            left, right = sides
            toks = set(hit_tokens(left, right))
            if toks:
                collect(m.start() - len(left), left, toks)
                collect(m.end(), right, toks)

    if not spans:
        return s, 0
    out: list[str] = []
    last = n = 0
    for a, b in sorted(spans):
        if a < last:
            continue                    # 重疊：同一處被兩條路徑各找到一次
        out.append(s[last:a])
        out.append(r"\partial")
        last = b
        n += 1
    out.append(s[last:])
    return "".join(out), n


def repair_bundle(root: Path, *, stamp: str) -> tuple[int, int]:
    """把修補落地到 `root` 底下每一份 `*.mineru_raw/content_list.json`。

    回傳（動到幾個項目, 換掉幾個 token）。

    寫回的慣例跟 `pp/rules/latex_fix.py` 的 `apply_to_items` 一樣，**不另立一套**：
    原文進 `_pp_original_<欄位>`（`setdefault`，只記第一次）、蓋 `_pp_repaired_at`。
    「只記第一次」很重要 —— 人工裁定過的項目原文早就記好了，被這一輪蓋掉的話
    就只退得回「這一輪之前」，退不回真正的原始解析結果。

    ⚠ 只寫真的有改動的檔案。沒改到的項目不蓋章，否則查帳時分不出
    「這一輪動過它」與「這一輪只是掃過它」。
    """
    n_items = n_tokens = 0
    for d in sorted(root.glob("*.mineru_raw")):
        cl = d / "content_list.json"
        if not cl.is_file():
            continue
        items = json.loads(cl.read_text(encoding="utf-8"))
        touched = False
        for it in items:
            for f in FIELDS:
                v = it.get(f)
                if not isinstance(v, str):
                    continue
                new, k = repair_text(v)
                if not k:
                    continue
                it.setdefault(f"_pp_original_{f}", v)
                it[f] = new
                it["_pp_repaired_at"] = stamp
                n_items += 1
                n_tokens += k
                touched = True
        if touched:
            cl.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    return n_items, n_tokens


# `side_tokens` 於 2026-08-12 刪除（原本在這裡）。
# 它與 `side_operators` 是同一套剖析，只差沒回報「後面有沒有被微分量」——
# 留著就是第二份會各自漂移的解析器。這個專案已經被「兩條路」咬過一次
# （十二道閘門裡 V1／V2 在兩個地方各寫一份，其中一份沒人叫）。
# 要拿舊行為就是 `[t for t, _ in side_operators(side)]`。


def scan(root: Path) -> tuple[list[dict], list[dict]]:
    """回傳（疑似誤讀, 剖析不了的 frac）。"""
    hits: list[dict] = []
    bad: list[dict] = []
    for d in sorted(root.glob("*.mineru_raw")):
        doc = d.name.removesuffix(".pdf.mineru_raw")
        cl = d / "content_list.json"
        if not cl.is_file():
            continue
        for n, it in enumerate(json.loads(cl.read_text())):
            for f in FIELDS:
                v = it.get(f)
                if not isinstance(v, str):
                    continue
                if "frac" in v:
                    for m in FRAC.finditer(v):
                        r = frac_sides(v, m.end())
                        if not r:
                            bad.append({"doc": doc, "item": n, "field": f,
                                        "off": m.start(), "ctx": v[m.start():m.start() + 70]})
                            continue
                        # **判準**：同一個（正規化後的）token 同時站在分子與分母的
                        # 算子位置上，**而且分母那側有被微分量** → 導數形狀 → 疑似 ∂。
                        # 後半是 2026-08-12 補的，擋掉 Favre 平均那個誤報。
                        for tok in hit_tokens(*r):
                            hits.append({"doc": doc, "item": n, "field": f, "token": tok,
                                         "off": m.start(), "ctx": v[m.start():m.start() + 90]})
                # 行內斜線寫法。**判準完全沿用上面那個**，只有找兩側的方式不同。
                if "/" in v:
                    for off, tok in slash_findings(v):
                        hits.append({"doc": doc, "item": n, "field": f, "token": tok,
                                     "off": off, "form": "slash",
                                     "ctx": v[max(0, off - 60):off + 60]})
    return hits, bad


BASELINE = REPO / "tests" / "scan-partial-baseline.json"


def tally(hits: list[dict]) -> dict[str, dict[str, int]]:
    """（文件 → token → 處數）。

    **不記位置。** 位置會隨任何一次補格／修補整段位移，那樣每次都是漂移，
    等於沒有基準（`canary` 也是比每份文件的數字，不是比位元組偏移）。
    """
    out: dict[str, dict[str, int]] = {}
    for h in hits:
        out.setdefault(h["doc"], {}).setdefault(h["token"], 0)
        out[h["doc"]][h["token"]] += 1
    return {d: dict(sorted(t.items())) for d, t in sorted(out.items())}


def main() -> int:
    env = load_env(REPO)
    ap = argparse.ArgumentParser(description="∂ 誤讀探針：上下同形判定＋基準漂移")
    add_workspace_arg(ap, env)
    ap.add_argument("--root", type=Path,
                    default=Path(env.get("DATA_ROOT", str(DEFAULT_DATA_ROOT))))
    ap.add_argument("--details", action="store_true", help="逐處印出上下文")
    ap.add_argument("--update", action="store_true", help="把目前結果認可為新基準")
    ap.add_argument("--repair", action="store_true",
                    help="把命中的位置換成 \\partial 並寫回 content_list.json"
                         "（原文留在 _pp_original_*）")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    parsed = DataPaths(a.root).parsed_dir
    if not parsed.is_dir():
        sys.exit(f"找不到 {parsed}")

    if a.repair:
        # 先掃一次再修，讓「改之前有幾處」留在輸出裡 —— 事後要對帳只有這個數字。
        before, _ = scan(parsed)
        stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        n_items, n_tokens = repair_bundle(parsed, stamp=stamp)
        after, _ = scan(parsed)
        print(f"修補前命中 {len(before)} 處")
        print(f"改動 {n_items} 個項目、{n_tokens} 個 token（原文留在 _pp_original_*，"
              f"時間戳 {stamp}）")
        print(f"修補後命中 {len(after)} 處")
        if after:
            print("⚠ 沒有歸零 —— 有東西沒被修到，先別重建索引，回頭看是什麼", file=sys.stderr)
            return 1
        print("⚠ 這只改了解析結果。知識庫要等 reindex 才會反映。")
        return 0

    hits, bad = scan(parsed)
    cur = tally(hits)
    ndocs = len(list(parsed.glob("*.mineru_raw")))

    if a.update:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(
            {"workspace": a.workspace, "docs_scanned": ndocs,
             "unparsed_frac": len(bad), "hits": cur},
            ensure_ascii=False, indent=1, sort_keys=True) + "\n")
        print(f"基準已更新 → {BASELINE}")
        print(f"  {sum(sum(t.values()) for t in cur.values())} 處、"
              f"{len({k for t in cur.values() for k in t})} 種 token")
        print("記得在 commit 訊息說明每一個數字為什麼變 —— 沒說明的變動"
              "等同未被察覺的漂移。")
        return 0

    if a.json:
        print(json.dumps({"workspace": a.workspace, "hits": hits,
                          "unparsed": bad, "tally": cur}, ensure_ascii=False, indent=1))
    else:
        by_tok: dict[str, list[dict]] = {}
        for h in hits:
            by_tok.setdefault(h["token"], []).append(h)
        print(f"=== ∂ 誤讀探針（上下同形）：{a.workspace} ===")
        print(f"掃過 {ndocs} 份；命中 {len(by_tok)} 種 token、{len(hits)} 處；"
              f"剖析不了的 frac {len(bad)} 處\n")
        for tok, xs in sorted(by_tok.items(), key=lambda kv: -len(kv[1])):
            docs = sorted({x["doc"] for x in xs})
            print(f"  {tok!r:30s} {len(xs):4d} 處　{', '.join(d[:28] for d in docs)}")
            for x in (xs if a.details else xs[:3]):
                print(f"        {x['doc'][:26]} #{x['item']} {x['field']}@{x['off']}　{x['ctx']}")

    # ── 與基準比對 ───────────────────────────────────────────────────
    # 為什麼是基準而不是「命中就報」：有些命中**結構上不可分**——
    # `\frac{ρ̄f̄}{ρ̄}`（Favre 平均）與 `\frac{∂}{∂x}` 的形狀完全鏡像，
    # 沒有結構差異可用。硬要濾掉它會連 `∂v̄/∂x` 一起濾（試過，見 docstring）。
    # 所以照 canary 的辦法：**記下現況，冒出新的才響**。
    if not BASELINE.is_file():
        print(f"\n沒有基準檔 {BASELINE}")
        print("先逐條看過目前的命中，確認每一筆都是已知的合法情形，再跑 --update。")
        return 3                      # 未設定 ≠ 通過，也 ≠ 漂移
    base = json.loads(BASELINE.read_text()).get("hits", {})

    drift: list[str] = []
    for doc in sorted(set(base) | set(cur)):
        b, c = base.get(doc, {}), cur.get(doc, {})
        for tok in sorted(set(b) | set(c)):
            if b.get(tok, 0) != c.get(tok, 0):
                drift.append(f"  {doc[:34]:<36}{tok!r:26s} {b.get(tok,0)} → {c.get(tok,0)}")
    if drift:
        print(f"\n**漂移 {len(drift)} 項** —— 冒出基準沒有的東西，停下回報：")
        print("\n".join(drift))
        print("\n若是預期中的改動，逐條確認後跑 `--update`，"
              "並在 commit 訊息說明每個數字為什麼變。")
        return 2
    print("\n與基準相同：沒有新的上下同形算子。")
    return 0


# ── 前兩代白名單累積的判斷（保留當文件，不再參與判定）────────────────────
# 這些 token 曾被逐一裁決為「真符號，不是誤讀的 ∂」。上下同形規則之下它們
# 本來就不會被報（沒有人寫 c̄x/c̄y），所以不需要排除清單——但這些判斷是花
# 時間換來的，刪掉就沒了。
#
#   \bar{c}              真 c̄／c̄_p（#724 #766 #957 #1123）
#   \bar{\mathrm{D}}     真物質導數 D̄/Dt（#187 #692）
#   \bar{\mathbf{D}}     真物質導數 D̄/Dt（#726）
#   \mathrm{D} \mathbf{D} \mathrm{Dt} \mathbf{Dt}   真物質導數（#494 #942 #947）
#   \tilde{\rho} \bar{\rho} \bar{\Psi}              真 ρ̃ ρ̄ Ψ̄
#   \mathfrak{O}         孔隙率符號 𝔒（C，非算子位置）
#   \mathcal{O}          大 O 複雜度記號（2026-JAX-BEM #60）
#                        ——注意它**同時**出現在誤讀清單裡（\hat{\mathcal{O}}），
#                        所以「這個 token 是不是真符號」本來就不能只看 token，
#                        必須看位置與形狀。這正是換成規則的理由。

if __name__ == "__main__":
    sys.exit(main())
