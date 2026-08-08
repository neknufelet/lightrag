"""`apply` 在 `LIGHTRAG_FORCE_REPARSE_MINERU` 開著時必須拒絕執行。

**為什麼這道鎖存在**：那個旗標開著時，LightRAG 在重抓解析結果前會無條件
`clear_dir_contents(raw_dir)`。於是 `apply` 寫進去的修補在下一次 scan 就被刪掉，
而索引照樣建成功、**沒有任何錯誤訊息** —— 連同整份文件 6–10 小時的解析成果一起沒。

**為什麼不能只測判讀函式**：純函式測試只能證明「字串比對是對的」，證不到
「apply 真的會停下來」。這正是本專案鐵則 7 記載的第一個實例（測到字面、沒測到
行為，到現場才當場失敗）。所以下面兩組缺一不可：判讀本身，以及 `cmd_apply`
在旗標開著時的實際退出碼。
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "postprocess.py"
sys.path.insert(0, str(ROOT / "scripts"))

from pp.oracle import force_reparse_is_on  # noqa: E402

# 「關著」的四種寫法，含大小寫與前後空白。這些必須放行，否則正常工作被擋死。
OFF_VALUES = ("", "0", "false", "no", "  ", "FALSE", " No ", "\tfalse\n")
# 「開著」以及**不認得的值**。不認得一律當開著 —— 猜錯的代價是靜默毀掉解析成果。
ON_VALUES = ("1", "true", "yes", "TRUE", "on", "2", "maybe", "0x0", "false-ish")


@pytest.mark.parametrize("value", OFF_VALUES)
def test_off_values_do_not_block(value: str) -> None:
    assert force_reparse_is_on(value) is False, f"{value!r} 應視為關著，不該擋下 apply"


@pytest.mark.parametrize("value", ON_VALUES)
def test_on_and_unknown_values_block(value: str) -> None:
    assert force_reparse_is_on(value) is True, f"{value!r} 應視為開著（不認得也算開）"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("postprocess_force_reparse", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _StubOracle:
    """只回答旗標值。被問到別的事就是設計錯了，所以其餘一律拋錯。"""

    def __init__(self, flag: str, **_: object) -> None:
        self._flag = flag
        self.asked = 0

    def force_reparse_flag(self) -> str:
        self.asked += 1
        return self._flag

    def __getattr__(self, name: str) -> object:  # pragma: no cover - 防呆用
        raise AssertionError(f"旗標開著時不該再呼叫 Oracle.{name}")


def _args() -> argparse.Namespace:
    return argparse.Namespace(workspace="test", doc=None, commit=True,
                              no_tables=False, workers=1)


def test_apply_refuses_when_flag_is_on(monkeypatch: pytest.MonkeyPatch,
                                      capsys: pytest.CaptureFixture[str]) -> None:
    """旗標開著 ⇒ 退出碼 2，而且**在讀任何 bundle 之前**就停下來。

    `find_bundles` 換成會爆的版本：鎖如果沒有先擋住，這裡就會炸開 ——
    也就是說這個測試證明的是「順序」，不只是「有印訊息」。
    """
    import pp.oracle as oracle_mod

    module = _module()
    stub = _StubOracle("1")
    monkeypatch.setattr(oracle_mod, "Oracle", lambda **kw: stub)
    monkeypatch.setattr(module, "find_bundles",
                        lambda *a, **k: pytest.fail("鎖沒擋住：已經開始找 bundle"))

    rc = module.cmd_apply(_args(), env={})

    assert rc == 2, "旗標開著時 apply 必須回非零，否則呼叫端會以為修補成功"
    assert stub.asked == 1, "旗標只該問一次容器"
    out = capsys.readouterr().out
    assert "拒絕執行" in out
    assert "LIGHTRAG_FORCE_REPARSE_MINERU" in out
    # 訊息要能直接照著做，不能只說「不行」。
    assert "--force-recreate" in out
    assert "raw cache hit" in out


def test_apply_proceeds_when_flag_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """旗標關著 ⇒ 鎖放行，流程往下走到找 bundle。

    沒有這一半，「鎖永遠擋住」也會讓上面那條通過 —— 那是把可用性換成安全，
    而且同樣不報錯。
    """
    import pp.oracle as oracle_mod

    module = _module()
    stub = _StubOracle("")
    reached: list[str] = []

    monkeypatch.setattr(oracle_mod, "Oracle", lambda **kw: stub)
    monkeypatch.setattr(module, "find_bundles",
                        lambda *a, **k: (reached.append("找了"), [])[1])

    rc = module.cmd_apply(_args(), env={})

    assert reached == ["找了"], "旗標關著時不該被擋下"
    assert rc == 0
