"""藍桶 4「不要用 print 當 log」——但 CLI 的輸出不是 log。

**為什麼不是用 ruff 的 T20**：T20 對整包開會抓到 336 處，而 2026-08-08 逐檔查證的
結果是**那 336 處全部落在 CLI 入口**，沒有一個是拿 print 當 log。也就是這條規則
其實早就滿足了，開 T20 只會製造 336 個假警報，然後逼人寫一份 18 個檔的豁免清單——
而那份清單每新增一支腳本就要維護一次，忘了加就是一片紅。

**規則的實質是「誰在說話」**：

    入口（有 `if __name__ == "__main__":`）  print 就是它給人看的輸出，正當
    模組（被別的程式 import）                 print 會污染呼叫端的 stdout，
                                              而且沒有等級、沒有時間、關不掉

所以判準寫成程式，而不是寫成一份檔案清單。檔案清單會過期，判準不會。

⚠ 用 AST 不用 grep：`grep print` 會命中字串裡的 "print"、註解、以及
`self.print_summary()` 這種方法名。判準要精確，否則第一次假紅燈就會有人把它關掉。
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


def _is_entry_point(tree: ast.Module) -> bool:
    """檔案裡有沒有 `if __name__ == "__main__":`。"""
    for node in tree.body:
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if (isinstance(test, ast.Compare)
                and isinstance(test.left, ast.Name)
                and test.left.id == "__name__"):
            return True
    return False


def _print_lines(tree: ast.Module) -> list[int]:
    """真的呼叫內建 print 的行號。"""
    return sorted(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "print"
    )


def test_library_modules_do_not_print() -> None:
    """被 import 的模組不得 print。

    模組 print 的害處不只是難看：它污染呼叫端的 stdout（本專案多支腳本用
    `--json` 把輸出餵給下一支程式），而且沒有等級、沒有時間戳、關不掉。
    """
    offenders: dict[str, list[int]] = {}
    for path in sorted(SCRIPTS.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if _is_entry_point(tree):
            continue
        lines = _print_lines(tree)
        if lines:
            offenders[str(path.relative_to(ROOT))] = lines
    assert not offenders, (
        "這些檔沒有 `if __name__ == \"__main__\":`（＝會被別人 import），"
        f"卻在裡面 print：{offenders}。改用 logging，或者它其實是入口就補上 main 區塊")


def test_the_classifier_actually_finds_both_kinds() -> None:
    """判準本身要有探針（鐵則 6）。

    如果 `_is_entry_point` 哪天壞成永遠回 True，上面那支會永遠通過而且沒有人知道。
    所以這裡斷言兩類都真的存在——只剩一類就代表分類器壞了或專案結構變了。
    """
    entries, modules = [], []
    for path in sorted(SCRIPTS.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        (entries if _is_entry_point(tree) else modules).append(path.name)
    assert entries, "一個 CLI 入口都認不出來 —— 分類器壞了"
    assert modules, "一個模組都認不出來 —— 分類器壞了"


def test_print_detector_ignores_lookalikes() -> None:
    """`print` 出現在字串、註解、或方法名裡都不算。

    grep 會把這三種都算進去。第一次假紅燈就會有人把檢查關掉，所以判準要精確。
    """
    tree = ast.parse(
        'x = "print(1)"\n'
        '# print(2)\n'
        'obj.print(3)\n'
        'printer(4)\n')
    assert _print_lines(tree) == []
    assert _print_lines(ast.parse("print(5)\n")) == [1]
