r"""載入 `scripts/` 底下檔名帶連字號的腳本 —— **同一支只載一次**。

## 為什麼要有這支

檔名帶連字號的腳本（`eq-dup.py`、`scan-partial.py`…）沒辦法用一般 `import`，
所以測試都用 `spec_from_file_location` 自己建 module 再塞進 `sys.modules`。
**兩個測試檔載同一支腳本時，就會有兩個 module 物件。**

2026-08-13 被咬過一次：新測試檔用這個方式載入 `intake.py`（那支其實 import
得動），塞回 `sys.modules["intake"]` 之後，`test_intake.py` monkeypatch 的
模組層常數落在 A 物件上、被測的函式讀的是 B 物件的 —— 那支測試當場變紅，
而**紅的理由跟它要測的東西完全無關**。

⚠ 這正是專案反覆記著的「同一件事兩個地方」，連測試也不例外。差別只在於
正式碼漂移時不會報錯，而測試漂移時會紅在一個看不懂的地方。

⚠ **能一般 import 的就一般 import**（`intake.py`、`ledger.py` 這種），
不要為了統一而全部走這裡 —— 那會把一個沒問題的東西也拉進這個機制。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent


def load(name: str, filename: str) -> ModuleType:
    """載入 `scripts/<filename>`，以 `name` 註冊。**已載過就回同一個物件。**

    `name` 是註冊名（底線版，例：`eq_dup`），`filename` 是實際檔名
    （連字號版，例：`eq-dup.py`）。
    """
    if (cached := sys.modules.get(name)) is not None:
        return cached
    path = ROOT / "scripts" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if not (spec and spec.loader):
        raise RuntimeError(f"載入不了 {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
