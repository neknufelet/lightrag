"""`--env-file` 疊加：只變一個東西，而且變了什麼一定看得見。

**為什麼是疊加不是取代**：受控比對的前提是「只變一個變數」。取代的話覆寫檔要抄
一份完整設定，而抄的過程中漏掉或抄錯任何一個鍵，就多變了一個變數 —— 安靜地多變。

**為什麼一定要回報異動清單**：鍵名打錯（`PP_EYE_A_MODLE`）時疊加會安靜地成功、
什麼都沒改，而實驗結果看起來就像「換了模型但沒差」—— 那是本專案最貴的一種錯，
因為它會被當成結論寫進報告。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from mineru_common import (  # noqa: E402
    EnvFileMissing,
    overlay_env,
    parse_env_text,
    resolve_env,
)

BASE = {
    "WORKSPACE": "acoustics_v2",
    "LLM_BINDING_HOST": "http://100.71.26.77:8080/v1",
    "LLM_MODEL": "qwen3.6-35b-a3b",
    "PP_EYE_B_MODEL": "gpt-5.6-luna",
}


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "trial.env"
    p.write_text(text, encoding="utf-8")
    return p


def test_overlay_keeps_everything_it_did_not_mention(tmp_path: Path) -> None:
    """沒提到的鍵原封不動 —— 這就是「只變一個變數」的機械保證。"""
    env, _ = overlay_env(BASE, _write(tmp_path, "PP_EYE_A_MODEL=qwen/qwen3-vl-32b-instruct\n"))
    assert env["PP_EYE_A_MODEL"] == "qwen/qwen3-vl-32b-instruct"
    for key, value in BASE.items():
        assert env[key] == value, f"{key} 被動到了"


def test_overlay_reports_new_versus_overwritten(tmp_path: Path) -> None:
    """異動清單要分「覆寫」與「新增」。

    打錯的鍵名會落在「新增」那一欄 —— 那正是要看的地方。
    """
    p = _write(tmp_path, "LLM_MODEL=deepseek-v4-flash\nPP_EYE_A_MODLE=typo\n")
    _, changes = overlay_env(BASE, p)
    assert dict(changes) == {"LLM_MODEL": "覆寫", "PP_EYE_A_MODLE": "新增"}


def test_missing_overlay_file_raises_instead_of_being_ignored(tmp_path: Path) -> None:
    """檔案不存在要炸掉，不能當成「沒有覆寫」繼續跑。

    當成沒有覆寫的話，整場比對會**用正式設定跑完**而看起來一切正常 ——
    然後你會拿著「換了模型但數字沒變」的結論去做決定。
    """
    with pytest.raises(EnvFileMissing):
        overlay_env(BASE, tmp_path / "不存在.env")


def test_parser_handles_values_containing_semicolons() -> None:
    """`LIGHTRAG_PARSER` 的值含 `;`。用 shell source 會把分號後面當指令，
    所以覆寫檔必須跟 `.env` 走同一支解析器。"""
    env = parse_env_text('LIGHTRAG_PARSER=a;b;c\nX="quoted"\n# 註解=不算\n')
    assert env["LIGHTRAG_PARSER"] == "a;b;c"
    assert env["X"] == "quoted"
    assert "# 註解" not in env


def test_resolve_env_without_flag_is_a_plain_load(monkeypatch: pytest.MonkeyPatch,
                                                 tmp_path: Path) -> None:
    """不帶 `--env-file` 時等於原本的 `load_env`，而且不印任何東西。

    這條守的是「加了旗標不會影響既有用法」。
    """
    (tmp_path / ".env").write_text("WORKSPACE=acoustics_v2\nLLM_MODEL=qwen3.6-35b-a3b\n",
                                   encoding="utf-8")
    env, lines = resolve_env(tmp_path, [])
    assert env == {"WORKSPACE": "acoustics_v2", "LLM_MODEL": "qwen3.6-35b-a3b"}
    assert lines == []


def test_resolve_env_applies_flag_and_returns_report(monkeypatch: pytest.MonkeyPatch,
                                                     tmp_path: Path) -> None:
    """帶了旗標就疊加，而且回報行數不為空（呼叫端負責印出來）。"""
    (tmp_path / ".env").write_text("WORKSPACE=acoustics_v2\nLLM_MODEL=qwen3.6-35b-a3b\n",
                                   encoding="utf-8")
    over = _write(tmp_path, "LLM_MODEL=deepseek-v4-flash\nPP_EYE_A_MODEL=qwen3.6-35b-a3b\n")
    env, lines = resolve_env(tmp_path, ["--env-file", str(over), "check", "--doc", "X"])
    assert env["LLM_MODEL"] == "deepseek-v4-flash"
    assert env["PP_EYE_A_MODEL"] == "qwen3.6-35b-a3b"
    assert env["WORKSPACE"] == "acoustics_v2", "沒提到的鍵被動到了"
    assert any("設定覆寫" in line for line in lines)
    assert any("新增" in line and "PP_EYE_A_MODEL" in line for line in lines)


def test_report_never_contains_values(tmp_path: Path) -> None:
    """回報只有鍵名。覆寫檔裡會有金鑰，印出去就是外洩。

    2026-08-08 這個專案外洩過一次金鑰（`docker inspect` 印整條 Cmd），
    所以現在任何「把設定印出來」的路徑都要有這條測試。
    """
    (tmp_path / ".env").write_text("WORKSPACE=acoustics_v2\n", encoding="utf-8")
    secret = "sk-or-v1-this-would-be-a-real-key"
    over = _write(tmp_path, f"PP_EYE_A_API_KEY={secret}\n")
    _, lines = resolve_env(tmp_path, ["--env-file", str(over)])
    blob = "\n".join(lines)
    assert "PP_EYE_A_API_KEY" in blob
    assert secret not in blob, "金鑰被印進回報裡了"
