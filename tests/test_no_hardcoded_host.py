"""「腳本一律從 `BIND_ADDR` 讀，不要寫死 localhost」要有執行者（`.env.example:333`）。

**為什麼需要**：這條規則 2026-08-03 就寫在 `.env.example` 裡了，而 2026-08-08
當天新寫的 `context-budget.py` 照樣寫死 `localhost`，第一次跑就 connection
refused —— 服務綁在 `BIND_ADDR`（dker 上是 Tailscale 位址），不在 loopback。
**寫在文件裡而沒有東西在守，等級就是「沒有人」。**

**判準的難處是四種用法長得一模一樣**：

    env.get("BIND_ADDR", "127.0.0.1")          備援預設 —— 正是規則要的寫法
    oracle.py("...http://localhost:9621...")   在**容器內**執行，localhost 才對
    code = "...localhost..."; oracle.py(code)  同上，只是先存進變數
    \"\"\"...從 host 打 127.0.0.1 會連不上\"\"\"  docstring 在解釋這件事
    base = "http://localhost:9621"             ← 只有這種是錯的

所以不能用 grep 數命中（實測 19 處命中、0 處違規）。判準看的是**這個字面值
被交給誰**：`.get()` 的第二個參數是備援；`Oracle.py()`／`Oracle.sh()` 收到的
（直接傳、或先存成變數再傳）是容器內要跑的碼——那兩支就是 `docker exec` 的
入口（`pp/oracle.py:155,185`）。

⚠ **docstring 是字串字面值，不是註解**，AST 看得到它。第一版就是在這裡假紅燈：
`chunk_top_k_effect` 的 docstring 正在說明「在容器內打 localhost」而被判違規。
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"

LOOPBACK = ("localhost", "127.0.0.1")

# `docker exec` 進容器執行的入口（`pp/oracle.py:155,170,185`）。收到的字串是
# 容器內要跑的碼，localhost 才對。
# ⚠ 漏一個就是假紅燈：第一版漏了 `py_argv`，`chunk_top_k_effect` 立刻被誤判。
CONTAINER_CALLS = frozenset({"py", "py_argv", "sh"})
# 再加上 `.get()`：第二個參數是備援預設，規則要的就是這個寫法。
SANCTIONED_CALLS = CONTAINER_CALLS | {"get"}


def _parent_map(tree: ast.Module) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _docstring_ids(tree: ast.Module) -> set[int]:
    """docstring 節點的 id()。它是說明文字，不是位址。"""
    holders = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    found: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, holders) or not node.body:
            continue
        first = node.body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                and isinstance(first.value.value, str):
            found.add(id(first.value))
    return found


def _loopback_literals(tree: ast.Module) -> list[ast.Constant]:
    """真的是字串字面值、而且含 loopback 位址的節點。註解與變數名不算。"""
    return [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and any(needle in node.value for needle in LOOPBACK)
    ]


def _ancestors(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> list[ast.AST]:
    chain: list[ast.AST] = []
    current = parents.get(node)
    while current is not None:
        chain.append(current)
        current = parents.get(current)
    return chain


def _handed_to_a_sanctioned_call(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """字面值直接被交給 `.get()`／`.py()`／`.sh()`。"""
    return any(
        isinstance(parent, ast.Call)
        and isinstance(parent.func, ast.Attribute)
        and parent.func.attr in SANCTIONED_CALLS
        for parent in _ancestors(node, parents)
    )


def _container_payload_names(function: ast.AST) -> set[str]:
    """這個函式裡，最後被交給容器執行入口的變數名。"""
    names: set[str] = set()
    for node in ast.walk(function):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in CONTAINER_CALLS):
            names.update(inner.id for inner in ast.walk(node)
                         if isinstance(inner, ast.Name))
    return names


def _stored_then_sent_to_container(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """字面值先存進變數、那個變數之後被交給容器執行入口。"""
    chain = _ancestors(node, parents)
    assignment = next((item for item in chain if isinstance(item, ast.Assign)), None)
    function = next((item for item in chain
                     if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))), None)
    if assignment is None or function is None:
        return False
    targets = {name.id for target in assignment.targets
               for name in ast.walk(target) if isinstance(name, ast.Name)}
    return bool(targets & _container_payload_names(function))


def _offenders(tree: ast.Module) -> list[int]:
    """寫死 loopback 位址、而且不在正當用法裡的行號。"""
    parents = _parent_map(tree)
    docstrings = _docstring_ids(tree)
    bad: list[int] = []
    for literal in _loopback_literals(tree):
        if id(literal) in docstrings:
            continue
        if _handed_to_a_sanctioned_call(literal, parents):
            continue
        if _stored_then_sent_to_container(literal, parents):
            continue
        bad.append(literal.lineno)
    return sorted(set(bad))


def test_no_script_hardcodes_a_loopback_base_url() -> None:
    """host 端的位址一律從 `BIND_ADDR` 來。

    寫死 loopback 的失敗方式很難查：在 coder 上（服務不在這台）連不上，
    在 dker 上有時**剛好通**，於是它會活到某次換機器才爆。
    """
    offenders: dict[str, list[int]] = {}
    for path in sorted(SCRIPTS.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        lines = _offenders(tree)
        if lines:
            offenders[str(path.relative_to(ROOT))] = lines
    assert not offenders, (
        f"這些地方寫死了 localhost／127.0.0.1：{offenders}。"
        "host 端要 `env.get('BIND_ADDR', ...)`；如果本來就要在容器內跑，"
        "走 `Oracle.py()`／`Oracle.sh()`")


def test_the_scan_actually_reaches_the_sanctioned_uses() -> None:
    """控制組：正當用法必須真的被掃到（鐵則 6）。

    一個「什麼都沒找到」的掃描器與「全部合規」在畫面上長得一樣。這裡確認
    掃描器有走到檔案 —— 只要有一天它壞成永遠回空，上面那支會永遠通過而
    沒有人知道。
    """
    found = 0
    for path in sorted(SCRIPTS.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        found += len(_loopback_literals(tree))
    assert found >= 5, f"只掃到 {found} 個 loopback 字面值 —— 掃描器可能沒走到檔案"


def test_the_detector_separates_the_lookalikes() -> None:
    """五種長得一樣的用法要分得開，否則第一次假紅燈就會有人把它關掉。"""
    # 違規：host 端寫死
    assert _offenders(ast.parse('base = "http://localhost:9621"\n')) == [1]
    assert _offenders(ast.parse('base = "http://127.0.0.1:9621"\n')) == [1]
    # f-string 裡的也要抓得到 —— 那正是最常見的寫法
    assert _offenders(ast.parse('base = f"http://localhost:{port}"\n')) == [1]
    # 正當：備援預設
    assert _offenders(ast.parse('h = env.get("BIND_ADDR", "127.0.0.1")\n')) == []
    # 正當：直接交給容器執行入口
    assert _offenders(ast.parse('o.py("r=u.urlopen(\'http://localhost:9621\')")\n')) == []
    assert _offenders(ast.parse('o.sh("curl http://localhost:9621/health")\n')) == []
    # 正當：先存進變數再交給容器執行入口
    assert _offenders(ast.parse(
        "def build(self):\n"
        '    code = "curl http://localhost:9621"\n'
        "    return self.py(code)\n")) == []
    # 正當：docstring 在解釋這件事
    assert _offenders(ast.parse(
        "def f():\n"
        '    """從 host 打 127.0.0.1 會連不上。"""\n'
        "    return 1\n")) == []
    # 註解與變數名不是字串字面值，不得命中
    assert _offenders(ast.parse("# 不要寫死 localhost\nlocalhost_note = 1\n")) == []
