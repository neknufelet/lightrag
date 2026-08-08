#!/usr/bin/env python3
"""擋下已知會出事的臨時指令。這是 pre-commit 擋不到的那一半。

**為什麼需要這支**：2026-08-08 一天之內，同一類錯各犯了三次與兩次，而規則**早就
寫在文件裡**：

  秘密進了輸出（3 次）  `cairn/secrets-handling.md` 已寫明正解
  離開碼抓錯地方（2 次）第二次犯時，第一次的教訓已在當天的 commit 訊息裡

⇒ **知道規則不等於套用規則。** 寫進文件的規則只在有人記得的時候生效；
  寫成擋得住的檢查才每次都生效。

pre-commit 守的是「提交的碼」，但上面兩次都發生在**臨時打的指令**裡，從來不會
進版控。所以守門要往前移到指令執行之前。

用法（Claude Code 的 PreToolUse hook，見 .claude/settings.json）：
    echo '{"tool_name":"Bash","tool_input":{"command":"..."}}' | guard-command.py
退出碼：0 放行；2 擋下（訊息寫 stderr，呼叫端會看到）。

也可以手動檢查一條指令：
    guard-command.py --check 'docker inspect x --format "{{.Config.Env}}"'

**設計原則：寧可漏放不可誤擋。** 一個會誤擋的守衛會被關掉，然後連真的那次也
擋不到——同 `systemd-units.py:63` 那條「預期中的紅燈會訓練人無視所有紅燈」。
所以每條樣式都要能講出「它擋的是哪一次真實事故」，講不出來的就不要加。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern[str]
    why: str          # 擋它的理由，要指向真實事故
    instead: str      # 該怎麼做，必須是可以直接照抄的指令


# ── A. 秘密經由「整包輸出」離開 ────────────────────────────────────────
# 2026-08-08 三次外洩，全部是「先取出整包、再想辦法遮」。正解是一開始就只取要的。
SECRET_RULES: tuple[Rule, ...] = (
    Rule(
        "docker-inspect-dumps-config",
        # **只擋整包傾印的動詞**，不擋 `index .Config.Cmd 13`（那正是正解）。
        # 第一版擋了整個 .Config.Cmd，連自己建議的替代做法都會被擋 ——
        # 一個會擋掉正解的守衛，第一次用就會被關掉。測試抓到這個誤擋。
        re.compile(r"docker\s+(inspect|container\s+inspect)\b[^|;&]*"
                   r"((join|json|range)\s+\.Config\.(Cmd|Env|Entrypoint)"
                   r"|\{\{\s*\.Config\.(Cmd|Env|Entrypoint)\s*\}\}"
                   r"|json\s+\.Config\s*\}\})"),
        "docker inspect 印整條 Cmd／Env 會把 --api-key 的值一起帶出來"
        "（2026-08-08 實測外洩一次）",
        "只取要的那一格：docker inspect <容器> --format '{{index .Config.Cmd 13}}'",
    ),
    Rule(
        "compose-config-resolves-env",
        # `docker compose config` 會把 .env 的值全部展開印出來
        re.compile(r"docker\s+compose\b[^|;&]*\bconfig\b(?![^|;&]*--hash)"),
        "docker compose config 會把 .env 的值全部展開印出來",
        "要雜湊用 --hash '*'；要看服務定義先確認該檔沒有 env_file 或秘密插值",
    ),
    Rule(
        "whole-env-dump",
        re.compile(r"(^|[|;&]\s*)(env|printenv)\s*($|[|;&])"),
        "env／printenv 不帶鍵名會印出全部環境變數",
        "指定鍵：printenv PROMPT_DIR",
    ),
    Rule(
        "cat-dotenv",
        # `(?![.\w])` 是關鍵：不能命中 `.env.example`（那是範本，沒有秘密）。
        # 第一版漏了它，測試當場抓到誤擋。
        re.compile(r"\b(cat|less|more|head|tail|bat)\b[^|;&]*(^|[\s=/])\.env(?![.\w])"),
        "直接讀 .env 就是把秘密整包印出來",
        "只要鍵名：grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' .env | tr -d '='　"
        "只要某個值：grep -E '^KEY=' .env | cut -d= -f2-",
    ),
    Rule(
        "source-dotenv",
        re.compile(r"(^|[|;&]\s*)(source|\.)\s+[^\s|;&]*\.env\b"),
        "source .env 會讓秘密進入後續每一條指令的環境；"
        "而且本專案的 .env 含 `;`，source 會把分號後面當指令執行",
        "取單一鍵：grep -E '^KEY=' .env | cut -d= -f2-",
    ),
    Rule(
        "redact-after-the-fact",
        # 「先取出再遮蔽」的形狀：把整包導進 sed/grep 去遮
        re.compile(r"\.Config\.(Cmd|Env)[^|;&]*\|\s*(sed|awk|grep|python)"),
        "「先取出再遮蔽」的設計本身就是錯的 —— 遮蔽樣式寫錯就全洩，"
        "2026-08-08 兩次外洩都是這個形狀（見 cairn/secrets-handling.md）",
        "不要取出來再遮，一開始就只取不含秘密的那一格",
    ),
)

# ── B. 離開碼抓錯地方 ──────────────────────────────────────────────────
# `cmd | tail; echo $?` 抓到的是 tail 的。2026-08-08 兩次因此漏報真紅燈。
EXIT_CODE_RULES: tuple[Rule, ...] = (
    Rule(
        "exit-code-after-pipe",
        # 同一條複合指令裡：先有管線，之後才用 $?
        re.compile(r"\|[^;&\n]*[;&]\s*[^;&\n]*\$\?"),
        "管線後面的 $? 是**最後那支**的離開碼，不是你要的那支"
        "（2026-08-08 兩次因此把 rc=2 報成 rc=0，漏掉真紅燈）",
        "先存再管線：cmd > /tmp/out 2>&1; rc=$?; tail /tmp/out; echo \"rc=$rc\"",
    ),
)

ALL_RULES: tuple[Rule, ...] = SECRET_RULES + EXIT_CODE_RULES


# heredoc 的內容是**資料不是指令**。commit 訊息、寫入檔案的文字裡提到
# `cat .env` 這種字樣是完全正常的 —— 這份守衛自己的 commit 訊息就提到了。
#
# 血淚：守衛上線的第一次提交就被自己擋下，因為 commit 訊息裡引用了規則名稱與
# 範例指令。**一個會擋掉「討論它自己」的守衛，第一天就會被關掉。**
_HEREDOC = re.compile(
    r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1.*?^\2\s*$",
    re.DOTALL | re.MULTILINE)


def strip_heredocs(command: str) -> str:
    """把 heredoc 的內容拿掉，只留下真正會被執行的部分。"""
    return _HEREDOC.sub("<<HEREDOC", command)


def check(command: str) -> list[Rule]:
    """回傳這條指令命中的規則。空清單＝放行。"""
    # 逐條規則比對字串（去掉 heredoc 內容之後）。刻意不做完整 shell 解析——
    # 解析器本身會有落差，而落差會變成「看起來檢查過了」的假保證。
    text = strip_heredocs(command)
    return [r for r in ALL_RULES if r.pattern.search(text)]


def report(hits: list[Rule], command: str) -> str:
    lines = [f"擋下這條指令（命中 {len(hits)} 條規則）：", f"  {command[:200]}", ""]
    for r in hits:
        lines += [f"▸ {r.name}", f"  為什麼：{r.why}", f"  改用：  {r.instead}", ""]
    lines.append("確定要跑就改寫成上面的形式；規則本身寫在 scripts/guard-command.py。")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", help="直接檢查一條指令（不走 hook 的 JSON 介面）")
    a = ap.parse_args()

    if a.check is not None:
        command = a.check
    else:
        try:
            payload = json.load(sys.stdin)
        except (json.JSONDecodeError, ValueError):
            return 0                      # 讀不到就放行，守衛不該把工作卡死
        if payload.get("tool_name") != "Bash":
            return 0
        command = str(payload.get("tool_input", {}).get("command", ""))

    hits = check(command)
    if not hits:
        return 0
    print(report(hits, command), file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
