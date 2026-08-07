#!/usr/bin/env python3
"""那 63 筆解析不了的抽取輸出，內容有沒有靜靜掉了？唯讀。

決定性的問題不是「JSON 合不合法」，是「實體有沒有進索引」——
我的 json.loads 失敗**不等於** LightRAG 的 parser 失敗。
所以直接拿「該 chunk 在索引裡有幾個實體」來對照。
"""
from __future__ import annotations
import json, re, subprocess, sys, collections

def psql(sql: str):
    out = subprocess.run(["docker","exec","-i","lightrag-postgres","psql","-U","deeptutor",
                          "-d","lightrag","-tAqX","-f","-"], input=sql,
                         capture_output=True, text=True, timeout=300)
    if out.returncode != 0:
        print("psql 失敗：", out.stderr.strip()[:300]); sys.exit(1)
    return json.loads(out.stdout.strip() or "[]")

CACHE = """select coalesce(json_agg(t),'[]'::json)::text from (
  select chunk_id,
         case when original_prompt like '---Task---%Based on the last extraction task%'
              then 'gleaning' else 'initial' end as kind,
         return_value from lightrag_llm_cache
  where workspace='acoustics_v2' and cache_type='extract') t;"""

# chunk_ids 是**陣列欄位**（複數），一個實體可對多個 chunk —— 要展開才對得上。
# 第一版用 chunk_id（單數）直接炸，三組都回 0；**三組都 0 就是壞了不是結果**。
ENTS = """select coalesce(json_agg(t),'[]'::json)::text from (
  select cid as chunk_id, count(*) as n from (
    select jsonb_array_elements_text(chunk_ids) as cid
    from lightrag_entity_chunks where workspace='acoustics_v2') s
  group by cid) t;"""

def why(rv: str) -> str:
    s = (rv or "").strip()
    if not s: return "空字串"
    if s.startswith("```"): return "包在 markdown 圍籬裡"
    if not s.lstrip().startswith("{"): return f"不是以 {{ 開頭（開頭：{s[:24]!r}）"
    try:
        json.loads(s); return "（其實可解析）"
    except json.JSONDecodeError as e:
        if "Expecting" in str(e) and s.rstrip()[-1] not in "}]":
            return "被截斷（結尾不是 } 或 ]）"
        return f"JSON 語法錯：{str(e)[:48]}"

def main() -> int:
    rows = psql(CACHE)
    ents = {r["chunk_id"]: r["n"] for r in psql(ENTS)}
    bad, per_chunk = [], collections.defaultdict(dict)
    for r in rows:
        s = (r["return_value"] or "").strip()
        try:
            ok = isinstance(json.loads(s), dict)
        except json.JSONDecodeError:
            ok = False
        per_chunk[r["chunk_id"]][r["kind"]] = ok
        if not ok:
            bad.append(r)
    print(f"母體 {len(rows)} 筆 / {len(per_chunk)} 個 chunk；解析不了 {len(bad)} 筆\n")
    print("=== 為什麼解析不了 ===")
    for k, v in collections.Counter(why(r["return_value"]) for r in bad).most_common():
        print(f"  {v:>3}  {k}")
    print("\n=== 有壞輸出的 chunk，索引裡還有沒有實體 ===")
    grp = {"兩輪都好": [], "壞一輪": [], "兩輪都壞": []}
    for cid, d in per_chunk.items():
        n_bad = sum(1 for v in d.values() if not v)
        key = "兩輪都好" if n_bad == 0 else ("壞一輪" if n_bad == 1 else "兩輪都壞")
        grp[key].append(ents.get(cid, 0))
    hdr = f"{'':10}{'chunk 數':>9}{'索引實體總數':>14}{'每 chunk 平均':>14}{'實體=0 的':>11}"
    print(hdr); print("-" * 100)
    for k, v in grp.items():
        if not v: continue
        print(f"{k:10}{len(v):>9}{sum(v):>14,}{sum(v)/len(v):>14.1f}{sum(1 for x in v if x==0):>11}")
    allzero = all(sum(v) == 0 for v in grp.values() if v)
    if allzero:
        print("\n⚠ 三組都是 0 —— 這是 join 壞了，不是結果，別採信")
    else:
        print("\n判讀：若「壞一輪／兩輪都壞」的每 chunk 平均**明顯低於**「兩輪都好」，")
        print("      表示內容真的掉了；若相近，表示 LightRAG 的 parser 比我寬容，沒掉。")
    print("\n=== 抽一筆壞的看長相（前 300 字）===")
    if bad:
        print(repr(bad[0]["return_value"][:300]))
    return 0

sys.exit(main())
