"""`oracle.py` 不得讓秘密上指令列，也不得把秘密印進錯誤訊息。

**為什麼需要這支**：2026-08-08 實測外洩。一次呼叫錯誤（把 env 字典當 workspace
傳給 `container_for`）讓容器名變成 `lightrag-{整包設定}`，docker 的 stderr 原樣
回聲，於是 `LIGHTRAG_API_KEY` 與 `POSTGRES_PASSWORD` 印進了終端機。

查下去發現兩條路徑，第二條更嚴重：

| 路徑 | 舊行為 |
|---|---|
| 非零 exit | `shlex.join(cmd[:4])` 截斷（安全）＋ `p.stderr` 原樣（**會回聲**） |
| **逾時** | `shlex.join(cmd)` —— **完整指令**，六個 `-e KEY=VALUE` 全出來 |

而且就算沒有例外，`-e KEY=VALUE` 本身就讓同機任何人 `ps aux` 看得到全部秘密。

修法：`docker exec --env-file`（值不進 argv，檔案 0600、用完即刪）＋ 錯誤訊息
遮蔽秘密值。這支測試守住兩邊。
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from pp.oracle import Oracle, OracleError, _redact, is_secret_key  # noqa: E402

# `.env.example` 開頭那份秘密清單，逐字。刻意手抄而不是從檔案讀 —— 這是獨立的
# 第二份判準，自動推導出來的清單無法抓出「`is_secret_key` 本身漏判」。
# 漂移由 test_env_example_has_no_unlisted_secret_key 守住（見下）。
KNOWN_SECRET_KEYS = (
    "LIGHTRAG_API_KEY", "POSTGRES_PASSWORD", "LLM_BINDING_API_KEY",
    "EMBEDDING_BINDING_API_KEY", "RERANK_BINDING_API_KEY", "MINERU_API_TOKEN",
    # 眼睛 A 2026-08-09 從抽取 LLM 拆出來，指向 OpenRouter 之後自己有一把金鑰。
    # 在那之前它沿用 LLM_BINDING_API_KEY，所以清單上沒有這一條。
    "PP_EYE_A_API_KEY",
    "PP_EYE_B_API_KEY", "PP_EYE_C_API_KEY",
)

SECRET = "s3cr3t-value-do-not-leak"
ENV = {"WORKSPACE": "ws_x", "LIGHTRAG_API_KEY": SECRET, "POSTGRES_PASSWORD": SECRET}


def test_every_known_secret_key_is_recognised() -> None:
    """每個已知的秘密鍵都要被認出來。漏一個就是安靜地洩漏那一個。"""
    missed = [k for k in KNOWN_SECRET_KEYS if not is_secret_key(k)]
    assert not missed, f"這些鍵沒被當成秘密：{missed}"


def test_secret_table_matches_known_secret_keys() -> None:
    """`.env.example` 開頭那張「哪些是秘密、去哪裡拿」的表要與上面的清單一致。

    **為什麼需要這支**：那張表是重建時唯一的秘密來源說明。2026-08-08 切成本機
    Infinity 時新增了 `RERANK_BINDING_API_KEY`，表裡沒有它——重建的人於是不知道
    那把金鑰也要重新產生。

    這**不是外洩**：`is_secret_key()` 用樣式比對，含 `KEY` 就會被遮蔽，漏列不影響
    遮蔽。壞的是**重建說明少一條**，而那要到重建當下才會發現。
    """
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    listed = set(re.findall(r"^#\s+([A-Z][A-Z0-9_]*)\s+\|", text, re.MULTILINE))
    assert listed == set(KNOWN_SECRET_KEYS), (
        f"表裡多出來：{sorted(listed - set(KNOWN_SECRET_KEYS))}／"
        f"表裡漏掉：{sorted(set(KNOWN_SECRET_KEYS) - listed)}")


def test_known_secret_keys_all_exist_in_env_example() -> None:
    """清單上的每個鍵都要真的存在於 `.env.example`。

    否則會出現反向漂移：鍵已經退役（像 2026-08-07 的四個 `NEO4J_*`），清單和
    秘密表卻還留著，重建時去產生一把沒有人要的金鑰。
    """
    keys = {
        line.split("=", 1)[0]
        for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", line)
    }
    missing = [k for k in KNOWN_SECRET_KEYS if k not in keys]
    assert not missing, f"清單上有鍵在 `.env.example` 裡不存在：{missing}"


def test_ordinary_keys_are_not_over_redacted() -> None:
    """一般鍵不該被當秘密——過度遮蔽會讓錯誤訊息失去診斷價值。"""
    for key in ("WORKSPACE", "HOST", "PORT", "MINERU_IS_OCR", "LLM_MODEL"):
        assert not is_secret_key(key), key


def test_redact_replaces_value_but_keeps_key_name() -> None:
    """遮的是值不是鍵名。鍵名讓人知道是哪一個出事，值才不能外流。"""
    out = _redact(f"stderr: token={SECRET} 之類", ENV)
    assert SECRET not in out
    assert "LIGHTRAG_API_KEY" in out or "POSTGRES_PASSWORD" in out


def test_secrets_never_reach_the_command_line(monkeypatch: pytest.MonkeyPatch) -> None:
    """**核心斷言**：秘密的值不得出現在 argv 裡。

    `-e KEY=VALUE` 會讓同機任何人 `ps aux` 看到。改用 --env-file 之後，argv
    只會有檔案路徑。
    """
    seen: list[list[str]] = []

    def fake_run(cmd, **_kw):
        seen.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    Oracle(container="c")._run(["python", "-c", "pass"], ENV)

    assert seen, "沒有攔到任何指令"
    joined = " ".join(seen[0])
    assert SECRET not in joined, f"秘密出現在指令列：{joined}"
    assert "--env-file" in seen[0], "應該改用 --env-file 傳遞"


def test_timeout_message_is_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    """逾時那條舊版印完整 cmd —— 六個秘密一次全出來。"""
    def fake_run(cmd, **_kw):
        raise subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(OracleError) as e:
        Oracle(container="c")._run(["python", "-c", "pass"], ENV)
    assert SECRET not in str(e.value), f"逾時訊息洩漏：{e.value}"


def test_nonzero_exit_message_is_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    """stderr 會原樣回聲我們傳進去的東西 —— 2026-08-08 外洩就是走這條。"""
    def fake_run(cmd, **_kw):
        return SimpleNamespace(returncode=1, stdout="",
                               stderr=f"No such container: lightrag-{ENV}")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(OracleError) as e:
        Oracle(container="c")._run(["python", "-c", "pass"], ENV)
    assert SECRET not in str(e.value), f"錯誤訊息洩漏：{e.value}"


def test_env_file_is_cleaned_up(monkeypatch: pytest.MonkeyPatch) -> None:
    """暫存檔用完即刪 —— 留著等於把秘密寫到磁碟上放著。"""
    captured: list[str] = []

    def fake_run(cmd, **_kw):
        captured.append(cmd[cmd.index("--env-file") + 1])
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    Oracle(container="c")._run(["python", "-c", "pass"], ENV)
    assert captured and not Path(captured[0]).exists(), "暫存的 env 檔沒有刪掉"


def test_value_with_newline_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """含換行的值會破壞 env-file 格式。靜靜跳過會讓設定少一個鍵且無訊號。"""
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""))
    with pytest.raises(OracleError) as e:
        Oracle(container="c")._run(["python", "-c", "pass"], {"A": "x\ny"})
    assert "換行" in str(e.value)
