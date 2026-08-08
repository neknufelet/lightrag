#!/usr/bin/env python3
"""量一次查詢的 context 預算實際花到哪裡去。

**為什麼需要這支**：2026-08-08 調整 `MAX_ENTITY_TOKENS` 之前，我用算式估「每個
chunk 約 600 token」，實測是 **1,818** —— 錯 3 倍，而且結論因此完全相反。
同一天還估錯過「圖譜的上限只是上限、實際用不到」，實測是 5,983/6,000（99.7%）。

⇒ **預算分配不要用算的，要問系統。** 這支就是那個「問」。

作法：發一次 `only_need_context=true` 的查詢（不生成、不花 LLM 時間），把回來的
context 用**容器裡同一個 tokenizer** 數。不做任何換算或抽樣估計。

用法：
    ./context-budget.py                     # 用內建題組
    ./context-budget.py --query "..."       # 指定一題
    ./context-budget.py --mode naive        # 換檢索模式（預設 mix）
    ./context-budget.py --json              # 給程式解析／存基準

看得懂輸出的關鍵：`Document Chunks` 那一列的「筆」是實際回來幾段原文。
它受兩個東西夾擊，要分得出是哪一個在擋：
    數量上限  CHUNK_TOP_K（預設 20）
    token 預算 MAX_TOTAL_TOKENS 扣掉圖譜與系統提示之後剩下的
筆數 < 上限 ⇒ 是 token 在擋，加預算有用；筆數 == 上限 ⇒ 加預算沒用，要調上限。
"""
from __future__ import annotations

import argparse
import itertools
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mineru_common import load_env  # noqa: E402
from pp.oracle import container_for, env_workspace  # noqa: E402

REPO = Path(__file__).resolve().parent.parent

# 內建題組：刻意混合「符號密集」與「散文」兩型。
# 2026-08-08 實測碎片化的浪費在這兩型之間差很多（18% vs 0%），只用一型會誤導。
DEFAULT_QUERIES: tuple[str, ...] = (
    "How does a coiled-up channel lower the resonance frequency of an absorber?",
    "What is the relationship between the micro-perforated panel impedance Z_Mi and its hole diameter?",
    "Why do coupled resonators broaden the absorption bandwidth?",
    "What determines the acoustic impedance of an orifice partition?",
)

# context 的分段標題。LightRAG 用這幾個字串起頭，後面接說明文字，所以只比對開頭。
SECTION_HEADS: tuple[str, ...] = (
    r"Knowledge Graph Data \([^)]*\)",
    r"Document Chunks",
)


def _sections(ctx: str) -> list[tuple[str, str]]:
    """把 context 切成 (段名, 內容)。切不開時整包當成一段回，不要靜靜地少算。"""
    pattern = "|".join(SECTION_HEADS)
    marks = [(m.start(), m.group(0).strip())
             for m in re.finditer(rf"^\s*({pattern})", ctx, re.MULTILINE)]
    if not marks:
        return [("<未分段>", ctx)]
    bounds = [*marks, (len(ctx), "<END>")]
    return [(name, ctx[start:end])
            for (start, name), (end, _) in itertools.pairwise(bounds)]


# 在容器裡數 token 的小程式。**一定要用 LightRAG 自己的 tokenizer**：
# 拿字元數除以某個係數會錯得離譜，中英混排尤其。宿主上沒有 lightrag 套件，
# 所以把文字餵進容器數，而不是在宿主重新實作一份「差不多的」計算。
_COUNTER = (
    "import json,sys\n"
    "from lightrag.utils import TiktokenTokenizer\n"
    "t=TiktokenTokenizer()\n"
    "print(json.dumps([len(t.encode(s)) for s in json.load(sys.stdin)]))\n"
)


def count_tokens(texts: list[str], container: str) -> list[int]:
    """用容器裡的 tokenizer 數這幾段各是多少 token。"""
    p = subprocess.run(
        ["docker", "exec", "-i", container, "python", "-c", _COUNTER],
        input=json.dumps(texts), capture_output=True, text=True,
        timeout=120, check=False)
    if p.returncode != 0:
        raise RuntimeError(f"在 {container} 內數 token 失敗：{p.stderr.strip()[:300]}")
    return json.loads(p.stdout)


def measure(query: str, mode: str, base: str, api_key: str,
            timeout: int, container: str) -> dict:
    """發一次只要 context 的查詢，回各段的 token 數與筆數。"""
    req = urllib.request.Request(
        f"{base}/query",
        data=json.dumps({"query": query, "mode": mode,
                         "only_need_context": True}).encode(),
        headers={"Content-Type": "application/json", "X-API-Key": api_key},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        ctx = json.loads(r.read())["response"]

    sections = _sections(ctx)
    counts = count_tokens([ctx, *(body for _, body in sections)], container)
    return {
        "query": query,
        "mode": mode,
        "total_tokens": counts[0],
        "sections": [
            # LightRAG 每筆是一行 JSON，所以數 `\n{"` 就是筆數
            {"name": name, "tokens": tokens, "rows": body.count('\n{"')}
            for (name, body), tokens in zip(sections, counts[1:], strict=True)
        ],
    }


def _print(rec: dict) -> None:
    print(f"\n【{rec['mode']}】{rec['query'][:70]}")
    print(f"  整包 {rec['total_tokens']:>7,} token")
    kg = 0
    for s in rec["sections"]:
        short = s["name"].split("(")[0].strip() + (
            f"（{s['name'].split('(')[1].rstrip(')')}）" if "(" in s["name"] else "")
        print(f"    {short:<34} {s['tokens']:>7,} token   {s['rows']:>4} 筆")
        if "Knowledge Graph" in s["name"]:
            kg += s["tokens"]
    print(f"    {'圖譜合計':<34} {kg:>7,} token")
    print(f"    {'原文合計':<34} {rec['total_tokens'] - kg:>7,} token")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--query", action="append", help="要量的問題，可重複；不給就用內建題組")
    ap.add_argument("--mode", default="mix", help="檢索模式（預設 mix）")
    ap.add_argument("--base", default="",
                    help="LightRAG 位址（預設由 .env 的 BIND_ADDR 與 HOST_PORT 組出來）")
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--container", default="",
                    help="數 token 用的容器（預設由 .env 的 WORKSPACE 推導）")
    ap.add_argument("--json", action="store_true", help="輸出 JSON")
    a = ap.parse_args()

    # 讀 .env 放在 parse_args 之後：coder 上刻意沒有 .env，但 `--help` 應該還是
    # 要能看（一支 --help 會掛掉的工具，下一個人只會放棄用它）。
    env = load_env(REPO)
    # **不要寫死 localhost。** 服務綁在 BIND_ADDR（dker 上是 Tailscale 位址），
    # 寫死 localhost 會連不上——`.env.example` 那條「腳本一律從這裡讀」就是為此。
    base = a.base or f"http://{env.get('BIND_ADDR', '127.0.0.1')}:{env.get('HOST_PORT', '9621')}"
    queries = a.query or list(DEFAULT_QUERIES)
    api_key = env.get("LIGHTRAG_API_KEY", "")
    if not api_key:
        print("找不到 LIGHTRAG_API_KEY", file=sys.stderr)
        return 2

    container = a.container or container_for(env_workspace())
    records = [measure(q, a.mode, base, api_key, a.timeout, container)
               for q in queries]

    if a.json:
        print(json.dumps(records, ensure_ascii=False, indent=2))
        return 0

    for rec in records:
        _print(rec)

    print("\n" + "─" * 60)
    chunk_rows = [s["rows"] for r in records for s in r["sections"]
                  if "Document Chunks" in s["name"]]
    if chunk_rows:
        print(f"原文筆數：{chunk_rows}　（CHUNK_TOP_K 預設 20）")
        print("  筆數 < 20 ⇒ 是 token 預算在擋，加預算有用")
        print("  筆數 = 20 ⇒ 是數量上限在擋，加預算沒用")
    print(f"MAX_TOTAL_TOKENS={env.get('MAX_TOTAL_TOKENS', '<未設>')}　"
          f"MAX_ENTITY_TOKENS={env.get('MAX_ENTITY_TOKENS', '<未設，預設 6000>')}　"
          f"MAX_RELATION_TOKENS={env.get('MAX_RELATION_TOKENS', '<未設，預設 8000>')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
