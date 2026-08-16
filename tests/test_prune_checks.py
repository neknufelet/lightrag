"""`prune-checks.sh` 的守衛。

**為什麼需要這支**：2026-08-16 之前這段邏輯內嵌在 `daily-check.sh` 裡，用
`find … | sort | head -n -120 | xargs rm` 實作。`sort` 排的是完整路徑，
而 `canary-` 的字母序排在 `compat-`／`coverage-`／`deploy-`／`fresh-`／
`parse-`／`scan-`／`units-` **全部之前** —— 於是總數一碰到上限，第一個被刪的
永遠是 canary，包括同一輪剛寫好的那一份。

後果不是「少留了一份報告」，是**紅燈訊息指著一個不存在的檔案**：
daily-check 報「canary 規則漂移 → canary-<ts>.txt」，而那個檔已經被同一支
腳本刪掉了。**紅燈是真的，證據被自己銷毀。**

所以下面第一條測試是**針對那個事故本身**：canary 是最新的檔案時，它必須活下來。
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PRUNE = ROOT / "scripts" / "prune-checks.sh"

# 與腳本裡的樣式一致。順序刻意照字母序排 —— 那正是舊版用來排序的順序，
# 所以這個清單同時也是「舊版會依序刪掉誰」的紀錄。
PREFIXES = ("canary", "compat", "coverage", "deploy", "fresh", "parse", "scan", "units")


def _make(dirpath: Path, prefix: str, stamp: str, mtime: float) -> Path:
    p = dirpath / f"{prefix}-{stamp}.txt"
    p.write_text("x", encoding="utf-8")
    os.utime(p, (mtime, mtime))
    return p


def _run(dirpath: Path, keep: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(PRUNE), str(dirpath), str(keep)],
        capture_output=True, text=True, check=False,
    )


def test_script_is_executable() -> None:
    """不可執行的話 daily-check 會在最後一步靜靜失敗。"""
    assert PRUNE.is_file(), f"{PRUNE} 不見了"
    assert os.access(PRUNE, os.X_OK), f"{PRUNE} 沒有執行權限"


def test_newest_canary_survives(tmp_path: Path) -> None:
    """**這條就是 2026-08-16 那個事故。**

    canary 是全場最新的檔案，其餘七種都比它舊。保留 3 份時它必須在。
    舊版（按檔名排）會第一個刪掉它。
    """
    for i, prefix in enumerate(PREFIXES):
        _make(tmp_path, prefix, f"2026081{i}T000000", mtime=1000.0 + i)
    canary = _make(tmp_path, "canary", "20260816T104320", mtime=9999.0)

    r = _run(tmp_path, 3)
    assert r.returncode == 0, r.stderr

    assert canary.exists(), (
        "最新的 canary 報告被刪掉了 —— 這正是舊版按檔名排序造成的事故："
        "紅燈訊息會指著一個不存在的檔案"
    )
    assert len(list(tmp_path.iterdir())) == 3


def test_keeps_exactly_n_newest(tmp_path: Path) -> None:
    """保留的必須是**最新的 N 份**，而且不多不少。"""
    made = [
        _make(tmp_path, PREFIXES[i % len(PREFIXES)], f"2026080{i % 10}T00000{i % 10}",
              mtime=1000.0 + i)
        for i in range(12)
    ]
    r = _run(tmp_path, 5)
    assert r.returncode == 0, r.stderr

    survivors = sorted(p.name for p in tmp_path.iterdir())
    expected = sorted(p.name for p in made[-5:])
    assert survivors == expected, "保留的不是最新的 5 份"


def test_under_the_limit_deletes_nothing(tmp_path: Path) -> None:
    """沒超過上限就一個都不該動。"""
    made = [_make(tmp_path, "compat", f"2026080{i}T000000", mtime=1000.0 + i)
            for i in range(4)]
    r = _run(tmp_path, 120)
    assert r.returncode == 0, r.stderr
    assert all(p.exists() for p in made)


def test_ignores_files_outside_the_patterns(tmp_path: Path) -> None:
    """`latest.json` 與 `tests-*` 不在樣式裡，永遠不該被碰。

    `latest.json` 是當前狀態，刪掉等於整個體檢的結果消失。
    """
    latest = tmp_path / "latest.json"
    latest.write_text("{}", encoding="utf-8")
    os.utime(latest, (1.0, 1.0))          # 最舊，若被納入樣式會第一個被刪
    tests = _make(tmp_path, "tests", "20260801T000000", mtime=2.0)

    for i in range(6):
        _make(tmp_path, "compat", f"2026081{i}T000000", mtime=1000.0 + i)

    r = _run(tmp_path, 2)
    assert r.returncode == 0, r.stderr
    assert latest.exists(), "latest.json 被刪了 —— 那是當前狀態，不是歷史報告"
    assert tests.exists(), "tests-* 不在樣式裡，不該被碰"


def test_dry_run_deletes_nothing(tmp_path: Path) -> None:
    made = [_make(tmp_path, "compat", f"2026080{i}T000000", mtime=1000.0 + i)
            for i in range(5)]
    r = subprocess.run(
        [str(PRUNE), str(tmp_path), "2"],
        capture_output=True, text=True, check=False,
        env={**os.environ, "PRUNE_DRY_RUN": "1"},
    )
    assert r.returncode == 0, r.stderr
    assert all(p.exists() for p in made), "乾跑不該刪任何東西"
    assert len(r.stdout.strip().splitlines()) == 3


@pytest.mark.parametrize("bad", ["abc", "-1", ""])
def test_rejects_bad_keep_count(tmp_path: Path, bad: str) -> None:
    """保留份數打錯字時要拒絕，不要當成 0 把整個目錄清空。"""
    keeper = _make(tmp_path, "compat", "20260801T000000", mtime=1.0)
    r = _run(tmp_path, bad)
    assert r.returncode != 0
    assert keeper.exists(), "參數錯誤時不得刪任何東西"


def test_missing_dir_is_an_error(tmp_path: Path) -> None:
    """目錄不存在要當場失敗，不要靜靜成功 —— 那會讓「沒清到」看起來像「清過了」。"""
    r = _run(tmp_path / "nope", 5)
    assert r.returncode != 0


def test_daily_check_calls_it_and_records_canary_rc() -> None:
    """兩件事一起守：daily-check 有呼叫這支，而且 latest.json 記得下 canary。

    `canary_rc` 那半是 2026-08-16 的另一個缺陷：canary 的離開碼原本寫成
    `cmd || fail_msgs+=(… $? …)`，**沒有被存進變數**，所以 latest.json 裡
    根本沒有這一欄 —— canary 紅了只出現在 stderr，讀 latest.json 的人看不到。

    ⚠ **2026-08-17：latest.json 改由 `check-levels.py` 產生**，原本那一行
    printf 的 `"canary_rc":%d` 不在了。守的東西沒變（「canary 的離開碼要落進
    latest.json」），改成斷言它有被餵進去那支。
    """
    src = (ROOT / "scripts" / "daily-check.sh").read_text(encoding="utf-8")
    assert "prune-checks.sh" in src, "daily-check 沒有呼叫 prune-checks.sh"
    assert "sort | head -n -120" not in src, "按檔名排序的舊版又回來了"
    assert "canary_rc=$?" in src, "canary 的離開碼沒有被存下來"
    assert '--rc "canary=$canary_rc"' in src, "canary 的離開碼沒有進 latest.json"
