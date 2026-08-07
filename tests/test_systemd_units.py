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
                              workspace="ws_x", data_root="/srv/data",
                              stack_dir="/srv/stack", bind_addr="10.0.0.9",
                              diff=False)


def _installed(module: ModuleType, target: Path) -> Path:
    """把 repo 的單元渲染進 target，模擬一台裝好的機器。"""
    target.mkdir(parents=True, exist_ok=True)
    for name, body in module.render_all(Path("/srv/lightrag"), "svc",
                                        "ws_x", "/srv/data",
                                        "/srv/stack", "10.0.0.9").items():
        (target / name).write_text(body, encoding="utf-8")
    return target


def test_render_substitutes_every_placeholder() -> None:
    """四個佔位符都要被換掉 —— 漏一個就等於這份 repo 只能在一台機器上用。

    2026-08-07：`@NTFY_URL@` 隨 ntfy 一起移除，從五個變四個。
    """
    module = _module()
    rendered = module.render_all(Path("/srv/lightrag"), "svc",
                                 "ws_x", "/srv/data")
    assert rendered, "deploy/systemd/ 是空的，下面的斷言會假通過"
    blob = "\n".join(rendered.values())
    for token in ("@REPO@", "@USER@", "@WORKSPACE@", "@DATA_ROOT@"):
        assert token not in blob, f"{token} 沒有被取代"
    assert "/srv/lightrag/scripts/daily-check.sh" in blob
    assert "User=svc" in blob
    assert "--workspace ws_x" in blob and "/srv/data/inbox" in blob


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


def test_units_are_exactly_the_six_that_remain() -> None:
    """六個單元一個都不能少、一個都不能多。

    2026-08-07 拆掉 ntfy，兩個 `-crashed` 備援單元一起移除（它們的內容就是
    `curl` 到 ntfy）。**所以現在沒有任何 OnFailure 觸發的單元**——腳本本身掛掉
    只留在 journal，沒有人會被打斷。這條斷言同時擋住「有人把備援加回來卻沒有
    通知管道」。

    **2026-08-07 由五個變六個**：加了 `lightrag-stack.service`。理由不是想加功能，
    是實測重開機之後 lightrag 與 kbapi **不會回來**——docker 比 tailscale 早起，
    綁 `100.87.88.7` 失敗（`cannot assign requested address`），而那是啟動失敗不是
    程序死亡，restart policy 救不了。同一台上別人的 10 個容器綁 `0.0.0.0`，
    所以只有我們踩到。
    """
    module = _module()
    names = set(module.render_all(Path("/x"), "u", "w", "/d", "/s", "1.2.3.4").keys())
    assert names == {
        "lightrag-daily-check.service", "lightrag-daily-check.timer",
        "lightrag-cold-backup.service", "lightrag-cold-backup.timer",
        "lightrag-intake.service", "lightrag-stack.service",
    }, names
    assert set(module.ENABLE) == names - {"lightrag-daily-check.service",
                                          "lightrag-cold-backup.service"}
    blob = "\n".join(module.render_all(Path("/x"), "u", "w", "/d").values())
    # **帶等號**是必要的：`OnFailure` 三個字也出現在單元檔的說明註解裡，
    # 不帶等號的比對會抓到自己寫的註解（2026-08-07 實際踩到，這條測試當場紅）。
    # 判準是「有沒有這個 systemd 指令」，不是「有沒有出現這個字」。
    assert "OnFailure=" not in blob, "有人加回 OnFailure= 卻沒有通知管道"
