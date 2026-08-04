#!/usr/bin/env python3
"""比同一個 `lightrag` DB 裡兩個 workspace 對同一份文件的索引結果。

為什麼要有這支：v155 凍結當對照組，v2 重建。兩邊的差異必須**從資料庫本人問出來**，
不能靠人工記錄的數字 —— 記錄會抄錯、會過期，而且抄錯時沒有任何訊號。

多個知識庫共存於同一組 Postgres／Neo4j，靠 `workspace` 欄位隔離（見 README
「儲存後端」）。所以「比兩個 workspace」就是同一張表加一個 where，不需要連兩個庫。

量四個數：

    chunks        切了幾片
    entities      抽出幾個實體　（lightrag_full_entities.count，逐文件）
    relations     抽出幾條關係　（lightrag_full_relations.count，逐文件）
    含掉字 chunk  掉字偵測器命中的片數

掉字偵測器用的是 README 記載、已驗證過的 `\\y` 版：

    (?:\\s+[a-z]{1,2}\\y){5,}

**不要**改成兩側都是 `\\s` 的版本 —— 前一次匹配會吃掉後一次的前導空白，
於是它永遠回 0，而「偵測器壞了」跟「一個都沒有」在畫面上長得一模一樣。

文件母體取自 `lightrag_doc_status` 而不是 chunks：文件登記了卻一片 chunk 都沒有
（抽取失敗、或還沒跑）是**有意義的狀態**，從 chunks 出發的話那種文件會整列消失，
看起來像沒這份文件。

用法：
    compare-ws.py Equivalent <workspace-a>               # wsB 預設本 checkout 的 WORKSPACE
    compare-ws.py Equivalent <workspace-a> <workspace-b>
    compare-ws.py '' <workspace-a> <workspace-b>         # 空關鍵字＝全部文件
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mineru_common import load_env, postgres_container  # noqa: E402
from pp.oracle import env_workspace  # noqa: E402

REPO = Path(__file__).resolve().parent.parent

# 已驗證的掉字偵測器（README）。\y 是 Postgres 的字界，等同 \b。
MANGLED_RE = r"(?:\s+[a-z]{1,2}\y){5,}"


def q(s: str) -> str:
    """SQL 字串字面值。自己包引號，不用 shell 插值 —— 檔名裡有引號、空白、
    中文都不會壞掉，也不會把資料當成程式碼執行。"""
    return "'" + s.replace("'", "''") + "'"


def psql(env: dict, sql: str) -> list[list[str]]:
    container = postgres_container(env)
    cmd = ["docker", "exec", container, "psql",
           "-U", env.get("POSTGRES_USER", "deeptutor"),
           "-d", env.get("POSTGRES_DATABASE", "lightrag"),
           "-tAF|", "-c", sql]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        sys.exit(f"compare-ws: psql 失敗（{container}）：{p.stderr.strip()[:400]}")
    return [ln.split("|") for ln in p.stdout.strip().splitlines() if ln.strip()]


def fetch(env: dict, keyword: str, wss: list[str]) -> dict:
    where_ws = " or ".join(f"s.workspace = {q(w)}" for w in wss)
    # 用 position() 而不是 LIKE：關鍵字裡的 % 與 _ 不會變成萬用字元。
    where_kw = ("" if not keyword else
                f" and position(lower({q(keyword)}) in lower(s.file_path)) > 0")
    sql = f"""
select s.workspace, s.file_path, s.status,
       coalesce(c.n, 0), coalesce(c.mangled, 0),
       coalesce(e.count, 0), coalesce(r.count, 0)
from lightrag_doc_status s
left join (
    select workspace, full_doc_id, count(*) as n,
           count(*) filter (where content ~ {q(MANGLED_RE)}) as mangled
    from lightrag_doc_chunks group by 1, 2
) c on c.workspace = s.workspace and c.full_doc_id = s.id
left join lightrag_full_entities  e on e.workspace = s.workspace and e.id = s.id
left join lightrag_full_relations r on r.workspace = s.workspace and r.id = s.id
where ({where_ws}){where_kw}
order by s.file_path, s.workspace;
"""
    out: dict[str, dict[str, dict]] = {}
    for row in psql(env, sql):
        ws, fp, status, n, mang, ents, rels = row
        out.setdefault(fp, {})[ws] = {
            "status": status, "chunks": int(n), "mangled": int(mang),
            "entities": int(ents), "relations": int(rels),
        }
    return out


ZERO = {"status": "（無此文件）", "chunks": 0,
        "mangled": 0, "entities": 0, "relations": 0}
METRICS = [("chunks", "chunks"), ("entities", "entities"),
           ("relations", "relations"), ("mangled", "含掉字 chunk")]


def _w(s: str) -> int:
    """顯示寬度。CJK 佔兩欄，用 len() 對齊會歪掉。"""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in s)


def lpad(s: str, n: int) -> str:
    return " " * max(0, n - _w(s)) + s


def rpad(s: str, n: int) -> str:
    return s + " " * max(0, n - _w(s))


def main() -> int:
    env = load_env(REPO)
    ap = argparse.ArgumentParser(description="比兩個 workspace 對同一份文件的索引結果")
    ap.add_argument("keyword", help="檔名關鍵字（空字串＝全部文件）")
    ap.add_argument("ws_a", help="對照組 workspace")
    ap.add_argument("ws_b", nargs="?", default=None,
                    help="預設為本 checkout .env 的 WORKSPACE")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    ws_b = a.ws_b or env_workspace()
    if a.ws_a == ws_b:
        sys.exit(f"compare-ws: 兩邊都是 {ws_b}，沒有可比的東西")

    docs = fetch(env, a.keyword, [a.ws_a, ws_b])
    if not docs:
        sys.exit(f"compare-ws: {a.ws_a} 與 {ws_b} 都找不到符合 {a.keyword!r} 的文件")

    if a.json:
        print(json.dumps(docs, ensure_ascii=False, indent=1))
        return 0

    for fp in sorted(docs):
        A = docs[fp].get(a.ws_a, ZERO)
        B = docs[fp].get(ws_b, ZERO)
        print(f"\n=== {fp} ===")
        print(rpad("", 16) + lpad(a.ws_a, 18) + lpad(ws_b, 18) + lpad("差", 12))
        print(rpad("status", 16) + lpad(A["status"], 18) + lpad(B["status"], 18))
        for key, label in METRICS:
            d = B[key] - A[key]
            print(rpad(label, 16) + lpad(f"{A[key]:,}", 18)
                  + lpad(f"{B[key]:,}", 18) + lpad(f"{d:+,}", 12))
    print(f"\n共 {len(docs)} 份文件。"
          f"『含掉字 chunk』用 README 記載的 \\y 版偵測器：{MANGLED_RE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
