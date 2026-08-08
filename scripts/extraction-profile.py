#!/usr/bin/env python3
"""圖譜是用哪一版抽取規則建的 —— 記下來，並在規則變了的時候有人知道。

**為什麼需要這支**：解析那一側早就有這個東西（`_manifest.json` 的
`options_signature`，`compat-check` 的 A-11 在守它），改了 MinerU 選項就會紅燈說
「這份 bundle 是用不同解析選項產生的」。**抽取這一側完全沒有對應物。**

後果是：改了 `prompts/entity_type/acoustics.yml` 之後，新進的文件用新規則、舊的
還是舊規則，圖譜混著兩代，而**沒有任何紅燈**。而且「這批是用哪版抽的」事後補不
回來——只能靠推測。

**雜湊算的是 LightRAG 實際生效的指引，不是磁碟上的檔案。** 兩者會不一致：
檔案改了但容器沒重啟時，跑著的還是舊規則。算檔案的話會誤報「已經更新」——
那正是最糟的方向（以為換過了，其實沒有）。

用法：
    ./extraction-profile.py show            # 現在生效的是哪一版
    ./extraction-profile.py stamp           # 重抽完成後記錄（會覆寫）
    ./extraction-profile.py check           # 比對現行與記錄，不一致回 2

紀錄檔：`${DATA_ROOT}/records/extraction-profile.json`
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mineru_common import add_workspace_arg, load_env  # noqa: E402
from pp.oracle import Oracle, OracleError, container_for  # noqa: E402
from pp.paths import DataPaths, configured_data_root  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
RECORD_NAME = "extraction-profile.json"

# 在容器裡問「現在生效的抽取指引是什麼」。刻意問解析後的結果而不是讀檔：
# 檔案改了但容器沒重啟時，這兩者不一樣，而跑著的那份才是真的。
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


def indexed_docs(env: dict[str, str], workspace: str) -> list[str]:
    """目前索引裡有哪些文件。記進紀錄，才知道那個雜湊涵蓋了哪些。"""
    from mineru_common import postgres_container
    sql = ("select file_path from lightrag_doc_status where workspace = '"
           + workspace.replace("'", "''") + "' order by 1;")
    p = subprocess.run(
        ["docker", "exec", postgres_container(env), "psql", "-U",
         env.get("POSTGRES_USER", "deeptutor"), "-d",
         env.get("POSTGRES_DATABASE", "lightrag"), "-tAqX", "-c", sql],
        capture_output=True, text=True, timeout=30, check=False)
    if p.returncode != 0:
        raise RuntimeError(f"psql 失敗：{p.stderr.strip()[:200]}")
    return [ln.strip() for ln in p.stdout.splitlines() if ln.strip()]


def _head_commit() -> str:
    p = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
                       capture_output=True, text=True, timeout=30, check=False)
    return p.stdout.strip() or "unknown"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=("show", "stamp", "check"))
    a_env = load_env(REPO)
    add_workspace_arg(ap, a_env)
    a = ap.parse_args()

    paths = DataPaths(configured_data_root())
    oracle = Oracle(container=container_for(a.workspace))
    try:
        profile = active_profile(oracle)
    except OracleError as exc:
        print(f"問不到現行抽取規則：{exc}", file=sys.stderr)
        return 3
    now_hash = profile_hash(profile)
    record = read_record(paths)

    if a.cmd == "show":
        print(f"現行生效的抽取規則　{now_hash}")
        print(f"  來源檔　{profile['file'] or '（上游預設，沒有自訂）'}")
        print(f"  指引長度　{len(profile['guidance']):,} 字元")
        if record:
            same = record.get("profile_hash") == now_hash
            print(f"\n圖譜建立時的規則　{record.get('profile_hash')}"
                  f"　{'（相同）' if same else '**（不同 —— 圖譜是舊規則抽的）**'}")
            print(f"  記錄於　{record.get('stamped_at')}　commit {record.get('commit')}")
            print(f"  涵蓋　{len(record.get('documents', []))} 份文件")
        else:
            print(f"\n**還沒有紀錄**（{record_path(paths)} 不存在）"
                  "—— 無從得知圖譜是用哪版規則抽的")
        return 0

    if a.cmd == "stamp":
        docs = indexed_docs(a_env, a.workspace)
        payload = {
            "profile_hash": now_hash,
            "profile_file": profile["file"],
            "guidance_chars": len(profile["guidance"]),
            "workspace": a.workspace,
            "documents": docs,
            "commit": _head_commit(),
            "stamped_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        path = record_path(paths)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        print(f"已記錄　{now_hash}")
        print(f"  涵蓋 {len(docs)} 份文件，寫入 {path}")
        return 0

    # check
    if record is None:
        print("**沒有紀錄** —— 無從得知圖譜是用哪版規則抽的。"
              "重抽完成後跑一次 `extraction-profile.py stamp`。", file=sys.stderr)
        return 2
    if record.get("profile_hash") != now_hash:
        print(f"**抽取規則已變，但圖譜還是舊規則抽的**\n"
              f"  圖譜建立時　{record.get('profile_hash')}"
              f"（{record.get('stamped_at')}，{len(record.get('documents', []))} 份）\n"
              f"  現在生效　　{now_hash}\n"
              f"  ⇒ 要嘛重抽讓兩者一致，要嘛把規則改回去。"
              f"不重抽的話，新舊文件會用不同規則而沒有訊號。", file=sys.stderr)
        return 2
    print(f"一致　{now_hash}　（{len(record.get('documents', []))} 份文件）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
