#!/usr/bin/env python3
"""把 postprocess 依賴的假設變成可執行的斷言。

為什麼需要這支：後處理不修改 LightRAG 任何程式碼，改的是磁碟上的檔案，所以耦合
的對象是「LightRAG 如何讀寫 __parsed__ 底下的東西」這組**未言明的契約**。升級、
或 MinerU 雲端換模型，都可能讓契約失效 —— 而失效是靜默的：沒有錯誤訊息，只是
修補被丟掉、雜訊回來、索引悄悄退化。

文件會過期，斷言不會。所以這些假設寫成程式而不是寫成註解，並且排程每天跑，
因為外部變動不會挑你升級的日子發生。

用法：
    ./compat-check.py                      # 契約層 + 環境
    ./compat-check.py --doc 'Equivalent'   # 加上該文件的資料層檢查
    ./compat-check.py --json               # 給程式解析
退出碼：0 全過；2 有 hard 失敗（不得動工）；5 只有 soft 失敗（可續）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pp.oracle import Oracle, OracleError, container_for  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DATA_ROOT = Path(os.environ.get("PP_DATA_ROOT", "/data/rag/lightrag"))

# 已知的 content_list 項目型別。出現沒見過的型別 = 版面型態超出規則涵蓋範圍，
# 過濾與修補的判斷都可能不適用，所以擋下而不是猜。
# 「已知」的意思是**我們決定過 LightRAG 怎麼對待它**，不是「看過這個字串」。
# 出現在這裡以外的型別，代表有一批內容的去向沒人判斷過。
#
#   text/header/footer/…  ir_builder 有對應分支，或 fallback 取得到文字
#   aside_text            走 fallback，text 有內容所以進得了索引（頁碼側欄那些
#                         是被 layout_noise 消音的，那是刻意的）
#   chart                 走 fallback 但 content 固定是空字串 → 整個被丟掉。
#                         由 pp/rules/chart_type.py 轉成 image；轉完就不會再
#                         出現在資料裡，留在這裡是為了「新解析的文件出現 chart
#                         時不要當成未知型別驚慌」——它有處置方式，跑 apply 即可。
KNOWN_TYPES = {
    "text", "header", "footer", "table", "equation", "image",
    "page_number", "page_footnote", "code", "list",
    "aside_text", "chart",
}


@dataclass
class Result:
    id: str
    level: str              # hard | soft | info
    what: str
    ok: bool | None = None  # None = 略過
    detail: str = ""
    data: dict = field(default_factory=dict)


class Checker:
    def __init__(self, oracle: Oracle, workspace: str):
        self.o = oracle
        self.ws = workspace
        self.results: list[Result] = []

    def add(self, r: Result) -> Result:
        self.results.append(r)
        return r

    def check(self, id_: str, level: str, what: str):
        """裝飾器：把例外變成失敗，而不是讓整支掛掉。"""
        def deco(fn):
            try:
                ok, detail, data = fn()
            except OracleError as e:
                ok, detail, data = False, f"oracle 失敗：{e}", {}
            except Exception as e:  # noqa: BLE001
                ok, detail, data = False, f"{type(e).__name__}: {e}", {}
            return self.add(Result(id_, level, what, ok, detail, data))
        return deco

    # ---------- 契約層 ----------

    def contract(self):
        @self.check("A-01", "hard", "探針與 server 執行的是同一份 lightrag")
        def _():
            d = self.o.module_identity()
            hashes = {h for _, h in d["cache_copies"]}
            ok = len(hashes) <= 1
            return ok, (f"{len(d['cache_copies'])} 份副本，"
                        f"{'md5 一致' if ok else 'md5 不一致 —— 探針可能不是實際執行的那份'}"), d

        @self.check("A-02", "hard", "is_bundle_valid 可用且簽章不變")
        def _():
            d = self.o.py(
                "import json,inspect\n"
                "from lightrag.parser.external.mineru.cache import is_bundle_valid as f\n"
                "print(json.dumps(str(inspect.signature(f))))")
            want = "(raw_dir: 'Path', source_file: 'Path', *, overrides:"
            return d.startswith(want), d, {"signature": d}

        @self.check("A-03", "hard", "磁碟佈局常數不變")
        def _():
            c = self.o.constants()
            want = {"RAW_SUFFIX": ".mineru_raw", "PARSED_SUFFIX": ".parsed",
                    "PARSED_DIR_NAME": "__parsed__",
                    "MANIFEST_FILENAME": "_manifest.json", "MANIFEST_VERSION": "1.0"}
            bad = {k: (c.get(k), v) for k, v in want.items() if c.get(k) != v}
            return not bad, (f"lightrag {c['lightrag_version']}"
                             + (f"；不符：{bad}" if bad else "")), c

        @self.check("A-05", "hard", "快取驗證只看 6 項，不看 total_size_bytes")
        def _():
            src = self.o.py(
                "import json,inspect\n"
                "from lightrag.parser.external.mineru import cache as c\n"
                "print(json.dumps(inspect.getsource(c.is_bundle_valid)))")
            checks_total = "total_size_bytes" in src
            checks_listdir = ("iterdir" in src) or ("listdir" in src) or ("glob" in src)
            crit = "critical_file" in src and "sha256" in src
            ok = crit and not checks_total and not checks_listdir
            notes = []
            if checks_total:
                notes.append("竟然驗了 total_size_bytes")
            if checks_listdir:
                notes.append("竟然列舉了目錄 —— 我們寫進 raw_dir 的任何檔案都會讓快取失效")
            if not crit:
                notes.append("找不到 critical_file/sha256 檢查")
            return ok, ("；".join(notes) or "如預期：只驗 critical_file 的 size+sha256"), {}

        @self.check("A-06", "hard", "_coerce_text 讀的欄位不變（決定消音清哪個欄位）")
        def _():
            fields = self.o.ir_text_fields()
            want = ["text", "content", "body", "code_body"]
            return fields == want, f"{fields}", {"fields": fields}

        @self.check("A-24", "hard", "drawing 的型別集合與 caption 欄位不變（chart→image 的前提）")
        def _():
            c = self.o.ir_drawing_contract()
            types, fields = c.get("types") or [], c.get("fields") or []
            want_t = ["image", "picture", "drawing"]
            # 只要求 caption/footnote 這兩個關鍵欄位還在；img_path 等其餘欄位
            # 增減不影響我們。
            need_f = {"image_caption", "image_footnote"}
            ok = types == want_t and need_f <= set(fields)
            note = f"型別 {types}；讀 {fields}"
            if types != want_t:
                note += ("　← chart 已被 LightRAG 認得，轉換規則可以退休"
                         if "chart" in types else "　← 集合變了，重新確認 chart 的去向")
            return ok, note, {"types": types, "fields": fields}

        @self.check("A-06b", "hard", "page_number 在 heading 偵測之前被無條件跳過")
        def _():
            src = self.o.py(
                "import json,inspect\n"
                "from lightrag.parser.external.mineru import ir_builder as B\n"
                "print(json.dumps(inspect.getsource(B)))")
            i_pn = src.find('item_type == "page_number"')
            i_hd = src.find("_detect_heading(item, item_type)")
            ok = 0 < i_pn < i_hd
            return ok, ("page_number 在前，符合預期" if ok
                        else "順序改變 —— page_number 可能被當成標題進 IR"), {}

        @self.check("A-07", "hard", "LIGHTRAG_FORCE_REPARSE_MINERU 未開啟")
        def _():
            v = self.o.force_reparse_flag()
            ok = v.strip().lower() in ("", "0", "false", "no")
            return ok, (f"值 ={v!r}。開啟時會先 clear_dir_contents(raw_dir) 再重抓，"
                        "修補會在生效前被刪掉且 pipeline 回報成功"
                        if not ok else "未設定"), {"value": v}

        @self.check("A-17", "hard", "host 有 poppler 工具")
        def _():
            missing = [t for t in ("pdftoppm", "pdftotext", "pdfinfo") if not shutil.which(t)]
            return not missing, (f"缺少 {missing}" if missing else "pdftoppm / pdftotext / pdfinfo 都在"), {}

    # ---------- 環境層 ----------

    def environment(self, api_key: str, port: int):
        @self.check("A-18", "soft", "VLM 端點可用")
        def _():
            import urllib.error
            import urllib.request
            env = _load_env()
            host = env.get("LLM_BINDING_HOST", "")
            if not host:
                return False, "找不到 LLM_BINDING_HOST", {}
            try:
                r = urllib.request.urlopen(f"{host}/models", timeout=10)
                models = json.loads(r.read()).get("data", [])
                names = [m.get("id") for m in models][:3]
                return True, f"{host} 可用，模型 {names}", {"models": names}
            except (urllib.error.URLError, OSError) as e:
                return False, f"{host} 連不上：{e}", {}

        @self.check("A-19", "hard", "pipeline 目前 idle")
        def _():
            d = self.o.pipeline_idle(api_key, port)
            busy = d.get("busy") or d.get("scanning") or d.get("destructive_busy")
            return (not busy), (f"busy={d.get('busy')} scanning={d.get('scanning')} "
                                f"job={d.get('job_name')!r}"), d

        @self.check("A-25", "soft", "chunk_top_k 仍然控制回傳的片段數（kbapi 的節流靠它）")
        def _():
            """kbapi 的 chunks 參數就是下傳成 chunk_top_k。它一旦失效，
            /kb/*/search 會靜靜地回到每次 55–60KB —— 不會報錯，只是把呼叫端的
            context 灌爆。所以寧可每次都真的打一次查詢來驗。

            順帶記下不要用 max_total_tokens 收：它是先扣圖譜再給原文，設太小
            時 available_chunk_tokens 變負數，chunk 直接回 0 個且不報錯。
            """
            try:
                got = self.o.chunk_top_k_effect(api_key)
            except OracleError as e:
                return None, f"查不動（{str(e)[:60]}），跳過", {}
            a, b = got.get("2", -1), got.get("8", -1)
            return (a <= 2 and b <= 8 and b > a), \
                   f"chunk_top_k=2 → {a} 個、=8 → {b} 個", got

        @self.check("A-22", "hard", "每張向量表都有向量索引")
        def _():
            import subprocess
            env = _load_env()
            model = env.get("EMBEDDING_MODEL", "").replace("-", "_")
            dim = env.get("EMBEDDING_DIM", "")
            suffix = f"{model}_{dim}d".lower()
            sql = (
                "select t.relname, count(i.indexrelid) filter ("
                "  where am.amname in ('hnsw','ivfflat','vchordrq')) "
                "from pg_class t "
                "join pg_namespace n on n.oid=t.relnamespace and n.nspname='public' "
                "left join pg_index i on i.indrelid=t.oid "
                "left join pg_class ic on ic.oid=i.indexrelid "
                "left join pg_am am on am.oid=ic.relam "
                f"where t.relkind='r' and t.relname like 'lightrag\\_vdb\\_%{suffix}' "
                "group by 1 order by 1;"
            )
            p = subprocess.run(
                ["docker", "exec", "deeptutor-v4-postgres", "psql", "-U",
                 env.get("POSTGRES_USER", "deeptutor"), "-d",
                 env.get("POSTGRES_DATABASE", "lightrag"), "-tAF|", "-c", sql],
                capture_output=True, text=True, timeout=30)
            rows = [ln.split("|") for ln in p.stdout.strip().splitlines() if "|" in ln]
            if not rows:
                return False, f"找不到 *{suffix} 的向量表", {}
            bad = [r[0] for r in rows if int(r[1]) == 0]
            return not bad, (
                f"{len(rows)} 張表都有向量索引"
                if not bad else
                f"{bad} 沒有向量索引 —— 查詢會退化成全表掃描。"
                "常見原因：維度 > 2000 而未設 POSTGRES_VECTOR_INDEX_TYPE=HNSW_HALFVEC，"
                "建索引失敗只在啟動日誌留一行 ERROR，服務照樣 healthy"), {"tables": rows}

        @self.check("A-23", "hard", "綁模型的觀察仍對應現行模型")
        def _():
            """模型換代時，綁模型的觀察會靜默失效 —— 規則還在，前提沒了。

            實測記錄的「eye_b 會看錯字元、eye_a 會切錯結構」這類觀察，換一個
            模型就可能完全相反。這條斷言不判斷觀察對不對，只確認**它是對現在
            這組模型量的**。不一致就 FAIL，逼人重新量測。
            """
            f = REPO / "tests" / "model-observations.json"
            if not f.is_file():
                return False, f"缺少 {f.name}", {}
            rec = json.loads(f.read_text())
            want_a, want_b = rec.get("eye_a"), rec.get("eye_b")
            env = _load_env()
            got_a = env.get("LLM_MODEL")
            got_b = env.get("PP_EYE_B_MODEL", "gpt-5.6-luna")
            ok = (want_a == got_a) and (want_b == got_b)
            msg = (f"量測於 {rec.get('measured_on')}：{want_a} + {want_b}"
                   if ok else
                   f"觀察量測於 {want_a} + {want_b}，但現行是 {got_a} + {got_b} —— "
                   f"綁模型的觀察已失效，重新量測後更新 {f.name}")
            return ok, msg, {}

        @self.check("A-21", "info", "MinerU token 到期日")
        def _():
            import base64
            import time
            env = _load_env()
            tok = env.get("MINERU_API_TOKEN", "")
            if not tok or tok.count(".") != 2:
                return False, "找不到或格式不對", {}
            pl = tok.split(".")[1]
            pl += "=" * (-len(pl) % 4)
            exp = json.loads(base64.urlsafe_b64decode(pl))["exp"]
            days = (exp - time.time()) / 86400
            ok = days > 14
            return ok, (f"{time.strftime('%Y-%m-%d', time.localtime(exp))}，剩 {days:.0f} 天"
                        + ("" if ok else " —— 整批解析要 6–10 小時，中途過期會讓後半批全滅")), {"days": days}

    # ---------- 資料層（逐文件）----------

    def document(self, raw_dir: Path):
        name = raw_dir.name.removesuffix(".mineru_raw")

        @self.check("A-10", "hard", f"{name}：content_list.json 只在 critical_file")
        def _():
            m = json.loads((raw_dir / "_manifest.json").read_text())
            in_files = [f["path"] for f in m.get("files", [])
                        if f["path"] == "content_list.json"]
            crit = (m.get("critical_file") or {}).get("path")
            ok = crit == "content_list.json" and not in_files
            return ok, ("critical_file=content_list.json，且不在 files[] —— "
                        "更新 manifest 只需改 critical_file"
                        if ok else
                        f"critical_file={crit!r}，files[] 內{'有' if in_files else '無'} —— "
                        "更新邏輯需要跟著改，否則快取會失效並靜默丟棄修補"), {}

        @self.check("A-11", "hard", f"{name}：options 簽章與現行設定相符")
        def _():
            m = json.loads((raw_dir / "_manifest.json").read_text())
            cur = self.o.options_signature()
            ok = m.get("options_signature") == cur
            return ok, ("相符" if ok else
                        f"不符 —— 這份 bundle 是用不同解析選項產生的，"
                        f"重新索引時會被丟棄並重解（manifest {m.get('options_signature','')[7:19]}… "
                        f"vs 現行 {cur[7:19]}…）"), {}

        @self.check("A-13", "hard", f"{name}：來源 PDF 可用內容定址找到")
        def _():
            m = json.loads((raw_dir / "_manifest.json").read_text())
            want = m["source_content_hash"]
            cands = [raw_dir.parent / f"{name}", raw_dir.parent.parent / f"{name}",
                     *raw_dir.glob("*_origin.pdf")]
            for c in cands:
                if c.exists() and c.is_file():
                    h = "sha256:" + hashlib.sha256(c.read_bytes()).hexdigest()
                    if h == want:
                        return True, f"命中 {c.name}", {"path": str(c)}
            return False, (f"{len(cands)} 個候選都對不上 source_content_hash —— "
                           "不得寫死路徑，來源 PDF 會被 archive_source 搬走"), {}

        @self.check("A-14", "hard", f"{name}：layout.json 頁序未位移")
        def _():
            lay = json.loads((raw_dir / "layout.json").read_text())
            pi = lay["pdf_info"]
            bad = [k for k, p in enumerate(pi) if p.get("page_idx") != k]
            sizes = {tuple(p.get("page_size") or []) for p in pi}
            ok = not bad and len(sizes) == 1
            return ok, (f"{len(pi)} 頁，page_size {sizes.pop() if len(sizes)==1 else sizes}"
                        if ok else
                        f"錯位頁 {bad[:5]} 或頁面尺寸不一致 {sizes} —— "
                        "書眉每頁幾何相同，錯頁比對照樣會 IoU 命中"), {}

        @self.check("A-16", "hard", f"{name}：沒有未知的項目型別")
        def _():
            items = json.loads((raw_dir / "content_list.json").read_text())
            types = {i.get("type") for i in items}
            unknown = types - KNOWN_TYPES
            return not unknown, (f"型別 {sorted(types)}"
                                 + (f"；未知 {sorted(unknown)}" if unknown else "")), {}

        @self.check("A-20", "info", f"{name}：目前的量測基準")
        def _():
            items = json.loads((raw_dir / "content_list.json").read_text())
            tag = re.compile(r"<[^>]+>")
            tabs = [i for i in items if i.get("type") == "table"]
            hf = [i for i in items if i.get("type") in ("header", "footer")]
            body = sum(len(i.get("text") or "") for i in items
                       if i.get("type") in ("text", "header", "footer"))
            noise = sum(len(i.get("text") or "") for i in hf)
            d = {
                "項目": len(items),
                "header": sum(1 for i in items if i.get("type") == "header"),
                "footer": sum(1 for i in items if i.get("type") == "footer"),
                "雜訊佔比": round(100 * noise / max(body, 1), 2),
                "表格": len(tabs),
                "缺 table_body": sum(1 for t in tabs if "table_body" not in t),
                "空殼": sum(1 for t in tabs if "table_body" in t
                            and not tag.sub("", t["table_body"]).strip()),
                "含 img": sum(1 for t in tabs if "<img" in (t.get("table_body") or "")),
            }
            return True, "、".join(f"{k} {v}" for k, v in d.items()), d


def _load_env() -> dict:
    p = REPO / ".env"
    if not p.exists():
        return {}
    out = {}
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip("'\"")
    return out


def main():
    env = _load_env()
    ap = argparse.ArgumentParser(description="驗證 postprocess 依賴的假設")
    ap.add_argument("--workspace", default=env.get("WORKSPACE", "acoustics_v155"))
    # 容器名由 workspace 推導，不寫死。寫死的後果是「在 v2 的 checkout 跑檢查，
    # 探針卻打進 v155 的容器」—— 契約層全綠，但驗的是別的庫，而且沒有任何訊號。
    ap.add_argument("--container", default=None,
                    help="預設 lightrag-<workspace>")
    # 資料層檢查**預設跑全部文件**。原本是 `if a.doc:` 才跑，等於不指定就一份
    # 都不檢查 —— 而你只會對「正在處理的那一份」指定。實測代價：A-16
    # （沒有未知的項目型別）本來就抓得到 chart，但 184 個 chart 分散在 11 份
    # 文件裡，從專案開始到發現為止一次都沒被喊過。探針要能在沒人問的時候發聲，
    # 否則它防的是「你已經懷疑的事」，那不需要探針。
    ap.add_argument("--doc", help="檔名關鍵字，只檢查符合的文件（預設全部）")
    ap.add_argument("--no-docs", action="store_true",
                    help="跳過資料層檢查，只驗契約與環境")
    # A-19 的 pipeline_status 是**在容器內**打 localhost，所以要的是容器自己
    # 監聽的 PORT，不是發佈到宿主的 HOST_PORT。v155 兩者剛好都是 9621，看不出
    # 差別；v2 的 HOST_PORT=9622，沿用 HOST_PORT 會在容器內連不上 —— 而
    # 「連不上」跟「pipeline 真的在忙」在結果上長得一樣，是假性 hard FAIL。
    ap.add_argument("--port", type=int, default=int(env.get("PORT", 9621)),
                    help="容器內監聽的埠（不是發佈到宿主的 HOST_PORT）")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    container = a.container or container_for(a.workspace)
    o = Oracle(container=container)
    if not o.alive():
        print(f"compat-check: 容器 {container} 連不上", file=sys.stderr)
        sys.exit(2)

    c = Checker(o, a.workspace)
    c.contract()
    c.environment(env.get("LIGHTRAG_API_KEY", ""), a.port)

    n_docs = 0
    doc_from = len(c.results)          # 之後的結果都是資料層的，印的時候要收合
    if not a.no_docs:
        pdir = DATA_ROOT / a.workspace / "inputs" / a.workspace / "__parsed__"
        hits = [d for d in pdir.glob("*.mineru_raw")
                if not a.doc or a.doc.lower() in d.name.lower()]
        if not hits:
            print(f"compat-check: {pdir} 底下找不到"
                  + (f"符合 {a.doc!r} 的 bundle" if a.doc else "任何 bundle"), file=sys.stderr)
            sys.exit(2)
        for raw in sorted(hits):
            c.document(raw)
        n_docs = len(hits)

    # 20 份 × 6 支探針 = 120 行，全印會把契約層的結果洗掉。所以資料層預設
    # 只印失敗的；指定了 --doc 就是在看那一份，全部印出來。
    collapse = n_docs > 1 and not a.doc

    if a.json:
        print(json.dumps([r.__dict__ for r in c.results], ensure_ascii=False, indent=1))
    else:
        mark = {True: "  ok  ", False: " FAIL ", None: " skip "}
        print(f"{'ID':<7} {'層級':<6} {'結果':^6}  說明")
        print("-" * 100)
        # 20 份 × 6 支探針 = 120 行，全印會把契約層的結果洗掉。所以資料層
        # 預設只印失敗的；指定了 --doc 就是在看那一份，全部印出來。
        for i, r in enumerate(c.results):
            if collapse and i >= doc_from and r.ok is True:
                continue
            print(f"{r.id:<7} {r.level:<6} {mark[r.ok]:^6}  {r.what}")
            if r.detail:
                print(f"{'':<21}  └ {r.detail}")

    hard = [r for r in c.results if r.level == "hard" and r.ok is False]
    soft = [r for r in c.results if r.level == "soft" and r.ok is False]
    if not a.json:
        print("-" * 100)
        # 收合的那些必須報出數量，否則「沒印出來」跟「沒檢查」在畫面上一樣，
        # 而這整段修改就是為了修掉那種一樣。
        hidden = sum(1 for i, r in enumerate(c.results)
                     if collapse and i >= doc_from and r.ok is True)
        print(f"hard 失敗 {len(hard)}　soft 失敗 {len(soft)}　共 {len(c.results)} 項"
              + (f"（{n_docs} 份文件的資料層檢查，{hidden} 項通過未列出）" if hidden else ""))
    sys.exit(2 if hard else (5 if soft else 0))


if __name__ == "__main__":
    main()
