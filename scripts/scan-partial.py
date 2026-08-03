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

## 已知未覆蓋

- 行內除法（`a/b` 不走 `\frac`）：歷史 1,044 筆裡有 10 筆屬此類。上一代同樣
  沒處理。要補的話錨點是 `/` 兩側，但誤報風險高很多（任何比值都長那樣），
  **量了再說**，不要先加。
- 單側重複（同一 token 在同一側出現兩次、另一側沒有）：規則放寬到「≥2 次」
  可多抓 94 筆，但那會讓「同側兩個獨立導數」型的合法式子進來。目前取嚴。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mineru_common import add_workspace_arg, load_env  # noqa: E402

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


def side_tokens(side: str) -> list[str]:
    r"""這一側**站在算子位置上**、而且不是 `\partial` 的候選 token（已正規化）。

    「算子位置」＝式子開頭，或前一個算子單元吃掉被微分量之後的下一格。
    連續兩個誤讀算子（`∂x_i∂x_j`）要都抓得到，所以吃掉被微分量後繼續。
    """
    out: list[str] = []
    i = 0
    while i < len(side):
        u, ni = read_unit(side, i)
        if not u:
            break
        i = skip_scripts(side, ni)
        if norm(u) == r"\partial":
            pass                        # 真算子：吃掉被微分量，下一格仍是算子位
        elif CAND.match(u):
            # **帶下標的 accent 不是算子**：算子不帶下標，`ρ̃_ss` 那種是具名的量。
            # 下標在 skip_scripts 之前判斷，因為那一步會把它吃掉。
            j = ni
            while j < len(side) and side[j].isspace():
                j += 1
            if j < len(side) and side[j] == "_":
                break
            c = canon(u)
            if c is None:
                break                   # 蓋在運算式上（系綜平均）→ 不是這一族
            # **被微分量必須是普通的量，不能又是一個 accent。**
            # 導數的 ∂ 後面接變數（∂p、∂z）；而 `ρ̄ f̄ / ρ̄ ũ` 這種是**平均量的
            # 乘積比值**，兩個因子都戴帽子。實測 2026-08-03：這一條把今天資料上
            # 唯一剩下的誤報（N Flow #149 的 Favre 平均）清成 0，且不影響 425
            # 筆歷史正例（∂ 後面從來不是 accent）。
            nxt, _ = read_unit(side, i)
            if nxt and CAND.match(nxt.lstrip()):
                break
            out.append(c)
        else:
            break                       # 其餘（一般變數、\rho、\left…）不是這一族
        _, i2 = read_unit(side, i)      # 被微分量
        i = skip_scripts(side, i2)
    return out


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
                if not isinstance(v, str) or "frac" not in v:
                    continue
                for m in FRAC.finditer(v):
                    r = frac_sides(v, m.end())
                    if not r:
                        bad.append({"doc": doc, "item": n, "field": f,
                                    "off": m.start(), "ctx": v[m.start():m.start() + 70]})
                        continue
                    num, den = (side_tokens(s) for s in r)
                    # **判準**：同一個（正規化後的）token 同時站在分子與分母的
                    # 算子位置上 → 導數形狀 → 疑似被讀錯的 ∂。
                    for tok in set(num) & set(den):
                        hits.append({"doc": doc, "item": n, "field": f, "token": tok,
                                     "off": m.start(), "ctx": v[m.start():m.start() + 90]})
    return hits, bad


def main() -> int:
    env = load_env(REPO)
    ap = argparse.ArgumentParser(description="∂ 誤讀探針：上下同形判定")
    add_workspace_arg(ap, env)
    ap.add_argument("--root", type=Path,
                    default=Path(env.get("DATA_ROOT", "/data/rag/lightrag")))
    ap.add_argument("--details", action="store_true", help="逐處印出上下文")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    parsed = a.root / a.workspace / "inputs" / a.workspace / "__parsed__"
    if not parsed.is_dir():
        sys.exit(f"找不到 {parsed}")
    hits, bad = scan(parsed)

    if a.json:
        print(json.dumps({"workspace": a.workspace, "hits": hits, "unparsed": bad},
                         ensure_ascii=False, indent=1))
        return 2 if hits else 0

    by_tok: dict[str, list[dict]] = {}
    for h in hits:
        by_tok.setdefault(h["token"], []).append(h)
    print(f"=== ∂ 誤讀探針（上下同形）：{a.workspace} ===")
    print(f"掃過 {len(list(parsed.glob('*.mineru_raw')))} 份；"
          f"疑似誤讀 {len(by_tok)} 種 token、{len(hits)} 處；剖析不了的 frac {len(bad)} 處\n")
    for tok, xs in sorted(by_tok.items(), key=lambda kv: -len(kv[1])):
        docs = sorted({x["doc"] for x in xs})
        print(f"  ⚠ {tok!r:30s} {len(xs):4d} 處　{', '.join(d[:28] for d in docs)}")
        for x in (xs if a.details else xs[:4]):
            print(f"        {x['doc'][:26]} #{x['item']} {x['field']}@{x['off']}　{x['ctx']}")
    if bad:
        print(f"\n  ⚠ 剖析不了的 frac：{len(bad)} 處"
              f"（**這也是訊號**：剖析器跟不上新的排版形狀）")
        for x in bad[:6]:
            print(f"        {x['doc'][:26]} #{x['item']} {x['field']}@{x['off']}　{x['ctx']}")
    if hits or bad:
        print("\n**停下回報。** 上下同形＝導數形狀，而站在算子位置的不是 \\partial。")
        return 2
    print("乾淨：沒有上下同形的非 \\partial 算子。")
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
