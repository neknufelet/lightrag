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


def test_missing_result_is_not_a_pass(tmp_path: Path) -> None:
    """沒有結果檔 ⇒ `missing`，不得是 `ok`。

    回 ok 會讓「從來沒檢查過」看起來像「檢查通過」。
    """
    got = _app(tmp_path).daily_checks()
    assert got["state"] == "missing"
    assert "不存在" in str(got.get("reason"))


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
