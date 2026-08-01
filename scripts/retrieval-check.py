#!/usr/bin/env python3
"""量後處理對**檢索**有沒有用。

先前所有量測都是中間指標（解析品質、對照原文比例、表格一致性），沒有一個
回答「RAG 答得比較好嗎」。消音掉 5.58% 的雜訊聽起來合理，但那是推論不是量測。

不需要建兩份索引就能量的東西：**雜訊有沒有真的被檢索到**。

  沒被檢索到 → 消音只是好看，對檢索沒有幫助
  被檢索到   → 消音直接省下 context 窗口，而且擠掉的是真內容

做法：對每個檢索回來的 chunk，比對該文件的消音清單。目前索引裡 19 份是
**未經處理**的，所以雜訊還在，量得到。

用法：
    retrieval-check.py                      # 用內建題組
    retrieval-check.py --query "..." --top-k 10
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mineru_common import load_env  # noqa: E402
from pp.docctx import DocContext, DocContextError  # noqa: E402
from pp.rules import layout_noise  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DATA_ROOT = Path(os.environ.get("PP_DATA_ROOT", "/data/rag/lightrag"))

# 涵蓋這批文件主題的題組。刻意混合具體與概念性的問題 —— 兩者檢索到的
# chunk 型態不同（具體題容易命中表格與數值，概念題容易命中散文）。
QUERIES = [
    "sound absorption coefficient of porous materials",
    "Helmholtz resonator design parameters",
    "how is scattering coefficient measured",
    "finite element method for room acoustics",
    "muffler transmission loss calculation",
    "impedance tube measurement setup",
]


def ask(host: str, key: str, q: str, top_k: int) -> list[dict]:
    body = json.dumps({"query": q, "mode": "mix", "top_k": top_k,
                       "only_need_context": True}).encode()
    req = urllib.request.Request(f"{host}/query/data", data=body,
                                 headers={"X-API-Key": key,
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.loads(r.read())
    return (d.get("data") or {}).get("chunks") or []


def noise_index(workspace: str) -> dict[str, set[str]]:
    """每份文件的消音字串集合。用檔名當鍵，對得上 chunk 的 file_path。"""
    pdir = DATA_ROOT / workspace / "inputs" / workspace / "__parsed__"
    out: dict[str, set[str]] = {}
    for raw in sorted(pdir.glob("*.mineru_raw")):
        try:
            ctx = DocContext(raw)
            plan = layout_noise.plan(ctx.items, ctx.n_pages)
        except (DocContextError, Exception):       # noqa: BLE001
            continue
        # 已經 apply 過的文件，text 已清空、原文在 _pp_original_text
        texts = {m.text.strip() for m in plan.mutes if m.text.strip()}
        for it in ctx.items:
            o = (it.get("_pp_original_text") or "").strip()
            if o:
                texts.add(o)
        if texts:
            out[ctx.doc_name] = texts
    return out


def main() -> int:
    env = load_env(REPO)
    ap = argparse.ArgumentParser(description="量雜訊有沒有被檢索到")
    ap.add_argument("--workspace", default=env.get("WORKSPACE", "acoustics_v155"))
    ap.add_argument("--query", action="append")
    ap.add_argument("--top-k", type=int, default=10)
    a = ap.parse_args()

    host = f"http://{env.get('BIND_ADDR','127.0.0.1')}:{env.get('HOST_PORT','9621')}"
    key = env.get("LIGHTRAG_API_KEY", "")
    noise = noise_index(a.workspace)
    print(f"消音清單：{len(noise)} 份文件\n")

    tot_chars = tot_noise = tot_chunks = hit_chunks = 0
    print(f"{'查詢':<44}{'chunks':>8}{'字元':>9}{'雜訊字元':>10}{'佔比':>8}")
    print("-" * 80)
    for q in (a.query or QUERIES):
        chunks = ask(host, key, q, a.top_k)
        c_chars = c_noise = 0
        for ch in chunks:
            content = ch.get("content") or ""
            doc = Path(ch.get("file_path") or "").name
            c_chars += len(content)
            hit = 0
            for t in noise.get(doc, ()):
                # 同一段雜訊可能在 chunk 裡出現多次（跨頁的書眉）
                hit += content.count(t) * len(t)
            c_noise += hit
            tot_chunks += 1
            hit_chunks += hit > 0
        tot_chars += c_chars
        tot_noise += c_noise
        print(f"{q[:42]:<44}{len(chunks):>8}{c_chars:>9,}{c_noise:>10,}"
              f"{c_noise/max(c_chars,1):>7.2%}")

    print("-" * 80)
    print(f"{'合計':<44}{tot_chunks:>8}{tot_chars:>9,}{tot_noise:>10,}"
          f"{tot_noise/max(tot_chars,1):>7.2%}")
    print(f"\n{hit_chunks}/{tot_chunks} 個檢索到的 chunk 含有雜訊"
          f"（{hit_chunks/max(tot_chunks,1):.0%}）")
    print("\n這個比例就是消音實際省下的 context —— 不是推論，是量到的。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
