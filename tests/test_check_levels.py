"""紅燈語意的判準：擋流程的紅／提醒的紅／驗不了。

**為什麼要守這一份。** 2026-08-16 實測，每日體檢的 `status` 天天是 `fail`，
而四盞紅裡有一盞永遠不會綠 —— `tests_rc=3` 的意思是「dker 上沒有 node，
那支 JS 測試根本沒跑」，不是測試失敗。同一天真的紅燈 `fresh_rc=2`
（`lightrag-intake.service` 跑著 58.3 小時前的舊碼）就埋在那片紅裡沒人看出來。

所以這裡守的不是「哪一盞會亮」，是**「亮的那一盞代表什麼」**。
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check-levels.py"

_spec = importlib.util.spec_from_file_location("check_levels", SCRIPT)
assert _spec and _spec.loader
cl = importlib.util.module_from_spec(_spec)
sys.modules["check_levels"] = cl
_spec.loader.exec_module(cl)


# ── 三態的分界 ─────────────────────────────────────────────────────────────

def test_tests_rc_3_is_unverified_not_failure() -> None:
    """這一條就是整件事的起因：`run-tests.sh` 回 3 ＝「這台驗不了全部」。

    它自己的訊息寫著「跑得動的都通過了，但這台驗不了全部（node 缺=1）」。
    當成失敗，紅燈就永遠亮著；當成通過，「沒跑」會長得跟「跑過了」一樣。
    """
    assert cl.level_of("tests", 3) == cl.UNVERIFIED
    assert cl.level_of("tests", 1) == cl.BLOCK, "真的有測試掛掉還是要擋"
    assert cl.level_of("tests", 0) == cl.OK


def test_compat_soft_is_warn_and_hard_is_block() -> None:
    """離開碼的定義來自 `compat-check.py:1182`：2 ＝ hard 不過、5 ＝ 只有 soft。

    soft 是那支工具**自己**標成「參考不擋」的那一類，所以照它的話走。
    """
    assert cl.level_of("compat", 5) == cl.WARN
    assert cl.level_of("compat", 2) == cl.BLOCK
    assert cl.level_of("compat", 9) == cl.BLOCK, "沒定義的非零 ＝ 腳本自己掛了"


def test_canary_separates_no_corpus_from_no_baseline() -> None:
    """金絲雀的三態：驗不了／擋／通過。**「守著 0 份」不得回 0。**

    2026-08-21 實測，`tests/canary-baseline.json` 是 `{}` 而它天天回
    「金絲雀通過」rc=0 —— 守著 0 份文件，報告上跟真的守住長得一模一樣。

    ⚠ 兩個分支刻意不同態（`postprocess.py` 的 `CANARY_*`）：
      3 沒有任何 bundle    母體不存在，誰都做不了事      → 驗不了
      4 沒有基準／基準是空  有人要去跑 `canary --update`  → 擋（做得完的事）
    後者與 `scan` 回 3 的裁決同一族，見 `level_of` 最後一段。
    """
    assert cl.level_of("canary", 3) == cl.UNVERIFIED, "沒有母體 ＝ 驗不了"
    assert cl.level_of("canary", 4) == cl.BLOCK, "基準是空的要擋，不是提醒"
    assert cl.level_of("canary", 2) == cl.BLOCK, "真的漂移要擋"
    assert cl.level_of("canary", 0) == cl.OK


def test_content_rulers_are_warn() -> None:
    """`parse` 與 `coverage` 量的是語料內容，不是系統壞掉，而且假訊號很多。

    實跑母體 317 份：`parse-check` WARN 283（89%）；`coverage-check` 15 份超標
    裡逐份查證的 5 份**全部**是量錯。設計文件第一層的裁決是「只印警告不擋」。
    """
    assert cl.level_of("parse", 1) == cl.WARN
    assert cl.level_of("coverage", 1) == cl.WARN


def test_deployment_checks_stay_blocking() -> None:
    """「跑著的東西跟它該是的樣子不一樣」一律是擋 —— 降級這幾盞等於關掉守衛。"""
    for name in ("canary", "scan", "units", "deploy", "fresh"):
        assert cl.level_of(name, 2) == cl.BLOCK, name


def test_scan_no_baseline_is_block_unlike_tests() -> None:
    """兩個 rc=3 是不同的事，不要因為數字一樣就一起降級。

    `tests` 的 3 ＝ 這台機器**永遠**驗不了（沒有 node，明天也不會有）；
    `scan` 的 3 ＝ 沒有基準檔，那是**有人去建就會消失**的事。
    """
    assert cl.level_of("scan", 3) == cl.BLOCK
    assert cl.level_of("tests", 3) == cl.UNVERIFIED


def test_unknown_check_is_block_not_silently_dropped() -> None:
    """打錯字的檢查名如果落成「提醒」，它會安靜地從紅燈名單裡消失。拒絕，不猜。"""
    assert cl.level_of("這不是任何一支檢查", 1) == cl.BLOCK


# ── 彙總 ───────────────────────────────────────────────────────────────────

ALL_GREEN = {"compat": 0, "canary": 0, "scan": 0, "units": 0,
             "deploy": 0, "fresh": 0, "tests": 0, "parse": 0, "coverage": 0}


def test_only_blocking_turns_status_to_fail() -> None:
    """2026-08-17 的實際盤面：只剩提醒與驗不了，status 應該是 pass。"""
    today = {**ALL_GREEN, "compat": 5, "parse": 1, "coverage": 1, "tests": 3}
    got = cl.summarise(today)
    assert got["status"] == "pass"
    assert got["blocking"] == []
    # 名字一律帶 `_rc`，跟 latest.json 的欄位與橫幅回的清單同一種寫法。
    assert got["warnings"] == ["compat_rc", "coverage_rc", "parse_rc"]
    assert got["unverified"] == ["tests_rc"]


def test_a_real_red_still_fails_even_among_warnings() -> None:
    """這是回歸測試：08-16 那天 `fresh_rc=2` 被一片天天都在的紅淹掉了。"""
    that_day = {**ALL_GREEN, "compat": 5, "parse": 1, "coverage": 1,
                "tests": 3, "fresh": 2}
    got = cl.summarise(that_day)
    assert got["status"] == "fail"
    assert got["blocking"] == ["fresh_rc"]


def test_all_green_is_pass_with_empty_lists() -> None:
    got = cl.summarise(ALL_GREEN)
    assert got["status"] == "pass"
    assert got["blocking"] == [] and got["warnings"] == [] and got["unverified"] == []


def test_every_light_is_printed_including_unverified() -> None:
    """「驗不了」不印出來就等於被當成通過了 —— 那正是要避開的形狀。"""
    lines = cl.messages({**ALL_GREEN, "tests": 3, "parse": 1, "fresh": 2},
                        {"tests": "/checks/tests-x.txt"})
    joined = "\n".join(lines)
    assert "[擋]" in joined and "[提醒]" in joined and "[驗不了]" in joined
    assert "/checks/tests-x.txt" in joined, "報告路徑要跟著印，不然要人自己去翻"
    assert lines[0].startswith("[擋]"), "擋流程的紅要排在最前面"


# ── CLI：daily-check.sh 真正呼叫的那條路 ───────────────────────────────────

def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True, check=False)


def test_cli_emits_latest_json_with_old_fields_intact() -> None:
    """舊欄位一個都不能少 —— 讀 `latest.json` 的人還在用它們（鐵則 2）。"""
    r = _run(["--at", "20260817T000000", "--commit", "c34dc41",
              "--detail", "/checks/compat-x.json",
              *[f"--rc={k}={v}" for k, v in
                {**ALL_GREEN, "compat": 5, "tests": 3, "parse": 1, "coverage": 1}.items()]])
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    for key in ("at", "status", "commit", "detail", "compat_rc", "canary_rc",
                "scan_rc", "units_rc", "deploy_rc", "fresh_rc", "tests_rc",
                "parse_rc", "coverage_rc"):
        assert key in got, f"舊欄位 {key} 不見了"
    assert got["status"] == "pass"
    assert got["levels"]["tests_rc"] == "unverified"
    assert got["levels"]["compat_rc"] == "warn"
    assert got["blocking"] == []


def test_every_light_says_what_it_watches_in_plain_language() -> None:
    """2026-08-21 PO：「這三個能不能講白話功能，這樣我有點看不懂」。

    橫幅上原本印的是 `compat_rc、coverage_rc、parse_rc` —— 程式內部的變數名。
    橫幅是本專案**唯一**的警報管道（2026-08-08 裁決），一句看不懂的警報等於
    沒有警報，因為看的人無法判斷該不該理它。
    """
    for name in ("compat", "canary", "scan", "units", "deploy",
                 "fresh", "tests", "parse", "coverage"):
        text = cl.WHAT.get(name, "")
        assert text and text != name, f"{name} 沒有白話說法"
        assert "_rc" not in text, f"{name} 的說法還是變數名：{text!r}"
        assert any("\u4e00" <= ch <= "\u9fff" for ch in text), \
            f"{name} 的說法沒有中文，PO 讀不了：{text!r}"


def test_cli_emits_a_label_for_every_light() -> None:
    """`labels` 要跟 `levels` 一對一 —— 少一盞，那一盞在橫幅上就會退回變數名。"""
    r = _run(["--at", "t", "--commit", "c",
              *[f"--rc={k}={v}" for k, v in {**ALL_GREEN, "compat": 5}.items()]])
    got = json.loads(r.stdout)
    assert set(got["labels"]) == set(got["levels"]), "每盞燈都要有說法"
    assert got["labels"]["compat_rc"] == cl.WHAT["compat"]


def test_cli_exit_1_only_when_something_blocks() -> None:
    r = _run(["--at", "t", "--commit", "c",
              *[f"--rc={k}={v}" for k, v in {**ALL_GREEN, "fresh": 2}.items()]])
    assert r.returncode == 1
    assert json.loads(r.stdout)["blocking"] == ["fresh_rc"]


def test_cli_rejects_malformed_rc_instead_of_guessing() -> None:
    r = _run(["--at", "t", "--commit", "c", "--rc", "fresh"])
    assert r.returncode != 0


def test_daily_check_calls_it_and_exits_with_its_code() -> None:
    """守住接線：判準寫好了沒被呼叫等於沒寫。"""
    src = (ROOT / "scripts" / "daily-check.sh").read_text(encoding="utf-8")
    assert "scripts/check-levels.py" in src, "daily-check 沒有呼叫判準"
    assert 'exit "$levels_rc"' in src, "daily-check 沒有沿用它的離開碼"
    # ⚠ 比對 `fail_msgs=()`（陣列初始化）而不是 `fail_msgs` —— 後者會命中檔裡
    # 那段講 2026-08-16 canary 缺欄位的**註解**，測試就永遠是紅的。
    assert "fail_msgs=()" not in src, "舊的『任何非零都是失敗』又回來了"
    for name in ("compat", "canary", "scan", "units", "deploy",
                 "fresh", "tests", "parse", "coverage"):
        assert f'--rc "{name}=$' in src, f"{name} 沒有被餵進判準"
