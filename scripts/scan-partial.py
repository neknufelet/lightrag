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
                    default=Path(env.get("DATA_ROOT", "/data/rag/lightrag")))
    ap.add_argument("--details", action="store_true", help="逐處印出上下文")
    ap.add_argument("--update", action="store_true", help="把目前結果認可為新基準")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    parsed = a.root / a.workspace / "inputs" / a.workspace / "__parsed__"
    if not parsed.is_dir():
        sys.exit(f"找不到 {parsed}")
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
