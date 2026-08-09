#!/usr/bin/env python3
"""檢索評分：同一組題目問兩個知識庫，用 reranker 當裁判比較回傳內容的相關度。

**為什麼要有這支**：先前所有比較都是圖譜的形狀（節點數、型別分佈、泛用標籤），
沒有一個回答「它答得比較好嗎」。而 2026-08-09 量到 DeepSeek 抽出的關係比
llama.cpp 少約三成 —— 少掉的是雜訊還是真連結，**圖譜指標永遠回答不了**，
只有拿問題去問才知道。

**為什麼題本進版控**：上一版的評分腳本與題目只存在於某次工作階段的暫存區，
隨那個工作區一起消失。`cairn/retrieval-tuning.md` 留下了結論（「中文問英文論文
差 63–86%」）卻留不下方法，於是那些數字再也重跑不了。

**為什麼用 reranker 當裁判而不是自己算相似度**：cross-encoder 跨語言沒問題
（實測中文問題對英文正確答案 0.9134、對無關雜訊 0.0000），所以它評中文題是
公平的。自己拿 embedding 算餘弦則會把「向量檢索跨語言差」這個待測的病
混進裁判裡。

用法：
    ./retrieval-score.py --a 9621 --b 9635
    ./retrieval-score.py --a 9621 --b 9635 --top 3 --json out.json

⚠ 兩邊的文件母體必須一樣，否則差異有一部分來自文件數而不是抽取模型。
   跑之前自己確認（`lightrag_doc_status` 的列數）。
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import urllib.request
from collections.abc import Mapping
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mineru_common import load_env  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
QUESTIONS = REPO / "tests" / "retrieval-questions.json"


def _post(url: str, body: object, headers: Mapping[str, str], timeout: int = 180) -> object:
    """POST 一個 JSON。

    ⚠ **兩個服務的認證方式不同，標頭不可共用。** LightRAG 收 `X-API-Key`，
    而 Infinity（Cohere 相容）收 `Authorization: Bearer`。兩個一起送的話
    LightRAG 會把那個 Bearer 當成 JWT 並回 401 —— 實測踩過，而且錯誤訊息
    只說 Unauthorized，看起來像金鑰錯了。
    """
    req = urllib.request.Request(
        url, method="POST", data=json.dumps(body).encode(),
        headers={**headers, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return json.loads(resp.read() or "{}")


def retrieve(host: str, port: int, api_key: str, query: str, top_k: int) -> list[str]:
    """把一題丟給知識庫，取回它認為相關的原文段落。

    `only_need_context=True`：我們要的是「它撈到什麼」，不是它生成的答案。
    生成那一層會把檢索的好壞洗掉 —— 撈錯了但寫得很順的答案，讀起來一樣像對的。
    """
    data = _post(f"http://{host}:{port}/query/data", {
        "query": query, "mode": "mix", "only_need_context": True,
        "chunk_top_k": top_k}, {"X-API-Key": api_key})
    if not isinstance(data, dict):
        raise RuntimeError(f"/query/data 回傳不是物件：{type(data).__name__}")
    inner = data.get("data")
    chunks = (inner or {}).get("chunks") if isinstance(inner, dict) else None
    out: list[str] = []
    for c in chunks or []:
        if isinstance(c, dict):
            text = c.get("content") or c.get("text") or ""
            if text.strip():
                out.append(text)
    return out


def rerank(host: str, port: int, api_key: str, model: str,
           query: str, docs: list[str], top_n: int) -> list[float]:
    """用 cross-encoder 對取回的段落打分。回傳前 top_n 名的分數（由高到低）。"""
    data = _post(f"http://{host}:{port}/rerank",
                 {"model": model, "query": query, "documents": docs,
                  "top_n": min(top_n, len(docs))},
                 {"Authorization": f"Bearer {api_key}"})
    if not isinstance(data, dict):
        raise RuntimeError(f"/rerank 回傳不是物件：{type(data).__name__}")
    scores = [float(r["relevance_score"]) for r in (data.get("results") or [])
              if isinstance(r, dict) and "relevance_score" in r]
    return sorted(scores, reverse=True)[:top_n]


def score_one(env: Mapping[str, str], host: str, port: int, question: str,
              top_k: int, top_n: int) -> tuple[float | None, int]:
    """一題一庫的分數。**撈不到東西時回 None 不回 0。**

    回 0 的話「檢索壞了」與「檢索到但都不相關」在報表上長得一樣，而這兩件事
    要做的處置完全不同（鐵則第 7 條：乾淨的 0 要先當成量錯）。
    """
    docs = retrieve(host, port, env.get("LIGHTRAG_API_KEY", ""), question, top_k)
    if not docs:
        return None, 0
    scores = rerank(host, int(env.get("INFINITY_PORT", "7997")),
                    env.get("RERANK_BINDING_API_KEY", ""),
                    env.get("RERANK_MODEL", "BAAI/bge-reranker-v2-m3"),
                    question, docs, top_n)
    if not scores:
        return None, len(docs)
    return statistics.fmean(scores), len(docs)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--a", type=int, required=True, help="對照組的 HOST_PORT（例如正式庫 9621）")
    ap.add_argument("--b", type=int, required=True, help="實驗組的 HOST_PORT")
    ap.add_argument("--label-a", default="A")
    ap.add_argument("--label-b", default="B")
    ap.add_argument("--top-k", type=int, default=10, help="每題取回幾段原文")
    ap.add_argument("--top", type=int, default=3, help="打分取前幾名平均")
    ap.add_argument("--questions", type=Path, default=QUESTIONS)
    ap.add_argument("--json", type=Path, help="把逐題結果寫成 JSON")
    a = ap.parse_args()

    env = load_env(REPO)
    host = env.get("BIND_ADDR", "127.0.0.1")
    book = json.loads(a.questions.read_text(encoding="utf-8"))
    questions = book["questions"]

    rows: list[dict[str, object]] = []
    print(f"題本 {a.questions.name}　{len(questions)} 題　"
          f"取回 {a.top_k} 段、前 {a.top} 名平均\n")
    print(f"{'題':<6}{'語言':<5}{a.label_a:>10}{a.label_b:>10}   題目")
    print("-" * 92)
    for q in questions:
        sa, na = score_one(env, host, a.a, q["text"], a.top_k, a.top)
        sb, nb = score_one(env, host, a.b, q["text"], a.top_k, a.top)
        rows.append({"id": q["id"], "lang": q["lang"], "pair": q.get("pair"),
                     "text": q["text"], "a": sa, "b": sb,
                     "a_chunks": na, "b_chunks": nb})
        fa = f"{sa:.4f}" if sa is not None else "驗不了"
        fb = f"{sb:.4f}" if sb is not None else "驗不了"
        mark = "" if sa is None or sb is None else ("  ←B" if sb > sa else ("  ←A" if sa > sb else "  ="))
        print(f"{q['id']:<6}{q['lang']:<5}{fa:>10}{fb:>10}   {q['text'][:44]}{mark}")

    def avg(key: str, lang: str | None = None) -> float | None:
        vals = [r[key] for r in rows
                if r[key] is not None and (lang is None or r["lang"] == lang)]
        return statistics.fmean(vals) if vals else None  # type: ignore[arg-type]

    print("-" * 92)
    for lang, name in ((None, "全部"), ("en", "英文"), ("zh", "中文")):
        va, vb = avg("a", lang), avg("b", lang)
        if va is None or vb is None:
            print(f"{name:<6} 驗不了（有題目撈不到原文）")
            continue
        delta = (vb - va) / va * 100 if va else 0.0
        print(f"{name:<6}{'':>5}{va:>10.4f}{vb:>10.4f}   {delta:+.1f}%")

    wins_b = sum(1 for r in rows if r["a"] is not None and r["b"] is not None and r["b"] > r["a"])  # type: ignore[operator]
    wins_a = sum(1 for r in rows if r["a"] is not None and r["b"] is not None and r["a"] > r["b"])  # type: ignore[operator]
    print(f"\n逐題：{a.label_b} 勝 {wins_b}、{a.label_a} 勝 {wins_a}")
    print("⚠ 幾個百分點的差距是雜訊不是效果 —— 2026-08-08 花兩小時比較兩個落在雜訊裡的選項，"
          "而真正的洞大 2.5 倍。看逐題勝負與中英差距，不要只看總平均。")

    if a.json:
        a.json.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"逐題結果 → {a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
