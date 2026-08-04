"""systemd 單元漂移偵測的自測。

**為什麼要有這支**：`systemd-units.py verify` 是「探針的探針」——它守著那兩個
排程單元，而那兩個單元守著整個知識庫的健康。它自己失效的話沒有第三層會發現。

三種故障各測一次：缺檔、內容被手改、母體是空的。第三種是鐵則 7 那一族——
`deploy/systemd/` 空掉時「0 個不一致」看起來像通過，實際是根本沒有東西可比。
"""
from __future__ import annotations

import argparse
import importlib.util
import shutil
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "systemd-units.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("systemd_units", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _args(module: ModuleType) -> argparse.Namespace:
    return argparse.Namespace(repo=Path("/srv/lightrag"), user="svc",
                              ntfy="http://127.0.0.1:9800/lightrag", diff=False)


def _installed(module: ModuleType, target: Path) -> Path:
    """把 repo 的單元渲染進 target，模擬一台裝好的機器。"""
    target.mkdir(parents=True, exist_ok=True)
    for name, body in module.render_all(Path("/srv/lightrag"), "svc",
                                        "http://127.0.0.1:9800/lightrag").items():
        (target / name).write_text(body, encoding="utf-8")
    return target


def test_render_substitutes_every_placeholder() -> None:
    """三個佔位符都要被換掉 —— 漏一個就等於這份 repo 只能在一台機器上用。"""
    module = _module()
    rendered = module.render_all(Path("/srv/lightrag"), "svc", "http://ntfy.local/x")
    assert rendered, "deploy/systemd/ 是空的，下面的斷言會假通過"
    blob = "\n".join(rendered.values())
    for token in ("@REPO@", "@USER@", "@NTFY_URL@"):
        assert token not in blob, f"{token} 沒有被取代"
    assert "/srv/lightrag/scripts/daily-check.sh" in blob
    assert "User=svc" in blob
    assert "http://ntfy.local/x" in blob


def test_matching_units_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "SYSTEM_DIR", _installed(module, tmp_path / "etc"))
    monkeypatch.setattr(module, "ENABLE", ())          # enable 那條要真的 systemctl
    assert module.cmd_verify(_args(module)) == 0


def test_missing_unit_is_caught(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                capsys: pytest.CaptureFixture[str]) -> None:
    """缺檔 = 這台機器根本沒有那個排程。腳本還在、排程沒了，看起來一切正常。"""
    module = _module()
    etc = _installed(module, tmp_path / "etc")
    (etc / "lightrag-cold-backup.timer").unlink()
    monkeypatch.setattr(module, "SYSTEM_DIR", etc)
    monkeypatch.setattr(module, "ENABLE", ())
    assert module.cmd_verify(_args(module)) == 2
    out = capsys.readouterr().out
    assert "沒安裝" in out and "lightrag-cold-backup.timer" in out


def test_hand_edited_unit_is_caught(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                    capsys: pytest.CaptureFixture[str]) -> None:
    """內容不符 = 有人手改了 /etc 沒回寫 repo。那個 .bak-20260804 就是這樣來的。"""
    module = _module()
    etc = _installed(module, tmp_path / "etc")
    unit = etc / "lightrag-daily-check.timer"
    unit.write_text(unit.read_text().replace("08:30", "09:00"), encoding="utf-8")
    monkeypatch.setattr(module, "SYSTEM_DIR", etc)
    monkeypatch.setattr(module, "ENABLE", ())
    assert module.cmd_verify(_args(module)) == 2
    out = capsys.readouterr().out
    assert "內容不符" in out and "lightrag-daily-check.timer" in out


def test_empty_source_is_not_a_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                    capsys: pytest.CaptureFixture[str]) -> None:
    """母體是空的時候「0 個不一致」不是通過（鐵則 7）。

    deploy/systemd/ 被誤刪時，逐檔比對會走完 0 圈然後回報一切正常 ——
    那正是「乾淨的 0 要先當成量錯」講的情況。
    """
    module = _module()
    monkeypatch.setattr(module, "UNIT_DIR", tmp_path / "empty")
    (tmp_path / "empty").mkdir()
    monkeypatch.setattr(module, "SYSTEM_DIR", tmp_path / "etc")
    assert module.cmd_verify(_args(module)) == 2
    assert "母體是空的" in capsys.readouterr().out


def test_units_cover_both_timers_and_their_failover() -> None:
    """六個單元一個都不能少，而且兩個 -crashed 刻意不進 timers.target。"""
    module = _module()
    names = set(module.render_all(Path("/x"), "u", "http://h/").keys())
    assert names == {
        "lightrag-daily-check.service", "lightrag-daily-check.timer",
        "lightrag-cold-backup.service", "lightrag-cold-backup.timer",
        "lightrag-check-crashed.service", "lightrag-cold-backup-crashed.service",
    }, names
    assert set(module.ENABLE) == {"lightrag-daily-check.timer",
                                  "lightrag-cold-backup.timer"}
    # 備援單元由 OnFailure= 觸發，enable 它們沒有意義而且會排進 timers.target
    for unit in ("lightrag-check-crashed.service", "lightrag-cold-backup-crashed.service"):
        assert unit not in module.ENABLE
