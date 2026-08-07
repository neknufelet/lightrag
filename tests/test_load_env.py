"""`load_env` 在 `.env` 不存在時必須大聲失敗。

**為什麼需要這支**：舊版寫 `if not p.exists(): return {}`。2026-08-07 把 `.env`
搬到 `/opt/stacks/lightrag/` 時踩到——16 支呼叫端全部拿到空字典**繼續跑**：
`MINERU_IS_OCR` 沒了（文字層路徑會靜默吃掉 x-height 字母）、
`ENTITY_EXTRACTION_USE_JSON` 沒了（關係會被 LightRAG 100% 拒收），
而畫面上一個錯誤訊息都沒有。

不是壞掉，是**安靜地做錯事**——本專案一路在防的就是這個形狀。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from mineru_common import EnvFileMissing, load_env  # noqa: E402


def test_missing_env_raises_not_returns_empty(tmp_path: Path) -> None:
    """檔案不在 ⇒ 例外。回空字典是 2026-08-07 的坑，不得回歸。"""
    with pytest.raises(EnvFileMissing) as e:
        load_env(tmp_path)
    msg = str(e.value)
    assert "/opt/stacks/lightrag/.env" in msg, "錯誤訊息要指出現役的 .env 在哪"
    assert "coder" in msg, "要說明 coder 上刻意沒有它，否則會有人去 coder 上找"


def test_required_false_still_allows_empty(tmp_path: Path) -> None:
    """逃生門存在但要顯式指定 —— 目前沒有呼叫端用它。"""
    assert load_env(tmp_path, required=False) == {}


def test_reads_keys_and_strips_quotes(tmp_path: Path) -> None:
    """正常路徑：註解與空行略過，引號剝掉。"""
    (tmp_path / ".env").write_text(
        "# 註解\n\nA=1\nB='two'\nC=\"three\"\nNEO4J_URI=bolt://x:7687\n",
        encoding="utf-8")
    env = load_env(tmp_path)
    assert env == {"A": "1", "B": "two", "C": "three", "NEO4J_URI": "bolt://x:7687"}


def test_key_with_digit_is_not_dropped(tmp_path: Path) -> None:
    """含數字的鍵名要讀得到。

    2026-08-07 用 `^[A-Z_]+=` 數鍵，配不到 `NEO4J_URI` 的 `4`，少算 4 個並把
    錯的數字寫進 commit。`load_env` 本身沒有這個 bug，這條是防它長出來。
    """
    (tmp_path / ".env").write_text("NEO4J_URI=x\nPP_EYE_C_PROVIDER=y\n", encoding="utf-8")
    assert set(load_env(tmp_path)) == {"NEO4J_URI", "PP_EYE_C_PROVIDER"}
