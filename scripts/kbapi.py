#!/usr/bin/env python3
"""補 LightRAG 缺的唯讀端點：圖片與單篇結構化內容。

LightRAG 1.5.5 的 API 只有 /query、/query/stream、/query/data 與文件管理，
**沒有任何圖片端點** —— 1,786 張圖躺在 work/parsed/<doc>.mineru_raw/images/
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
    GET /kb/{ws}/search?query=&chunks=&chars=&mode=&hl_keywords=&ll_keywords=
        chunks 預設 6（下傳為 LightRAG 的 chunk_top_k）、chars 預設 12000
        hl_keywords／ll_keywords 逗號分隔，**自帶才可重現**（見下）
        （字元上限，LightRAG 沒有對應參數，只能在這裡截）
    GET /health

所有端點都支援 `?format=md` 回傳 Markdown（預設 json）。

**md 是給 agent 用的預設選擇。** 回 JSON 的話 skill 必須寫成
`curl -o /tmp/x.json` 再 `jq` 解析 —— 而 `/tmp` 在 PowerShell 不存在
（Git Bash 會映射到 LOCALAPPDATA 的 Temp，PowerShell 直接失敗），
`jq` 在 Windows 也要另外裝。回 Markdown 就只需要 `curl -s <url>`，
Linux／macOS／Git Bash／PowerShell 四種環境的指令完全一樣。

用法：
    kbapi.py --port 9700
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mineru_common import compact_drawings, load_env  # noqa: E402
from pp.paths import DataPaths, configured_data_root  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DATA_ROOT = configured_data_root()
ENV = load_env(REPO)
# 本服務服務的 workspace。沒有預設值：一個猜錯的預設會讓端點靜靜回別的庫的
# 資料（見下方 kb 路由的 400 擋板）。設不出來就不要起。
WORKSPACE = ENV.get("WORKSPACE") or sys.exit(
    "kbapi: .env 缺 WORKSPACE —— 本服務靠它判斷 URL 要的庫是不是自己")
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
    return DataPaths(DATA_ROOT).parsed_dir


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
    raw = DataPaths(DATA_ROOT).parsed_bundle_dir(doc)
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
    raw = DataPaths(DATA_ROOT).parsed_bundle_dir(doc)
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



def needs_keywords(mode: str, hl: list[str], ll: list[str], allow: str) -> bool:
    """走圖譜卻沒帶關鍵詞就該擋。**這是判準，只有這一份。**

    ⚠ `naive` 不走圖譜，所以不需要關鍵詞 —— 它本來就確定（2026-08-13 實測：
    同一題三次逐位元相同）。其餘三個模式會先用後端 LLM 把問題變成關鍵詞，
    那一步沒有快取也不確定，實測同一題三次拿到三組不同段落。

    ⚠ **空字串算沒帶。** `hl_keywords=` 這種送下去，LightRAG 會當成「關鍵詞就是
    空的」而不是「請你自己抽」，圖譜那段等於沒查 —— 而且不報錯。
    ⚠ 只要有一邊有值就放行：兩邊都要求會逼人硬湊，而硬湊的關鍵詞比沒有更糟。
    """
    return mode != "naive" and not (hl or ll) and str(allow).lower() not in ("1", "true", "yes")


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

    def _md(self, text: str, code=200):
        self._send(code, text.encode(), "text/markdown; charset=utf-8")

    def _out(self, obj, fmt: str, render, code=200):
        """format=md 時走 render()，否則回 JSON。錯誤一律用純文字，
        免得 agent 還要判斷型別。"""
        if fmt == "md":
            if isinstance(obj, dict) and "error" in obj:
                return self._md(f"錯誤：{obj['error']}\n", code)
            return self._md(render(obj), code)
        return self._json(obj, code)

    def log_message(self, fmt, *a):                          # 安靜一點
        sys.stderr.write("  %s\n" % (fmt % a))

    def do_GET(self):                                        # noqa: N802
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        fmt = (q.get("format") or ["json"])[0].lower()
        parts = [urllib.parse.unquote(p) for p in u.path.strip("/").split("/")]

        if parts == ["health"]:
            return self._json({"status": "ok", "data_root": str(DATA_ROOT)})

        if len(parts) >= 3 and parts[0] == "kb":
            ws, kind = parts[1], parts[2]
            rest = parts[3] if len(parts) > 3 else ""

            # URL 裡的 workspace 必須等於本服務所服務的那個，否則 400。
            #
            # 為什麼需要這道擋板：`search` **不看 `ws`**——它走 lightrag()，
            # 目的地固定是 .env 的 BIND_ADDR:HOST_PORT。但檔案類端點
            # （docs / doc / figures / images）**看** `ws`，直接讀
            # DATA_ROOT/inputs/{ws}…。兩者對同一個 URL 的解讀不一致。
            #
            # 實測過這個混合狀態（2026-08-03 CUTOVER 當下，舊庫磁碟還在時）：
            #     GET /kb/acoustics_v155/search → 回的是 acoustics_v2 的內容
            #     GET /kb/acoustics_v155/docs   → 回的是 acoustics_v155 的檔案
            # 兩個都是 200，都不報錯。呼叫端會把兩邊的東西當成同一個庫的。
            #
            # 最惡劣的後果是切換時「忘了改 skill」不會有任何訊號——查詢照樣
            # 回得出東西，只是答案來自別的庫。所以這裡寧可 400 也不要靜靜答對
            # 一半：**能查到** 與 **查的是你以為的那個庫** 是兩件事。
            if ws != WORKSPACE:
                return self._json(
                    {"error": f"本服務服務的是 workspace {WORKSPACE!r}，"
                              f"URL 要的是 {ws!r}",
                     "hint": "search 端點不看 URL 的 workspace，只看 .env；"
                             "不擋的話會回錯庫的答案且不報錯"}, 400)

            if kind == "docs":
                pdir = parsed_dir(ws)
                if not pdir.is_dir():
                    return self._json({"error": f"沒有 workspace {ws}"}, 404)
                docs = []
                for raw in sorted(pdir.glob("*.mineru_raw")):
                    name = raw.name.removesuffix(".mineru_raw")
                    docs.append({"doc": name,
                                 "figures": len(_index(ws, name)["by_hash"])})
                return self._out(
                    {"workspace": ws, "documents": docs}, fmt,
                    lambda o: f"# {o['workspace']}：{len(o['documents'])} 份文件\n\n"
                    + "\n".join(f"- {d['doc']}　（{d['figures']} 張圖）"
                                 for d in o["documents"]) + "\n")

            if kind == "doc" and rest:
                def _doc_md(o):
                    L = [f"# {o['doc']}", "",
                         f"{o['items']} 個項目｜表格 {len(o['tables'])}｜"
                         f"方程式 {len(o['equations'])}｜圖 {len(o['figures'])}", ""]
                    if o["headings"]:
                        L += ["## 章節", ""] + [f"- p{h['page']}　{h['text']}"
                                                for h in o["headings"]] + [""]
                    if o["tables"]:
                        L += ["## 表格", ""]
                        for t in o["tables"]:
                            mark = "（已修補）" if t["repaired"] else ""
                            L.append(f"- #{t['index']} p{t['page']}{mark}　{t['caption']}")
                        L.append("")
                    if o["equations"]:
                        L += ["## 方程式", ""]
                        for e in o["equations"]:
                            L.append(f"- p{e['page']} #{e['index']}　`{e['latex']}`")
                        L.append("")
                    if o["figures"]:
                        L += ["## 圖片", ""]
                        for f in o["figures"]:
                            L.append(f"- `{f['alias']}`　p{f['page']}"
                                     + (f"　{f['caption']}" if f["caption"] else ""))
                    return "\n".join(L) + "\n"
                return self._out(doc_summary(ws, rest), fmt, _doc_md)

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
                # top_k 控制的是**圖譜檢索廣度**，不是回傳量，而且方向和直覺相反。
                # operate.py:5230：
                #     available_chunk_tokens = max_total_tokens
                #         - (sys_prompt + kg_context + query + buffer)
                # 總額固定 30,000。top_k 餵給 entities_vdb / relationships_vdb，
                # 開大 → kg_context 變大 → 原文的預算被擠掉。實測同一個查詢：
                #     top_k=3   實體 7   chunk 20 個 / 70,796 bytes
                #     top_k=40  實體 98  chunk 12 個 / 41,241 bytes
                #
                # 真正控制片段數的是 chunk_top_k（utils.py:4842，直接切 list），
                # 而且它切在 token 截斷之前，所以設了以後 top_k 就只剩「回幾個實體」
                # 這一個作用 —— 實測 top_k 3/10/20/40 配 chunk_top_k=6，
                # 拿到的 6 個 chunk 位元組數完全相同。兩個參數因此是正交的。
                #
                # 不用 max_total_tokens 收：它是先扣圖譜再給原文，設 8000 時
                # 圖譜就把預算吃光，chunk 直接回 0 個而且不報錯。
                max_chunks = int((q.get("chunks") or ["6"])[0])
                max_chars = int((q.get("chars") or ["12000"])[0])
                # 呼叫端自帶關鍵詞 —— **這是讓查詢可重現的唯一辦法**。
                #
                # 不帶的話 LightRAG 會自己用 LLM 把問題變成關鍵詞，而那一步跑在
                # 查詢端的溫度上、**而且沒有快取**（lightrag_llm_cache 只有
                # extract／summary 兩類）。2026-08-09 實測：一個沒查過的問題連問
                # 三次，拿回三組不同的段落 —— 使用者不會有任何訊號。
                #
                # 帶了之後那一步不做（數 llama.cpp 日誌：0 次請求，不帶時是 1 次），
                # 三題各三次全部相同，分數一題更好、兩題持平、零題變差。
                # ⚠ 不會變快：那次呼叫只佔 0.7–0.9 秒，5 秒的耗時在向量比對與圖譜上。
                #
                # 逗號分隔。hl＝高層（主題、概念），ll＝低層（具體名詞、參數）。
                def _kw(name: str) -> list[str]:
                    raw = (q.get(name) or [""])[0]
                    return [s.strip() for s in raw.split(",") if s.strip()]

                hl, ll = _kw("hl_keywords"), _kw("ll_keywords")
                # 走圖譜卻沒帶關鍵詞 → **拒絕，不要安靜地變成不確定**。
                # 判準抽成模組層的 `needs_keywords()`，不要 inline —— inline 的話
                # 沒有測試搆得到它，而這是一條「安靜失敗」的守衛，正是最需要守的那種。
                #
                # 上面那段註解記著「三次拿回三組不同的段落，使用者不會有任何訊號」，
                # 而在 2026-08-13 之前**沒有任何東西擋著它** —— skill 的說明有寫，
                # 但說明不是執行者。當天實測（走這一層、同一題各三次）：
                #
                #     naive   不帶／帶      三次相同 ／ 三次相同
                #     mix     不帶／帶      **三次不同** ／ 三次相同
                #     local   不帶／帶      **三次不同** ／ 三次相同
                #     global  不帶／帶      **三次不同** ／ 三次相同
                #
                # ⚠ 不改成自動退回 naive：那是**安靜地換掉檢索策略**，圖譜整張不查
                #   而呼叫端不會知道。寧可回錯誤讓人改呼叫，也不要偷偷給別的東西。
                # ⚠ 逃生門留著（`allow_llm_keywords=1`）：擋下的東西要有辦法明確要求，
                #   否則遲早有人繞過整個這一層。
                if needs_keywords(mode, hl, ll,
                                  (q.get("allow_llm_keywords") or ["0"])[0]):
                    return self._json({
                        "error": "走圖譜的模式必須自帶關鍵詞，否則同一題每次拿到不同段落",
                        "why": ("mode=mix/local/global 會先用後端 LLM 把問題變成關鍵詞，"
                                "那一步沒有快取也不確定。實測同一題三次拿到三組不同段落。"),
                        "how": ("加上 hl_keywords（高層概念 2–3 個）與 "
                                "ll_keywords（具體名詞參數 3–5 個），逗號分隔；"
                                "或用 mode=naive（確定，但不查圖譜）；"
                                "真的要不確定的行為就加 allow_llm_keywords=1"),
                        "mode": mode}, 400)
                body = {"query": query, "mode": mode, "top_k": k,
                        "chunk_top_k": max_chunks, "only_need_context": True}
                # 只在真的有值時才送。送空陣列的話 LightRAG 會當成「關鍵詞就是空的」
                # 而不是「請你自己抽」，於是圖譜那一段等於沒查 —— 而且不報錯。
                if hl:
                    body["hl_keywords"] = hl
                if ll:
                    body["ll_keywords"] = ll
                try:
                    d = lightrag("/query/data", body)
                except Exception as e:                       # noqa: BLE001
                    return self._json({"error": f"LightRAG 查詢失敗: {e}"}, 502)
                data = d.get("data") or {}
                # 只回 agent 用得到的欄位。原始回應還有 entities/relationships，
                # 但那些對「拿原文自己整合」的用法是雜訊，會擠掉 context。
                raw_chunks = data.get("chunks") or []
                kept, used = [], 0
                for c in raw_chunks[:max_chunks]:
                    # **壓縮要在字元預算之前做**，否則省下來的額度不會變成更多原文。
                    body = compact_drawings(c.get("content") or "")
                    room = max_chars - used
                    if room <= 0:
                        break
                    if len(body) > room:
                        body = body[:room] + "\n…（截斷）"
                    used += len(body)
                    kept.append({"doc": Path(c.get("file_path") or "").name,
                                 "content": body})
                out = {
                    "query": query, "mode": mode,
                    "chunks": kept,
                    # chunk_top_k 下傳之後 raw_chunks 已經是被 LightRAG 切過的，
                    # 不再是「總共有幾個」。叫 available 會讓呼叫端誤以為還有更多
                    # 可以撈，所以改成 retrieved —— 它就是 max_chunks（或更少）。
                    "truncated": {"chunks_retrieved": len(raw_chunks),
                                  "chunks_returned": len(kept),
                                  "cap_chunks": max_chunks,
                                  "chars": used, "cap_chars": max_chars},
                    # 回報有沒有自帶關鍵詞。**沒帶就是這次查詢不可重現**，
                    # 而呼叫端看不到這件事的話，會把偶然的結果當成穩定的結果。
                    "keywords": {"supplied": bool(hl or ll), "hl": hl, "ll": ll,
                                 "note": ("" if (hl or ll) else
                                          "未自帶關鍵詞：後端用 LLM 抽，同一個問題"
                                          "重問可能拿到不同段落")},
                    "entities": [e.get("entity_name") for e in (data.get("entities") or [])][:30],
                }
                return self._out(out, fmt, lambda o:
                    f"# 查詢：{o['query']}（mode={o['mode']}）\n\n"
                    + f"相關實體：{', '.join(x for x in o['entities'] if x)}\n\n"
                    + f"_取 {o['truncated']['chunks_returned']}/"
                      f"{o['truncated']['chunks_retrieved']} 個片段"
                      f"（上限 {o['truncated']['cap_chunks']}）、"
                      f"{o['truncated']['chars']:,} 字元_\n\n"
                    + "\n".join(f"## {c['doc']}\n\n{c['content']}\n"
                                for c in o["chunks"]))

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
                return self._out(
                    {"query": query, "figures": figs[:k], "workspace": ws}, fmt,
                    lambda o: f"# 找到 {len(o['figures'])} 張圖\n\n"
                    + "\n".join(
                        f"- `{f['alias']}`　{f['doc']}　p{f['page']}"
                        + (f"\n  caption: {f['caption']}" if f["caption"] else "")
                        for f in o["figures"])
                    + f"\n\n下載：`/kb/{o['workspace']}/images/<alias>`\n")

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
