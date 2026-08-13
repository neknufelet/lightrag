r"""兩個測試檔不准各自載入同一支腳本 —— **同一個模組兩個物件**。

2026-08-13 被咬過：新測試檔用 `spec_from_file_location` 載 `intake.py` 並塞回
`sys.modules["intake"]`，於是 `test_intake.py` monkeypatch 的模組層常數落在
A 物件、被測的函式讀 B 物件的 —— 那支當場變紅，而**紅的理由跟它要測的東西
完全無關**，查了三輪才找到。

⚠ 這是專案反覆記著的「同一件事兩個地方」，連測試也不例外。差別只在於正式碼
漂移時不會報錯，測試漂移時會紅在一個看不懂的地方。

共用載入器在 `tests/_scripts.py`（已載過就回同一個物件）。
"""
from __future__ import annotations

import collections
import re
from pathlib import Path

TESTS = Path(__file__).resolve().parent
# `spec_from_file_location("名字", …)` —— 第一個引數就是註冊名。
REGISTER = re.compile(r"spec_from_file_location\(\s*[\"'](\w+)[\"']")


def test_no_two_test_files_load_the_same_script() -> None:
    """**本檔的理由。** 同一個註冊名只准有一個檔案自己載。"""
    owners: dict[str, list[str]] = collections.defaultdict(list)
    for f in sorted(TESTS.glob("test_*.py")):
        for name in set(REGISTER.findall(f.read_text(encoding="utf-8"))):
            owners[name].append(f.name)
    clashes = {n: fs for n, fs in owners.items() if len(fs) > 1}
    assert not clashes, (
        f"這些腳本被兩個以上的測試檔各自載入：{clashes}。"
        "改用 `from _scripts import load` —— 它會回同一個物件。")


def test_the_shared_loader_returns_the_same_object() -> None:
    """控制組：載入器真的有共用，不是只是換個寫法。"""
    import sys
    sys.path.insert(0, str(TESTS))
    from _scripts import load
    assert load("eq_dup", "eq-dup.py") is load("eq_dup", "eq-dup.py")
