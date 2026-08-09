"""對 LightRAG 那組 Postgres 下唯讀查詢。

**為什麼要有這個檔**：`graph-shape.py`（量）與 `graph-clean.py`（刪）都要撈同一批
節點。各寫一份 `docker exec … psql` 的話，兩份的逾時、欄位分隔、錯誤處理會各自漂走
—— 而「量到 66、刪掉 39、下次量還是 66」這種分岔不會有錯誤訊息。

⚠ **只放唯讀查詢。** 改圖譜一律走 `pp/ragapi.py` 的官方端點：向量表、圖節點表、
圖邊表三者的一致性是 LightRAG 的內部契約，在容器外自己下 DELETE 等於重做一次
（鐵則第 3 條）。

⚠ **每一句 SQL 都要帶 `workspace`。** 同一組 Postgres 裡六個試驗 workspace 與正式庫
共存，而它們的 `file_path` 是同一批 PDF 檔名 —— 漏掉條件時逐份報表會把兩邊的同一份
文件併成一列，數字看起來完全正常（大約兩倍）、不報錯、不會有任何訊號。
2026-08-03 實測踩過。
"""
from __future__ import annotations

import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mineru_common import postgres_container  # noqa: E402


def sql_literal(value: str) -> str:
    """把值寫成 SQL 字串字面值。單引號要成對跳脫。"""
    return "'" + value.replace("'", "''") + "'"


def psql(env: Mapping[str, str], sql: str, timeout: int = 60) -> list[list[str]]:
    """跑一句 SQL，回傳逐列切好的欄位。失敗就炸掉，不回空清單。

    回空清單的話「查詢失敗」與「真的沒有資料」在呼叫端長得一樣 —— 而本專案
    踩過的坑有一半是這個形狀（鐵則第 7 條：乾淨的 0 要先當成量錯）。
    """
    p = subprocess.run(
        ["docker", "exec", postgres_container(dict(env)), "psql", "-U",
         env.get("POSTGRES_USER", "deeptutor"), "-d",
         env.get("POSTGRES_DATABASE", "lightrag"), "-tAF|", "-c", sql],
        capture_output=True, text=True, timeout=timeout, check=False)
    if p.returncode != 0:
        raise RuntimeError(f"psql 失敗：{p.stderr.strip()[:300]}")
    return [ln.split("|") for ln in p.stdout.strip().splitlines() if ln.strip()]
