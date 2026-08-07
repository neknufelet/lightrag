"""`cairn/LOG.md` 不得落後於實際工作。

**為什麼需要這支**：Cairn 的維護規則寫著「每有實質進展，在 `cairn/LOG.md` 最上面加一則」，
但沒有任何東西會發現沒做。2026-08-07 實測：LOG 最新一則是 08-05，之後累積了
**14 個 commit** 完全沒記，而且沒有任何訊號。

規則的落地版在 `docs/knowledge-routing.md`（2026-08-07 之前這支引用的是 `AGENTS.md`，
但那句話從來不在 `AGENTS.md` 裡——引用本身就是漂移的實例）。

這與 `tests/test_pits.py`（已隨 173 條坑清單於 2026-08-07 一併刪除）是同一個公式
的第二個實例：**規則要有執行者，
沒有執行者的規則不是規則，是願望。** 那支守「待補清單只准變短」，
這支守「流水帳不准落後於 git」。

**判準用「落後最後一個 commit 幾天」而不是「落後今天幾天」**：沒有工作的日子
不該紅（沒進展就沒有東西要記）。也不用「未記錄的 commit 數」當硬判準——
這個專案的節奏是一天 40–50 個 commit，用數量會天天紅，變成噪音，
而假警報會讓人開始忽略警報（`docs/judgement-flow.md`）。

**三態**：讀不到 git ⇒ 驗不了（skip），不是通過也不是失敗。
"""
from __future__ import annotations

import re
import subprocess
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "cairn" / "LOG.md"

# 落後幾天算斷了。1 天是刻意的寬容：當天的工作允許隔天早上補記。
MAX_LAG_DAYS = 1

_DATE_HEADING = re.compile(r"^##\s+(\d{4})-(\d{2})-(\d{2})", re.MULTILINE)


def _git(*args: str) -> str | None:
    """跑一條 git 指令。git 不可用或不是 repo 時回 None（＝驗不了）。"""
    try:
        out = subprocess.run(("git", "-C", str(ROOT), *args),
                             capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def _latest_log_date() -> date | None:
    if not LOG.is_file():
        return None
    hits = _DATE_HEADING.findall(LOG.read_text(encoding="utf-8"))
    if not hits:
        return None
    # 檔案是逆時序（最新在最上面），但不假設它真的有序 —— 取最大值。
    return max(date(int(y), int(m), int(d)) for y, m, d in hits)


def test_log_exists_and_has_dated_entries() -> None:
    """流水帳本身要在，而且要有日期標題。

    沒有日期就無法判斷落後 —— 而「無法判斷」會讓下面那條永遠通過，
    也就是「乾淨的 0」那一族。
    """
    assert LOG.is_file(), f"{LOG.relative_to(ROOT)} 不見了 —— 那是「發生了什麼」的唯一去處"
    assert _latest_log_date() is not None, (
        "LOG.md 裡找不到任何 `## YYYY-MM-DD` 標題。"
        "沒有日期就量不出落後，這支檢查會變成永遠通過的裝飾。")


def test_log_is_not_behind_the_commits() -> None:
    """LOG 最新一則不得落後最後一個 commit 超過 MAX_LAG_DAYS 天。"""
    last_commit = _git("log", "-1", "--format=%cs")
    if not last_commit:
        pytest.skip("讀不到 git（不是 repo 或 git 不可用）⇒ 驗不了，不當成通過")

    commit_date = date.fromisoformat(last_commit)
    log_date = _latest_log_date()
    assert log_date is not None  # 由上一條守著

    lag = (commit_date - log_date).days
    if lag <= MAX_LAG_DAYS:
        return

    since = log_date.isoformat()
    unlogged = _git("log", f"--since={since} 23:59:59", "--format=%s") or ""
    lines = [ln for ln in unlogged.splitlines() if ln.strip()]
    preview = "\n  ".join(lines[:5])
    more = f"\n  …另外 {len(lines) - 5} 個" if len(lines) > 5 else ""

    pytest.fail(
        f"cairn/LOG.md 最新一則是 {log_date}，最後一個 commit 是 {commit_date}"
        f"（落後 {lag} 天，上限 {MAX_LAG_DAYS} 天）。\n"
        f"這段期間有 {len(lines)} 個 commit 沒有進流水帳：\n  {preview}{more}\n"
        "docs/knowledge-routing.md：「每有實質進展，在 cairn/LOG.md 最上面加一則」。"
        "在最上面補一則（摘要＋指標，≤20 行），這條就會轉綠。")
