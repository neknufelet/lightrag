#!/usr/bin/env python3
"""查詢 LightRAG 知識庫的命令列介面，給 CLI agent（Claude Code / Codex CLI / agy）呼叫。

為什麼是這個而不是 MCP：CLI agent 本來就有 shell，「怎麼呼叫」只需要一行指示，
不需要一套協定。MCP 在不同 agent、不同平台的支援程度不一致，這裡繞開它。

為什麼不用 LightRAG 的 Ollama 相容端點（/api/chat）：那個端點是為了假扮成 Ollama
給只會講 Ollama 協定的 app 用，而且回傳的是已經生成好的答案。agent 要的是檢索到的
原始脈絡，自己判斷 —— 所以預設走 /query/data，拿 entities / relationships / chunks。

預設輸出是人讀的摘要；agent 要解析就加 --json。

用法：
    askrag "mechanical impedance"
    askrag --mode local "sound power"
    askrag --json "orifice impedance" | jq '.data.chunks'
    askrag --answer "what is mechanical impedance?"   # 要 LightRAG 直接生成答案
    askrag --docs                                     # 列出已索引的文件
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

# 設定來源：環境變數優先，其次讀 repo 的 .env（單一真實來源，改 key 只改一處）
REPO_ENV = Path(__file__).resolve().parent.parent / ".env"
DEFAULT_URL = "http://100.87.88.7:9621"


def load_env() -> dict:
    if not REPO_ENV.exists():
        return {}
    out = {}
    for line in REPO_ENV.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip("'\"")
    return out


def call(path: str, payload: dict | None, base: str, key: str, timeout: int):
    url = f"{base.rstrip('/')}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data,
        headers={"X-API-Key": key, **({"Content-Type": "application/json"} if data else {})},
        method="POST" if data else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        sys.exit(f"askrag: HTTP {e.code} — {detail}")
    except urllib.error.URLError as e:
        sys.exit(f"askrag: 連不上 {base} — {e.reason}")


def render(d: dict) -> str:
    """把 /query/data 的結構化結果整理成人讀的形式。"""
    data = d.get("data") or {}
    meta = d.get("metadata") or {}
    out = []

    kw = meta.get("keywords") or {}
    if kw:
        hl = ", ".join(kw.get("high_level") or [])
        ll = ", ".join(kw.get("low_level") or [])
        out.append(f"# 檢索關鍵字\n高階: {hl}\n低階: {ll}")

    ents = data.get("entities") or []
    if ents:
        out.append(f"\n# 實體 ({len(ents)})")
        for e in ents:
            name = e.get("entity_name") or e.get("entity") or "?"
            desc = (e.get("description") or "").replace("\n", " ")
            out.append(f"- {name}: {desc[:180]}")

    rels = data.get("relationships") or []
    if rels:
        out.append(f"\n# 關係 ({len(rels)})")
        for r in rels:
            s = r.get("src_id") or r.get("source") or "?"
            t = r.get("tgt_id") or r.get("target") or "?"
            desc = (r.get("description") or "").replace("\n", " ")
            out.append(f"- {s} ~ {t}: {desc[:150]}")

    chunks = data.get("chunks") or []
    if chunks:
        out.append(f"\n# 原文片段 ({len(chunks)})")
        for c in chunks:
            src = c.get("file_path") or c.get("full_doc_id") or "?"
            content = (c.get("content") or "").strip()
            out.append(f"\n--- {src}\n{content}")

    refs = data.get("references") or []
    if refs:
        out.append(f"\n# 出處\n" + "\n".join(
            f"- {r.get('file_path') or r}" for r in refs))

    return "\n".join(out) if out else "（沒有檢索到任何內容）"


def main():
    env = load_env()
    ap = argparse.ArgumentParser(
        prog="askrag", description="查詢 LightRAG 知識庫",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="mode 說明：local 走實體鄰域、global 走關係全域、hybrid 兩者併用、"
               "naive 純向量、mix 全部混合。不確定就用預設的 hybrid。")
    ap.add_argument("query", nargs="?", help="要查的問題")
    ap.add_argument("--mode", default="hybrid",
                    choices=["local", "global", "hybrid", "naive", "mix", "bypass"])
    ap.add_argument("--json", action="store_true", help="輸出原始 JSON，給程式解析")
    ap.add_argument("--answer", action="store_true",
                    help="要 LightRAG 生成答案，而非只回傳脈絡")
    ap.add_argument("--top-k", type=int, default=20)
    ap.add_argument("--chunk-top-k", type=int, default=8)
    ap.add_argument("--max-tokens", type=int, default=None, help="脈絡的 token 上限")
    ap.add_argument("--docs", action="store_true", help="列出已索引的文件後結束")
    ap.add_argument("--url", default=os.environ.get("LIGHTRAG_URL", DEFAULT_URL))
    ap.add_argument("--key", default=os.environ.get("LIGHTRAG_API_KEY")
                    or env.get("LIGHTRAG_API_KEY", ""))
    ap.add_argument("--timeout", type=int, default=180)
    a = ap.parse_args()

    if not a.key:
        sys.exit("askrag: 找不到 API key。設 LIGHTRAG_API_KEY 或確認 "
                 f"{REPO_ENV} 存在且可讀。")

    if a.docs:
        d = call("/documents", None, a.url, a.key, a.timeout)
        if a.json:
            print(json.dumps(d, ensure_ascii=False, indent=1))
            return
        for status, docs in (d.get("statuses") or {}).items():
            for doc in docs:
                print(f"[{status}] {doc.get('file_path')} "
                      f"chunks={doc.get('chunks_count')}")
        return

    if not a.query:
        ap.error("要給一個查詢字串，或用 --docs 列出文件")

    payload = {
        "query": a.query,
        "mode": a.mode,
        "top_k": a.top_k,
        "chunk_top_k": a.chunk_top_k,
        # rerank 沒設定模型，明講關掉，否則每次查詢都會噴一行 warning
        "enable_rerank": False,
    }
    if a.max_tokens:
        payload["max_total_tokens"] = a.max_tokens

    if a.answer:
        d = call("/query", payload, a.url, a.key, a.timeout)
        print(json.dumps(d, ensure_ascii=False, indent=1) if a.json
              else (d.get("response") or json.dumps(d, ensure_ascii=False)))
        return

    d = call("/query/data", payload, a.url, a.key, a.timeout)
    print(json.dumps(d, ensure_ascii=False, indent=1) if a.json else render(d))


if __name__ == "__main__":
    main()
