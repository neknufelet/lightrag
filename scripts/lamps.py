#!/usr/bin/env python3
"""全部的燈點名，並檢查每一盞有沒有「證明它會紅」的測試。

**為什麼需要這支。** 近 30 天有 17 次修補是同一個形狀：**一盞燈說了假話，
而說的假話是「綠」，所以沒有人發現。** 逐一舉例（commit）：

    7d4a878  金絲雀路徑搬家時弄丟了比對函式 —— 等於沒在比
    0b3319d  金絲雀漏了 LaTeX 四個量 —— 三條規則完全沒被守著
    6af2c80  永遠不會綠的那盞淹掉了真紅燈
    48efe50  橫幅只認 `ok` 是綠，但程式寫的是 `pass`
    24d4283  A-22 對 HuggingFace 模型 ID 全部假紅燈
    4fa4f69  A-38 讀行程環境變數，所以永遠說「沒跑」
    d9c5373  金絲雀守著 0 份卻天天說通過
    …（共 17 次）

前面十七次**每次只修一盞燈**。這支修的是**整個類別**：

    一盞燈被寫出來 → 沒有人證明過它會紅 → 它壞掉時預設變綠
    ⇒ 「從來沒證明過」與「好好的」在畫面上長得一模一樣

真的火災警報器都有一顆測試鈕，按下去會叫。這裡的燈沒有。這支就是那顆鈕：

    1. 名冊　　全部的燈**自動**列出來（手寫的名冊本身就是下一個 bug）
    2. 證明　　測試上標 `@pytest.mark.proves_red("<燈的編號>")` 表示
               「這條測試證明了那盞燈會紅」
    3. 守門　　`tests/test_lamp_coverage.py` 在有燈沒有證明時**讓 commit 失敗**，
               而現在證明不了的先進棘輪清單 `tests/lamp-unproven.json`，
               **那份清單只能變短不能變長**

⚠ **標記不等於證明，這支查不出來。** 它只知道「有沒有人宣稱證明過」。
宣稱是假的仍然要靠 review —— 但「連宣稱都沒有」現在會當場擋下來，
而那正是十七次裡每一次的起點。

用法：
    ./scripts/lamps.py              # 印全部的燈與證明狀態
    ./scripts/lamps.py --unproven   # 只印還沒有人證明會紅的
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
TESTS = REPO / "tests"

#: 標在測試上的記號：`@pytest.mark.proves_red("canary")`。
PROOF_MARKER = "proves_red"


@dataclass(frozen=True)
class Lamp:
    """一盞會亮的燈。`lamp_id` 是它在名冊與測試標記裡的唯一名字。"""

    lamp_id: str
    family: str
    what: str


def _module_constant(path: Path, name: str) -> object:
    """從原始碼取一個模組層級常數，**不 import**。

    不 import 的理由：`compat-check.py` 與 `ledger.py` 匯入時會拉起一串相依，
    而名冊只是要點名。點名不該有副作用，否則這支自己會變成下一盞說假話的燈。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        target = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target, value = node.target.id, node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            target, value = node.targets[0].id, node.value
        if target == name and value is not None:
            return ast.literal_eval(value)
    raise LookupError(f"{path.name} 裡找不到模組層級常數 {name}")


def _contract_assertions(path: Path) -> list[tuple[str, str]]:
    """`@self.check("A-01", "hard", "描述")` 這種宣告，全部撈出來。

    ⚠ **只用第一個參數（編號）判斷這是不是一條斷言。** 第一版額外要求「說明
    必須是字串常數」，而實測 34 條裡有 7 條的說明是 f-string（`A-21`、`A-10`、
    `A-11`、`A-13`、`A-14`、`A-16`、`A-20`）—— 它們就這樣從名冊上**無聲消失**，
    「待證明」清單看起來少了 7 盞，而那看起來像進步。

    這就是 `registry_self_check()` 存在的理由，也是它抓到的第一件事
    （2026-08-21：34 個呼叫點 vs 抽出 27 條）。**寬鬆地認、嚴格地數。**
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "check" or not node.args:
            continue
        head = node.args[0]
        if not (isinstance(head, ast.Constant) and isinstance(head.value, str)
                and head.value.startswith("A-")):
            continue
        desc = node.args[2] if len(node.args) >= 3 else None
        if isinstance(desc, ast.Constant) and isinstance(desc.value, str):
            what = desc.value
        elif desc is not None:
            # f-string 之類：留原始寫法，讀得懂就夠 —— 名冊要的是「有這盞燈」。
            what = ast.unparse(desc)[:80]
        else:
            what = "（沒有說明）"
        found.append((head.value, what))
    return sorted(set(found))


def all_lamps() -> list[Lamp]:
    """名冊。**三個來源全部自動讀出來，這裡不手寫任何一盞。**"""
    lamps: list[Lamp] = []
    what = _module_constant(SCRIPTS / "check-levels.py", "WHAT")
    assert isinstance(what, dict)
    lamps += [Lamp(f"daily:{k}", "每日檢查", str(v)) for k, v in sorted(what.items())]
    lamps += [Lamp(f"contract:{aid}", "契約斷言", desc)
              for aid, desc in _contract_assertions(SCRIPTS / "compat-check.py")]
    gates = _module_constant(SCRIPTS / "ledger.py", "GATES")
    assert isinstance(gates, list)
    lamps += [Lamp(f"gate:{g}", "體檢表閘門", str(g)) for g in gates]
    return lamps


def proven_ids(tests_dir: Path | None = None) -> dict[str, list[str]]:
    """掃測試裡的 `@pytest.mark.proves_red("…")`，回 `燈 → 哪幾條測試證明的`。"""
    out: dict[str, list[str]] = {}
    for path in sorted((tests_dir or TESTS).glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for deco in node.decorator_list:
                if not isinstance(deco, ast.Call) or not isinstance(deco.func, ast.Attribute):
                    continue
                if deco.func.attr != PROOF_MARKER:
                    continue
                for arg in deco.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        out.setdefault(arg.value, []).append(f"{path.name}::{node.name}")
    return out


def registry_self_check() -> list[str]:
    """名冊自己有沒有漏數。回一串問題描述，空的就是沒問題。

    ⚠ **這一支是防名冊自己的。** `_contract_assertions` 只認字面常數的
    `self.check("A-…")` —— 哪天有人用迴圈或 f-string 加斷言，它會從名冊上
    **無聲消失**，於是「待證明」清單變短，而那看起來像進步。
    這與 `49ff127`（`ledger.py summary` 那 151 個「通過」其實是幽靈文件的）
    是同一個形狀：**母體壞掉時，數字會往好看的方向跑。**

    ⇒ 同一件事要有**兩種數法**，數不一樣就出聲。
    """
    problems: list[str] = []

    # 1. 契約斷言：AST 撈到的 A-id 數，必須等於 `self.check(` 的呼叫點總數。
    compat = SCRIPTS / "compat-check.py"
    tree = ast.parse(compat.read_text(encoding="utf-8"))
    call_sites = sum(1 for n in ast.walk(tree)
                     if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                     and n.func.attr == "check")
    extracted = len(_contract_assertions(compat))
    if call_sites != extracted:
        problems.append(
            f"compat-check.py 有 {call_sites} 個 self.check(…) 呼叫點，"
            f"但名冊只抽出 {extracted} 條 —— 有斷言用了名冊認不得的寫法，"
            f"它會從「待證明」清單上無聲消失")

    # 2. 每日檢查：`daily-check.sh` 真的餵進判準的那幾支，必須等於 `WHAT` 的鍵。
    #    少一支 ＝ 它從來沒被判過態；多一支 ＝ 它沒有白話說法也不在名冊上。
    fed = set(re.findall(r'--rc "([a-z_]+)=\$', (SCRIPTS / "daily-check.sh")
                         .read_text(encoding="utf-8")))
    what = _module_constant(SCRIPTS / "check-levels.py", "WHAT")
    assert isinstance(what, dict)
    if fed != set(what):
        problems.append(
            f"daily-check.sh 餵了 {sorted(fed)}，但判準認得的是 {sorted(what)}"
            f" —— 差集 {sorted(fed ^ set(what))}")

    # 3. 懸空的證明：標記指到名冊上沒有的燈（燈改名或刪掉了）。
    #    留著的話它會一直算作「已證明」，而那盞燈其實已經不存在。
    known = {lamp.lamp_id for lamp in all_lamps()}
    for lamp_id, where in sorted(proven_ids().items()):
        if lamp_id not in known:
            problems.append(f"證明指到不存在的燈 {lamp_id!r}（{'、'.join(where)}）")
    return problems


def proven_count() -> int:
    """名冊上**真的存在**而且有人宣稱證明過的燈數。

    ⚠ 棘輪要守的是這個數字**只增不減**，不是「待證明清單的長度只減不增」。
    後者量錯了東西：一盞燈改名 → 死條目被規則逼著刪掉 → 清單變短，
    但**沒有任何一盞燈因此變得有人守**。
    """
    proven = proven_ids()
    return sum(1 for lamp in all_lamps() if lamp.lamp_id in proven)


def unproven_lamps() -> list[Lamp]:
    """還沒有任何測試宣稱證明過「它會紅」的燈。"""
    proven = proven_ids()
    return [lamp for lamp in all_lamps() if lamp.lamp_id not in proven]


def main() -> int:
    ap = argparse.ArgumentParser(description="全部的燈點名，看誰有測試鈕")
    ap.add_argument("--unproven", action="store_true", help="只印還沒有人證明會紅的")
    a = ap.parse_args()

    lamps, proven = all_lamps(), proven_ids()
    rows = [lamp for lamp in lamps if not a.unproven or lamp.lamp_id not in proven]
    for lamp in rows:
        mark = "✅" if lamp.lamp_id in proven else "—"
        print(f"  {mark} {lamp.lamp_id:<26} {lamp.family:<8} {lamp.what[:44]}")
    n_proven = sum(1 for lamp in lamps if lamp.lamp_id in proven)
    print(f"\n共 {len(lamps)} 盞燈；有人證明會紅的 {n_proven} 盞、"
          f"沒有的 {len(lamps) - n_proven} 盞")
    return 0


if __name__ == "__main__":
    sys.exit(main())
