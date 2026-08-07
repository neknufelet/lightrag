#!/usr/bin/env python3
"""補抓那輪的**邊際價值**：同一個 chunk，第二輪撈到的名字有多少是第一輪沒有的？

前一支量的是「補抓抽出多少實體」，但那些可能大量與第一輪重複、之後被合併掉
（原始抽取 10,280 個 → 最終索引 7,211 個，中間有三成被併掉）。
真正該問的是**新增了什麼**。唯讀。
"""
from __future__ import annotations
import json, pathlib, subprocess, sys

SQL = """
select coalesce(json_agg(t), '[]'::json)::text from (
  select chunk_id,
         case when original_prompt like '---Task---%Based on the last extraction task%'
              then 'gleaning' else 'initial' end as kind,
         return_value
  from lightrag_llm_cache
  where workspace = 'acoustics_v2' and cache_type = 'extract') t;
"""

def names(rv):
    s = (rv or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[-1].rsplit("```", 1)[0]
    try: d = json.loads(s)
    except json.JSONDecodeError: return None
    e = d.get("entities") if isinstance(d, dict) else None
    if not isinstance(e, list): return None
    return [str(x.get("name","")).strip().lower() for x in e if isinstance(x, dict) and x.get("name")]

def main() -> int:
    sym = json.loads(pathlib.Path(
        "/data/rag/lightrag/acoustics_v2/records/bench/symbolic-1482.json").read_text())
    Sl = {e["name"].lower() for e in sym["entities"]}
    out = subprocess.run(["docker","exec","-i","lightrag-postgres","psql","-U","deeptutor",
                          "-d","lightrag","-tAqX","-f","-"], input=SQL,
                         capture_output=True, text=True, timeout=300)
    rows = json.loads(out.stdout.strip() or "[]")
    by = {}
    for r in rows:
        ns = names(r["return_value"])
        if ns is None: continue
        by.setdefault(r["chunk_id"], {})[r["kind"]] = ns

    pairs = [(c, d["initial"], d["gleaning"]) for c, d in by.items()
             if "initial" in d and "gleaning" in d]
    tot_g = new_g = new_sym = 0
    for _, i, g in pairs:
        seen = set(i)
        tot_g += len(g)
        fresh = [n for n in g if n not in seen]
        new_g += len(fresh)
        new_sym += sum(1 for n in fresh if n in Sl)
    print(f"兩輪都可解析的 chunk：{len(pairs)}／510\n")
    print(f"補抓抽出的名字總數        {tot_g:,}")
    print(f"  其中第一輪已經有的      {tot_g-new_g:,}　（{(tot_g-new_g)/max(tot_g,1):.1%}　⇒ 重工）")
    print(f"  真正新增的              {new_g:,}　（{new_g/max(tot_g,1):.1%}）")
    print(f"    新增裡是符號型的      {new_sym:,}　（佔新增 {new_sym/max(new_g,1):.1%}）")
    print(f"    新增裡非符號型的      {new_g-new_sym:,}　← 這才是補抓真正買到的東西")
    print()
    print(f"補抓佔抽取時間約 40%（前一支量的）。")
    print(f"⇒ 用 40% 的時間換 {new_g-new_sym:,} 個非符號型新實體。")
    return 0

sys.exit(main())
