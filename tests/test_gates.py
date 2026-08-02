#!/usr/bin/env python3
"""兩道寫入閘門的自測。`python3 tests/test_gates.py`（不需要 pytest、不碰磁碟資料）。

為什麼要有這支：這兩道閘門是**規則被放寬的地方**，而放寬的規則沒有測試就只剩
註解在守著。三個案例對應 c-tables-disputes §7.1／7.2 定案的三條邊界：

    捏造的外部網址        → 擋下（閘門存在的理由；qwen 交出過 8 個 imgur 網址）
    與現值逐位元相同的參照 → 放行（定點補格的前提：現值對的格一個字不動）
    動到現值的非空位元組   → 擋下（curated 補格只加不改）

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


if __name__ == "__main__":
    print("閘門自測")
    case("1 捏造的圖片參照被擋下", t_fabricated_url)
    case("2 與現值逐位元相同的既有本地參照放行", t_existing_local_img)
    case("3 動到現值非空位元組的裁定檔被擋下", t_additive_only)
    if FAILED:
        sys.exit(f"\n{len(FAILED)} 個案例失敗：{FAILED}")
    print("\n3 個案例全部通過。")
