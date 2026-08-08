"""圖譜是用哪一版抽取規則建的 —— 判準本體。

CLI 在 `scripts/extraction-profile.py`（show／stamp／check），紅綠燈在
`compat-check` 的 A-32。兩邊**共用這裡的判準**，不各算一次 ——
同一件事算兩次就會有兩個答案，而沒有東西會發現它們不一致
（2026-08-08 審核台的「已處理 4／已進知識庫 5」就是這樣來的）。

**雜湊算的是 LightRAG 實際生效的指引，不是磁碟上的檔案。** 兩者會不一致：
檔案改了但容器沒重啟時，跑著的還是舊規則。算檔案的話會誤報「已經更新」——
那正是最糟的方向（以為換過了，其實沒有）。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pp.oracle import Oracle
from pp.paths import DataPaths

RECORD_NAME = "extraction-profile.json"

# 在容器裡問「現在生效的抽取指引是什麼」。刻意問解析後的結果而不是讀檔。
_PROBE = (
    "import json\n"
    "from lightrag.addon_params import default_addon_params\n"
    "from lightrag.prompt import resolve_entity_extraction_prompt_profile\n"
    "a = default_addon_params()\n"
    "p = resolve_entity_extraction_prompt_profile(a, True)\n"
    "print(json.dumps({\n"
    "    'guidance': p['entity_types_guidance'],\n"
    "    'json_examples': p['entity_extraction_json_examples'],\n"
    "    'file': a.get('entity_type_prompt_file') or '',\n"
    "}))\n"
)


def active_profile(oracle: Oracle) -> dict:
    """LightRAG 現在實際生效的抽取指引。"""
    return oracle.py(_PROBE)


def profile_hash(profile: dict) -> str:
    """指引內容的雜湊。只算內容，不算檔名 —— 換個檔名但內容相同不該算變動。"""
    payload = json.dumps(
        {"guidance": profile["guidance"], "json_examples": profile["json_examples"]},
        ensure_ascii=False, sort_keys=True)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def record_path(paths: DataPaths) -> Path:
    return paths.records_dir / RECORD_NAME


def read_record(paths: DataPaths) -> dict | None:
    p = record_path(paths)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
