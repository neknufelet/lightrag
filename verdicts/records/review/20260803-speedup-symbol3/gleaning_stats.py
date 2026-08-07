#!/usr/bin/env python3
"""量「補抓那輪」（gleaning）佔了多少 LLM 呼叫、換回多少實體。

在 dker 跑（要 DB）。唯讀，一個字都不寫。

為什麼要量：390 份的抽取約 60 小時，而每個 chunk 現在被讀兩次——
初次抽取 ＋「補抓遺漏」。若後者佔一半成本卻只換回少量實體，那就是
擴量前最大的一筆可省成本，而且不必動模型或引擎。
"""
from __future__ import annotations

import json
import subprocess
import sys

SQL = """
select coalesce(json_agg(t), '[]'::json)::text from (
  select
    case when original_prompt like '---Task---%Based on the last extraction task%'
         then 'gleaning' else 'initial' end as kind,
    chunk_id,
    length(original_prompt) as prompt_chars,
    length(return_value)    as out_chars,
    return_value
  from lightrag_llm_cache
  where workspace = 'acoustics_v2' and cache_type = 'extract'
) t;
"""


def parse_counts(rv: str) -> tuple[int, int, bool]:
    """回 (實體數, 關係數, 解析成功)。解析不了要看得見，不能當成 0。"""
    s = (rv or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        d = json.loads(s)
    except json.JSONDecodeError:
        return 0, 0, False
    if not isinstance(d, dict):
        return 0, 0, False
    e = d.get("entities"); r = d.get("relationships")
    return (len(e) if isinstance(e, list) else 0,
            len(r) if isinstance(r, list) else 0, True)


def main() -> int:
    out = subprocess.run(
        ["docker", "exec", "-i", "lightrag-postgres", "psql", "-U", "deeptutor",
         "-d", "lightrag", "-tAqX", "-f", "-"],
        input=SQL, capture_output=True, text=True, timeout=300)
    if out.returncode != 0:
        print("psql 失敗：", out.stderr.strip()[:300]); return 1
    rows = json.loads(out.stdout.strip() or "[]")
    print(f"母體：{len(rows)} 筆 extract 快取\n")

    agg: dict[str, dict[str, int]] = {}
    unparsed: dict[str, int] = {}
    for r in rows:
        k = r["kind"]
        a = agg.setdefault(k, {"calls": 0, "prompt": 0, "out": 0, "ent": 0, "rel": 0})
        e, rl, ok = parse_counts(r["return_value"])
        a["calls"] += 1; a["prompt"] += r["prompt_chars"]; a["out"] += r["out_chars"]
        a["ent"] += e; a["rel"] += rl
        if not ok:
            unparsed[k] = unparsed.get(k, 0) + 1

    tot_calls = sum(a["calls"] for a in agg.values())
    tot_out = sum(a["out"] for a in agg.values())
    tot_ent = sum(a["ent"] for a in agg.values())

    hdr = f"{'':10}{'呼叫數':>8}{'佔比':>7}{'輸出字元':>12}{'佔比':>7}{'抽出實體':>10}{'佔比':>7}{'每次實體':>9}"
    print(hdr); print("-" * len(hdr) * 2)
    for k in ("initial", "gleaning"):
        a = agg.get(k)
        if not a:
            continue
        print(f"{k:10}{a['calls']:>8}{a['calls']/tot_calls:>7.1%}"
              f"{a['out']:>12,}{a['out']/max(tot_out,1):>7.1%}"
              f"{a['ent']:>10,}{a['ent']/max(tot_ent,1):>7.1%}"
              f"{a['ent']/max(a['calls'],1):>9.1f}")
    if unparsed:
        print(f"\n⚠ 有 {sum(unparsed.values())} 筆 return_value 解析不了：{unparsed}"
              f"　—— 它們的實體數被算成 0，會低估該組")

    g = agg.get("gleaning")
    if g and tot_out:
        print(f"\n輸出 token 大致與時間成正比（解碼是瓶頸）。")
        print(f"補抓那輪佔輸出字元 {g['out']/tot_out:.1%}"
              f"　⇒ 390 份約 60 小時裡，約 {60*g['out']/tot_out:.0f} 小時花在它身上。")
        print(f"它換回 {g['ent']:,} 個實體（佔 {g['ent']/max(tot_ent,1):.1%}）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
