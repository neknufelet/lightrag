#!/usr/bin/env python3
"""粗估「上游 OCR 污染」這一族在索引裡有多大。唯讀。

**這不是偵測器，是規模估計。** 用的是幾個字形訊號，一定有誤報；
目的只是回答「值不值得為它做一支真正的偵測器」。

刻意不做的事：不列「已知錯法清單」。scan-partial.py 的三代演進已經證明
枚舉那條路會失敗（清單永遠在長），要做偵測器必須找結構性規則。
"""
from __future__ import annotations
import json, re, subprocess, sys

SQL = """
select coalesce(json_agg(t), '[]'::json)::text from (
  select entity_name from lightrag_vdb_entity_text_embedding_3_large_3072d
  where workspace = 'acoustics_v2') t;
"""

# 字形訊號（**不是**錯法清單，是「這種長相在學術文字裡不自然」）
SIGNALS = {
    "數字 11/111 疑似羅馬 II/III": re.compile(r"(?<![\d.])1{2,3}(?![\d.])"),
    "詞中大寫（BroT 型）":         re.compile(r"\b[A-Z][a-z]+[A-Z][a-z]*\b"),
    "孤立單字母（Γ→L 型）":        re.compile(r"(?:^|\s)[A-Z](?:\s|$)"),
    "字母數字黏連（V11x 型）":      re.compile(r"\b[A-Za-z]\d{2,}[A-Za-z]\b"),
}

def main() -> int:
    out = subprocess.run(["docker","exec","-i","lightrag-postgres","psql","-U","deeptutor",
                          "-d","lightrag","-tAqX","-f","-"], input=SQL,
                         capture_output=True, text=True, timeout=300)
    if out.returncode != 0:
        print("psql 失敗：", out.stderr.strip()[:200]); return 1
    names = [r["entity_name"] for r in json.loads(out.stdout.strip() or "[]")]
    print(f"母體：{len(names):,} 個實體名\n")
    hit_any = set()
    for label, rx in SIGNALS.items():
        hits = [n for n in names if rx.search(n)]
        hit_any.update(hits)
        print(f"{label:28} {len(hits):>5} 個　例：{hits[:4]}")
    print(f"\n至少命中一個訊號：{len(hit_any):,} 個（{len(hit_any)/max(len(names),1):.1%}）")
    print("\n⚠ 這是**上界估計**，誤報一定有（例如 `Region I`、`Type II` 是正常寫法，")
    print("   `McGraw` 這種詞中大寫也是真的）。要真的判定必須回去比對原文。")
    return 0

sys.exit(main())
