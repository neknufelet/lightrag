"""審核台 `:9710` 必須把每日檢查的紅綠燈顯示出來，而且分得出「過期」。

**為什麼需要這支**：2026-08-08 PO 裁決「只要在 9710 有警告就好，我都會透過那個」
—— 這是本專案**唯一**的警報管道（ntfy 於 2026-08-07 拆除）。在此之前紅綠狀態
只落在 `${DATA_ROOT}/checks/latest.json`，**而沒有任何人會經過那裡**：實測當天
`latest.json` 寫著 `status: fail` 已經超過一天，沒有人知道。

**最重要的一條是 stale。** 排程停掉之後 `latest.json` 會凍在最後一次的結果，
於是「一週前通過」跟「剛剛通過」長得一模一樣。過期的綠燈比紅燈危險，因為它會
讓人跳過該做的查證（同 `tests/verified-findings.json` 的 `_rule`）。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from intake import IntakeApp  # noqa: E402
from pp.paths import DataPaths  # noqa: E402


def _app(tmp_path: Path) -> IntakeApp:
    paths = DataPaths(tmp_path / "data")
    paths.inbox_dir.mkdir(parents=True, exist_ok=True)
    return IntakeApp(paths, "test", [paths.inbox_dir])


def _write(app: IntakeApp, payload: dict, *, age_s: float = 0.0) -> Path:
    app.paths.checks_dir.mkdir(parents=True, exist_ok=True)
    path = app.paths.checks_dir / "latest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    if age_s:
        old = time.time() - age_s
        os.utime(path, (old, old))
    return path


@pytest.mark.proves_red("meta:missing")
def test_missing_result_is_not_a_pass(tmp_path: Path) -> None:
    """沒有結果檔 ⇒ `missing`，不得是 `ok`。

    回 ok 會讓「從來沒檢查過」看起來像「檢查通過」。
    """
    got = _app(tmp_path).daily_checks()
    assert got["state"] == "missing"
    assert "不存在" in str(got.get("reason"))


@pytest.mark.proves_red("meta:unreadable")
def test_unreadable_result_is_not_a_pass(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.paths.checks_dir.mkdir(parents=True, exist_ok=True)
    (app.paths.checks_dir / "latest.json").write_text("{壞掉的 json", encoding="utf-8")
    assert app.daily_checks()["state"] == "unreadable"


def test_fresh_pass_is_ok(tmp_path: Path) -> None:
    app = _app(tmp_path)
    _write(app, {"at": "20260808T000000", "status": "ok",
                 "compat_rc": 0, "tests_rc": 0})
    got = app.daily_checks()
    assert got["state"] == "ok"
    assert got["failing"] == []


def test_fresh_fail_lists_which_checks_failed(tmp_path: Path) -> None:
    """紅燈要指名道姓 —— 只說「失敗」等於要人自己去翻檔案。"""
    app = _app(tmp_path)
    _write(app, {"at": "20260808T000000", "status": "fail",
                 "compat_rc": 0, "scan_rc": 2, "tests_rc": 1,
                 "detail": "/data/lightrag/checks/compat-x.json"})
    got = app.daily_checks()
    assert got["state"] == "fail"
    assert got["failing"] == ["scan_rc", "tests_rc"]
    assert got["detail"]


# ── 三態：擋流程的紅／提醒的紅／驗不了（2026-08-17）────────────────────────
# 原本這裡把「任何非零的 `*_rc`」都塞進 `failing`，於是永遠不會綠的那一盞
# （`tests_rc=3` ＝ 這台沒有 node）跟真的紅燈（`fresh_rc=2` ＝ 跑著舊碼）在
# 畫面上長得一模一樣。判準在 `check-levels.py`，這裡只是照著分欄。

def _levelled(**rcs: int) -> dict:
    import importlib.util
    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location(
        "check_levels_for_banner", root / "scripts" / "check-levels.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    summary = mod.summarise(rcs)
    payload = {"at": "20260817T000000", "status": summary["status"],
               "levels": summary["levels"]}
    payload.update({f"{k}_rc": v for k, v in rcs.items()})
    return payload


def test_banner_separates_the_three_kinds(tmp_path: Path) -> None:
    """2026-08-17 的實際盤面：一盞真紅，其餘是提醒與驗不了。"""
    app = _app(tmp_path)
    _write(app, _levelled(compat=5, parse=1, coverage=1, tests=3, fresh=2,
                          canary=0, scan=0, units=0, deploy=0))
    got = app.daily_checks()
    assert got["failing"] == ["fresh_rc"], "要喊的只有跑著舊碼那一盞"
    assert got["warnings"] == ["compat_rc", "coverage_rc", "parse_rc"]
    assert got["unverified"] == ["tests_rc"]


def test_permanently_unverifiable_light_does_not_shout(tmp_path: Path) -> None:
    """`tests_rc=3` 單獨存在時，橫幅不得把它喊成紅燈 —— 但也不得讓它消失。"""
    app = _app(tmp_path)
    _write(app, _levelled(tests=3, compat=0, canary=0, scan=0, units=0,
                          deploy=0, fresh=0, parse=0, coverage=0))
    got = app.daily_checks()
    assert got["failing"] == []
    assert got["unverified"] == ["tests_rc"], "驗不了不得從畫面上消失"


def test_light_missing_from_levels_is_treated_as_blocking(tmp_path: Path) -> None:
    """`levels` 裡沒登記的非零燈要併進 failing —— 錯了會吵，不會沉默。

    新加一支檢查卻忘了在 `check-levels.py` 登記時，它會走到這條路。
    """
    app = _app(tmp_path)
    _write(app, {"at": "20260817T000000", "status": "pass",
                 "levels": {"tests_rc": "unverified"},
                 "tests_rc": 3, "新檢查_rc": 2})
    got = app.daily_checks()
    assert got["failing"] == ["新檢查_rc"]
    assert got["unverified"] == ["tests_rc"]


# ── 橫幅畫出來長什麼樣 ─────────────────────────────────────────────────────

def _banners(checks: dict) -> list[str]:
    import re

    from intake import render_html
    html = render_html({"checks": checks})
    return re.findall(r"<div class='banner[^>]*>.*?</div>", html)


BASE = {"at": "20260817T000000", "age_s": 60.0, "commit": "6af2c80",
        "detail": "/checks/compat-x.json"}


def test_pass_is_green_and_does_not_paint_a_red_banner() -> None:
    """⚠ `daily-check.sh` 寫的是 `pass` 不是 `ok`，而橫幅原本只在 `ok` 時隱藏。

    2026-08-17 之前 status **從來沒有 pass 過**（任何非零都算失敗），所以這個
    洞一直沒被踩到。紅燈分三態之後 pass 變成常態 —— 不修的話橫幅會天天用
    警示色喊「每日檢查 pass（…）：未指明」，等於把被換掉的那個形狀原樣搬過來。
    """
    got = _banners({**BASE, "state": "pass", "failing": []})
    assert got == [], f"全綠不該有橫幅，卻畫了 {got}"


def test_warnings_are_visible_but_not_alarming() -> None:
    """提醒與驗不了天天都在：消失就是靜靜丟掉，用警示色就是天天紅。"""
    got = _banners({**BASE, "state": "pass", "failing": [],
                    "warnings": ["compat_rc", "parse_rc"],
                    "unverified": ["tests_rc"]})
    assert len(got) == 1
    assert "banner quiet" in got[0], "提醒不該用警示色"
    assert "compat_rc" in got[0] and "tests_rc" in got[0], "指名道姓，不要只說有幾個"
    assert "bad" not in got[0]


def test_a_blocking_red_still_shouts_and_keeps_the_quiet_line() -> None:
    got = _banners({**BASE, "state": "fail", "failing": ["fresh_rc"],
                    "warnings": ["parse_rc"], "unverified": ["tests_rc"]})
    assert any("banner bad" in b and "fresh_rc" in b for b in got), "真紅燈要喊"
    assert any("banner quiet" in b for b in got), "提醒不得被紅燈吃掉"


def test_banner_says_what_the_light_watches_not_the_variable_name() -> None:
    """2026-08-21 PO：「這三個能不能講白話功能，這樣我有點看不懂」。

    當天橫幅上寫的是「提醒 3：compat_rc、coverage_rc、parse_rc」——
    那是程式內部的變數名，不是人話。橫幅是本專案**唯一**的警報管道
    （2026-08-08 裁決），而**看不懂的警報等於沒有警報**：看的人無法
    判斷該不該理它，久了就整條略過。

    說法只有一份：`check-levels.py` 的 `WHAT` → `latest.json` 的 `labels`。
    """
    got = _banners({**BASE, "state": "pass", "failing": [],
                    "warnings": ["compat_rc", "parse_rc"],
                    "unverified": ["tests_rc"],
                    "labels": {"compat_rc": "設定與現況對照",
                               "parse_rc": "PDF 拆解出碎字",
                               "tests_rc": "測試"}})
    assert len(got) == 1
    assert "設定與現況對照" in got[0] and "PDF 拆解出碎字" in got[0]
    assert "compat_rc" not in got[0], "變數名不得出現在給人看的橫幅上"
    assert "parse_rc" not in got[0]


def test_blocking_banner_speaks_plainly_too() -> None:
    """真紅燈那條也要講人話 —— 它比提醒更需要被看懂。"""
    got = _banners({**BASE, "state": "fail", "failing": ["fresh_rc"],
                    "labels": {"fresh_rc": "跑著的是不是最新的碼"}})
    assert any("banner bad" in b and "跑著的是不是最新的碼" in b for b in got)
    assert not any("fresh_rc" in b for b in got), "變數名不得出現在給人看的橫幅上"


def test_banner_falls_back_to_the_raw_key_when_labels_are_missing() -> None:
    """升級當下 `latest.json` 還是上一輪那份，沒有 `labels`。

    退回印原鍵名 —— 看不懂的警報還是警報，**消失的不是**。
    """
    got = _banners({**BASE, "state": "pass", "failing": [],
                    "warnings": ["compat_rc"]})
    assert len(got) == 1 and "compat_rc" in got[0]


def test_old_result_without_levels_falls_back_to_shouting(tmp_path: Path) -> None:
    """升級當下 `latest.json` 還是上一輪那份，沒有 `levels`。寧可多叫，不可漏叫。"""
    app = _app(tmp_path)
    _write(app, {"at": "20260817T000000", "status": "fail",
                 "compat_rc": 5, "tests_rc": 3, "fresh_rc": 0})
    got = app.daily_checks()
    assert got["failing"] == ["compat_rc", "tests_rc"]
    assert got["warnings"] == [] and got["unverified"] == []


@pytest.mark.proves_red("meta:stale")
def test_stale_pass_is_reported_as_stale_not_ok(tmp_path: Path) -> None:
    """**本檔最重要的一條。**

    排程停掉之後結果會凍住。「一週前通過」不得顯示成「通過」——那會讓人以為
    現在是健康的，而實際上根本沒有在檢查。
    """
    app = _app(tmp_path)
    _write(app, {"at": "20260801T000000", "status": "ok"},
           age_s=IntakeApp.CHECKS_STALE_AFTER_S + 60)
    got = app.daily_checks()
    assert got["state"] == "stale", "過期的通過必須標成 stale"
    assert got["reported"] == "ok", "原值仍要看得到，才知道它凍在哪個狀態"
    assert got["age_s"] > IntakeApp.CHECKS_STALE_AFTER_S


def test_state_payload_carries_checks(tmp_path: Path) -> None:
    """要真的出現在 /api/state 裡，否則畫面拿不到。"""
    app = _app(tmp_path)
    _write(app, {"at": "20260808T000000", "status": "fail", "tests_rc": 1})
    assert app.state()["checks"]["state"] == "fail"


def test_commit_is_carried_through(tmp_path: Path) -> None:
    """結果要帶上產生它的 commit。

    **為什麼**：沒有版本的話，「這條檢查後來被修好了」與「這個問題還在」在畫面上
    長得一樣，讀者會照著一份舊碼的判斷去處置。這是要升上游的通則之一：
    檢查結果必須帶上產生它的版本。
    """
    app = _app(tmp_path)
    _write(app, {"at": "20260808T000000", "status": "fail",
                 "commit": "9a727fb", "tests_rc": 1})
    assert app.daily_checks()["commit"] == "9a727fb"


def test_old_format_without_commit_still_readable(tmp_path: Path) -> None:
    """舊格式沒有 commit 欄位，不得因此整個讀不了。

    升級當下 `latest.json` 還是舊的那一份——如果新欄位是必填，審核台會在最需要
    它的時候（剛部署完）變成 unreadable。
    """
    app = _app(tmp_path)
    _write(app, {"at": "20260808T000000", "status": "fail", "tests_rc": 1})
    got = app.daily_checks()
    assert got["state"] == "fail"
    assert got["commit"] is None


def test_new_rc_fields_show_up_in_failing(tmp_path: Path) -> None:
    """新增的 deploy_rc／fresh_rc 要自動出現在 failing 清單裡。

    `failing` 是掃所有 `_rc` 結尾的鍵算出來的，所以新檢查不必改這裡——但那個
    「不必改」要有測試守著，否則下次有人把它改成寫死清單也不會有人發現。
    """
    app = _app(tmp_path)
    _write(app, {"at": "20260808T000000", "status": "fail", "commit": "abc1234",
                 "compat_rc": 0, "deploy_rc": 2, "fresh_rc": 2, "tests_rc": 0})
    assert app.daily_checks()["failing"] == ["deploy_rc", "fresh_rc"]


def test_dirty_inputs_error_gives_a_runnable_remedy(tmp_path: Path) -> None:
    """擋下來不等於把問題丟給人 —— 錯誤訊息要給可以直接跑的下一步。

    2026-08-08 實測：手動跑管線時把 PDF scp 進 inputs、跑完沒清，四篇一放行全部
    撞到這個守衛。當時的訊息只有「不是純淨空目錄：<檔名>」，**沒說怎麼辦**，
    於是每一次都要人去查。`ledger.py` 在體檢表脫節時就是印出處置指令的，
    這裡照同一個模式。
    """
    import pytest

    app = _app(tmp_path)
    inputs = app.paths.inputs_dir(app.workspace)
    inputs.mkdir(parents=True, exist_ok=True)
    (inputs / "殘留.pdf").write_bytes(b"%PDF-1.4\n")

    with pytest.raises(RuntimeError) as e:
        app._assert_inputs_empty()
    msg = str(e.value)
    assert "殘留.pdf" in msg, "要指名道姓是哪個檔"
    assert "繞過後處理" in msg, "要說清楚為什麼擋，否則下一個人會想繞過它"
    assert "mv " in msg and "library" in msg, "要給可以直接跑的指令"
    assert "不要直接刪" in msg, "要提醒那可能是唯一副本"


def test_clean_inputs_passes(tmp_path: Path) -> None:
    """__parsed__ 是 compose 掛進去的目錄，本來就在，不該被當成殘留。"""
    app = _app(tmp_path)
    inputs = app.paths.inputs_dir(app.workspace)
    (inputs / "__parsed__").mkdir(parents=True, exist_ok=True)
    app._assert_inputs_empty()   # 不得丟例外
