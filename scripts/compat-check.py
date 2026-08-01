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
from pp.oracle import Oracle, OracleError  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DATA_ROOT = Path(os.environ.get("PP_DATA_ROOT", "/data/rag/lightrag"))

# 已知的 content_list 項目型別。出現沒見過的型別 = 版面型態超出規則涵蓋範圍，
# 過濾與修補的判斷都可能不適用，所以擋下而不是猜。
KNOWN_TYPES = {
    "text", "header", "footer", "table", "equation", "image",
    "page_number", "page_footnote", "code", "list",
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
    ap.add_argument("--container", default="lightrag-acoustics_v155")
    ap.add_argument("--doc", help="檔名關鍵字，加做該文件的資料層檢查")
    ap.add_argument("--port", type=int, default=int(env.get("HOST_PORT", 9621)))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    o = Oracle(container=a.container)
    if not o.alive():
        print(f"compat-check: 容器 {a.container} 連不上", file=sys.stderr)
        sys.exit(2)

    c = Checker(o, a.workspace)
    c.contract()
    c.environment(env.get("LIGHTRAG_API_KEY", ""), a.port)

    if a.doc:
        pdir = DATA_ROOT / a.workspace / "inputs" / a.workspace / "__parsed__"
        hits = [d for d in pdir.glob("*.mineru_raw") if a.doc.lower() in d.name.lower()]
        if not hits:
            print(f"compat-check: {pdir} 底下找不到符合 {a.doc!r} 的 bundle", file=sys.stderr)
            sys.exit(2)
        for raw in sorted(hits):
            c.document(raw)

    if a.json:
        print(json.dumps([r.__dict__ for r in c.results], ensure_ascii=False, indent=1))
    else:
        mark = {True: "  ok  ", False: " FAIL ", None: " skip "}
        print(f"{'ID':<7} {'層級':<6} {'結果':^6}  說明")
        print("-" * 100)
        for r in c.results:
            print(f"{r.id:<7} {r.level:<6} {mark[r.ok]:^6}  {r.what}")
            if r.detail:
                print(f"{'':<21}  └ {r.detail}")

    hard = [r for r in c.results if r.level == "hard" and r.ok is False]
    soft = [r for r in c.results if r.level == "soft" and r.ok is False]
    if not a.json:
        print("-" * 100)
        print(f"hard 失敗 {len(hard)}　soft 失敗 {len(soft)}　共 {len(c.results)} 項")
    sys.exit(2 if hard else (5 if soft else 0))


if __name__ == "__main__":
    main()
