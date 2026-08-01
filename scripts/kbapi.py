#!/usr/bin/env python3
"""補 LightRAG 缺的唯讀端點：圖片與單篇結構化內容。

LightRAG 1.5.5 的 API 只有 /query、/query/stream、/query/data 與文件管理，
**沒有任何圖片端點** —— 1,786 張圖躺在 __parsed__/<doc>.mineru_raw/images/
但拿不到。這支就是把磁碟上已經有的東西開出來。

為什麼不做 MCP：現有的 DeepTutor skill 全部直接打 HTTP 且明寫 never MCP，
那個模式在運作。MCP 只是多一層要維護的東西，而且規格 2026-07-28 才剛淘汰
一批傳輸與認證機制。LightRAG 本來就是 HTTP，包一層不會變得更好連。

為什麼是 stdlib：主機上沒有 fastapi/flask，而且這支只做讀檔與轉發，
不值得為它引入相依。跟 pp/oracle.py、mineru_common.py 一致。

唯讀。沒有任何寫入端點 —— 加文件要走 postprocess 那條完整流程
（解析 → 修補 → 抽取），一個 HTTP 呼叫塞不進去，硬做只會繞過所有品質檢查。

端點：
    GET /kb/{ws}/docs                     文件清單（含解析品質）
    GET /kb/{ws}/doc/{name}               單篇：章節、表格、方程式、圖片
    GET /kb/{ws}/figures?query=&top_k=    依查詢找圖，回傳可讀檔名與 caption
    GET /kb/{ws}/images/{name}            圖片本體（雜湊名或可讀別名都吃）
    GET /kb/{ws}/search?query=&top_k=&mode=  查詢（代轉 LightRAG，金鑰由本服務保管）
    GET /health

用法：
    kbapi.py --port 9700
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mineru_common import load_env  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DATA_ROOT = Path(os.environ.get("PP_DATA_ROOT", "/data/rag/lightrag"))
ENV = load_env(REPO)
# chunk 內容裡的圖片長這樣（ir_builder 產生）：
#   <drawing id="im-…" format="jpg" caption="(a) Concentric resonator"
#            path="K Muffler Acoustics.blocks.assets/c69b8f97….jpg" />
# 注意 path 指向 .parsed/ 底下的 assets —— 那個目錄**每次抽取都會被砍掉重建**，
# 不能依賴。但雜湊與 .mineru_raw/images/ 完全一致（已驗證），所以取檔名回查
# 耐久的那份。
DRAWING = re.compile(r'<drawing[^>]*?caption="([^"]*)"[^>]*?path="([^"]+)"', re.I)

MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".gif": "image/gif", ".webp": "image/webp"}


def parsed_dir(ws: str) -> Path:
    return DATA_ROOT / ws / "inputs" / ws / "__parsed__"


def slug(name: str) -> str:
    """文件名 → 檔名安全的短代號。Obsidian 的 ![[…]] 顯示的就是檔名，
    雜湊名對人完全沒有意義。"""
    s = unicodedata.normalize("NFKD", Path(name).stem)
    s = re.sub(r"[^\w\s-]", "", s, flags=re.U).strip().lower()
    return re.sub(r"[\s_]+", "-", s)[:48].strip("-") or "doc"


@lru_cache(maxsize=64)
def _index(ws: str, doc: str) -> dict:
    """一份文件的圖片索引：雜湊檔名 → (可讀別名, 頁碼, caption)。

    caption 取自 content_list 的 image_caption；MinerU 對 chart 型別常常
    留空，那時候只剩頁碼可用 —— 別名仍然比雜湊好認。
    """
    raw = parsed_dir(ws) / f"{doc}.mineru_raw"
    out: dict = {"by_hash": {}, "by_alias": {}, "doc": doc}
    try:
        items = json.loads((raw / "content_list.json").read_text())
    except Exception:                                        # noqa: BLE001
        return out
    sl, n = slug(doc), 0
    for it in items:
        p = it.get("img_path") or ""
        if not p:
            continue
        base = Path(p).name
        n += 1
        page = it.get("page_idx")
        cap = it.get("image_caption") or it.get("chart_caption") or it.get("table_caption")
        if isinstance(cap, list):
            cap = " ".join(str(x) for x in cap if str(x).strip())
        alias = f"{sl}-p{(page or 0) + 1:02d}-{n:02d}{Path(base).suffix or '.jpg'}"
        rec = {"hash": base, "alias": alias, "page": (page or 0) + 1,
               "caption": (cap or "").strip(), "type": it.get("type")}
        out["by_hash"][base] = rec
        out["by_alias"][alias] = rec
    return out


def find_image(ws: str, name: str) -> Path | None:
    """雜湊名或可讀別名都能取到。別名要掃各文件的索引才對得回去。"""
    pdir = parsed_dir(ws)
    if not pdir.is_dir():
        return None
    if "/" in name or ".." in name:          # 路徑穿越
        return None
    for raw in pdir.glob("*.mineru_raw"):
        direct = raw / "images" / name
        if direct.is_file():
            return direct
        idx = _index(ws, raw.name.removesuffix(".mineru_raw"))
        rec = idx["by_alias"].get(name)
        if rec:
            cand = raw / "images" / rec["hash"]
            if cand.is_file():
                return cand
    return None


def lightrag(path: str, body: dict | None = None) -> dict:
    host = f"http://{ENV.get('BIND_ADDR','127.0.0.1')}:{ENV.get('HOST_PORT','9621')}"
    req = urllib.request.Request(
        host + path, method="POST" if body is not None else "GET",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"X-API-Key": ENV.get("LIGHTRAG_API_KEY", ""),
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read() or "{}")


def doc_summary(ws: str, doc: str) -> dict:
    """單篇的結構。不回全文 —— N Flow 有 66,000 字元，塞進 agent 的 context
    只會擠掉別的東西。要全文請用 search 定位到章節再取。"""
    raw = parsed_dir(ws) / f"{doc}.mineru_raw"
    try:
        items = json.loads((raw / "content_list.json").read_text())
    except Exception as e:                                   # noqa: BLE001
        return {"error": f"讀不到 {doc}: {e}"}
    heads, tables, eqs = [], [], []
    for i, it in enumerate(items):
        t = it.get("type")
        if t == "header" and (it.get("text") or "").strip():
            heads.append({"page": (it.get("page_idx") or 0) + 1,
                          "text": it["text"].strip()[:120]})
        elif t == "table":
            cap = it.get("table_caption")
            if isinstance(cap, list):
                cap = " ".join(str(x) for x in cap)
            tables.append({"index": i, "page": (it.get("page_idx") or 0) + 1,
                           "caption": (cap or "").strip()[:120],
                           "repaired": "_pp_repaired_at" in it})
        elif t == "equation":
            eqs.append({"index": i, "page": (it.get("page_idx") or 0) + 1,
                        "latex": (it.get("text") or "")[:300]})
    idx = _index(ws, doc)
    return {"doc": doc, "items": len(items),
            "headings": heads[:60], "tables": tables,
            "equations": eqs[:80],
            "figures": list(idx["by_hash"].values()),
            "note": "headings/equations 有上限，完整內容請用 search 定位"}


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(),
                   "application/json; charset=utf-8")

    def log_message(self, fmt, *a):                          # 安靜一點
        sys.stderr.write("  %s\n" % (fmt % a))

    def do_GET(self):                                        # noqa: N802
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        parts = [urllib.parse.unquote(p) for p in u.path.strip("/").split("/")]

        if parts == ["health"]:
            return self._json({"status": "ok", "data_root": str(DATA_ROOT)})

        if len(parts) >= 3 and parts[0] == "kb":
            ws, kind = parts[1], parts[2]
            rest = parts[3] if len(parts) > 3 else ""

            if kind == "docs":
                pdir = parsed_dir(ws)
                if not pdir.is_dir():
                    return self._json({"error": f"沒有 workspace {ws}"}, 404)
                docs = []
                for raw in sorted(pdir.glob("*.mineru_raw")):
                    name = raw.name.removesuffix(".mineru_raw")
                    docs.append({"doc": name,
                                 "figures": len(_index(ws, name)["by_hash"])})
                return self._json({"workspace": ws, "documents": docs})

            if kind == "doc" and rest:
                return self._json(doc_summary(ws, rest))

            if kind == "images" and rest:
                p = find_image(ws, rest)
                if not p:
                    return self._json({"error": f"找不到圖片 {rest}"}, 404)
                return self._send(200, p.read_bytes(),
                                  MIME.get(p.suffix.lower(), "application/octet-stream"))

            if kind == "search":
                # 代轉查詢的唯一理由是**可攜性**：LightRAG 的 /query/data 需要
                # X-API-Key，skill 只能去讀伺服器上的 .env 拿 —— 那個路徑只有
                # 這台機器有，複製到別台就是 401。由本服務保管金鑰之後，三個
                # skill 都變成「打 9700、不用認證」，任何機器複製過去直接能用，
                # 金鑰也不會散落在各台機器的 skill 檔案裡。
                query = (q.get("query") or [""])[0]
                if not query:
                    return self._json({"error": "缺少 query"}, 400)
                mode = (q.get("mode") or ["mix"])[0]
                k = int((q.get("top_k") or ["10"])[0])
                try:
                    d = lightrag("/query/data",
                                 {"query": query, "mode": mode, "top_k": k,
                                  "only_need_context": True})
                except Exception as e:                       # noqa: BLE001
                    return self._json({"error": f"LightRAG 查詢失敗: {e}"}, 502)
                data = d.get("data") or {}
                # 只回 agent 用得到的欄位。原始回應還有 entities/relationships，
                # 但那些對「拿原文自己整合」的用法是雜訊，會擠掉 context。
                return self._json({
                    "query": query, "mode": mode,
                    "chunks": [{"doc": Path(c.get("file_path") or "").name,
                                "content": c.get("content") or ""}
                               for c in (data.get("chunks") or [])],
                    "entities": [e.get("entity_name") for e in (data.get("entities") or [])][:30],
                })

            if kind == "figures":
                query = (q.get("query") or [""])[0]
                k = int((q.get("top_k") or ["10"])[0])
                if not query:
                    return self._json({"error": "缺少 query"}, 400)
                try:
                    d = lightrag("/query/data",
                                 {"query": query, "mode": "mix", "top_k": k,
                                  "only_need_context": True})
                except Exception as e:                       # noqa: BLE001
                    return self._json({"error": f"LightRAG 查詢失敗: {e}"}, 502)
                chunks = (d.get("data") or {}).get("chunks") or []
                seen, figs = set(), []
                for ch in chunks:
                    doc = Path(ch.get("file_path") or "").name
                    if not doc:
                        continue
                    idx = _index(ws, doc)
                    for cap, path in DRAWING.findall(ch.get("content") or ""):
                        h = Path(path).name
                        rec = idx["by_hash"].get(h)
                        if not rec or rec["alias"] in seen:
                            continue
                        seen.add(rec["alias"])
                        # chunk 裡的 caption 是 ir_builder 整理過的，比
                        # content_list 的原始欄位乾淨，優先採用
                        figs.append({**rec, "doc": doc,
                                     "caption": cap.strip() or rec["caption"]})
                return self._json({"query": query, "figures": figs[:k],
                                   "hint": "用 /kb/{ws}/images/{alias} 下載"})

        self._json({"error": "unknown path",
                    "paths": ["/health", "/kb/{ws}/docs", "/kb/{ws}/doc/{name}",
                              "/kb/{ws}/figures?query=", "/kb/{ws}/images/{name}"]}, 404)


def main():
    ap = argparse.ArgumentParser(description="LightRAG 的唯讀補充端點")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=9700)
    a = ap.parse_args()
    print(f"kbapi 監聽 {a.host}:{a.port}　DATA_ROOT={DATA_ROOT}", flush=True)
    ThreadingHTTPServer((a.host, a.port), H).serve_forever()


if __name__ == "__main__":
    main()
