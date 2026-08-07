#!/usr/bin/env python3
"""補抓那輪撈到的，是不是不成比例地都是符號型（＝沒檢索價值的那族）？

若是，砍掉 gleaning 就是「省 24 小時且主要丟掉垃圾」；
若否，那 24 小時是真的買到東西，砍不得。唯讀。
"""
from __future__ import annotations
import json, pathlib, subprocess, sys

SQL = """
select coalesce(json_agg(t), '[]'::json)::text from (
  select case when original_prompt like '---Task---%Based on the last extraction task%'
              then 'gleaning' else 'initial' end as kind,
         return_value
  from lightrag_llm_cache
  where workspace = 'acoustics_v2' and cache_type = 'extract') t;
"""

def names(rv: str) -> list[str] | None:
    s = (rv or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        d = json.loads(s)
    except json.JSONDecodeError:
        return None
    e = d.get("entities") if isinstance(d, dict) else None
    if not isinstance(e, list):
        return None
    return [str(x.get("name", "")).strip() for x in e if isinstance(x, dict) and x.get("name")]

def main() -> int:
    sym = json.loads(pathlib.Path(
        "/data/rag/lightrag/acoustics_v2/records/bench/symbolic-1482.json").read_text())
    S = {e["name"] for e in sym["entities"]}
    # LightRAG 存進圖譜時名字會正規化（首字大寫等），比對放寬到大小寫不敏感
    Sl = {n.lower() for n in S}
    out = subprocess.run(["docker","exec","-i","lightrag-postgres","psql","-U","deeptutor",
                          "-d","lightrag","-tAqX","-f","-"], input=SQL,
                         capture_output=True, text=True, timeout=300)
    rows = json.loads(out.stdout.strip() or "[]")
    agg = {}
    for r in rows:
        ns = names(r["return_value"])
        if ns is None:
            continue
        a = agg.setdefault(r["kind"], {"ent": 0, "sym": 0, "calls": 0})
        a["calls"] += 1; a["ent"] += len(ns)
        a["sym"] += sum(1 for n in ns if n.lower() in Sl)
    print(f"符號桶母體 {len(S):,} 個名字\n")
    hdr = f"{'':10}{'可解析呼叫':>11}{'抽出實體':>10}{'其中符號型':>12}{'符號型佔比':>12}"
    print(hdr); print("-" * 96)
    for k in ("initial", "gleaning"):
        a = agg.get(k)
        if not a: continue
        print(f"{k:10}{a['calls']:>11}{a['ent']:>10,}{a['sym']:>12,}{a['sym']/max(a['ent'],1):>12.1%}")
    i, g = agg.get("initial"), agg.get("gleaning")
    if i and g:
        pi = i["sym"]/max(i["ent"],1); pg = g["sym"]/max(g["ent"],1)
        print(f"\n差距：補抓那輪的符號型佔比是初次的 {pg/max(pi,1e-9):.2f} 倍")
        print("（>1.3 才算「補抓主要在撈渣」；接近 1 表示兩輪品質相當，砍不得）")
    return 0

sys.exit(main())
