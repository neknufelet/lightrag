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
    assert cl.level_of("tests", 0, 3) == cl.OK


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
    assert cl.level_of("canary", 0, 172) == cl.OK


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

#: 每一支都報了分母。**沒有它，全綠不再是綠** —— 見 level_of 的「綠燈必須帶
#: 分母」。數值取自 2026-08-21 dker 實跑的量級，不是隨手編的。
ALL_SCOPES = {"compat": 1060, "canary": 172, "scan": 172, "units": 7,
              "deploy": 1, "fresh": 5, "tests": 3, "parse": 172, "coverage": 172,
              "drill": 2}

ALL_GREEN = {"compat": 0, "canary": 0, "scan": 0, "units": 0, "deploy": 0,
             "fresh": 0, "tests": 0, "parse": 0, "coverage": 0, "drill": 0}


def test_only_blocking_turns_status_to_fail() -> None:
    """2026-08-17 的實際盤面：只剩提醒與驗不了，status 應該是 pass。"""
    today = {**ALL_GREEN, "compat": 5, "parse": 1, "coverage": 1, "tests": 3}
    got = cl.summarise(today, ALL_SCOPES)
    assert got["status"] == "pass"
    assert got["blocking"] == []
    # 名字一律帶 `_rc`，跟 latest.json 的欄位與橫幅回的清單同一種寫法。
    assert got["warnings"] == ["compat_rc", "coverage_rc", "parse_rc"]
    assert got["unverified"] == ["tests_rc"]


def test_a_real_red_still_fails_even_among_warnings() -> None:
    """這是回歸測試：08-16 那天 `fresh_rc=2` 被一片天天都在的紅淹掉了。"""
    that_day = {**ALL_GREEN, "compat": 5, "parse": 1, "coverage": 1,
                "tests": 3, "fresh": 2}
    got = cl.summarise(that_day, ALL_SCOPES)
    assert got["status"] == "fail"
    assert got["blocking"] == ["fresh_rc"]


def test_all_green_is_pass_with_empty_lists() -> None:
    got = cl.summarise(ALL_GREEN, ALL_SCOPES)
    assert got["status"] == "pass"
    assert got["blocking"] == [] and got["warnings"] == [] and got["unverified"] == []


def test_every_light_is_printed_including_unverified() -> None:
    """「驗不了」不印出來就等於被當成通過了 —— 那正是要避開的形狀。"""
    lines = cl.messages({**ALL_GREEN, "tests": 3, "parse": 1, "fresh": 2},
                        {"tests": "/checks/tests-x.txt"}, ALL_SCOPES)
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
                 "fresh", "tests", "parse", "coverage", "drill"):
        assert f'--rc "{name}=$' in src, f"{name} 沒有被餵進判準"


# ── 綠燈必須帶分母（2026-08-21）─────────────────────────────────────────────
# 近 30 天 17 次「燈說假話」裡最大的一族，全部是**綠燈在空集合上算出來的**：
# 金絲雀守著 0 份（d9c5373）、比對函式在搬家中丟失所以比了 0 次（7d4a878）、
# 基準被清空成 `{}`（4a6e533）、少守 4 個量（0b3319d）。
# 每一次的處置都只修那一盞燈；這一族的通則在 `level_of` 的 `scope`。

def test_a_green_that_compared_nothing_is_not_green() -> None:
    """**本檔最重要的一條。** 比對了 0 件事不得回綠。

    這就是 `d9c5373` 當天的形狀：`postprocess.py canary` 印著
    「金絲雀通過：0 份基準文件的數字都沒變」並回 rc=0，而 `latest.json` 上
    它與「比對了 172 份都沒變」**完全無法區分**。
    """
    assert cl.level_of("canary", 0, 0) == cl.UNVERIFIED, "守著 0 份不是通過"
    assert cl.level_of("canary", 0, 172) == cl.OK


def test_a_green_without_any_denominator_is_not_green() -> None:
    """沒報分母也不給綠 —— 「還沒接上」不該長得像「驗過了」。

    ⚠ 這條刻意比較嚴：一支檢查改版之後忘了印 `#scope`，它會退回「驗不了」
    而不是安靜地繼續發綠燈。**寧可吵，不要沉默**（同 `level_of` 對不認得的
    檢查名的處置）。
    """
    assert cl.level_of("fresh", 0) == cl.UNVERIFIED
    assert cl.level_of("fresh", 0, 5) == cl.OK


def test_denominator_does_not_rescue_a_real_red() -> None:
    """分母只管綠燈。真的紅了，報再大的分母也還是紅。"""
    assert cl.level_of("fresh", 2, 9999) == cl.BLOCK
    assert cl.level_of("canary", 2, 172) == cl.BLOCK
    assert cl.level_of("tests", 3, 3) == cl.UNVERIFIED


def test_the_denominator_is_visible_to_a_human_and_to_a_machine() -> None:
    """分母要進 `latest.json`，也要進給人看的那一行。

    只印 rc 的話，「比對了 0 件事」與「比對了 172 件事都沒變」長得一模一樣 ——
    而那正是這條規則要修的東西。
    """
    got = cl.summarise({**ALL_GREEN, "canary": 0}, {**ALL_SCOPES, "canary": 0})
    assert got["levels"]["canary_rc"] == "unverified"
    line = "\n".join(cl.messages({**ALL_GREEN, "canary": 0}, {},
                                 {**ALL_SCOPES, "canary": 0}))
    assert "比對了 0 件" in line, f"人看不到分母：{line}"


def test_a_typo_in_the_denominator_name_is_rejected_not_ignored() -> None:
    """打錯的檢查名要吵。

    默默丟掉的話，那盞燈會退回「沒報分母」而看起來只是還沒接上 ——
    真正的原因（打錯字）永遠不會被發現。
    """
    r = _run(["--at", "t", "--commit", "c", "--rc", "canary=0", "--scope", "cnaary=1"])
    assert r.returncode != 0
    assert "不存在的檢查" in r.stderr


def test_daily_check_actually_collects_the_denominators() -> None:
    """守住接線：規則寫好了沒被呼叫等於沒寫。

    ⚠ 這條守的是 `5de6735` 那個形狀 —— canary 的離開碼當時**根本沒有被存下來**，
    紅了只出現在 stderr，讀 `latest.json` 的人看不到。分母同理。
    """
    src = (ROOT / "scripts" / "daily-check.sh").read_text(encoding="utf-8")
    assert "scope_of()" in src, "daily-check 沒有撿分母的函式"
    assert '"${scope_args[@]}"' in src, "撿到的分母沒有被餵進判準"
    for name in ("compat", "canary", "scan", "units", "deploy",
                 "fresh", "tests", "parse", "coverage", "drill"):
        assert f"add_scope {name} " in src or f"add_scope {name:<8} " in src, \
            f"{name} 沒有被撿分母"


def test_the_json_producers_print_the_denominator_on_the_path_daily_check_takes(
) -> None:
    """`--json` 的那兩支，分母要印在**提早 return 之前**。

    ⚠ **這條是被真的漏掉逼出來的。** 2026-08-21 第一版把 `#scope` 印在
    `coverage-check.py` 的 `report()` 裡，而 `--json` 會在呼叫 `report()`
    之前就 return —— 而 daily-check 用的正是 `--json`。上面那條 grep 測試
    照樣綠，因為檔案裡**確實有** `#scope` 這幾個字。

    ⇒ 「檔案裡有這行」與「那行跑得到」是兩件事。這正是本輪主題的縮影，
    而且它發生在修這個主題的 commit 裡。

    ⚠ **這仍然只是代理證明。** 真正的證明是在 dker 上用 `--json` 跑一次、
    看 stderr 有沒有那一行 —— 那需要 `.env`，coder 上刻意沒有。
    """
    import ast  # noqa: PLC0415

    for name in ("coverage-check.py", "compat-check.py"):
        src = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        tree = ast.parse(src)
        main = next((n for n in ast.walk(tree)
                     if isinstance(n, ast.FunctionDef) and n.name == "main"), None)
        assert main is not None, f"{name} 沒有 main()"

        # ⚠ **必須印在 `main()` 裡面。** 印在別的函式裡不算 —— `report()` 定義在
        # 檔案前面但**呼叫在 `--json` 分支之後**，所以「行號比較小」完全證明不了
        # 「執行得到」。第一版守衛就是用行號比大小，把 bug 搬回去它照樣綠。
        in_main = [n.lineno for n in ast.walk(main)
                   if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                   and n.func.id == "print" and "#scope" in ast.unparse(n)]
        assert in_main, (
            f"{name} 的分母沒有印在 main() 裡 —— 印在別的函式裡的話，"
            f"`--json` 那條路可能根本呼叫不到它（2026-08-21 實際踩過）")

        # 再確認它在會提早結束的 `--json` 分支**之前**。
        for node in ast.walk(main):
            if not isinstance(node, ast.If) or "json" not in ast.unparse(node.test):
                continue
            exits_early = any(
                isinstance(x, ast.Return)
                or (isinstance(x, ast.Call) and ast.unparse(x).startswith("sys.exit"))
                for x in ast.walk(node))
            if exits_early:
                assert min(in_main) < node.lineno, (
                    f"{name} 第 {node.lineno} 行的 `--json` 分支會提早結束，"
                    f"而分母印在第 {min(in_main)} 行 —— 跑不到")


def test_every_producer_prints_its_own_denominator() -> None:
    """分母要由**產出結果的那一支**自己印，不是由 daily-check 去 grep 它的散文。

    只有它自己知道它比對了什麼。讓 shell 去解析人類可讀的摘要，就是又一條
    會漂的路（同 `mineru_common` 檔頭警告的「同一份資料兩個答案」）。
    """
    producers = {
        "postprocess.py": "canary", "scan-partial.py": "scan",
        "parse-check.py": "parse", "coverage-check.py": "coverage",
        "compat-check.py": "compat", "systemd-units.py": "units",
        "deploy-stack.py": "deploy／fresh", "run-tests.sh": "tests",
        "drill.py": "drill",
    }
    missing = [f"{f}（{who}）" for f, who in producers.items()
               if "#scope" not in (ROOT / "scripts" / f).read_text(encoding="utf-8")]
    assert not missing, "這幾支沒有印分母，它們的綠燈會被判成驗不了：\n  " + "\n  ".join(missing)
