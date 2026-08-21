"""實地演習：在部署機上真的按一次測試鈕。

**為什麼要有演習，而且為什麼 pytest 取代不了它。** 近 30 天 17 次「燈說假話」
裡有兩族單元測試永遠抓不到：

    7d4a878  金絲雀的比對函式在路徑搬家中丟失 —— 源碼「能」紅，但跑著的那份
             根本沒在比。單元測試餵替身，替身不會跟著搬家一起壞。
    4a6e533  基準被清空成 {} —— 那是**資料操作**，當天任何 pytest 都全綠。

這一支測的是**演習本身**（三態語意、控制組不得省、分母要印）。演習真的跑起來
只能在 dker（那幾支檢查要 `.env`，coder 上刻意沒有）。
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "drill.py"

_spec = importlib.util.spec_from_file_location("drill", SCRIPT)
assert _spec and _spec.loader
drill = importlib.util.module_from_spec(_spec)
sys.modules["drill"] = drill
_spec.loader.exec_module(drill)


def test_a_lamp_that_did_not_ring_is_a_failure_not_a_pass() -> None:
    """**本檔最重要的一條。** 演習的意義全在這裡。

    弄壞了情境而燈沒紅 ⇒ 那盞燈死了 ⇒ 演習必須是失敗。回 0 的話，
    「燈死了」與「燈好好的」在 `latest.json` 上長得一模一樣 —— 那正是
    這整輪工單在修的形狀，而演習自己犯的話特別諷刺。
    """
    assert drill.DRILL_LAMP_DEAD != 0
    assert drill.DRILL_CANT_RUN != 0, "驗不了也不得回 0"
    assert drill.DRILL_LAMP_DEAD != drill.DRILL_CANT_RUN, \
        "「燈死了」與「這台驗不了」是兩件事，處置也不同"


def test_every_drill_checks_a_control_case_too() -> None:
    """只驗「壞的會紅」等於沒驗 —— 一盞天天亮的燈跟不會亮的一樣沒用。

    ⚠ 這條是文字檢查（代理），真正的保證在每場演習自己的斷言裡。
    寫不出控制組的演習不該存在。
    """
    src = SCRIPT.read_text(encoding="utf-8")
    for name in drill.DRILLS:
        fn = drill.DRILLS[name]
        body = src.split(f"def {fn.__name__}(", 1)[1].split("\ndef ", 1)[0]
        assert "控制組" in body, f"{name} 這場演習沒有控制組"


def test_every_drill_names_a_lamp_that_exists_in_the_registry() -> None:
    """演習要指向名冊上真的有的燈 —— 指到不存在的燈等於沒在演習任何東西。"""
    spec = importlib.util.spec_from_file_location("lamps_for_drill",
                                                  ROOT / "scripts" / "lamps.py")
    assert spec and spec.loader
    lamps = importlib.util.module_from_spec(spec)
    sys.modules["lamps_for_drill"] = lamps
    spec.loader.exec_module(lamps)
    known = {lamp.lamp_id for lamp in lamps.all_lamps()}

    src = SCRIPT.read_text(encoding="utf-8")
    named = {line.split('Outcome("', 1)[1].split('"', 1)[0]
             for line in src.splitlines() if 'Outcome("' in line}
    unknown = sorted(named - known - set(drill.DRILLS))
    assert not unknown, f"演習指到名冊上沒有的燈：{unknown}"


def test_the_drill_reports_its_own_denominator() -> None:
    """演習自己也是一盞燈，一樣要說「我這次演了幾場」。

    ⚠ 沒報分母的話，「一場都沒演」會跟「兩場都叫了」長得一樣 ——
    而演習正是為了消滅這種一樣。
    """
    src = SCRIPT.read_text(encoding="utf-8")
    assert "#scope" in src, "演習沒有印分母"
    assert "len(unver)" in src, "驗不了的場次不該算進分母"


def test_listing_the_drills_works_without_touching_any_data() -> None:
    """`--list` 只讀程式自己，任何機器上都跑得動。"""
    r = subprocess.run([sys.executable, str(SCRIPT), "--list"],
                       capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
    for name in drill.DRILLS:
        assert name in r.stdout, f"{name} 沒有被列出來"


@pytest.mark.proves_red("daily:drill")
def test_the_drill_lamp_itself_goes_red_when_a_lamp_did_not_ring(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """演習這盞燈自己的測試鈕：有燈沒叫時，它必須紅。

    真的跑 `drill.main([])`（不是驗分類器）—— 契約寫在 `pyproject.toml` 的
    marker 說明：**證明必須執行發訊號的那一支**。

    ⚠ 這一場的三段一次做完：
      對抗　 有一場演習回 `ok=False`（＝那盞燈死了）→ 必須是擋流程的紅
      恢復　 全部 `ok=True` → 綠
      控制組 有一場 `ok=None`（這台驗不了）→ **不得**當成燈死了，也不得回 0
    """
    def _fake(outcome: bool | None) -> Callable[[Path], drill.Outcome]:
        return lambda _tmp: drill.Outcome("daily:canary", outcome, "假的")

    monkeypatch.setattr(drill, "DRILLS", {"a": _fake(False), "b": _fake(True)})
    assert drill.main([]) == drill.DRILL_LAMP_DEAD
    assert "沒叫 1" in capsys.readouterr().out

    monkeypatch.setattr(drill, "DRILLS", {"a": _fake(True), "b": _fake(True)})
    assert drill.main([]) == drill.DRILL_OK

    monkeypatch.setattr(drill, "DRILLS", {"a": _fake(None), "b": _fake(True)})
    rc = drill.main([])
    assert rc == drill.DRILL_CANT_RUN
    assert rc != 0, "驗不了回 0 就跟通過長得一樣"
    assert "#scope 1" in capsys.readouterr().out, "驗不了的場次不該算進分母"


@pytest.mark.proves_red("daily:drill")
def test_a_drill_that_crashes_is_a_red_not_a_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """演習自己掛掉也是紅燈 —— 「跑不完」不得靜靜變成「沒問題」。"""
    def _boom(_tmp: Path) -> NoReturn:
        raise RuntimeError("演習自己爆了")

    monkeypatch.setattr(drill, "DRILLS", {"a": _boom})
    assert drill.main([]) == drill.DRILL_LAMP_DEAD
