"""指令守衛：每一條規則都要能擋下**真實發生過**的那一次，且不誤擋日常操作。

**誤擋比漏放更糟。** 一個會誤擋的守衛會被關掉，然後連真的那次也擋不到
（同 systemd-units.py:63「預期中的紅燈會訓練人無視所有紅燈」）。
所以下面每條規則都有兩組測試：真實事故的原句要被擋，日常操作要放行。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "guard_command", ROOT / "scripts" / "guard-command.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["guard_command"] = mod
    spec.loader.exec_module(mod)
    return mod


# ── 這些是 2026-08-08 真的打過、真的出事的指令 ──────────────────────────
REAL_INCIDENTS = [
    # 秘密外洩：印出整條命令列，裡面有 --api-key <值>
    ("""docker inspect llama-qwen36-moe --format '{{join .Config.Cmd " "}}'""",
     "docker-inspect-dumps-config"),
    # 「先取出再遮蔽」：值在下一格，遮蔽樣式抓不到
    ("""docker inspect x --format '{{json .Config.Cmd}}' | sed 's/api-key.*//'""",
     "redact-after-the-fact"),
    # 離開碼：抓到的是 tail 的，不是 compat-check 的
    ("""python3 scripts/compat-check.py --json | tail -5; echo "rc=$?" """,
     "exit-code-after-pipe"),
    ("""python3 scripts/deploy-stack.py freshness 2>&1 | tail -10; echo "rc=$?" """,
     "exit-code-after-pipe"),
]


@pytest.mark.parametrize(("command", "expected"), REAL_INCIDENTS)
def test_real_incidents_are_blocked(command: str, expected: str) -> None:
    """每條規則都要擋得住它當初沒擋住的那一次。"""
    hits = {r.name for r in _module().check(command)}
    assert expected in hits, f"{expected} 沒擋下：{command}"


@pytest.mark.parametrize("command", [
    "cat .env.example",                                   # 範本沒有秘密
    "grep -E '^KEY=' .env | cut -d= -f2-",                # 只取一個值，正解
    "grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' .env | tr -d '='",  # 只取鍵名，正解
    "printenv PROMPT_DIR",                                # 指定鍵
    "docker compose config --hash '*'",                   # 只要雜湊，不展開值
    "docker inspect x --format '{{index .Config.Cmd 13}}'",  # 只取一格，正解
    "docker inspect x --format '{{.State.StartedAt}}'",   # 跟設定無關
    "python3 scripts/compat-check.py --json > /tmp/o; rc=$?; tail /tmp/o",  # 正解
    "ls | wc -l",                                         # 普通管線
    "git log --oneline | head -5",
    "docker logs llama-qwen36-moe 2>&1 | grep n_slots",
])
def test_everyday_commands_are_not_blocked(command: str) -> None:
    """誤擋一次，守衛就會被關掉。日常操作與**正解本身**都必須放行。"""
    hits = _module().check(command)
    assert not hits, f"誤擋了：{command} → {[r.name for r in hits]}"


def test_every_rule_names_a_real_incident_and_an_alternative() -> None:
    """每條規則都要講得出「它擋的是哪一次」與「該怎麼做」。

    講不出來的規則就是憑感覺加的，那種規則遲早會誤擋，然後整個守衛被關掉。
    `instead` 必須是可以直接照抄的指令，不是「請小心」。
    """
    for r in _module().ALL_RULES:
        assert len(r.why) > 15, f"{r.name} 的理由太空泛"
        assert len(r.instead) > 15, f"{r.name} 沒給可照抄的替代做法"
        assert r.instead != r.why


def test_heredoc_content_is_data_not_command() -> None:
    """heredoc 裡提到危險指令不算 —— 那是資料不是指令。

    **血淚**：這份守衛上線的第一次提交就被自己擋下，因為 commit 訊息裡引用了
    規則名稱與範例指令（`cat .env.example`）。一個會擋掉「討論它自己」的守衛，
    第一天就會被關掉。
    """
    mod = _module()
    command = (
        "git commit -q -F - <<'EOF'\n"
        "feat(guard): 指令守衛\n"
        "\n"
        "  cat-dotenv    直接讀 .env 就是把秘密整包印出來\n"
        "  第一版誤擋了 cat .env.example，加 (?![.\\w]) 才修好\n"
        "  也擋過 docker inspect x --format '{{join .Config.Cmd \" \"}}'\n"
        "EOF"
    )
    hits = mod.check(command)
    assert not hits, f"heredoc 內容不該觸發：{[r.name for r in hits]}"


def test_a_real_command_before_a_heredoc_is_still_checked() -> None:
    """去掉 heredoc 不代表整條放行 —— heredoc 之外的部分照樣要看。"""
    mod = _module()
    command = "cat .env; git commit -F - <<'EOF'\n訊息\nEOF"
    assert {r.name for r in mod.check(command)} == {"cat-dotenv"}


def test_non_bash_tools_pass_through() -> None:
    """守衛只看 Bash。其他工具照原樣放行，不要卡住不相干的工作。"""
    mod = _module()
    assert mod.check("") == []


def test_report_tells_you_what_to_do_instead() -> None:
    """擋下來的訊息要含替代做法 —— 只說「不行」會讓人直接繞過檢查。"""
    mod = _module()
    cmd = """docker inspect x --format '{{join .Config.Cmd " "}}'"""
    text = mod.report(mod.check(cmd), cmd)
    assert "改用" in text
    assert "index .Config.Cmd" in text
