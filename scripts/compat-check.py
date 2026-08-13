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
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import NoReturn

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mineru_common import add_workspace_arg, load_env, postgres_container  # noqa: E402
from pp import eyes  # noqa: E402
from pp.docctx import (  # noqa: E402
    PAGE_SIZE_TOLERANCE_PT,
    cropping_pages_mismatch,
    page_size_spread,
    reference_page_size,
)
from pp.extraction_profile import active_profile, profile_hash, read_record  # noqa: E402
from pp.graph_labels import CERTAIN_RE  # noqa: E402
from pp.oracle import Oracle, OracleError, container_for, force_reparse_is_on  # noqa: E402
from pp.paths import DATA_ROOT_MARKER, DataPaths, configured_data_root  # noqa: E402
from pp.sources import DEFAULT_MAP_PATH, SourceMap, ledger_hashes  # noqa: E402


def _load_script(name: str, path: Path):  # noqa: ANN202
    """載入檔名帶連字號的腳本（`import` 進不去）。**不要複製它們的邏輯過來** ——
    判準只能有一份，抄一份就會漂移。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    if not (spec and spec.loader):
        raise RuntimeError(f"載入不了 {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

REPO = Path(__file__).resolve().parent.parent
DATA_ROOT = configured_data_root()
POSTGRES_USER_DEFAULT = "deeptutor"
MINERU_TOKEN_SOFT_FAIL_DAYS = 14

# 對外發佈、必須**從宿主**打得到的服務：(顯示名, .env 的埠鍵, 預設埠)。
#
# 為什麼要從宿主打：既有的 API 斷言全都走 `docker exec` 進容器再打 localhost
# （見 pp/oracle.py:352-361）。那條路在「容器活著但發佈的埠沒綁、或綁到別的
# 位址」時**照樣全綠**，而 skill、kbapi 的呼叫端、瀏覽器全都是從外面進來的。
# 判準必須是「打得到端點」不是「容器在跑」——原則寫在
# cairn/testing-restart-policy.md:114，這裡是它的執行者。
#
# 審核台沒有埠鍵：INTAKE_PORT 於 2026-08-08 移除（全 repo 零讀取），
# 現在唯一的來源是 intake.py 的 `--port` 預設值。
PUBLISHED_SERVICES: tuple[tuple[str, str | None, int], ...] = (
    ("LightRAG", "HOST_PORT", 9621),
    ("kbapi", "KBAPI_PORT", 9700),
    ("Infinity", "INFINITY_PORT", 7997),
    ("審核台", None, 9710),
)

# 範本記載、但實機的 `.env` 可以省略的鍵 —— 省略時由 compose 或程式用**有記載的
# 預設值**接手。這不是豁免清單，是一條有判準的規則：
#
#   省略會改變行為的鍵      → 兩邊都必須有（漏了就是重建會掉東西）
#   省略等於「用記載的預設」 → 範本負責記載，實機可省
#
# 兩個方向的嚴重程度差很多，所以只放寬這一邊：範本漏寫實機有的鍵（`only_live`）
# 永遠是紅燈，2026-08-08 就是那樣掉了 MAX_TOTAL_TOKENS 與四個 RERANK_*。
ENV_KEYS_OPTIONAL_IN_LIVE: frozenset[str] = frozenset({
    "INTAKE_SOURCES",   # 留空＝不掃描任何來源，intake.py:494 會明確警告而非誤報空
    "INFINITY_PORT",    # compose 寫 ${INFINITY_PORT:-7997}
    # 眼睛 A（轉錄者）2026-08-09 從抽取 LLM 拆出來。不設時 fallback 回
    # LLM_BINDING_*／LLM_MODEL，行為與拆分前逐欄位相同（tests/test_eye_a_split.py），
    # 所以實機的 .env 可以完全沒有這三個鍵。
    "PP_EYE_A_HOST",
    "PP_EYE_A_API_KEY",
    "PP_EYE_A_MODEL",
    "PP_EYE_A_PROVIDER",
    "PP_EYE_A_MAX_OUT",
})

# `.env` 的鍵 → LightRAG `MinerUParserOptions.from_env()` 的欄位。
# 比的是「檔案裡寫的」與「容器實際吃到的」，所以能抓出 compose 漏傳鍵。
MINERU_ENV_TO_OPTION: tuple[tuple[str, str], ...] = (
    ("MINERU_API_MODE", "api_mode"),
    ("MINERU_MODEL_VERSION", "model_version"),
    ("MINERU_LANGUAGE", "language"),
    ("MINERU_ENABLE_TABLE", "enable_table"),
    ("MINERU_ENABLE_FORMULA", "enable_formula"),
    ("MINERU_IS_OCR", "is_ocr"),
)

# 外部推論端點：(顯示名, host 鍵, 金鑰鍵, 備援金鑰鍵)。
# 備援那欄記的是程式裡真的存在的 fallback（pp/eyes.py:87），不是願望——
# 2026-08-08 就是那條 fallback 在 embedding 換成本機之後安靜地失效。
EXTERNAL_EYES: tuple[tuple[str, str, str, str | None], ...] = (
    ("第二雙眼睛", "PP_EYE_B_HOST", "PP_EYE_B_API_KEY", "EMBEDDING_BINDING_API_KEY"),
    ("第三隻眼睛", "PP_EYE_C_HOST", "PP_EYE_C_API_KEY", None),
)


def _env_key_names(path: Path) -> set[str]:
    """抽出一份 env 檔的鍵名。

    ⚠ 樣式必須容許鍵名含數字（`NEO4J_URI` 的 `4`）。用 `^[A-Z_]+=` 會少算，
    2026-08-07 因此把 55 個鍵寫成 51 個並提交出去。
    """
    return {
        line.split("=", 1)[0]
        for line in path.read_text(encoding="utf-8").splitlines()
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", line)
    }


def _http_get(url: str, headers: dict[str, str] | None = None,
              timeout: int = 10) -> tuple[int, bytes]:
    """打一個 GET，回 `(狀態碼, 內容)`。連不上時狀態碼為 0、內容是錯誤字串。

    刻意不丟例外：呼叫端要能區分「回了 401」與「根本連不上」，這兩者的處置
    完全不同（前者是金鑰錯，後者是服務沒起來）。
    """
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except (urllib.error.URLError, OSError) as e:
        return 0, str(e).encode()


def _as_text(value: object) -> str:
    """把 bool／str 正規化成可比較的小寫字串（env 只有字串，選項有 bool）。"""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip().lower()


def _vector_table_suffix(model: str, dim: str) -> str:
    """向量表名的後綴：LightRAG 用「模型名＋維度」命名，非英數一律換成底線。

    ⚠ **要換掉的不只是 `-`。** 舊版只 `replace("-", "_")`，那在模型叫
    `text-embedding-3-large` 的時代剛好可用；2026-08-08 換成 HuggingFace 的
    `BAAI/bge-m3` 之後，斜線沒被換掉 —— 推導出 `baai/bge_m3_1024d`，而實際表名是
    `lightrag_vdb_chunks_baai_bge_m3_1024d`，於是 A-22 報「找不到向量表」。

    那是**假紅燈，而且是 hard**（會擋動工），還被同時期的 psql 錯誤蓋住沒人發現。
    ⇒ 從資料推導名字時，要照著產生它的那一方的規則走，不要只處理眼前看得到的字元。
    """
    return re.sub(r"[^0-9a-z]+", "_", f"{model}_{dim}d".lower())


def _sql_literal(value: str) -> str:
    """將 workspace 安全地寫成 SQL 字串字面值。"""
    return "'" + value.replace("'", "''") + "'"


def postgres_document_count(env: dict[str, str], workspace: str) -> int:
    """從指定的 Postgres 容器讀取目前 workspace 的文件登記數。"""
    container = postgres_container(env)
    sql = ("select count(*) from lightrag_doc_status where workspace = "
           f"{_sql_literal(workspace)};")
    result = subprocess.run(
        ["docker", "exec", container, "psql", "-U",
         env.get("POSTGRES_USER", POSTGRES_USER_DEFAULT), "-d",
         env.get("POSTGRES_DATABASE", "lightrag"), "-tAqX", "-c", sql],
        capture_output=True, text=True, timeout=30, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"psql 失敗（{container}）：{result.stderr.strip()[:300]}")
    value = result.stdout.strip()
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"psql 回傳不是文件數：{value[:120]!r}") from exc

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


def data_root_state() -> tuple[bool, str, dict]:
    """資料根在不在那顆專用磁碟上、能不能寫。**A-34 與 `main()` 的前置檢查共用這一份。**

    資料根 2026-08-09 搬到一顆 **USB 外接**的 1TB SSD。USB 會掉。

    **擋的是「安靜地寫到別的地方」。** `/data/lightrag` 現在是掛載點；沒掛上時它就是
    底層磁碟上的一個空目錄，而 LightRAG 看到空的資料根會**高高興興建一個新的空知識庫，
    不報錯**。這個專案記過三次同一個形狀（備份回報成功、內容是空的），這是第四個入口。

    **三個訊號各擋一種失效**：

      記號檔  —— 掛載點目錄本身是 root:root mode 000，所以「沒掛上」時連讀都讀不到；
                記號檔還能分辨「掛到了另一顆碟」。
      唯讀    —— fstab 帶 `errors=remount-ro`，USB 中途掉線會讓檔案系統轉唯讀。
                **容器仍然在跑**，只有寫入會失敗 —— 沒有這一條的話，症狀會是零星的
                寫入錯誤而不是一句「碟壞了」。
      裝置    —— 印出來給人看，**不當判準**：換碟是合法操作，換了之後只要記號檔還在
                就該通過（不寫死 UUID —— 寫死的那版撐不過第一次換碟）。
    """
    root = Path(DATA_ROOT)
    marker = root / DATA_ROOT_MARKER
    src = subprocess.run(
        ["findmnt", "-n", "-o", "SOURCE,OPTIONS", "--target", str(root)],
        capture_output=True, text=True, timeout=15, check=False).stdout.strip()
    data = {"data_root": str(root), "mount": src}
    if not root.is_dir():
        return False, f"{root} 不存在 —— 硬碟沒掛上", data
    # ⚠ `Path.is_file()` **不會**吞掉 PermissionError（只吞 ENOENT／ENOTDIR 那幾種），
    # 而沒掛上時掛載點正是 root:root mode 000 —— 也就是最常見的那條路會直接丟例外。
    # 裝飾器會把它變成 hard 失敗（結論對），但訊息會變成一句 `PermissionError`，
    # 把「先不要動工」那段話吃掉。2026-08-09 測失效路徑時實際踩到，所以分開接。
    try:
        marker_ok = marker.is_file()
    except PermissionError:
        return False, (
            f"**{root} 讀不到（權限被拒）—— 這就是硬碟沒掛上的樣子。**"
            "掛載點目錄本身是 root:root mode 000，就是為了讓「沒掛上」立刻失敗，"
            "而不是讓 LightRAG 看到一個空資料根、安靜地建一個新的空庫。"
            "**先不要動工。** 掛回去：`sudo mount /data/lightrag`；"
            "碟不見的話查 `dmesg | tail`（USB 外接）。"), {**data, "unmounted": True}
    if not marker_ok:
        return False, (
            f"**記號檔 {DATA_ROOT_MARKER} 不在 {root}**。"
            "資料根不是那顆專用磁碟 —— 可能掛到了別顆，或這是一台還沒建過記號檔的"
            "新機器（新環境要 `touch` 一個，見 rebuild-checklist）。"
            "**先不要動工**，現在寫下去的東西會落在錯的地方。"
            f"　掛載狀態：{src or '（findmnt 問不到）'}"), data
    if os.statvfs(root).f_flag & os.ST_RDONLY:
        return False, (
            f"**{root} 是唯讀的。** fstab 帶 `errors=remount-ro`，所以這代表檔案系統"
            "出過錯而被轉成唯讀 —— USB 外接碟掉線的典型症狀。"
            "查 `dmesg | tail`，處理完重新掛載。"), {**data, "readonly": True}
    free = shutil.disk_usage(root).free
    data["free_bytes"] = free
    return True, f"{src}，可寫，剩 {free / 1024**3:.0f} GiB", data


@dataclass
class Result:
    id: str
    level: str              # hard | soft | info
    what: str
    ok: bool | None = None  # None = 略過
    detail: str = ""
    data: dict = field(default_factory=dict)


class Checker:
    def __init__(self, oracle: Oracle, workspace: str) -> None:
        self.o = oracle
        self.ws = workspace
        self.results: list[Result] = []

    def add(self, r: Result) -> Result:
        self.results.append(r)
        return r

    def check(self, id_: str, level: str, what: str
              ) -> Callable[[Callable[[], tuple[bool, str, dict]]], Result]:
        """裝飾器：把例外變成失敗，而不是讓整支掛掉。"""
        def deco(fn: Callable[[], tuple[bool, str, dict]]) -> Result:
            try:
                ok, detail, data = fn()
            except OracleError as e:
                ok, detail, data = False, f"oracle 失敗：{e}", {}
            except Exception as e:  # noqa: BLE001
                ok, detail, data = False, f"{type(e).__name__}: {e}", {}
            return self.add(Result(id_, level, what, ok, detail, data))
        return deco

    # ---------- 契約層 ----------

    def contract(self) -> None:
        @self.check("A-01", "hard", "探針與 server 執行的是同一份 lightrag")
        def _() -> tuple[bool, str, dict]:
            d = self.o.module_identity()
            hashes = {h for _, h in d["cache_copies"]}
            ok = len(hashes) <= 1
            return ok, (f"{len(d['cache_copies'])} 份副本，"
                        f"{'md5 一致' if ok else 'md5 不一致 —— 探針可能不是實際執行的那份'}"), d

        @self.check("A-02", "hard", "is_bundle_valid 可用且簽章不變")
        def _() -> tuple[bool, str, dict]:
            d = self.o.py(
                "import json,inspect\n"
                "from lightrag.parser.external.mineru.cache import is_bundle_valid as f\n"
                "print(json.dumps(str(inspect.signature(f))))")
            want = "(raw_dir: 'Path', source_file: 'Path', *, overrides:"
            return d.startswith(want), d, {"signature": d}

        @self.check("A-03", "hard", "磁碟佈局常數不變")
        def _() -> tuple[bool, str, dict]:
            c = self.o.constants()
            want = {"RAW_SUFFIX": ".mineru_raw", "PARSED_SUFFIX": ".parsed",
                    "PARSED_DIR_NAME": "__parsed__",
                    "MANIFEST_FILENAME": "_manifest.json", "MANIFEST_VERSION": "1.0"}
            bad = {k: (c.get(k), v) for k, v in want.items() if c.get(k) != v}
            return not bad, (f"lightrag {c['lightrag_version']}"
                             + (f"；不符：{bad}" if bad else "")), c

        @self.check("A-05", "hard", "快取驗證只看 6 項，不看 total_size_bytes")
        def _() -> tuple[bool, str, dict]:
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
        def _() -> tuple[bool, str, dict]:
            fields = self.o.ir_text_fields()
            want = ["text", "content", "body", "code_body"]
            return fields == want, f"{fields}", {"fields": fields}

        @self.check("A-24", "hard", "drawing 的型別集合與 caption 欄位不變（chart→image 的前提）")
        def _() -> tuple[bool, str, dict]:
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
        def _() -> tuple[bool, str, dict]:
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
        def _() -> tuple[bool, str, dict]:
            # 判準與 postprocess.py 的 apply 閘門共用（pp/oracle.py），不在這裡
            # 重寫一份 —— 兩份同義判準只要有人改一邊就會靜靜地不一致。
            v = self.o.force_reparse_flag()
            ok = not force_reparse_is_on(v)
            return ok, (f"值 ={v!r}。開啟時會先 clear_dir_contents(raw_dir) 再重抓，"
                        "修補會在生效前被刪掉且 pipeline 回報成功。"
                        "`postprocess.py apply` 已會據此拒絕執行"
                        if not ok else "未設定"), {"value": v}

        @self.check("A-17", "hard", "host 有 poppler 工具")
        def _() -> tuple[bool, str, dict]:
            missing = [t for t in ("pdftoppm", "pdftotext", "pdfinfo") if not shutil.which(t)]
            return not missing, (f"缺少 {missing}" if missing else "pdftoppm / pdftotext / pdfinfo 都在"), {}

    # ---------- 環境層 ----------

    def environment(self, api_key: str, port: int) -> None:
        @self.check("A-18", "soft", "看圖那隻眼睛的端點可用")
        def _() -> tuple[bool, str, dict]:
            """**檢查眼睛 A 的端點，不是抽取 LLM 的。**

            2026-08-09 之前這兩者是同一個（眼睛 A 直接讀 `LLM_BINDING_*`），
            所以查哪一個都一樣。拆開之後就不一樣了 —— 抽取指向 DeepSeek
            （`judge.py` 實測它不吃 image_url），而看圖的那隻在別的地方。
            繼續查 `LLM_BINDING_HOST` 的話，這條斷言會變成「檢查一個不看圖的
            服務通不通」，綠燈代表不了任何事。
            """
            import urllib.error
            import urllib.request
            env = load_env(REPO)
            eye_a, _ = eyes.eyes_from_env(env)
            host = eye_a.host
            if not host:
                return False, "眼睛 A 沒有 host（PP_EYE_A_HOST 與 LLM_BINDING_HOST 都空）", {}
            # ⚠ **佔位金鑰要當成沒設定。** OpenRouter 的 `/models` 是公開端點，
            #   拿 `TODO-…` 去打照樣回 200 —— 端點通、模型也在清單上，於是這條
            #   斷言會變綠，而真正要用的時候是 401。2026-08-09 實測踩到：
            #   填了佔位就轉綠，那種綠燈比紅燈危險。
            if not eye_a.api_key or eye_a.api_key.startswith(("TODO", "changeme", "貼在")):
                return False, (f"眼睛 A 的金鑰還是佔位值（{host}，{eye_a.model}）"
                               " —— 端點可能打得通，但真的呼叫會 401"), {}
            req = urllib.request.Request(
                f"{host}/models",
                headers={"Authorization": f"Bearer {eye_a.api_key}"} if eye_a.api_key else {})
            try:
                with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310
                    models = json.loads(r.read()).get("data", [])
            except (urllib.error.URLError, OSError) as e:
                return False, f"{host} 連不上：{e}（眼睛 A ＝ {eye_a.model}）", {}
            names = [m.get("id") for m in models]
            # 端點通不等於那個模型在。OpenRouter 會列出幾百個模型，本機 llama.cpp
            # 只列一個 —— 兩邊都要能判斷「我要用的那個在不在」。
            present = eye_a.model in names
            return present, (
                f"{host} 可用，眼睛 A ＝ {eye_a.model}"
                + ("" if present else f"　⚠ 這個模型不在端點的清單裡（{len(names)} 個）")
            ), {"host": host, "model": eye_a.model, "listed": len(names)}

        @self.check("A-19", "hard", "pipeline 目前 idle")
        def _() -> tuple[bool, str, dict]:
            d = self.o.pipeline_idle(api_key, port)
            busy = d.get("busy") or d.get("scanning") or d.get("destructive_busy")
            return (not busy), (f"busy={d.get('busy')} scanning={d.get('scanning')} "
                                f"job={d.get('job_name')!r}"), d

        @self.check("A-25", "soft", "chunk_top_k 仍然控制回傳的片段數（kbapi 的節流靠它）")
        def _() -> tuple[bool, str, dict]:
            """kbapi 的 chunks 參數就是下傳成 chunk_top_k。它一旦失效，
            /kb/*/search 會靜靜地回到每次 55–60KB —— 不會報錯，只是把呼叫端的
            context 灌爆。所以寧可每次都真的打一次查詢來驗。

            順帶記下不要用 max_total_tokens 收：它是先扣圖譜再給原文，設太小
            時 available_chunk_tokens 變負數，chunk 直接回 0 個且不報錯。

            **先問母體再判斷。** 斷言要求 b > a，而沒有已索引文件的 workspace
            兩邊恆為 0 —— 那是「這個母體驗不了」，不是「契約壞了」。判成 FAIL
            的話，v2 這種乾淨新庫從建庫到索引完成的每一天都會亮紅燈，而每天都
            亮的紅燈等於沒有紅燈：真的失效那天沒人會多看一眼。
            這是第一個在空母體上結構性驗不了的斷言。
            """
            try:
                st = self.o.indexed_docs(api_key, port)
            except OracleError as e:
                return None, f"問不到母體（{str(e)[:60]}），驗不了", {}
            n_proc = int(st.get("processed") or 0)
            if n_proc == 0:
                other = {k: v for k, v in st.items() if k != "processed"}
                return None, ("這個 workspace 沒有任何已索引文件"
                              + (f"（其他狀態 {other}）" if other else "（/documents 全空）")
                              + " —— chunk 數恆 0，b > a 結構性不可能成立，"
                                "驗不了；索引完成後這條會自動恢復判斷"), {"statuses": st}
            try:
                got = self.o.chunk_top_k_effect(api_key, port=port)
            except OracleError as e:
                return None, f"查不動（{str(e)[:60]}），驗不了", {}
            a, b = got.get("2", -1), got.get("8", -1)
            # 母體不只要有文件，還要有**夠多的 chunk**。整庫只有 1–2 個 chunk 時，
            # top_k 從 2 調到 8 也只會拿到同樣那幾個 —— b > a 結構性不可能成立。
            # 原本只擋「0 份文件」，於是第一份文件進來（1 個 chunk）就誤報 FAIL，
            # 而審核台把它當成整個流程失敗。與空母體那條是同一個病的小樣本版。
            if a >= 0 and a == b:
                return None, (f"chunk_top_k=2 → {a} 個、=8 → {b} 個：母體只有 {a} 個可命中的 "
                              f"chunk（{n_proc} 份文件），調大 top_k 也拿不到更多，"
                              "b > a 結構性不可能成立 —— 驗不了；母體長大後會自動恢復判斷"), got
            return (a <= 2 and b <= 8 and b > a), \
                   f"chunk_top_k=2 → {a} 個、=8 → {b} 個（母體 {n_proc} 份已索引）", got

        @self.check("A-26", "hard", "Postgres 與 LightRAG API 的文件母體一致")
        def _() -> tuple[bool, str, dict]:
            """用兩個獨立來源抓到探針連錯資料庫的情況。

            API 由目前的 LightRAG 容器回報文件狀態；SQL 則透過設定指定的
            Postgres 容器查目前 workspace 的文件登記。兩者不一致時，不能把
            向量索引或文件層結果當成同一套資料的證據。
            """
            try:
                statuses = self.o.indexed_docs(api_key, port)
            except OracleError as e:
                return None, f"問不到 LightRAG 文件母體（{str(e)[:60]}），驗不了", {}
            api_count = sum(int(value or 0) for value in statuses.values())
            env = load_env(REPO)
            sql_count = postgres_document_count(env, self.ws)
            data = {"api_documents": api_count, "postgres_documents": sql_count,
                    "postgres_container": postgres_container(env),
                    "workspace": self.ws}
            if api_count == 0 and sql_count == 0:
                return None, ("LightRAG API 與 Postgres 都是 0 份文件；沒有可供交叉比對的"
                              "母體，驗不了"), data
            return (api_count == sql_count), (
                f"API {api_count} 份、Postgres {sql_count} 份（workspace={self.ws!r}，"
                f"容器={postgres_container(env)}）"
                if api_count == sql_count else
                f"API {api_count} 份、Postgres {sql_count} 份不一致 —— 可能連到不同資料庫"
            ), data

        @self.check("A-22", "hard", "每張向量表都有向量索引")
        def _() -> tuple[bool, str, dict]:
            env = load_env(REPO)
            suffix = _vector_table_suffix(env.get("EMBEDDING_MODEL", ""),
                                          env.get("EMBEDDING_DIM", ""))
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
                ["docker", "exec", postgres_container(env), "psql", "-U",
                 env.get("POSTGRES_USER", POSTGRES_USER_DEFAULT), "-d",
                 env.get("POSTGRES_DATABASE", "lightrag"), "-tAF|", "-c", sql],
                capture_output=True, text=True, timeout=30, check=False)
            if p.returncode != 0:
                return False, f"psql 失敗：{p.stderr.strip()[:300]}", {}
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
        def _() -> tuple[bool, str, dict]:
            """模型換代時，綁模型的觀察會靜默失效 —— 規則還在，前提沒了。

            實測記錄的「eye_b 會看錯字元、eye_a 會切錯結構」這類觀察，換一個
            模型就可能完全相反。這條斷言不判斷觀察對不對，只確認**它是對現在
            這組模型量的**。不一致就 FAIL，逼人重新量測。

            ⚠ **eye_a 要從 `eyes_from_env` 拿，不要直接讀 `LLM_MODEL`。**
            2026-08-09 之前兩者是同一個，讀哪個都對；拆開之後 `LLM_MODEL` 是
            抽取用的（DeepSeek，不看圖），而觀察記的是**看圖那隻**的行為。
            繼續讀 `LLM_MODEL` 的話，這條會拿抽取模型去比對看圖的觀察 ——
            比錯對象，而紅綠燈看起來都很正常。
            """
            f = REPO / "tests" / "model-observations.json"
            if not f.is_file():
                return False, f"缺少 {f.name}", {}
            rec = json.loads(f.read_text())
            want_a, want_b = rec.get("eye_a"), rec.get("eye_b")
            env = load_env(REPO)
            eye_a, eye_b = eyes.eyes_from_env(env)
            got_a, got_b = eye_a.model, eye_b.model
            ok = (want_a == got_a) and (want_b == got_b)
            msg = (f"量測於 {rec.get('measured_on')}：{want_a} + {want_b}"
                   if ok else
                   f"觀察量測於 {want_a} + {want_b}，但現行是 {got_a} + {got_b} —— "
                   f"綁模型的觀察已失效，重新量測後更新 {f.name}")
            return ok, msg, {}

        @self.check(
            "A-21", "soft",
            f"MinerU token 到期日（低於 {MINERU_TOKEN_SOFT_FAIL_DAYS} 天升級警報）",
        )
        def _() -> tuple[bool, str, dict]:
            import base64
            import time
            env = load_env(REPO)
            tok = env.get("MINERU_API_TOKEN", "")
            if not tok or tok.count(".") != 2:
                return False, "找不到或格式不對", {}
            pl = tok.split(".")[1]
            pl += "=" * (-len(pl) % 4)
            exp = json.loads(base64.urlsafe_b64decode(pl))["exp"]
            days = (exp - time.time()) / 86400
            ok = days >= MINERU_TOKEN_SOFT_FAIL_DAYS
            return ok, (f"{time.strftime('%Y-%m-%d', time.localtime(exp))}，剩 {days:.0f} 天"
                        + ("" if ok else " —— 整批解析要 6–10 小時，中途過期會讓後半批全滅")), {
                            "days": days,
                            "soft_fail_below_days": MINERU_TOKEN_SOFT_FAIL_DAYS,
                            "expires_at": exp,
                        }

        @self.check("A-27", "hard", "對外發佈的埠從宿主打得到（不是「容器在跑」）")
        def _() -> tuple[bool, str, dict]:
            env = load_env(REPO)
            addr = env.get("BIND_ADDR", "")
            if not addr:
                return False, "找不到 BIND_ADDR —— 無法判斷服務發佈到哪個位址", {}
            seen: dict[str, int] = {}
            for name, port_key, default_port in PUBLISHED_SERVICES:
                port = int(env.get(port_key, default_port)) if port_key else default_port
                code, _body = _http_get(f"http://{addr}:{port}/health", timeout=5)
                seen[f"{name}:{port}"] = code
            bad = {k: v for k, v in seen.items() if v != 200}
            return not bad, (f"{addr} 上四個服務的 /health 全回 200" if not bad else
                             f"打不到：{bad}（0 = 連不上，其餘是實際狀態碼）"), seen

        @self.check("A-28", "hard", "Infinity 載著 .env 指名的那兩個模型")
        def _() -> tuple[bool, str, dict]:
            env = load_env(REPO)
            addr = env.get("BIND_ADDR", "")
            port = int(env.get("INFINITY_PORT", 7997))
            want = [m for m in (env.get("EMBEDDING_MODEL", ""),
                                env.get("RERANK_MODEL", "")) if m]
            if not addr or not want:
                return False, "缺 BIND_ADDR 或 EMBEDDING_MODEL／RERANK_MODEL", {}
            code, body = _http_get(f"http://{addr}:{port}/models", timeout=10)
            if code != 200:
                return False, f"/models 回 {code}（0 = 連不上）", {"status": code}
            loaded = [m.get("id") for m in json.loads(body).get("data", [])]
            missing = [m for m in want if m not in loaded]
            # 「服務活著」與「載對模型」是兩件事：模型換錯了不會報錯，只會讓
            # 向量表對不上、查詢安靜地退化。
            return not missing, ("載著 " + ", ".join(want) if not missing else
                                 f"缺 {missing}，實際載著 {loaded}"), {"loaded": loaded}

        @self.check("A-29", "soft", "外部推論端點的金鑰現在有效")
        def _() -> tuple[bool, str, dict]:
            env = load_env(REPO)
            out: dict[str, int] = {}
            for name, host_key, key_key, fallback_key in EXTERNAL_EYES:
                host = env.get(host_key, "")
                key = env.get(key_key, "") or (env.get(fallback_key, "") if fallback_key else "")
                if not host or not key:
                    out[name] = -1        # -1 = 沒設定，跟「打不到」要分得開
                    continue
                code, _body = _http_get(f"{host}/models",
                                        {"Authorization": f"Bearer {key}"}, timeout=10)
                out[name] = code
            bad = {k: v for k, v in out.items() if v != 200}
            # 為什麼要真的打一次：2026-08-08 第二雙眼睛的 fallback 沿用
            # EMBEDDING_BINDING_API_KEY，embedding 換成本機後那把不再是 OpenAI
            # 金鑰 —— 設定看起來完好、401 要到下次進料才浮出來。
            return not bad, ("兩個端點都回 200" if not bad else
                             f"不正常：{bad}（-1 沒設定／0 連不上／401 金鑰無效）"), out

        @self.check("A-30", "hard", "`.env` 與 `.env.example` 的鍵名一致")
        def _() -> tuple[bool, str, dict]:
            actual = REPO / ".env"
            example = REPO / ".env.example"
            if not actual.exists():
                return False, f"找不到 {actual}", {}
            live, doc = _env_key_names(actual), _env_key_names(example)
            only_live = sorted(live - doc)
            only_doc = sorted(doc - live - ENV_KEYS_OPTIONAL_IN_LIVE)
            ok = not only_live and not only_doc
            # only_live 是最貴的那一邊：範本沒寫的鍵，重建時就會消失。
            # 2026-08-08 這樣掉過 MAX_TOTAL_TOKENS（查詢會謊報「找不到」）
            # 與四個 RERANK_*。
            return ok, ("只剩記載了預設值、實機可省的 "
                        f"{sorted(ENV_KEYS_OPTIONAL_IN_LIVE)}" if ok else
                        f"範本漏寫（重建會掉）：{only_live}／"
                        f"範本寫了但實際沒有且沒記載預設：{only_doc}"), {
                            "only_in_env": only_live, "only_in_example": only_doc}

        @self.check("A-31", "hard", "容器實際吃到的 MinerU 選項與 `.env` 相符")
        def _() -> tuple[bool, str, dict]:
            env = load_env(REPO)
            # 不傳 env 給 oracle：要讀的正是**容器自己的環境**，那才是 LightRAG
            # 真的看到的值。傳進去就變成自己跟自己比，抓不到 compose 漏傳鍵。
            got = self.o.mineru_options()
            diff = {
                env_key: {"env 檔": env.get(env_key, "<沒有>"), "容器": got.get(field_)}
                for env_key, field_ in MINERU_ENV_TO_OPTION
                if _as_text(env.get(env_key, "")) != _as_text(got.get(field_))
            }
            return not diff, ("六項全部相符" if not diff else
                              f"不符：{diff}"), {"options": got}

        @self.check("A-32", "soft", "圖譜是用現行的抽取規則建的")
        def _() -> tuple[bool | None, str, dict]:
            """改了抽取規則而沒有重抽 —— 要有人知道。

            **為什麼是 soft**：規則比圖譜新不是壞掉，是「新舊文件會用不同規則」。
            擋下部署沒有意義（規則本來就會演進），但沉默更糟：新進的文件用新規則、
            舊的用舊規則，圖譜混著兩代而**沒有任何訊號**。

            **為什麼要在這裡**：判準本來只有 CLI（`extraction-profile.py check`），
            等級是「只在有人主動跑時才響」。接進這裡才會流進每日檢查、顯示在
            審核台 —— 那是本專案唯一的警報管道。

            判準與 CLI 共用 `pp/extraction_profile`，不各算一次。

            **空庫要三態，不能報紅。** 2026-08-09 清庫重建時抓到：圖譜已經是 0 份，
            這條還在拿一份留下來的舊紀錄比對，喊「圖譜是舊規則抽的」—— 而那個圖譜
            已經不存在了。**沒有母體時「規則一不一致」問不出答案**，跟 A-25／A-26
            同一個形狀：把「驗不了」講成「壞了」，會讓整個重建期間都亮著紅燈，
            而永遠紅的警報等於沒有警報。
            """
            paths = DataPaths(configured_data_root())
            record = read_record(paths)
            if postgres_document_count(load_env(REPO), self.ws) == 0:
                return None, (f"workspace={self.ws!r} 目前 0 份文件；沒有圖譜可以比對，"
                              "驗不了。進料完成後跑 `extraction-profile.py stamp`"), {
                    "documents": 0, "workspace": self.ws,
                    "stale_record": None if record is None else record.get("profile_hash")}
            if record is None:
                return False, ("沒有紀錄 —— 無從得知圖譜是用哪版規則抽的。"
                               "重抽完成後跑 `extraction-profile.py stamp`"), {}
            now = profile_hash(active_profile(self.o))
            was = str(record.get("profile_hash"))
            covered = len(record.get("documents", []))
            if now == was:
                return True, f"一致 {now}（{covered} 份文件）", {"hash": now}
            return False, (
                f"**抽取規則已變，圖譜還是舊規則抽的**："
                f"圖譜建立時 {was}（{record.get('stamped_at')}，{covered} 份）／"
                f"現在生效 {now}。要嘛重抽讓兩者一致，要嘛把規則改回去 —— "
                f"不重抽的話，之後新進的文件會用不同規則而沒有訊號"
            ), {"graph_hash": was, "active_hash": now, "documents": covered}

        @self.check("A-33", "soft", "圖譜裡沒有確定該刪的位置標記節點")
        def _() -> tuple[bool, str, dict]:
            """`equation 22`、`table i`、`reference 1` 這種節點還在圖譜裡 —— 要有人知道。

            **為什麼不能只靠提示詞**：規則 2a 寫在抽取提示詞裡，2026-08-08、08-09
            實測三次都沒守住，而且**守不住的程度隨後端而變**（受控比對：同樣的規則與
            解析成果，llama.cpp 與 vLLM 抽出來的人名機構是 35 對 49）。提示詞是請求，
            不是保證 —— 換模型、換量化、換溫度都會改變它的遵守度。

            **所以這是耐久規則，不綁模型**：位置標記長什麼樣子是文件的性質，本機
            llama.cpp 或雲端 vLLM 抽的都一樣要清、一樣要響。判準放在
            `pp/graph_labels.py`，`graph-shape.py`（量）與 `graph-clean.py`（刪）
            共用同一份，不各算一次。

            **為什麼是 soft**：殘留不表示系統壞了，表示「該跑清除了」。擋下部署沒有
            意義，但沉默的話這些節點會一直佔著檢索預算 —— 而只有人主動跑
            `graph-shape.py` 才看得到，那不算探針（鐵則第 6 條）。

            **只數 certain 那一組。** suspect（`region II`／`zone IV`／`mode ii`）
            由 PO 2026-08-09 裁決先不動，把它算進來會讓這條斷言永遠是紅的，
            而永遠紅的警報等於沒有警報。
            """
            env = load_env(REPO)
            # 用圖節點表而不是向量表：`graph-clean.py` 動的是圖譜，警報要跟它同源。
            # （2026-08-09 實測兩張表的命中數相同，都是 66。）
            sql = ("select count(*) from lightrag_graph_nodes where workspace = "
                   f"{_sql_literal(self.ws)} and id ~* {_sql_literal(CERTAIN_RE)};")
            p = subprocess.run(
                ["docker", "exec", postgres_container(env), "psql", "-U",
                 env.get("POSTGRES_USER", POSTGRES_USER_DEFAULT), "-d",
                 env.get("POSTGRES_DATABASE", "lightrag"), "-tAF|", "-c", sql],
                capture_output=True, text=True, timeout=30, check=False)
            if p.returncode != 0:
                return False, f"psql 失敗：{p.stderr.strip()[:300]}", {}
            out = p.stdout.strip()
            if not out.isdigit():
                return False, f"psql 回傳看不懂：{out[:120]!r}", {}
            n = int(out)
            if n == 0:
                return True, f"0 個（workspace={self.ws!r}）", {"certain": 0}
            return False, (
                f"**{n} 個位置標記節點還在圖譜裡**（workspace={self.ws!r}）。"
                f"它們佔著檢索預算又回答不了任何問題。"
                f"跑 `graph-clean.py plan` 看清單、`graph-clean.py apply` 清掉"
            ), {"certain": n, "workspace": self.ws}

        @self.check("A-34", "hard", "資料根掛在專用磁碟上，而且可寫")
        def _() -> tuple[bool, str, dict]:
            """判準在模組層的 `data_root_state()` —— `main()` 在連容器**之前**
            也要跑同一份（見那裡的說明）。兩邊叫同一個函式，不各寫一份。"""
            return data_root_state()

        @self.check("A-37", "soft", "Tier A 的等價類都審計過（骨架相同不等於同一條）")
        def _() -> tuple[bool, str, dict]:
            r"""**沒審過的組會安靜地從報告裡消失。**

            2026-08-13 抓到：`#=\frac{#}{#}`（X 等於 Y 除以 Z）這種骨架不帶資訊，
            兩條無關的公式會被判成同一條。三隻不同家族的模型全票確認，
            人工複核確認模型是對的。於是 `eq-dup` 改成只採信審計過的組
            —— 而**沒審過的一律排除**（少報不假報）。

            方向是安全的，問題在於**沒有人會被告知**：語料一長出新的等價類，
            Tier A 就會安靜縮水，而縮多少只有主動跑 `eq-dup` 才看得到。
            跟 A-35 同一個形狀、同一個理由用 soft：不表示系統壞了，
            表示「該補審計了」。

            補的方式：`python3 scripts/eq-label.py audit --out <檔>`，
            再把結果併進 `verdicts/eq-tier-a-audit.json`。
            """
            root = configured_data_root()
            parsed = DataPaths(root).parsed_dir
            if not parsed.is_dir():
                return False, f"找不到解析成果目錄 {parsed}", {}
            eq_dup = _load_script("eq_dup", REPO / "scripts" / "eq-dup.py")
            smap = SourceMap.load(DEFAULT_MAP_PATH)
            corpus = sorted(p.name.removesuffix(".pdf.mineru_raw")
                            for p in parsed.glob("*.mineru_raw"))
            smap.reconcile(corpus, ledger_hashes(root))
            eqs, _skipped = eq_dup.collect(parsed, smap)
            groups = eq_dup.tier_a(eqs)
            _kept, tally = eq_dup.audited(
                groups, eq_dup.load_audit(REPO / "verdicts" / "eq-tier-a-audit.json"))
            if not tally["unaudited"]:
                return True, (f"{len(groups)} 組都審過（同一條 {tally['same']}、"
                              f"不是 {tally['different']}、模型分歧 {tally['uncertain']}）"), tally
            return False, (
                f"**{tally['unaudited']}/{len(groups)} 組沒審過，現在不計入報告**。"
                f"跑 `eq-label.py audit` 補上"), tally

        @self.check("A-36", "hard", "釘住的供應商還在該模型的端點清單裡")
        def _() -> tuple[bool, str, dict]:
            """**A-29 驗的是金鑰有效，不是「程式實際會走的那條路打得到」。**

            2026-08-13 實測抓到：`PP_EYE_A_PROVIDER=alibaba/fp8` 在 OpenRouter 上
            **已經沒有端點了**（量化後綴被拿掉，現在叫 `alibaba`），於是
            `vlm.transcribe()` 送出的 `provider.order` 直接 404。而同一時間：

            ```
            裸呼叫（不釘供應商）      OK
            只要 JSON 格式            OK
            只釘供應商                HTTP 404 No endpoints found
            ```

            ⇒ 模型好的、金鑰好的、A-29 是綠的，**而實際那條路是死的**。
            供應商清單是外部的、會變，而釘住它正是交叉驗證的前提
            （不釘就分不清差異是模型讀錯還是換了後端，見 `eyes.Eye.provider`）。
            **釘住一個會消失的東西，就必須有人守著它還在不在。**

            ⚠ hard 不是 soft：這條紅的時候，兩雙眼睛只剩一雙，而多數決在
            兩票之間**沒有多數**——交叉驗證會安靜地退化成單一模型的說法。
            """
            env = load_env(REPO)
            pinned = [e for e in [*eyes.eyes_from_env(env), eyes.eye_c_from_env(env)]
                      if e is not None and e.provider and "openrouter" in e.host]
            if not pinned:
                return True, "沒有任何眼睛釘供應商（OpenRouter 之外不適用）", {}
            out: dict[str, str] = {}
            for eye in pinned:
                code, body = _http_get(
                    f"{eye.host.rstrip('/')}/models/{eye.model}/endpoints",
                    {"Authorization": f"Bearer {eye.api_key}"}, timeout=20)
                if code != 200:
                    out[eye.name] = f"問不到端點清單（HTTP {code}）"
                    continue
                tags = [str(x.get("tag") or x.get("provider_name") or "")
                        for x in ((json.loads(body).get("data") or {}).get("endpoints") or [])]
                out[eye.name] = ("ok" if eye.provider in tags else
                                 f"釘的 {eye.provider!r} 不在清單，現有：{tags}")
            bad = {k: v for k, v in out.items() if v != "ok"}
            return not bad, ("全部釘得到" if not bad else
                             f"**{len(bad)} 隻眼睛釘不到供應商** —— {bad}。"
                             f"改對應的 `PP_EYE_*_PROVIDER`"), out

        @self.check("A-35", "soft", "每份解析成果都登記了來源，而且檔案沒被換過")
        def _() -> tuple[bool, str, dict]:
            """**沒登記的文件會安靜地從公式交叉比對裡消失。**

            `eq-dup.py` 判斷「這條公式有沒有第二個獨立來源這樣寫」，而來源查表查不到
            的整份不進比對（`pp/sources.py`：少報不假報）。方向是安全的，
            **問題在於沒有人會被告知**：報告表頭那行寫得出數字，但要有人去看。
            2026-08-13 上線時 259 份全部登記，**下一批進來的預設會是 unknown** ——
            那正是這條斷言存在的理由。

            ⚠ **為什麼是 soft**：沒登記不表示系統壞了，表示「該補登記了」。
            擋下部署沒有意義（跟 A-33 同一個理由），但沉默的話比對母體會一直縮，
            而縮掉多少只有主動跑 `eq-dup` 才看得到 —— 那不算探針（鐵則第 6 條）。

            ⚠ 雜湊**不在這裡算**，讀體檢表的 `pdf_sha256`。有權威來源時不得自己重算。
            """
            root = configured_data_root()
            parsed = DataPaths(root).parsed_dir
            if not parsed.is_dir():
                return False, f"找不到解析成果目錄 {parsed}", {}
            corpus = sorted(p.name.removesuffix(".pdf.mineru_raw")
                            for p in parsed.glob("*.mineru_raw"))
            smap = SourceMap.load(DEFAULT_MAP_PATH)
            rec = smap.reconcile(corpus, ledger_hashes(root))
            facts = {"corpus": rec.corpus, "usable": rec.usable,
                     "unregistered": len(rec.unregistered),
                     "hash_changed": len(rec.hash_changed),
                     "no_ledger": len(rec.no_ledger), "stale": len(rec.stale)}
            if rec.usable == rec.corpus:
                return True, f"{rec.corpus} 份全部登記且雜湊對得上", facts
            bad = rec.unregistered + rec.hash_changed + rec.no_ledger
            return False, (
                f"**{len(bad)}/{rec.corpus} 份不計入跨來源比對** —— "
                f"未登記 {len(rec.unregistered)}、檔案換過 {len(rec.hash_changed)}、"
                f"體檢表沒有 {len(rec.no_ledger)}。它們的公式在 `eq-dup` 裡看不見。"
                f"先跑 `source-map.py check` 看清單，補進 `verdicts/source-map.json`"
                f"（判定怎麼下看 `docs/source-review-20260813.md`）"
            ), facts

    # ---------- 資料層（逐文件）----------

    def document(self, raw_dir: Path) -> None:
        name = raw_dir.name.removesuffix(".mineru_raw")

        @self.check("A-10", "hard", f"{name}：content_list.json 只在 critical_file")
        def _() -> tuple[bool, str, dict]:
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
        def _() -> tuple[bool, str, dict]:
            m = json.loads((raw_dir / "_manifest.json").read_text())
            cur = self.o.options_signature()
            ok = m.get("options_signature") == cur
            return ok, ("相符" if ok else
                        f"不符 —— 這份 bundle 是用不同解析選項產生的，"
                        f"重新索引時會被丟棄並重解（manifest {m.get('options_signature','')[7:19]}… "
                        f"vs 現行 {cur[7:19]}…）"), {}

        @self.check("A-13", "hard", f"{name}：來源 PDF 可用內容定址找到")
        def _() -> tuple[bool, str, dict]:
            m = json.loads((raw_dir / "_manifest.json").read_text())
            want = m["source_content_hash"]
            source_dir = DataPaths(DATA_ROOT).inputs_dir(self.ws)
            cands = [source_dir / name, raw_dir.parent / name,
                     *raw_dir.glob("*_origin.pdf")]
            for c in cands:
                if c.exists() and c.is_file():
                    h = "sha256:" + hashlib.sha256(c.read_bytes()).hexdigest()
                    if h == want:
                        return True, f"命中 {c.name}", {"path": str(c)}
            return False, (f"{len(cands)} 個候選都對不上 source_content_hash —— "
                           "不得寫死路徑，來源 PDF 會被 archive_source 搬走"), {}

        @self.check("A-14", "hard", f"{name}：layout.json 頁序未位移")
        def _() -> tuple[bool, str, dict]:
            lay = json.loads((raw_dir / "layout.json").read_text())
            pi = lay["pdf_info"]
            bad = [k for k, p in enumerate(pi) if p.get("page_idx") != k]
            # 尺寸判準從 pp/docctx.py import，**不在這裡再寫一份**。兩處同義判準
            # 只要有人改一邊就會靜靜地不一致——那會變成「檢查說可以、解析卻被擋下」。
            sizes = [(float(w), float(h))
                     for w, h in (tuple(p.get("page_size") or ()) for p in pi)
                     if len((w, h)) == 2]
            # 判準與解析時同一份 —— 只改一邊的話，同一份文件會「解析放行、
            # 檢查說不行」，而且是索引完了才被判失敗。2026-08-09 實測踩到：
            # 3 份封面頁不同的文件走到這裡才 hard FAIL。
            #
            # 2026-08-10：判準從「整份一致」改成「**要裁的那幾頁與基準相容**」，
            # 所以這裡也要讀 content_list —— 尺寸本身不再是充分條件。
            items = json.loads((raw_dir / "content_list.json").read_text())
            reference = reference_page_size(sizes) if sizes else (0.0, 0.0)
            bad_pages = cropping_pages_mismatch(sizes, items, reference) if sizes else []
            size_ok = bool(sizes) and not bad_pages
            ok = not bad and size_ok
            dw, dh = page_size_spread(sizes)
            return ok, (f"{len(pi)} 頁，page_size {sorted(set(sizes))}"
                        f"（寬差 {dw:g}、高差 {dh:g} 點，容差 {PAGE_SIZE_TOLERANCE_PT:g}）"
                        if ok else
                        f"錯位頁 {bad[:5]}"
                        + ("" if size_ok else
                           "／有表格落在與基準尺寸 "
                           f"{reference} 不相容的頁上："
                           + "、".join(f"第 {p} 頁 {sizes[p]}" for p in bad_pages[:5])
                           + f"（容差 {PAGE_SIZE_TOLERANCE_PT:g} 點）")
                        + " —— 書眉每頁幾何相同，錯頁比對照樣會 IoU 命中"), {}

        @self.check("A-16", "hard", f"{name}：沒有未知的項目型別")
        def _() -> tuple[bool, str, dict]:
            items = json.loads((raw_dir / "content_list.json").read_text())
            types = {i.get("type") for i in items}
            unknown = types - KNOWN_TYPES
            return not unknown, (f"型別 {sorted(types)}"
                                 + (f"；未知 {sorted(unknown)}" if unknown else "")), {}

        @self.check("A-20", "info", f"{name}：目前的量測基準")
        def _() -> tuple[bool, str, dict]:
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


def main() -> NoReturn:
    env = load_env(REPO)
    ap = argparse.ArgumentParser(description="驗證 postprocess 依賴的假設")
    add_workspace_arg(ap, env)
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

    # **資料根要在連容器之前驗。** 硬碟不見時容器也會連不上（守衛會停掉它們，
    # 或它們自己因為 I/O 錯誤倒下），於是原本會在這裡印一句「容器連不上」就結束
    # —— 那是症狀不是原因，而真正的原因（碟不在）永遠印不出來，因為 A-34 排在
    # 後面根本跑不到。2026-08-09 測失效路徑時實際發生。
    root_ok, root_detail, _ = data_root_state()
    if not root_ok:
        print(f"compat-check: 資料根有問題，先不要動工\n  {root_detail}", file=sys.stderr)
        sys.exit(2)

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
        pdir = DataPaths(DATA_ROOT).parsed_dir
        hits = [d for d in pdir.glob("*.mineru_raw")
                if not a.doc or a.doc.lower() in d.name.lower()]
        if not hits:
            print(f"compat-check: {pdir} 底下找不到"
                  + (f"符合 {a.doc!r} 的 bundle" if a.doc else "任何 bundle")
                  + " —— 文件層驗不了（母體為 0，不是失敗）", file=sys.stderr)
        for raw in sorted(hits):
            c.document(raw)
        n_docs = len(hits)

    # 20 份 × 6 支探針 = 120 行，全印會把契約層的結果洗掉。所以資料層預設
    # 只印失敗的；指定了 --doc 就是在看那一份，全部印出來。
    collapse = n_docs > 1 and not a.doc

    if a.json:
        print(json.dumps([r.__dict__ for r in c.results], ensure_ascii=False, indent=1))
    else:
        # ok=None 是三態的第三態「驗不了」，不是「跳過」—— 兩者的差別在於
        # 驗不了會留下原因，而且**永遠要印出來**（收合只藏 ok）。
        mark = {True: "  ok  ", False: " FAIL ", None: "驗不了"}
        print(f"{'ID':<7} {'層級':<6} {'結果':^6}  說明")
        print("-" * 100)
        # 20 份 × 6 支探針 = 120 行，全印會把契約層的結果洗掉。所以資料層
        # 預設只印失敗的；指定了 --doc 就是在看那一份，全部印出來。
        for i, r in enumerate(c.results):
            if collapse and i >= doc_from and r.ok is True:
                continue
            print(f"{r.id:<7} {r.level:<6} {mark[r.ok]}  {r.what}")
            if r.detail:
                print(f"{'':<21}  └ {r.detail}")

    hard = [r for r in c.results if r.level == "hard" and r.ok is False]
    soft = [r for r in c.results if r.level == "soft" and r.ok is False]
    # 「驗不了」自成一類，不計入 hard/soft 失敗，也不併進 ok。併進 ok 會讓
    # 「驗過了」與「沒得驗」在畫面上長得一樣 —— 那正是三態要防的事。
    unver = [r for r in c.results if r.ok is None]
    if not a.json:
        print("-" * 100)
        # 收合的那些必須報出數量，否則「沒印出來」跟「沒檢查」在畫面上一樣，
        # 而這整段修改就是為了修掉那種一樣。
        hidden = sum(1 for i, r in enumerate(c.results)
                     if collapse and i >= doc_from and r.ok is True)
        print(f"hard 失敗 {len(hard)}　soft 失敗 {len(soft)}　"
              f"驗不了 {len(unver)}{'（' + '、'.join(r.id for r in unver) + '）' if unver else ''}　"
              f"共 {len(c.results)} 項"
              + (f"（{n_docs} 份文件的資料層檢查，{hidden} 項通過未列出）" if hidden else ""))
    sys.exit(2 if hard else (5 if soft else 0))


if __name__ == "__main__":
    main()
