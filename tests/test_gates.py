#!/usr/bin/env python3
"""寫入路徑的自測。`python3 tests/test_gates.py`（不需要 pytest、不碰磁碟資料）。

為什麼要有這支：這裡全是**規則被放寬的地方**，而放寬的規則沒有測試就只剩註解
在守著。五個案例對應 c-tables-disputes §7.1／7.2／7.4／7.5 定案的邊界：

    捏造的外部網址        → 擋下（閘門存在的理由；qwen 交出過 8 個 imgur 網址）
    與現值逐位元相同的參照 → 放行（定點補格的前提：現值對的格一個字不動）
    動到現值的非空位元組   → 擋下（curated 補格只加不改）
    `~` 當**詞**的分隔     → 只黏字母，`~`／`-`／文字模式命令一個位元組都不動
    `\\times` 只在錨點換    → 真乘號、以及病因相同但位置不同的指數 x 都不碰

閘門用 `sys.exit` 拒絕（它掛在 CLI 的寫入路徑上，拒絕就是停整批），所以測試接
`SystemExit`；`assert_additive` 在函式庫層，拒絕丟 `ApplyError`。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "postprocess", Path(__file__).resolve().parent.parent / "scripts" / "postprocess.py")
pp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pp)

from pp.apply import ApplyError, assert_additive  # noqa: E402
from pp.rules import latex_fix  # noqa: E402

# C #520 的現值第 0 列：MinerU 抽出來的電路符號圖，檔案真的在 bundle 裡。
IMG = '<img src="images/8674e6692d62c521e087bcb07373a5dc3e0bb38b9da55e6f59c3bf4bb8a28198.jpg"/>'
CUR = f'<table><tr><td colspan="2">{IMG}</td></tr><tr><td>Changes rel. to Table 16</td></tr></table>'

FAILED: list[str] = []


def case(name: str, fn) -> None:
    try:
        fn()
    except AssertionError as e:
        FAILED.append(name)
        print(f"  ✗ {name}\n      {e}")
    else:
        print(f"  ✓ {name}")


def expect_exit(body: str, current: str, want: str) -> str:
    try:
        pp.gate_table_html(body, "測試", current)
    except SystemExit as e:
        msg = str(e.code)
        assert want in msg, f"訊息裡沒有 {want!r}：{msg}"
        return msg
    raise AssertionError("閘門放行了，應該擋下")


# ── 案例 1：捏造的外部網址 ─────────────────────────────────────────────
def t_fabricated_url():
    fake = '<img src="https://i.imgur.com/5Q7XZ6l.png" alt="Diagram"/>'
    body = CUR.replace(IMG, fake)
    msg = expect_exit(body, CUR, "i.imgur.com")
    print(f"      擋下：{msg.splitlines()[0][:110]}")
    # 假的本地檔名（qwen 的另一種型態，16/57）也要擋
    msg = expect_exit(CUR.replace(IMG, '<img src="placeholder_figure_1.png"/>'),
                      CUR, "placeholder_figure_1.png")
    print(f"      擋下：{msg.splitlines()[0][:110]}")
    # 現值有一個，裁定檔放兩個 —— 多出來的那個就是新增，要擋
    msg = expect_exit(CUR.replace(IMG, IMG + IMG), CUR, "現值沒有這個參照")
    print(f"      擋下（複製既有參照當新增）：{msg.splitlines()[0][:80]}")
    # 用 `images/../` 逃出 bundle 也要擋
    expect_exit(CUR.replace(IMG, '<img src="images/../../../etc/passwd"/>'),
                CUR, "拒絕使用")


# ── 案例 2：與現值逐位元相同的既有本地參照 ────────────────────────────
def t_existing_local_img():
    body = CUR.replace("</td></tr><tr>",
                       "</td><td>A square neck with $2a$ side length…</td></tr><tr>")
    out = pp.gate_table_html(body, "測試", CUR)
    assert out == body, "放行時不該改動內容"
    print(f"      放行：保留 {IMG[:46]}… 並新增一格")
    # 同一份 HTML 在「現值沒有這個參照」時必須被擋下 —— 差別只在現值，
    # 這一條證明放行的依據真的是現值，不是 tag 長得像本地路徑。
    expect_exit(body, "", "現值沒有這個參照")
    print("      同一份內容、現值為空 → 擋下（依據確實是現值）")


# ── 案例 3：動到現值的非空位元組 ──────────────────────────────────────
def t_additive_only():
    cur = '<table><tr><td>A 2bø</td><td>with porous absorber layer.</td></tr></table>'
    ok = cur.replace("<td>with porous",
                     "<td>A round neck with $2a$ diameter, partially filled with porous")
    ins = assert_additive(cur, ok, "測試")
    assert ins and all(s.startswith("insert") for s in ins), ins
    print(f"      放行：{len(ins)} 段插入　{ins[0][:96]}")

    for name, bad in (
        ("改字", cur.replace("porous absorber", "porous ABSORBER")),
        ("刪字", cur.replace(" layer.", ".")),
        ("整表換掉", '<table><tr><td>completely different</td></tr></table>'),
    ):
        try:
            assert_additive(cur, bad, "測試")
        except ApplyError as e:
            print(f"      擋下（{name}）：{str(e).splitlines()[0][:88]}")
        else:
            raise AssertionError(f"{name} 應該被擋下")


# ── 案例 4：`~` 是**詞**的分隔，不是字母的分隔（2.5 輪的教訓）─────────
def t_tilde_is_a_word_separator():
    src = (r"\mathrm { v e c t o r ~ f r o m ~ o r i g i n ~ o f ~ "
           r"c o - o r d i n a t e s ~ t o ~ t h e ~ o b s e r v e r ~ p o i n t }")
    out, made = latex_fix.unspace(src)
    assert "vector" in made and "from" in made and "origin" in made, made
    assert "vectorfrom" not in out and "fromorigin" not in out, out
    assert out.count("~") == src.count("~"), f"`~` 被吃掉了：{out}"
    assert "co - ordinates" in out, f"`-` 沒有中斷黏合：{out}"
    print(f"      {out}")

    # `\mathrm { ~ ; ~ }`：一個單字母都沒有 → 一個位元組都不准動。
    # coverage-check 的量測版會把它壓成 `;`（量測可以，寫回資料不行）。
    for s in (r"\mathrm { ~ ; ~ }", r"\mathsf { a } ^ { 2 }", r"\begin{array} { c c }"):
        assert latex_fix.unspace(s)[0] == s, f"{s} 被動到了：{latex_fix.unspace(s)[0]}"
    print("      `\\mathrm { ~ ; ~ }`／單一字母／array 欄位規格：一個位元組都沒動")

    # 文字模式命令（空白有意義）一律不碰
    t = r"\text { w i t h }"
    assert latex_fix.unspace(t)[0] == t, latex_fix.unspace(t)[0]
    print("      `\\text{…}`（文字模式）不碰")

    # 真正要救的那一類
    assert latex_fix.unspace(r"\mathsf { t a n h }")[0] == r"\mathsf { tanh }"
    print(r"      \mathsf { t a n h } → \mathsf { tanh }")


# ── 案例 5：`\times` 只在羅馬數字下標那個位置換 ────────────────────────
def t_times_anchor():
    src = r"$Z _ { 0 } \mathsf { v } _ { \mathsf { I } \times } ( \mathsf { x } )$"
    out, n = latex_fix.fix_times(src)
    assert n == 1 and r"_ { \mathsf { I } \mathsf { x } }" in out, out
    print(f"      {out}")

    # 真的乘號、以及**病因相同但位置不同**的指數 x —— 兩者都不准碰
    for s in (r"\right] $  $ \times \left[ 1 + \frac { j } { 4 a ^ { 2 } }",
              r"\mathrm { e } ^ { - \gamma _ { n , v } \times } \cos ( \eta _ { n } y )",
              r"\right\} \times \left\{"):
        assert latex_fix.fix_times(s) == (s, 0), latex_fix.fix_times(s)[0]
    print("      真乘號、以及指數裡同病因的 x：一處都沒動（錨點外＝不在授權範圍）")


# ── 案例 6：`\hat{\sigma}` → `\partial` 只在偏微分構造裡換 ────────────────
def t_partial_anchor():
    # 自證的那一條（B #816）：同一個分數，分子讀對成 \partial、分母讀錯成 σ̂
    src = r"\partial \mathbf{k} \big/ \hat{\sigma} \mathbf{t} + \hat{\sigma} \omega \big/ \hat{\sigma} x"
    out, n = latex_fix.fix_partial(src)
    assert n == 3 and r"\hat{\sigma}" not in out, out
    assert out.count(r"\partial") == 4, out
    print(f"      {out}")

    # ∂²U/∂x²（拉普拉斯）與 Jacobi 行列式：型態不同，一樣要中
    for s, k in ((r"\frac{\hat{\sigma}^{2}U}{\hat{\sigma}x^{2}}", 2),
                 (r"\frac{\hat{\sigma}(v^{1})}{\hat{\sigma}(u^{1})}", 2)):
        assert latex_fix.fix_partial(s)[1] == k, latex_fix.fix_partial(s)

    # **錨點外的一律不碰。** 孤零零一個 σ̂ 更可能是真的「sigma hat」；
    # 沒有分數／斜線構造的成對 σ̂ 也不動（偏微分必然寫成分子分母）。
    for s in (r"\hat{\sigma} = \sqrt{\frac{1}{n}\sum x^{2}}",     # 只有一個
              r"\hat{\sigma}_{1} + \hat{\sigma}_{2}"):            # 兩個但沒有分數
        assert latex_fix.fix_partial(s) == (s, 0), latex_fix.fix_partial(s)[0]

    # **同族但不同字元的 `\hat{c}` 一個都不准碰。** 全母體 9 處裡有 3 處
    # （F #259）是真的遞迴係數 ĉ_n，換掉會毀資料 —— 一次只放寬一條錨點。
    hatc = r"\hat{c}_{1}=(1-\beta^{2}) \quad ; \quad \hat{c}_{n}=\frac{k_{0}a}{n}\cdot \hat{c}_{n-1}"
    assert latex_fix.fix_partial(hatc) == (hatc, 0), latex_fix.fix_partial(hatc)[0]
    mixed = r"\frac{\hat{c}}{\hat{\sigma} u_{1}} + \frac{\hat{c}}{\hat{\sigma} u_{2}}"
    out2, n2 = latex_fix.fix_partial(mixed)
    assert n2 == 2 and out2.count(r"\hat{c}") == 2, out2
    print("      真 σ̂、無分數的成對 σ̂、以及整族 `\\hat{c}`：一處都沒動")


if __name__ == "__main__":
    print("寫入路徑自測")
    case("1 捏造的圖片參照被擋下", t_fabricated_url)
    case("2 與現值逐位元相同的既有本地參照放行", t_existing_local_img)
    case("3 動到現值非空位元組的裁定檔被擋下", t_additive_only)
    case("4 `~` 當詞分隔，其餘位元組不動", t_tilde_is_a_word_separator)
    case("5 `\\times` 只在羅馬數字下標的位置換", t_times_anchor)
    case("6 `\\hat{\\sigma}` 只在偏微分構造裡換", t_partial_anchor)
    if FAILED:
        sys.exit(f"\n{len(FAILED)} 個案例失敗：{FAILED}")
    print("\n6 個案例全部通過。")
