# postprocess.py 實作工單 v1

**適用**：LightRAG 1.5.5（image digest `sha256:206579ab…`）／容器 `lightrag-acoustics_v155`／設定 repo `/home/florian/ghq/github.com/neknufelet/lightrag-v1`／資料 `/data/rag/lightrag/acoustics_v155`

本工單綜合三份設計與三份對抗式審查。**審查提出的每一條缺陷在附錄 A 有對應處置**（採納 / 降級 / 明確接受風險）。

工單開頭先講一件事，因為它推翻了原本的任務描述：

> **改 `content_list.json` 本身不會讓 RAG 的檢索結果變一個字。**
> `ExternalParserBase.parse()` 是 `is_bundle_valid → (miss 才 download) → build_ir → write_sidecar → persist → archive_source` 一次走完；已索引的文件在 `/scan` 時走 `_ScanFileClass.PROCESSED → _archive("Skipping already processed file")`，連 `parse()` 都不會進。「MinerU 解析完、LightRAG 建 IR 前」這個時間窗**在程式上不存在**。
> 所以本工具的產出是「一份修好的快取 + 一次受控的重新索引」，不是「一次插隊」。重新索引是本工單的一級工作項（W9），不是附註。

---

## 1. 目標與範圍

### 1.1 要做的

在容器外、**不修改 LightRAG 任何程式碼**的前提下，對 `.mineru_raw/` bundle 做三件事，並讓修補真正進到索引：

| # | 事項 | 範圍 |
|---|---|---|
| F | **過濾**：讓 `header` / `footer` 項目不進 IR | 用「消音」（`text = ""`），不刪除項目 |
| R | **修補**：把缺 `table_body` 的表格用「裁圖 → 本機 VLM → HTML+LaTeX」補回 | 只修 `MISSING_KEY` 與 `EMPTY_SHELL` |
| L | **記錄**：所有改動、證據、原檔可查帳可還原 | 全部落在 `/data/rag/lightrag/acoustics_v155/records/`（restic 範圍內） |
| X | **重新索引**：讓上述修補生效 | `delete_document(delete_file=False)` → 放回 PDF → `/scan` → 驗 cache hit |

規模目標：390 份文件可分批執行、單份失敗隔離、可續跑、可全部還原。

### 1.2 明確不做的

| 不做 | 理由 |
|---|---|
| 不改 LightRAG 原始碼、不掛 patch、不 mount 覆蓋 | 升級即失效，且失效靜默 |
| 不重新實作 `is_bundle_valid` / `options_signature` | 重實作 = 第二套會漂移的真理。一律 `docker exec` 問 LightRAG 本人 |
| 不刪除 content_list 的任何項目 | 實測 `tables.json` 的 `self_ref` 是 `content_list.json#/6` 這種**陣列索引**；刪一個項目就讓其後所有 sidecar 引用指向別的東西，且不會報錯 |
| **不修**「`table_body` 存在且含 `<img>`」的表（本文件 28 張） | 實測這 28 張大多是**正常的表**，`<img>` 是電路符號圖（idx 7 caption `Table 2 & 3 Passive electrical and mechanical circuit components`，數學是正確的 inline LaTeX `$R = \frac{\Delta U}{I}$`）。覆寫它們＝製造工單失效模式 (a) 的鏡像 |
| 不做字串比對式過濾 | 實測「刪掉含 `Equivalent Networks` 的項目」會殺掉 idx 0（`text_level:1`，文件標題）與 idx 3（`C.1 Fundamentals of Equivalent Networks`） |
| 不碰 `page_number`（LightRAG 自己跳過）、不碰 `page_footnote`（真內容） | 動它們只製造無謂 diff／直接刪掉真內容 |
| 不做「自動修正未標記雜訊」 | 只偵測、只回報。自動化這裡等於引入字串比對 |
| 不用 `LIGHTRAG_FORCE_REPARSE_MINERU` 讓修補生效 | 它會先 `clear_dir_contents(raw_dir)` 再重抓，**修補在生效前就被刪掉**，而 pipeline 回報成功 |

---

## 2. 前置假設（本節 = `compat-check.py` 的規格）

每條都有 ID、斷言、驗證方式、失敗處置。`compat-check.py` 逐條執行、輸出 JSON、任一 `hard` 失敗即 exit 2。它是升級哨兵，排 cron 每日跑。

### 2.1 契約層（hard，失敗 → 中止整批）

| ID | 斷言 | 怎麼驗 | 已測值 |
|---|---|---|---|
| **A-01** | oracle 探到的 lightrag 就是 server 在跑的那份 | `docker exec … python -c "import lightrag; print(lightrag.__file__)"`；同時 md5 比對容器內全部 4 份 `cache.py`/`ir_builder.py`（`/app/lightrag`、`/app/.venv/lib/python3.12/site-packages/lightrag`、`/app/build/lib/lightrag`、`/root/.cache/uv/archive-v0/*/lightrag`）；讀 `/proc/1/cmdline` 與 `/proc/1/environ` 的 `PYTHONPATH` | 目前 4 份 md5 相同 |
| **A-02** | `lightrag.parser.external.mineru.cache.is_bundle_valid` 可 import、簽章為 `(raw_dir, source_file, overrides=…)` | `inspect.signature` | ✓ |
| **A-03** | 常數不變：`RAW_SUFFIX=.mineru_raw`、`PARSED_SUFFIX=.parsed`、`CONTENT_LIST_FILENAME=content_list.json`、`MANIFEST_FILENAME=_manifest.json`、`MANIFEST_VERSION` | import 後直接讀 | ✓ |
| **A-04** | `Manifest.to_dict()` 的 key 集合與順序不變 | 實際呼叫一次並記錄 | 14 個 key：`version, engine, api_mode, engine_version, endpoint_signature, options_signature, source_content_hash, source_size_bytes, source_filename_at_parse, task_id, downloaded_at, critical_file, files, total_size_bytes` |
| **A-05** | `is_bundle_valid` 只驗這 6 項：source size/hash、api_mode、options_signature、engine/endpoint、`critical_file.size+sha256`、`files[].size`。**不驗 `total_size_bytes`、不驗 `files[].sha256`（全為 null）、不列舉目錄** | 讀原始碼 + 對真 bundle 做正反例（改 `total_size_bytes` 應仍 valid；改 `critical_file.size` 應 invalid） | ✓；`sum(files[].size)+critical.size = 12687807 = total_size_bytes` |
| **A-06** | `ir_builder._coerce_text` 只讀 `("text","content","body","code_body")`；`page_number` 在 heading 偵測**之前**被無條件 `continue` | 讀原始碼 + fixture 回歸 | ✓ |
| **A-07** | `LIGHTRAG_FORCE_REPARSE_MINERU` 為空/假 | `docker exec env` | ✓（未設） |
| **A-08** | cache-miss 路徑會 `clear_dir_contents(raw_dir)`（＝raw_dir 內任何檔案都可能被清空） | 讀 `_base.py` | ✓ — 這條是**警告性斷言**，永遠為真，用途是提醒 A-09 |
| **A-09** | 備份／證據／標記檔**一律不放在 `.mineru_raw/` 內** | 靜態檢查我們自己的程式碼路徑 | 設計決定 |
| **A-10** | `content_list.json` **不在** `manifest.files[]`，只在 `critical_file`；但 `<task>_content_list_v2.json` **在** `files[]` | 讀 manifest | ✓（237 筆 files，含 `e1562777…_content_list_v2.json`、`…_origin.pdf`、`layout.json`、`full.md`）→ **升級風險 U-1，見 §7** |

### 2.2 資料層（hard／soft，逐文件）

| ID | 斷言 | 怎麼驗 | 失敗處置 |
|---|---|---|---|
| **A-11** | `manifest.options_signature == current_options_signature()` | `docker exec` 呼叫 LightRAG 的 signature 函式 | **hard，GATED_OUT 該文件**（訊息見 §4.2） |
| **A-12** | `is_bundle_valid(raw, src)` 回 True | oracle | hard，GATED_OUT |
| **A-13** | 來源 PDF 用**內容定址**找到：候選 `{inputs/<ws>/<doc>.pdf, inputs/<ws>/__parsed__/<doc>.pdf, raw_dir/*_origin.pdf}`，逐一 sha256 比對 `manifest.source_content_hash`，只接受相符者 | sha256 | hard，STOP 該文件。**不得寫死路徑** — 實測來源 PDF 已被 `archive_source` 搬到 `__parsed__/`，`inputs/<ws>/` 底下只剩 `__parsed__/` |
| **A-14** | `layout.json` 的 `pdf_info[k]["page_idx"] == k` 對所有 k 成立；`len(pdf_info) ≥ max(page_idx)+1`；每頁 `page_size` 一致 | 直接檢查 | hard，STOP。防「layout 與 content_list 整體位移」——書眉每頁幾何相同，錯頁比對照樣 IoU≈0.92 命中 |
| **A-15** | `origin.pdf` 與來源 PDF 在**同一個候選 bbox** 上 `pdftotext` 抽出的文字一致（容許空白差異） | 抽 3 個隨機 table bbox 比對 | hard，STOP。實測兩者 68 頁、439.4×666.1 pt、rot=0，僅 p27 差 1 個空白 |
| **A-16** | `set(item["type"]) ⊆ KNOWN_TYPES` | 集合運算 | hard，skip 該文件（新版面型別 = 規則涵蓋不完） |
| **A-17** | host 有 `pdftoppm` / `pdftotext` / `pdfinfo`；**沒有** PyMuPDF / pypdfium2 / PIL | `which` + `python -c import` | hard。裁圖與 PGM 解析只能用 poppler + stdlib |
| **A-18** | VLM 端點可用且**需要 api_key**：`/v1/models` 免金鑰、`/v1/chat/completions` 無金鑰回 401 | HTTP 探測 | soft（exit 5，可 `--resume`），**不得寫成 `failed`** |
| **A-19** | pipeline 目前 idle（非 scanning / non-busy） | `GET /documents/pipeline_status` | hard for `apply --commit`。`--require-idle` **預設開啟且不可關閉** |

### 2.3 基準值重測（本節取代工單口述的基準）

口述基準與實測不符，**以實測為準，並在 records 記錄兩者**：

| 項目 | 工單口述 | 實測（C Equivalent Networks，現行 bundle） |
|---|---|---|
| 空表格 | 10 | **16**（`table_body` key 不存在）；`EMPTY_SHELL` 0；含 `<img>` 28（其中 img-only-no-text **0**） |
| header/footer 佔比 5.6% | 5.6% | 分母不同差 6 倍：content_list 全 text 字元 **4.05%**（1317/32509）／IR `content_template` **5.72%**（含換行 6.21%）／`blocks.jsonl` content **0.97%**。**5.6% 對應的是 IR 分母** |
| header/footer 項目數 | 111 | **111**（全部 `type=header`，`footer` 0 個 → `footer` 分支未被行使） |
| chunks / entities / relations | 59 / 807 / 1324 | 由 `.parsed/` 與 rag_storage 重測後寫入 `records/env/`（本 bundle 產生） |

> **A-20（hard）**：`compat-check.py` 必須把「口述基準 vs 實測」的差異列成表格輸出。依 A4 原則，契約數字對不上就要查清楚，不能當註腳。已查清的結論：`10` 是舊測量、`5.6%` 的分母是 IR。

---

## 3. 資料流與檔案配置

### 3.1 模組佈局

```
/home/florian/ghq/github.com/neknufelet/lightrag-v1/scripts/
  compat-check.py         # §2 的全部斷言，可獨立跑、可 cron
  postprocess.py          # CLI 入口，只做參數解析與流程編排
  mineru_common.py        # 共用偵測器與磁碟契約（單一來源）
  parse-check.py          # 改：import mineru_common；修 DEFAULT_ROOT；修 L69（見 W1）
  pp/
    oracle.py             # 唯一與容器互動處（docker exec）
    model.py              # dataclass + SCHEMA 版本
    docctx.py             # DocContext：content_list / layout / pdf / pdftotext / manifest
    pdfcrop.py            # bbox → pt → 裁圖（poppler）
    vlm.py                # VLM 呼叫 + 回應閘門
    artifacts.py          # ArtifactStore（內容定址）
    plan.py apply.py verify.py revert.py reindex.py records.py
    rules/__init__.py     # RULES registry
    rules/layout_noise.py
    rules/empty_table.py
  tests/fixtures/mini_bundle/    # 合成 3 頁 PDF + 手寫 content_list/layout/manifest
```

`mineru_common.py` 用底線命名，因為 `parse-check.py` 帶連字號永遠 import 不了。

### 3.2 CLI

```
postprocess.py compat-check                                   # §2 全驗，cron 哨兵
postprocess.py status  [--json] [--state S]
postprocess.py plan    --doc <glob|@file|ALL> [--no-vlm] [--limit N] [--rules ...]
postprocess.py apply   --plan <path|latest> [--commit] [--resume] [--jobs 2]
postprocess.py verify  --doc <glob> [--deep]                  # --deep 在容器內真的 build_ir
postprocess.py reindex --doc <glob> [--commit]                # W9，讓修補生效
postprocess.py revert  --doc <glob> [--to origin|run:<id>]
postprocess.py repair-manifest --doc <glob> [--commit]        # 半狀態自癒
postprocess.py explain --doc <D> [--idx N]
postprocess.py review  --doc <D> --out review.html
postprocess.py selftest                                        # fixture 回歸
```

全域旗標：`--root /data/rag/lightrag`、`--workspace acoustics_v155`、`--container lightrag-acoustics_v155`、`--records <path>`、`--json`。

**退出碼**：

```
0  全通過，無 needs_review
1  完成，但有項目被 held / needs_review（內容層）
2  ABORT：契約層違反，磁碟未變更（或已自動還原）
3  使用者取消
4  部分完成，可 --resume（journal 有未 commit 步驟，且已自動回滾到已知狀態）
5  傳輸/基礎設施失敗（VLM 不可達、401、逾時）→ 可 --resume，**絕不寫成 failed**
```

**執行模式**：
- `plan` 對 bundle **零副作用**，只寫 `records/`。它是花錢前的預算表（ETA = 表數 × 6 s + 裁圖 0.4 s/表）。
- `apply` 沒帶 `--commit` 就是 dry-run：做完裁圖、VLM、全部驗證、寫完 records，唯獨不碰 `.mineru_raw/`。dry-run 的 artifact 直接成為 commit 的快取（內容定址命中，零次重複 VLM 呼叫）。
- `apply` **只接受 `--plan`**，不就地重算 —— 避免「看到的」與「套用的」不同。
- 併發只開在 VLM 呼叫層（`--jobs`，預設 2）。文件層永遠序列。

### 3.3 狀態機（每份文件）

```
GATE → SNAPSHOT → MEASURE(pre) → PLAN(filter+repair) → AUDIT
     → APPLY(in-memory) → IR-DIFF(暫存目錄，強制閘門) → COMMIT → POST-VALIDATE
     → REINDEX → INDEX-VERIFY
```

```python
STATES = ("planned", "gated_out", "snapshotted", "edited", "committed",
          "reindexed", "verified", "reverted", "failed", "transport_error", "skipped")
```

- 任一步失敗 → 已寫入磁碟者一律 `revert` 後才標記。
- **未 commit 的 journal 步驟一律自動回滾，不 resume**。resume 只適用於還沒碰 raw_dir 的階段（裁圖、VLM），那些本來就做在暫存目錄。
- `transport_error` 與 `failed` 分開：`--resume` **會**重試前者，跳過後者（除非 `--redo-repairs`）。

### 3.4 records/ 完整 schema

所有 JSON 帶 `"schema_version": 1`；改欄位語意就 +1。所有 sha256 一律帶 `"sha256:"` 前綴，前綴不可省。

```
/data/rag/lightrag/acoustics_v155/records/
  env/<env_id>.json
  postprocess/
    <run_id>/                       # run_id = UTC ISO8601 basic + 6 hex
      plan.json
      journal.ndjson
      report.json
      held.tsv
      coverage.tsv
      calibration.json
    <doc_id>/                       # doc_id = slug(stem)-<source_hash[7:15]>
      state.json
      origin/content_list.json      # 位元組級原檔（A1）
      origin/_manifest.json
      origin/SHA256SUMS
      applied/<run_id>/content_list.json    # 修補後全檔，不是 diff
      applied/<run_id>/_manifest.json
      applied/<run_id>/SHA256SUMS
      explain/<idx>.json
  repairs/<artifact_id>/            # artifact_id = sha256(crop||prompt_id||model_id||params)[:16]
    crop.png  crop.pgm  request.json  response.json  verdict.json  meta.json
```

#### `env/<env_id>.json`

```json
{
  "schema_version": 1,
  "env_id": "20260801T120000Z-a1b2c3",
  "captured_at": "2026-08-01T12:00:00Z",
  "container": "lightrag-acoustics_v155",
  "image_digest": "sha256:206579ab…",
  "lightrag_version": "1.5.5",
  "lightrag_file": "/app/lightrag/__init__.py",
  "lightrag_copies_md5": {
    "/app/lightrag/parser/external/mineru/cache.py": "…",
    "/app/.venv/.../cache.py": "…",
    "/app/build/lib/.../cache.py": "…",
    "/root/.cache/uv/.../cache.py": "…"
  },
  "pid1_cmdline": "python -m lightrag.api.lightrag_server",
  "pid1_pythonpath": "",
  "consts": {"RAW_SUFFIX": ".mineru_raw", "PARSED_SUFFIX": ".parsed",
             "CONTENT_LIST_FILENAME": "content_list.json",
             "MANIFEST_FILENAME": "_manifest.json", "MANIFEST_VERSION": 1},
  "manifest_key_order": ["version", "engine", "…"],
  "mineru_env": {"MINERU_API_MODE": "official", "MINERU_MODEL_VERSION": "pipeline",
                 "MINERU_LANGUAGE": "en", "MINERU_IS_OCR": "true",
                 "MINERU_ENABLE_TABLE": "true", "MINERU_ENABLE_FORMULA": "true",
                 "MINERU_PAGE_RANGES": null},
  "current_options_signature": "sha256:0b7a6a40…",
  "force_reparse": false,
  "vlm": {"endpoint": "http://100.71.26.77:8080/v1",
          "model": "/models/qwen3.6-35b-a3b/Qwen3.6-35B-A3B-UD-IQ4_XS.gguf",
          "capabilities": ["completion", "multimodal"],
          "api_key_ref": "env:VLM_API_KEY", "prompt_id": "table_html_v1",
          "prompt_sha256": "sha256:…", "temperature": 0, "max_tokens": 4096},
  "host_tools": {"pdftoppm": "…", "pdftotext": "…", "pdfinfo": "…"},
  "compat_check": {"result": "pass", "assertions": {"A-01": true, "…": true}},
  "baseline_discrepancies": [
    {"field": "empty_tables", "stated": 10, "measured": 16,
     "explanation": "口述值為舊測量；現行判準 = table_body key 不存在"},
    {"field": "header_pct", "stated": 5.6,
     "measured": {"content_list_text_chars": 4.05, "ir_content_template": 5.72,
                  "blocks_jsonl": 0.97},
     "explanation": "5.6% 對應 IR content_template 分母"}
  ]
}
```

#### `postprocess/<run_id>/plan.json`

```json
{
  "schema_version": 1,
  "plan_id": "sha256(canonical(ops)+content_list_sha_before)[:12]",
  "run_id": "20260801T120000Z-a1b2c3",
  "env_snapshot_id": "20260801T120000Z-a1b2c3",
  "created_at": "…",
  "docs": [{
    "doc_id": "c-equivalent-networks-1c7dcb0e",
    "doc_name": "C Equivalent Networks.pdf",
    "raw_dir": "/data/rag/lightrag/acoustics_v155/inputs/acoustics_v155/__parsed__/C Equivalent Networks.pdf.mineru_raw",
    "source_pdf": "…/__parsed__/C Equivalent Networks.pdf",
    "source_pdf_resolved_by": "content_hash",
    "origin_pdf": "…/e1562777…_origin.pdf",
    "source_content_hash": "sha256:1c7dcb0e…",
    "content_list_sha256_before": "sha256:7dbaf491…",
    "manifest_options_signature": "sha256:70a3780e…",
    "gate": {"ok": false, "reason": "options_signature 不符", "checks": {"A-11": false, "…": true}},
    "rules": [{"id": "layout_noise", "version": 1, "params": {}},
              {"id": "empty_table", "version": 1, "params": {"min_text_chars": 8}}],
    "ops": [{
      "op": "set_field", "field": "text",
      "target": {"idx": 12, "page_idx": 1, "type": "header",
                 "fingerprint": "sha256(canonical(item))[:16]"},
      "rule": "layout_noise@1", "reason": "running_header_corroborated",
      "new_value": "",
      "evidence": {"P1_layout_iou": 0.920, "P2_band_gap": 24,
                   "P3_repeat_pages": 67, "P4_token_subset": true,
                   "P5_fullmd_ratio": 0.03, "P6_pdftext_match": 1.0}
    }],
    "held": [{"idx": 431, "type": "header", "text": "…",
              "failed_guards": ["P3"], "detail": {}}],
    "repairs": [{
      "idx": 381, "page_idx": 26, "status": "MISSING_KEY",
      "bbox1000": [111, 222, 900, 555],
      "rect_pt": [48.8, 147.9, 395.5, 369.6],
      "artifact_id": "…", "gt_text_sha256": "sha256:…",
      "caption_from_crop": null
    }],
    "predicted": {
      "items_after": 556,
      "ir_char_delta": -1428,
      "ir_blocks_after": 19,
      "ir_tables_after": 57,
      "ir_equations_after": 76,
      "noise_string_residual": {"Equivalent Networks": 2, "C": 0}
    },
    "stats_before": { "…parse-check 全指標…" }
  }]
}
```

#### `postprocess/<run_id>/journal.ndjson`

Append-only，每個原子步驟兩行：

```json
{"ts":"…","doc_id":"…","step":"write_content_list","phase":"intent","before":"sha256:…","after":"sha256:…"}
{"ts":"…","doc_id":"…","step":"write_content_list","phase":"committed","actual":"sha256:…"}
```

#### `postprocess/<doc_id>/state.json`

```json
{
  "schema_version": 1, "doc_id": "…", "doc_name": "…",
  "state": "committed",
  "last_run_id": "…", "last_plan_id": "…",
  "content_list_sha256_origin": "sha256:7dbaf491…",
  "content_list_sha256_expected_after": "sha256:…",
  "manifest_sha256_expected_after": "sha256:…",
  "suppressed_count": 111, "repaired_count": 16,
  "held_count": 0, "unrepaired_defects": 0,
  "reindex": {"deleted_at": null, "scanned_at": null,
              "cache_hit_confirmed": false, "blocks_mtime_after_commit": false},
  "history": [{"ts":"…","run_id":"…","action":"apply","result":"ok"}]
}
```

#### `repairs/<artifact_id>/verdict.json`

```json
{
  "schema_version": 1, "artifact_id": "…", "doc_id": "…", "idx": 381,
  "model_id": "…", "prompt_id": "table_html_v1", "prompt_sha256": "sha256:…",
  "params": {"temperature": 0, "max_tokens": 4096, "dpi": 300,
             "pad_pt": [20, 6, 6, 6]},
  "finish_reason": "stop", "completion_tokens": 812, "latency_s": 6.1,
  "checks": {
    "V1_finish_reason_stop": true,
    "V2_ends_with_close_table": true,
    "V3_no_img_tag": true,
    "V4_no_leak": true,
    "V5_alpha_recall": 0.91,
    "V6_numeric_precision": 0.98,
    "V7_lcs_order_ratio": 0.86,
    "V8_negative_control": {"recall_self": 0.91, "recall_neighbours": [0.42, 0.38, 0.51],
                            "margin": 0.40, "pass": true},
    "V9_caption_present": true,
    "V10_row_count_vs_layout_lines": {"html_tr": 9, "layout_lines": 10, "delta_pct": 0.10},
    "V11_token_coverage_ratio": 0.53,
    "V12_gt_qualifying_tokens": 17
  },
  "verdict": "ACCEPT",
  "coverage_note": "本表自動化實際擔保 53% 的儲存格 token"
}
```

---

## 4. 實作項目

相依順序：`W0 → W1 → W2 → {W3, W4} → W5 → W6 → W7 → W8 → W9 → W10`。W11/W12 可平行。

### W0 — `pp/oracle.py`：唯一的容器互動層
**相依**：無 ｜ **驗收**：`compat-check.py` A-01..A-07 全綠

```python
@dataclass(frozen=True)
class BundleVerdict:
    valid: bool
    manifest_options_signature: str
    current_options_signature: str
    api_mode_now: str; endpoint_now: str
    force_reparse: bool
    lightrag_version: str; lightrag_file: str; image_digest: str
    copies_md5: dict[str, str]        # A-01
    consts: dict                      # A-03
    manifest_key_order: list[str]     # A-04
    probe_ok: bool; probe_error: str | None
```

`probe_ok=False`（import 失敗、簽章變了、常數沒了）本身就是「升級了且契約可能變了」→ 一律 STOP。
**絕不自行重算 signature 或 validity。**

### W1 — `mineru_common.py` + 修 `parse-check.py`
**相依**：無 ｜ **驗收**：`parse-check.py` 在現行 bundle 上輸出與修改前逐欄相同（除了下列兩項刻意改動）

搬進 `mineru_common.py`（單一來源）：`MATH` / `strip_math` / `MANGLED` / `TAG` / `table_text` / `LEAK` / `sha256_file` / `norm_to_pt` / `iou` / `doc_metrics` / 型別常數。

**必須修的三處**：

1. `DEFAULT_ROOT = Path("/data/lightrag")` → `Path("/data/rag/lightrag")`（現值是錯的，scan 直接找不到目錄）。
2. L69 `if t in ("text", "header"):` → `if t == "text":`。實測本文件 68 頁裡有 37 頁的「正文字元」全部來自書眉；消音之後 `無文字頁` 會從 0 跳到 37，越過 L102 的 `> max(3, 頁數*0.2)` 門檻 → **過濾做對了反而報 WARN**。同時 `字元數` 必須把 header 拆出來單獨計，否則 §5 的 `body_chars_unchanged` invariant 恆假。
3. `空表格` 判準拆開：現行 `not table_text(table_body)` 把 16 張 `MISSING_KEY` 全算進去（已重現 = 16），但把 28 張含 `<img>` 的算成 OK。改成輸出四個計數：`missing_key / empty_shell / img_with_text / img_only_no_text`。

```python
NOISE_TYPES = frozenset({"header", "footer"})
KEEP_TYPES  = frozenset({"page_footnote"})     # 真內容，永不動
SKIP_TYPES  = frozenset({"page_number"})       # LightRAG 自己跳過，我們不碰
KNOWN_TYPES = frozenset({"text","header","footer","page_number","page_footnote","equation",
                         "table","image","code","list","title","section_header",
                         "picture","drawing"})
COERCE_TEXT_KEYS = ("text", "content", "body", "code_body")   # 必須與 ir_builder 同步
```

### W2 — `pp/docctx.py`：DocContext 與內容定址的 PDF 解析
**相依**：W0, W1 ｜ **驗收**：A-13/A-14/A-15 在真 bundle 上通過

提供 `items` / `layout` / `manifest` / `pdf_path`（**內容定址解析，A-13**）/ `page_geometry()` / `bbox_to_rect()` / `page_text(page_idx)` / `page_text_in_rect(page_idx, rect_pt)` / `store` / `vlm`。

```python
@dataclass(frozen=True)
class PageGeom:
    page_idx: int; width_pt: float; height_pt: float; rot: int

def bbox_norm_to_pt(bbox1000, g: PageGeom):
    x0, y0, x1, y1 = bbox1000
    return (x0/1000*g.width_pt, y0/1000*g.height_pt,
            x1/1000*g.width_pt, y1/1000*g.height_pt)
```

注意：`layout.json` 的 `page_size` 是整數 `[439, 666]`（截斷自 `pdfinfo` 的 439.4×666.1），有 **0.4 pt 系統性誤差**。一律用 `pdfinfo` 的浮點值換算，`page_size` 只用來做一致性檢查（容許 ±1 pt）。

### W3 — `rules/layout_noise.py`：過濾（消音）
**相依**：W1, W2 ｜ **驗收**：§8 F 組全部命中

#### 機制：消音，不刪除

```python
def suppress_item(item: dict, run_id: str) -> dict:
    assert not any(item.get(k) for k in COERCE_TEXT_KEYS[1:]), \
        "item 帶 content/body/code_body，消音無效 —— 停手"
    out = dict(item)
    out["_pp"] = {"v": 1, "run_id": run_id, "action": "suppress",
                  "original_text": item.get("text", ""),
                  "original_type": item.get("type"),
                  "item_sha256": sha256_prefixed(canonical_json(item))}
    out["text"] = ""
    return out
```

依 A-06：`_coerce_text` 回 `""` → `_append_text` 回 `False` → 不寫入 `cb_lines`、也不 `_record_position`。效果等同刪除，但索引位置不變 → `self_ref` 全部穩定（**實測 `tables.json` 的 `self_ref` 是 `content_list.json#/6` 這種陣列索引，刪除會讓 41 個表 + 76 個公式的引用全部錯位且不報錯**）。

被拒絕的替代方案：
- **直接 `del`**：破壞 self_ref（上述）。
- **把 `type` 改成 `page_number`**：能被 ir_builder 硬跳過，索引也穩定，但摧毀了與 `layout.discarded_blocks` 對帳的能力，也讓「反向偵測」失去型別基準。效果與消音相同而代價更高，故不採用。

#### 六道閘門（全過才消音）

候選 = `type ∈ NOISE_TYPES`。**絕不做字串比對**。

| 閘門 | 內容 | 性質 | 失敗處置 |
|---|---|---|---|
| **P1 layout 一致性** | 同頁 `discarded_blocks` 中存在 **type 相同** 且 IoU ≥ 0.6 的 block | **一致性檢查，非授權** | 不一致 → REVIEW（代表契約壞了）。**一致不得當成通過條件** |
| **P2 幾何護欄** | 門檻逐文件自算：`max(y1 of 候選) < min(y0 of 保留正文)` | 獨立 | 有重疊 → 該項 REVIEW；重疊比例 > 10% → ABORT 整份 |
| **P3 重複性** | 正規化文字在 **≥ max(3, 0.05×頁數)** 個不同頁面出現 | 獨立 | held |
| **P4 token 保全** | 被消音文字的字母 token ⊆ 保留內容全文 token 集合 | 半獨立 | held |
| **P5 full.md 一致性** | 該字串在 `full.md` 出現次數 ≤ 候選次數的 20% | **一致性檢查，非授權** | 不符 → held + REVIEW |
| **P6 PDF 文字層背書** | 對候選 bbox 跑 `pdftotext -x/-y/-W/-H`，抽出文字與 `item["text"]` 正規化後相符 | **唯一完全獨立** | 不符 → held |

> **P1 與 P5 為何被降級**：實測 `layout.discarded_blocks` 的型別分布 `header 111 / page_number 67 / page_footnote 3` 與 `content_list.json` 的型別分布**完全相同**，111 個 header 逐一 IoU ≥ 0.9 對上（match 111, nomatch 0）。兩者是**同一個分類器的兩份序列化**，`full.md` 同源。它們的資訊量為零，把它們當「ground truth」會讓「MinerU 把正文標成 header」這種失效被三個同源視角一致放行。真正獨立的只有 P2 / P3 / P6。
>
> **P1 為何仍要求 type 相同**：實測 `discarded_blocks` 裡有 3 個 `page_footnote`（p4 / p11 的 `*) See Preface to the 2^{nd} edition.`），那是**真內容**。若只要求「同頁有 discarded block 且 IoU ≥ 0.6」，一個被標成 footer 的真腳註可以拿同頁的 page_footnote block 當授權被消音，理由欄還會漂亮地寫 `layout.discarded[p=4,i=0]`。

#### 量級護欄：精確預測，不用百分比

百分比分母不明會差 6 倍（4.05% / 5.72% / 0.97%），5% 門檻在不同分母下要嘛形同虛設要嘛立刻誤觸。改成**精確比對**：

- `ir_char_delta` 必須**恰好等於** `-(Σ len(被消音 text) + N)`（每項一個換行分隔符）。本文件 = `-(1317 + 111) = -1428`。
- 三個分母的百分比全部寫進 records 供報表，但**不作為閘門**。

#### 反向偵測（防「刪太少」）

`audit_filter` 現有的拒絕條件全部是誤刪防護，**刪 0 筆與刪對是同一種輸出**（綠色、無錯誤）。必須加：

```python
def detect_residual_running_head(items_after, page_size, n_pages) -> list[dict]:
    """與 type 完全無關。過濾後若某 len ≤ 60 的字串仍以獨立項目出現在
       ≥ 40% 頁面、且 bbox 落在上/下 10% 版面帶 → RESIDUAL_RUNNING_HEAD。"""
```

實測此偵測器在**未過濾**的本文件上會抓到 `'Equivalent Networks'`（67/68 頁）與 `'C'`（44/68 頁）；過濾正確後應歸零。這是唯一能同時抓到「type 改名」「模型漏標成 text」「filter 根本沒跑」三種失效的檢查。

另輸出 `coverage.tsv`（每頁消音計數），缺頁必須在 stdout 顯眼：

```
頁面覆蓋率 67/68（缺 p0）；'C' 變體僅覆蓋 44/68 頁 —— MinerU 在 24 頁漏標
```

#### 硬性 invariant（有方向性，不要恆真的裝飾）

| id | severity | 檢查 |
|---|---|---|
| `count_unchanged` | hard | `len(after) == len(before) == 556` |
| `only_text_field_changed` | hard | 除了被消音項的 `text` 與新增的 `_pp`，逐項 canonical JSON 相同 |
| `no_text_level_suppressed` | hard | 被消音項無 `text_level`（註：實測 111 個 header **全部沒有 text_level**，此條在本 corpus 從未被行使 → 標記 `unexercised`） |
| `suppressed_subset_of_repeated` | hard | 被消音文字集合 ⊆ 「在 ≥ 3 頁重複出現的字串集合」 |
| `body_chars_unchanged` | hard | `type=="text"` 的字元總數完全不變（32509 − 1317 = 31192 全部來自 text 型） |
| `page_footnote_preserved` | hard | 3 個 page_footnote 逐位元組不變 |
| `ir_char_delta_exact` | hard | 見上，`-1428` |
| `types_exercised` | soft | 輸出 `types_seen` / `types_matched`；`NOISE_TYPES` 中命中 0 次者列為 `unexercised`（本文件 `footer` = 0） |

**已刪除的裝飾性 invariant**：`mangled_not_increased` / `leak_not_increased` / `empty_table_not_increased` 對只做消音的規則單調不可能失敗，八條裡三條是假覆蓋。它們移到 `verify` 當跨規則檢查，不算在過濾的 invariant 裡。

### W4 — `rules/empty_table.py`：修補目標選擇與分類
**相依**：W1, W2 ｜ **驗收**：§8 R 組

```python
class TableStatus(enum.Enum):
    OK = "ok"
    MISSING_KEY = "missing_key"          # 實測 16/57
    EMPTY_SHELL = "empty_shell"          # <table><tr><td></td></tr></table>；實測 0/57
    IMG_WITH_TEXT = "img_with_text"      # 剝掉 <img> 仍有實質文字 → 正常表；實測 28/57
    IMG_ONLY_NO_TEXT = "img_only_no_text"  # 剝掉後 < 8 字元；實測 0/57

def table_status(item, *, min_text_chars=8) -> TableStatus:
    if "table_body" not in item:
        return TableStatus.MISSING_KEY
    body = item["table_body"] or ""
    if IMG_TAG.search(body):
        rest = table_text(IMG_TAG.sub("", body))
        return TableStatus.IMG_WITH_TEXT if len(rest) >= min_text_chars \
               else TableStatus.IMG_ONLY_NO_TEXT
    return TableStatus.OK if len(table_text(body)) >= min_text_chars \
           else TableStatus.EMPTY_SHELL
```

> 原設計的兩個分支都 `return IMG_ONLY` → OK 分支對任何含圖的表**不可達**，是死碼。而且把 28 張正常表誤分類。修正後 `IMG_WITH_TEXT` **永不修補**，只列進 `manual_review`。

**預設修補集合 = `MISSING_KEY ∪ EMPTY_SHELL`**（本文件 16 張）。`IMG_ONLY_NO_TEXT` 需 `--repair-img-only` 明確開啟，且原 `table_body` 完整存進 `records/repairs/`。

**`status` 必須把「未修復缺陷張數」當一級輸出並回退出碼 1**，不得因為修了 16 張就宣告成功。

不要用 `table_caption` 判斷：實測這 16 張的 `table_caption == ['']`，`if item['table_caption']:` 為真，任何 caption 檢查都會被騙過。

### W5 — `pp/pdfcrop.py`：裁圖 + rect 正確性證明
**相依**：W2, W4 ｜ **驗收**：§8 R-3

```python
def crop_table(t, pdf, g: PageGeom, dpi=300,
               pad_pt=(20, 6, 6, 6)) -> CropResult:
    """pad = (top, right, bottom, left)；top 特別大，把 'Table 5 continued'
       標題帶進來 —— 這 16 張 table_caption 是 ['']，caption 只能從圖裡讀回。
       pdftoppm -png -r DPI -f N -l N -x X -y Y -W W -H H，單位是該 dpi 下的像素。"""
```

#### rect 正確性必須用 rect 以外的資訊證明（關鍵）

crop 與 `pdftotext -x/-y/-W/-H` 共用同一個 rect。rect 一旦偏移（換錯 PDF、bbox 指到隔壁段落、頁面位移），VLM 抄錯區域、pdftotext 抽同一個錯區域，**兩邊完全一致、recall = 1.0，錯的內容靜默寫入**。所以：

- **C1**：用 `pdftotext -bbox-layout` 取該頁文字塊，斷言 rect 內的內容同時也落在 `layout.json` 該 table block 的 spans 範圍內 —— 兩條獨立管線推出同一組字才放行。
- **C2**：若 `table_caption` 非空（本文件 16 張皆為 `['']`，不適用；其他文件適用），斷言 caption 文字出現在 rect 抽字或其上方 pad 區。
- **C3**：`origin.pdf` 與來源 PDF 在同 rect 抽字一致（A-15）。
- 任一不過 → 該項 `held`，不寫入。

### W6 — `pp/vlm.py`：VLM 呼叫 + 回應閘門
**相依**：W5 ｜ **驗收**：§8 R-2

`base=http://100.71.26.77:8080/v1`、`model=/models/qwen3.6-35b-a3b/Qwen3.6-35B-A3B-UD-IQ4_XS.gguf`、`temperature=0`、**`max_tokens=4096`**、逾時 120 s、圖片以 base64 data URI 內嵌。

```python
@dataclass(frozen=True)
class VLMConfig:
    endpoint: str; model: str
    api_key: str | None        # 實測 /v1/chat/completions 無金鑰回 401；/v1/models 免金鑰
    temperature: float = 0.0
    max_tokens: int = 4096
    timeout_s: float = 120.0
    prompt_id: str = "table_html_v1"
```

**硬性回應閘門**（任一不過即 reject，不寫入）：

| id | 檢查 | 理由 |
|---|---|---|
| V1 | `finish_reason == "stop"` | **截斷完全沒被檢查是本設計最容易漏的洞**。待修表格實測有 `h=526 pt`、佔 64% 版面的巨表（idx 440, p41）；滿版 LaTeX 撞 2048 tokens 是常態。截斷輸出仍然：單一 `<table>` 開頭、有 `<tr>`、有非空 `<td>`、不含 `<img>`、MANGLED 不中、recall ≥ 0.4 —— **三段驗收全過，實際只有半張表** |
| V2 | 原始輸出（unwrap 前）以 `</table>` 結尾 | 同上 |
| V3 | 不含 `<img` | 不得把數學換成圖片參照（工單失效模式 a） |
| V4 | `LEAK` 不命中 | prompt 洩漏 |
| V5–V12 | 見 §5 交叉驗證 | |

`usage.completion_tokens`、`finish_reason`、`prompt_sha256` 全部寫進 `verdict.json`。**換 prompt 就換 `prompt_id`**，artifact key 隨之改變。

VLM 端點不可達 / 401 / 逾時 → `transport_error`（exit 5），**不是 `failed`**。否則 VLM 主機掛掉時每張表 reject → 全部 `failed` → 摘要全綠 → `--resume` 永遠跳過 → 3000 張表一張沒修，沒人會發現。

### W7 — `pp/apply.py`：IR-diff 強制閘門 + 原子提交
**相依**：W3, W4, W6 ｜ **驗收**：§8 A 組

#### 7.1 IR-diff 是強制閘門（成本 0.02 s）

`build_ir` 是純本機、純函式、不碰網路。在 commit 前，於**暫存目錄**套用 plan、在容器內用真的 `MinerUIRBuilder` 建 IR，比對：

```
blocks 數不變 ∧ 每個 heading 字串逐一不變 ∧ equations 數不變 ∧ drawings 數不變
∧ tables 數 == 舊值 + 修好的張數
∧ content 字元減少量 == Σlen(被消音 text) + N       ← 精確到個位數
∧ 被消音字串在新 IR 的出現次數 == 預期殘留數
```

實測本文件的完整消音差分（複製 raw_dir → 111 個 header 設 `text=""` → 兩邊各建一次 IR）：

```
BEFORE  chars 23008  'Equivalent Networks' 69  tables 41  eq 76
AFTER   chars 21580  'Equivalent Networks'  2  tables 41  eq 76   headings 完全相同
delta = 1428 = 1317 + 111
```

對不上就 ABORT。這一道同時抓得到「P1/P5 失效」「規則寫錯」「量級護欄失準」的所有後果。

#### 7.2 提交順序（`content_list.json` 與 `_manifest.json` 沒有共同原子性）

危險程度必須說清楚：兩檔不一致 → `is_bundle_valid=False` → `_base.py` 走 cache-miss → **`raw_dir.mkdir(); clear_dir_contents(raw_dir)`** → 12 MB bundle（含 `origin.pdf`、`layout.json`、`images/`）全被清空 → 向 mineru.net 重抓。日誌只有一行 `[mineru] Parsing …`。所以「退出碼 4 部分完成可續跑」在這個窗口內是**錯的語意**：那不是可續跑狀態，是一顆等下次 parse 引爆的炸彈。

```
0. --require-idle（預設開啟、不可關閉）；apply 全程輪詢 pipeline busy/scanning
1. 寫 records/<doc_id>/applied/<run_id>/{content_list.json,_manifest.json}（完整副本，非 diff）
2. 樂觀鎖：重讀 raw_dir/content_list.json 的 sha256，必須等於 plan 記的 before，否則 ABORT
3. 寫 content_list.json.tmp → fsync → os.replace → fsync(dir)
4. stat() 重新取 size；重新讀檔算 sha256    ← 絕不由記憶體字串推算
5. 寫 _manifest.json.tmp → fsync → os.replace → fsync(dir)
6. 立刻呼叫 oracle.is_bundle_valid()；False → 就地用 origin 還原並 exit 2
```

**`critical_file.size` 必須是 `len(json_bytes)` 不是 `len(json_str)`** —— 本檔含非 ASCII（實測有 `“direction of propagation”` 等彎引號），字元數 < 位元組數 → 必然 wipe。

`total_size_bytes` **不被 `is_bundle_valid` 驗證**（A-05），但仍同步更新以維持一致性；不要把心力放在它上面。真正致命的只有 `critical_file.size` 與 `critical_file.sha256` 兩欄。

`raw_dir` 內建 `.postprocess.lock`（pid + run_id + mtime）—— 注意這個 lock 檔本身也在 wipe 的爆炸半徑內，只用於同進程互斥，不作為狀態來源。

#### 7.3 `repair-manifest`：半狀態自癒

manifest 對 content_list 的部分（size + sha256）**可從磁碟完全重算**。所以 `apply --resume` 的第一步是無條件跑 `repair-manifest`，讓中斷留下的半狀態自癒，再判斷續跑點。

### W8 — `pp/verify.py` + `revert.py`
**相依**：W7 ｜ **驗收**：§6、§8 V 組

### W9 — `pp/reindex.py`：讓修補真正生效
**相依**：W8 ｜ **驗收**：§8 X 組 —— **這是本工單的核心工作項，不是附註**

唯一安全配方（逐條對過 `document_routes.py` / `pipeline.py` / `utils.py`）：

```
1. DELETE /documents/<doc_id>  且 delete_file=False
      ← delete_file=True 會對 <basename>.mineru_raw 直接 shutil.rmtree
        （_file_path_for_parsed_artifact_dir 把 .mineru_raw 列入 PARSED_ARTIFACT_DIR_SUFFIXES）
2. cp "__parsed__/<原檔名>.pdf" → "inputs/<ws>/<原檔名>.pdf"
      ← basename 一個字都不能改：parsed_dir 由 document_name 決定
        （parser/base.py:78 parsed_artifact_dir_for(document_name, parent_hint=…)）
3. POST /documents/scan
4. 在容器 log 確認出現：[mineru] raw cache hit doc_id=…
      ← 沒看到這行 = 快取沒命中 = MinerU 已重抓 = 你的修補已經沒了
5. 斷言 .parsed/*.blocks.jsonl 的 mtime > commit 時間
6. 跑 INDEX-VERIFY（§5.3）
```

**副作用**：`archive_source` 會因 `__parsed__/` 已有同名檔而產生 `<stem>_001.pdf`（`utils.py:801 get_unique_filename_in_parsed`）。不影響快取，但每次 re-ingest 多一份垃圾，390 份 × N 輪要清 → `reindex --commit` 結束時列出這些檔案並提供 `--cleanup-archived`。

`state.verified` 的定義改成「INDEX-VERIFY 通過」，**不得用 content_list 自證**。

### W10 — `postprocess.py` CLI + `status` / `explain` / `review`
**相依**：W9

### W11 — `compat-check.py`（§2 全部斷言）
**相依**：W0 ｜ 可與 W3–W9 平行 ｜ **必須排 cron**

### W12 — `tests/fixtures/mini_bundle/` + `selftest`
**相依**：W1, W2 ｜ 可平行

合成 3 頁 PDF（含文字層）+ 手寫 content_list / layout / manifest，覆蓋：正常 header、被誤標成 header 的真標題（帶 `text_level`）、`page_footnote` 落在 discarded_blocks、`MISSING_KEY` 表、`IMG_WITH_TEXT` 表、`EMPTY_SHELL` 表、截斷的 VLM 回應。每加一條規則就加一個致命樣本。

---

## 5. 交叉驗證方案

### 5.1 過濾：怎麼確認沒誤刪

| 層級 | 方法 | 比例 | 判準 |
|---|---|---|---|
| 全量 | §4 W3 的 8 條 invariant + IR-diff 精確比對 | 100% | 全綠，`ir_char_delta == -1428` |
| 全量 | `detect_residual_running_head` | 100% | 過濾後命中數 = 0 |
| 全量 | `coverage.tsv` 每頁計數 | 100% | 人眼掃過；缺頁必須列出 |
| **抽驗** | 每份文件隨機抽 **10 個**被消音項（不足 10 取全部），對其 bbox 跑 `pdftotext -x/-y/-W/-H`，人工比對抽出文字 == `_pp.original_text` | 每文件 10 項；390 份共 3900 項太多 → **前 20 份 100% 抽 10 項，其餘每 10 份抽 1 份** | 不符 1 項即整批停手 |
| **抽驗** | `held` 佇列 100% 人工看過 | 100% | 本文件預期 held = 0 |

### 5.2 表格修補：怎麼確認轉錄正確（核心難點）

**原設計的召回率閘門實測沒有鑑別力，必須整組換掉。**

實測（本文件 16 張 `MISSING_KEY` 表，兩組獨立測法）：

```
測法 A（拿 B 表正確轉錄去頂 A 表）：
  240 組錯配中 108 組通過 (recall≥0.60 ∧ 數字 recall≥0.80) = 45.0%
  16 張裡 13 張可被別張表「驗證通過」，多組是 (1.0, 0.8) 滿分錯配
測法 B（門檻 0.40）：
  240 對中 97% 通過；70% 拿到 ≥0.70 完全放行
```

原因：(1) 這 16 張是同一張跨頁續表的片段（p26/28/29、p39/40、p42/43/44、p46/47/48、p56/57、p59/60/61），gt 詞彙就是 `impedance / orifice / partition / coupling / mode / norms` 那組領域詞；(2) `|gt| = 10–23`，唯一數字 token 每張只有 4–6 個（多半是 0/1/2 上下標），0.80 數字召回形同無門檻；(3) **召回率只管「真文字有沒有出現」，完全不管 HTML 多出來什麼** —— 幻覺加行、複製上一張表、行列轉置、數值抄到隔壁欄，全部通過。

換成十二道閘門：

| id | 檢查 | 門檻 | 擋什麼 |
|---|---|---|---|
| V1 | `finish_reason == "stop"` | hard | 截斷 |
| V2 | 原始輸出以 `</table>` 結尾 | hard | 截斷 |
| V3 | 不含 `<img` | hard | 數學被換成圖片 |
| V4 | `LEAK` 不命中 | hard | prompt 洩漏 |
| **V5** | **alpha recall**：gt 的 `[A-Za-z]{3,}` 小寫集合在 HTML 的召回，**經文件內 IDF 過濾**（出現在該文件 >20% 表格區域的詞權重歸零） | ≥ 0.70 | 漏抄 |
| **V6** | **數值 precision**（新增，原設計完全沒有）：HTML 內每個數值 token 必須存在於區域文字 | ≥ 0.95 | 幻覺、抄錯欄、複製別張表 |
| **V7** | **LCS 順序比例**：gt token 在輸出中的最長共同子序列 / |gt| | ≥ 0.60 | 順序全亂、只轉了前三列 |
| **V8** | **負向控制**（最重要的一道）：同時對「同文件鄰近 3 張表區域的 gt」算 recall。`recall_self − max(recall_neighbours) ≥ 0.15` | hard | 上述 45%/97% 的洞。若不成立 → **該文件的對帳指標宣告無效**，全部表進人工佇列 |
| **V9** | caption（若非空）出現在輸出或 crop 抽字 | hard | rect 錯位 |
| **V10** | 結構對帳：`layout.json` 該區 block 的 `lines` 數 vs HTML `<tr>` 數 | 差 ≤ 30% | 漏列、多列 |
| **V11** | **token 覆蓋率記錄**：非空白 token（含數字與單字元）覆蓋率 | 記錄，不擋 | 誠實揭露自動化擔保多少 |
| **V12** | **分母下限**：gt 唯一 alpha token < 8 或唯一數字 < 6 → 標 `unverified` | hard | **真空通過**：純數字表、純符號表在空集合上召回率恆為 1.0 |

**為什麼不用「雙取樣一致性」**：同一模型、同 prompt、temperature 0，只換 padding 與 dpi。系統性錯誤（漏一欄、吃掉符號格、對某字型一貫誤讀）會在兩次取樣中一模一樣地重現，`structural_fingerprint` 完全相等、Jaccard = 1.0 → 判定通過。它只能抓隨機抖動，抓不到系統性省略 —— 而系統性省略正是本專案踩過三次的型態。保留為 soft 記錄，不作為閘門。

**為什麼恢復比對數字**：實測 PDF 文字層的數字是活的（`a2`、`J0`、`J1`、`S0;n`、`n=0 2`），數字與下標才是鑑別 token。亂碼的是希臘字母（η→`†`、`Œ`、`‚`）—— 把非 ASCII 排掉就好，不必連數字一起丟。

**V5 的覆蓋率必須誠實揭露**：實測全文件表格非空儲存格 679 個，剝掉 `$…$` 後仍含 ≥3 字母單字的只有 358 個 = **52.7%**。也就是「整欄丟掉數學與單字元」的修補，V5 召回率仍可以是 100%。而單字元欄正是這類表的關鍵（idx 7 的 Letter 欄是 R / C / L）。`V11` 把這個數字寫進 `verdict.json` 與報表。

**人工抽驗比例**（自動化擋不住的部分）：

| 階段 | 比例 | 判準 |
|---|---|---|
| 前 20 份文件 | **修補表 100% 人工看 crop.png vs 產出 HTML** | 任一張錯 → 停手改 prompt/參數 |
| 第 21–100 份 | 每份抽 **30%**，且**必含 `V11 < 0.5` 與 `V10 delta > 15%` 的全部** | 錯誤率 > 5% → 退回 100% |
| 第 101 份以後 | 每份抽 **10%** + 上述高風險項全部 | 錯誤率 > 5% → 退回 30% |
| 全程 | `unverified` / `held` **100% 人工看** | — |

### 5.3 INDEX-VERIFY（end-to-end，同時是最好的升級哨兵）

`verify --deep` 在容器內用真的 `MinerUIRBuilder` 建 IR，並讀磁碟上的 `.parsed/`：

1. 噪音字串在所有 block 內命中數 == 預期殘留（本文件 `'Equivalent Networks'` 應為 2）。
2. `tables.json` 的 entry 數 == 57（修補前 41）。
3. 每張被修補的表至少 2 個儲存格文字出現在 `tables.json` 對應 entry 的 `content`。
4. `equations.json` 仍為 76；`blocks.jsonl` 行數不變。
5. `.parsed/*.blocks.jsonl` mtime > commit 時間；否則標 **`INDEX_STALE`** 並回非零。
6. chunks / entities / relations 重測，與 records 的 pre 值一起輸出（**不設門檻**，實體抽取有 LLM 隨機性；只要求人看過並簽字）。

---

## 6. 可復原設計

### 6.1 原檔保全（A1）

- `content_list.json` 與 `_manifest.json` 的原始位元組在第一次動手前落到 `records/postprocess/<doc_id>/origin/`，落地後**驗回 sha256**。
- **絕不放在 `.mineru_raw/` 內**（A-08/A-09）。原本「V1 證明多放檔案不會讓快取失效 → 免費的修補標記檔」的想法是錯的：那個標記檔跟修補在**同一個爆炸半徑**內，在唯一需要它的情境（cache miss / UI 刪檔 / force reparse）下必定一起消失。而且它還是反向風險 —— 升級若改成列舉目錄驗證，多出來的檔案本身就會讓快取失效。
- `records/` 內同時保存**修補後**的 `content_list.json` 與 `_manifest.json` **全檔副本**（243 KB × 2 × 390 ≈ 190 MB，restic 內），讓靜默 wipe 之後的復原是 `cp` 而不是花錢重解析。**只存 diff 不夠。**

### 6.2 還原步驟

```bash
# 單一文件回到修補前（位元組級）
postprocess.py revert --doc "C Equivalent Networks" --to origin --commit
#   1. --require-idle
#   2. cp records/<doc_id>/origin/content_list.json → raw_dir/  (atomic + fsync)
#   3. cp records/<doc_id>/origin/_manifest.json   → raw_dir/  (atomic + fsync)
#   4. 驗回 SHA256SUMS
#   5. oracle.is_bundle_valid() 必須為 True
#   6. state → reverted
#   7. 若要讓還原生效，必須再跑 reindex（同 W9）

# 整批回退
postprocess.py revert --run 20260801T120000Z-a1b2c3 --commit

# bundle 被 wipe 之後的復原（不重跑 VLM）
postprocess.py apply --plan records/postprocess/<run_id>/plan.json --replay --commit
#   --replay 只在 content_list_sha256_before 完全相同時放行；否則拒絕並要求重 plan
#   artifact 內容定址 → crop 相同 → key 相同 → 直接命中，零次 VLM 呼叫
```

### 6.3 續跑

`journal.ndjson` append-only，每步 `intent` / `committed` 兩行帶 before/after sha256。
`--resume`：先跑 `repair-manifest` 自癒 → 有 `intent` 無 `committed` 的步驟**用 origin 還原後重做**，不做猜測性接續。

---

## 7. 升級存活

### 7.1 偵測機制（三層）

| 層 | 機制 | 頻率 | 觸發後 |
|---|---|---|---|
| L1 | `compat-check.py`（§2 全部斷言，含 A-01 四份 lightrag md5、A-04 manifest key 順序、A-05 驗證邏輯正反例） | cron 每日 + 每次 `apply` 前 | 任一 hard 失敗 → 中止整批，告警 |
| L2 | **`audit`：全庫 tripwire** —— 逐 bundle 比對現況 `content_list.json` sha256 與 `state.json` 的 `expected_after` | cron 每日 | 不符 → 分類為 `UNPATCHED`（修補被還原）/ `MISSING`（bundle 被清空）/ `DRIFTED`（第三方改動），告警 |
| L3 | **INDEX-VERIFY（§5.3）** —— 驗輸出不驗契約 | 每次 reindex 後 + cron 每週抽 5% | 噪音字串回來 / tables 掉回 41 → 告警 |

L3 是最重要的一層，因為它**不依賴任何契約假設**：不管 LightRAG 改了什麼，只要索引裡又出現書眉、或表格數掉回去，它就會叫。

### 7.2 已識別的具體升級風險

| id | 風險 | 偵測 | 處置 |
|---|---|---|---|
| **U-1** | **升級改成讀 `<task>_content_list_v2.json` 而非 `content_list.json`**。該檔**已經在 bundle 裡**（402 KB，且在 `manifest.files[]` 有 size 記錄）。屆時我們改 `content_list.json` 會「成功、驗證通過、完全沒效果」 | A-03（`CONTENT_LIST_FILENAME` 常數）+ **L3**（唯一能抓到「改對了但沒效果」的） | 採納：L3 是必要的，不能只靠 A-03 |
| **U-2** | 快取驗證邏輯改變（例如開始列舉目錄、開始驗 `files[].sha256`、`signature_version` 提版） | A-05 正反例 + A-12 | 中止整批；重跑 plan |
| **U-3** | `_coerce_text` 開始讀更多 key，或 `page_number` 不再被跳過 | A-06 + fixture 回歸 + L3 | 消音失效 → 噪音回來 → L3 抓 |
| **U-4** | 探針探到不是 server 在跑的那份 lightrag（容器內有 4 份） | A-01 | 中止 |
| **U-5** | `MINERU_*` 任一 env 變動 → `options_signature` 改變 → 全庫快取失效 → **全部重解析、修補全消失、無錯誤訊息** | A-11 逐文件 + L2 | 中止；`.env` 納入 git 且變更需 review |

### 7.3 最可能的毀滅路徑不是升級，是操作

按實際發生機率排序，全部**沒有任何錯誤訊息**：

1. **操作員在 UI 刪文件時勾了 delete file** → `shutil.rmtree(<basename>.mineru_raw)`。
2. **有人設 `LIGHTRAG_FORCE_REPARSE_MINERU=1` 想「讓修補生效」** → 下載前無條件 `clear_dir_contents`，**修補在生效前被刪掉**，索引照樣建成功。
3. 來源 PDF 位元組變動（改版、重新掃描）→ cache miss → wipe。
4. commit 中途斷電 → manifest/content_list 不一致 → 下次 parse wipe。

處置：
- `apply` 啟動時檢查 `LIGHTRAG_FORCE_REPARSE_MINERU`，非空即拒絕執行並印出正確配方。
- README 與 `reindex` 的輸出都明文寫：「讓修補生效的唯一正確作法是 `delete_document(delete_file=False)` → 放回 PDF → `/scan` → 確認 log 出現 `raw cache hit`。**絕不可 force reparse，絕不可勾 delete file**。」
- L2 audit 每日跑，讓 1–4 在 24 小時內可見。

---

## 8. 驗收條件

全部針對 `C Equivalent Networks.pdf`。每項可客觀判定。

### 前置（P 組）

| id | 條件 | 預期 |
|---|---|---|
| P-1 | `compat-check.py` 執行 | A-01..A-10、A-14、A-16、A-17 全綠 |
| P-2 | A-11 options_signature | **不符**：manifest `sha256:70a3780e…`（反解 = `model_version=vlm, language=ch, is_ocr=true`）vs 現行 env `sha256:0b7a6a40…`（`pipeline / en / is_ocr=true`）。→ **本文件必須 GATED_OUT，這是正確行為** |
| P-3 | GATE 訊息 | 必須包含反解出的兩組選項、以及「這份快取下次掃描就會被丟棄重抓，修補它等於丟錢」 |
| P-4 | A-13 來源 PDF 解析 | 由 sha256 `1c7dcb0e…` 命中 `__parsed__/C Equivalent Networks.pdf`（1 614 611 B）。**不得寫死 `inputs/<ws>/`** |
| P-5 | A-14 | `pdf_info` 長度 68、`page_idx[k]==k` 全成立、`page_size` 全為 `[439,666]` |
| P-6 | A-20 基準差異表 | 輸出 `10 vs 16`、`5.6% vs {4.05, 5.72, 0.97}` 兩列，附解釋 |

> **P-2 的意義**：本文件現在唯一的驗收方式是「以 `pipeline/en/is_ocr=true` 重新解析後」再跑一遍。所有下列數字必須在**新 bundle** 上重測並更新（§9 R-3）。舊 bundle 的數字只用來驗證程式邏輯（在 `--allow-gated-out-for-dryrun` 下跑 dry-run）。

### 過濾（F 組，dry-run on 現行 bundle）

| id | 條件 | 預期 |
|---|---|---|
| F-1 | 候選數 | 111（全部 `type=header`；`footer` 0 個，標記 `unexercised`） |
| F-2 | 消音數 | 111，`held` = 0 |
| F-3 | 被消音字串詞彙表 | 恰 2 種：`'Equivalent Networks'` × 67、`'C'` × 44 |
| F-4 | P2 幾何 | 候選 `max(y1) = 76`、正文 `min(y0) = 100`，空隙 24，無重疊 |
| F-5 | P1 一致性 | 111/111 找到同 type、IoU ≥ 0.6 的 discarded block（實測 IoU min 0.918 / median 0.920 —— 上限 0.92 而非 1.0，是 0–1000 量化的系統性損失） |
| F-6 | P6 PDF 文字層 | 抽驗 10 項 100% 相符 |
| F-7 | `count_unchanged` | `len(after) == 556` |
| F-8 | `only_text_field_changed` | 445 個未動項目 canonical JSON 逐一相同 |
| F-9 | `body_chars_unchanged` | `type=="text"` 字元數不變（31 192） |
| F-10 | `page_footnote_preserved` | 3 個逐位元組不變 |
| F-11 | **`ir_char_delta_exact`** | **恰好 `-1428`**（= 1317 + 111） |
| F-12 | IR 噪音殘留 | `'Equivalent Networks'` 69 → **2**；headings 完全相同 |
| F-13 | `coverage.tsv` | 頁面覆蓋 67/68（缺 p0 = 標題頁，正常）；`'C'` 變體僅 44/68 → **anomalies 必須列出這 24 頁** |
| F-14 | `detect_residual_running_head` | 過濾**前**命中 `'Equivalent Networks'`(67 頁) 與 `'C'`(44 頁)；過濾**後**命中 **0** |
| F-15 | 百分比報表 | 三個分母全部輸出：4.05% / 5.72% / 0.97%，且標明 |

### 修補（R 組）

| id | 條件 | 預期 |
|---|---|---|
| R-1 | 表格分類 | 57 張：`MISSING_KEY` **16**、`EMPTY_SHELL` **0**、`IMG_WITH_TEXT` **28**、`IMG_ONLY_NO_TEXT` **0**、`OK` 13 |
| R-2 | 修補目標 | **16 張**（idx 381/391/397/435/440/448/454/459/467/472/477/508/512/519/524/529，p26/28/29/39/40/42/43/44/46/47/48/56/57/59/60/61）。**28 張 `IMG_WITH_TEXT` 一張都不能被碰** |
| R-3 | rect 證明 | C1/C3 對 16 張全過；C2 不適用（`table_caption` 全為 `['']`） |
| R-4 | V1/V2 截斷 | 16 張 `finish_reason == "stop"`，全部以 `</table>` 結尾 |
| R-5 | **V8 負向控制** | 16 張的 `recall_self − max(recall_neighbours) ≥ 0.15`。**若不成立，該文件對帳指標宣告無效，16 張全進人工佇列**（依實測跨表 recall mean 0.79 / median 0.88，這一關很可能觸發 —— 觸發是正確行為） |
| R-6 | V12 分母 | 各表 gt 唯一 alpha token 實測 10–23；唯一數字 4–6 → **多數會落在 `< 6` 而標 `unverified`**。預期 `unverified` 張數 > 0 並列入人工佇列 |
| R-7 | V11 覆蓋率 | 寫入每張的 `verdict.json`；文件層彙總預期 ≈ 0.53 |
| R-8 | 人工抽驗 | 前 20 份文件階段 → 16 張 **100% 人工比對 crop.png**，錯 0 張 |

### 提交與驗證（A / V / X 組）

| id | 條件 | 預期 |
|---|---|---|
| A-1 | `apply` 不帶 `--commit` | 磁碟 `content_list.json` sha256 仍為 `sha256:7dbaf491…`，size 仍 243 468 |
| A-2 | `--commit` 後 | `is_bundle_valid()` 回 **True**；`critical_file.size == len(bytes)`（非字元數）；`critical_file.sha256` 由重讀檔案計算 |
| A-3 | 中斷模擬 | 在步驟 3 與 5 之間 kill → `--resume` 先跑 `repair-manifest` → `is_bundle_valid()` 回 True → 續跑成功 |
| A-4 | 併發保護 | 手動改動 `content_list.json` 後 apply → 樂觀鎖 ABORT，exit 2，磁碟未變 |
| V-1 | `verify --deep` | IR：blocks 19、equations 76、**tables 41 → 57**、headings 不變 |
| V-2 | `tables.json` | entry 數 41 → **57**；每張被修補的表 ≥ 2 個儲存格文字命中 |
| V-3 | `self_ref` 穩定 | 修補前後所有既有 entry 的 `self_ref` 逐一相同（例：`content_list.json#/6` 仍是 `#/6`） |
| X-1 | `reindex --commit` | 容器 log 出現 `[mineru] raw cache hit doc_id=…` |
| X-2 | `.parsed/` 更新 | `blocks.jsonl` mtime > commit 時間；否則 `INDEX_STALE` + 非零退出 |
| X-3 | INDEX-VERIFY | 索引內 `'Equivalent Networks'` 出現在 block 的次數 == 2 |
| X-4 | 下游指標 | chunks / entities / relations 重測後與 pre 值並列輸出（pre = 59 / 807 / 1324）。**不設門檻**，只要求人看過並在 `report.json` 簽字。合理預期：chunks 略減（1428 字元）、entities 減少（書眉不再被抽成實體）、relations 隨之變動 |
| X-5 | `--cleanup-archived` | 列出並清掉 `<stem>_001.pdf` 這類 re-ingest 殘留 |
| S-1 | `selftest` | fixture 全綠，含「被誤標成 header 的 `text_level` 項目必須 held」「截斷回應必須 reject」 |
| S-2 | `revert --to origin --commit` | `content_list.json` sha256 回到 `sha256:7dbaf491…`，size 回到 243 468，`is_bundle_valid()` True |
| S-3 | `--replay` | 刪掉 bundle → 重新解析 → `--replay` 拒絕（sha 不同）；bundle 位元組還原後 `--replay` 通過且 VLM 呼叫數 = 0 |

---

## 9. 已知風險與接受的取捨

### 9.1 接受的風險（明確不處理）

| id | 風險 | 為什麼接受 |
|---|---|---|
| **R-1** | **消音無法防「MinerU 把正文行系統性標成 header」** | P1/P5 同源已降級，P6（PDF 文字層）只能證明「這個 bbox 裡確實是這串字」，不能證明「這串字是不是正文」。P2/P3 能擋大部分（正文不會全部落在頂帶、不會在 67 頁重複），但一段重複出現、用詞在別處也出現的真內容（多頁表格的續表欄標題、每頁重複的條款標頭）三道全過。**接受，靠 F-13 的每頁計數表 + 抽驗 10 項讓它可見。** |
| **R-2** | **反向失效（書眉被標成 `text`）本工具無法自動修** | 自動化這裡就要引入字串比對，那會殺掉 idx 0 / idx 3 這種標題。`detect_residual_running_head` 只回報不動手。**接受。** |
| **R-3** | **所有校準數字量自一份注定被丟棄的 bundle（vlm/ch）** | 磁碟上目前只剩 1 份 `.mineru_raw`，另外 9 份抽樣的原始資料已不存在，設計裡的數字無人能複驗。`pipeline+OCR` 的 content_list 可能有不同 type 詞彙、不同表格切分、不同 bbox。**處置：`plan` 必須在重新解析後的新 bundle 上重跑校準，並把校準集（≥10 份的 content_list.json + layout.json）存進 `records/env/<run>/calibration/`。在校準完成前，本工單所有數字都標記為 `provisional`。** |
| **R-4** | **V5 只擔保 52.7% 的儲存格** | 剩下 47.3% 是數學與單字元。V6（數值 precision）+ V10（列數）部分覆蓋，但「整欄符號被吃掉」仍可能通過。**接受，靠 V11 誠實揭露 + 人工抽驗。** |
| **R-5** | **`$…$` 內容只做結構性計數**（`\frac`/`\sum`/上下標數量），不做語義比對 | 沒有第二個獨立的數學 OCR 來源。工單已確認一次人工比對完全正確，但 n=1。**接受，且前 20 份文件的表格 100% 人工看。** |
| **R-6** | **`IMG_WITH_TEXT` 的 28 張表不修** | 它們大多是正常的表，`<img>` 是電路符號圖。少數真的該修的會被漏掉。**接受 —— 漏修是可見的（`status` 把「未修復缺陷張數」當一級輸出），誤修是不可見的。** |
| **R-7** | **`--replay` 依賴渲染器輸出穩定** | poppler 版本變動會讓 crop bytes 改變 → artifact key 全滅 → 需重跑 VLM。**接受，靠 bbox 量化 + `meta.json` 記錄 poppler 版本緩解。** |
| **R-8** | **需要容器在跑才能執行任何權威檢查（D1 的代價）** | CI 無法離線跑；每次 exec 約 0.3–1 s。**接受 —— 替代方案（自己重算 signature）是本專案最危險的靜默失效溫床。** |
| **R-9** | **X-4（chunks/entities/relations）不設門檻** | 實體抽取有 LLM 隨機性，設門檻只會製造假警報或假安心。**接受，改成強制人工簽字。** |
| **R-10** | **390 份的人工抽驗成本** | 前 20 份 100% 人工看表格（若每份 16 張，約 320 張 × 1 分鐘 ≈ 5.3 小時）。**接受 —— 這是「有產出 ≠ 產出正確」的唯一解，不能省。** |

### 9.2 誠實的自我修正

- 設計文件原本寫「五道誤刪防護」，實際只有 **兩道獨立（P2、P3）+ 一道半獨立（P4）+ 一道新增獨立（P6）+ 兩道一致性檢查（P1、P5）**。文件必須這樣寫，否則後續維護者會依賴一個不存在的安全邊際。
- 設計文件原本寫「工單記的 5.6% 重現不出來，所以門檻按實測訂」—— 實際上 5.6% 完全對得上 IR 分母（5.72%）。依 A4 原則，契約數字對不上就該查清楚，不該當註腳帶過。已查清並寫入 A-20。
- 設計文件原本把 `total_size_bytes` 列為「必須更新的三個欄位之一」—— 實際上它**根本不被 `is_bundle_valid` 檢查**。真正致命的只有 `critical_file.size` 與 `.sha256`。這個認知偏差會讓人把心力放錯地方。
- 原本三份設計都把「MinerU 解析後、LightRAG 建 IR 前插隊」當作前提 —— **那個時間窗在程式上不存在**。整個 W9 是為此新增的。
- 原本的 `table_status()` 兩個分支都 return `IMG_ONLY`，是死碼；且把 28 張正常表誤分類成缺陷。已修。

---

## 附錄 A — 審查缺陷處置對照表

| 來源 | 缺陷 | 處置 | 位置 |
|---|---|---|---|
| safety D1 | 備份放 `.mineru_raw/` 會被 `clear_dir_contents` 刪掉 | **採納**：全部移到 `records/`；A-09 靜態檢查；`apply` 拒絕在 `FORCE_REPARSE` 下執行 | §6.1, A-08/A-09, §7.3 |
| safety D2 | P1/P5 同義反覆，五道實際只有 2.5 道 | **採納**：P1/P5 降級為一致性檢查；新增 P6（`pdftotext` 文字層）；文件改寫成「兩道獨立 + 一道半獨立 + 一道新增 + 兩道一致性」 | §4 W3, §9.2 |
| safety D3 | 沒有任何閘門在驗結果，IR-diff 是免費的（0.02 s） | **採納**：IR-diff 成為 `apply` 的強制閘門，含精確字元差 `-1428` | §4 W7.1, F-11/F-12 |
| safety D4 | `table_status` 的 IMG_ONLY 是死碼且分類錯誤 | **採納**：拆成 `IMG_WITH_TEXT` / `IMG_ONLY_NO_TEXT`；28 張永不修；`status` 把未修復缺陷當一級輸出 | §4 W4, R-1/R-2 |
| safety D5 | manifest/content_list 兩次寫入非原子；size 必須用 bytes；`total_size_bytes` 不被驗證 | **採納**：固定順序 + fsync + 重讀重算 + post-condition；未 commit 一律回滾不 resume；新增「manifest 不一致」狀態 | §4 W7.2, A-2/A-3 |
| safety D6 | 雙取樣一致性不是獨立證據 | **採納**：降為 soft 記錄；改用 V6/V7/V8/V10 | §5.2 |
| safety D7 | V5 只覆蓋 52.7%；空集合真空通過 | **採納**：V11 覆蓋率記錄 + V12 分母下限 + V6 數值 precision + `$…$` 結構計數 | §5.2, R-6/R-7, §9.1 R-4/R-5 |
| safety D8 | 量級護欄分母未定義，差 6 倍；5.6% 其實可重現 | **採納**：改用精確預測比對，% 只留報表；A-20 記錄三個分母 | §4 W3, F-11/F-15, §9.2 |
| safety D9 | 升級時最先垮的是「讀哪個檔案」，替代檔已在 bundle 裡 | **採納**：U-1；A-03 常數檢查 + L3 端到端（唯一能抓到「改對了但沒效果」） | §7.2 U-1 |
| ops 1 | `apply --commit` 全綠後索引一個字都不會變 | **採納**：新增 W9 `reindex` + `REINDEX`/`INDEXED` 狀態；`verified` 重新定義；正確配方明文寫進 README | §4 W9, X 組 |
| ops 2 | 對帳無鑑別力（97% 錯配通過 0.40）；crop 與 gt 同 bbox | **採納**：V8 負向控制 + IDF 過濾 + 恢復數字比對 + V7 LCS 順序；rect 正確性由 C1/C2/C3 獨立證明 | §5.2, §4 W5 |
| ops 3 | 校準數字量自注定被丟棄的 bundle | **採納 + 明確接受殘餘風險**：P-2 使本文件 GATED_OUT 是正確行為；`plan` 必須在新 bundle 重跑校準並存 calibration set；所有數字標 `provisional` | P-2, §9.1 R-3 |
| ops 4 | 只有「刪太多」防護，沒有「刪太少」偵測 | **採納**：`detect_residual_running_head`（與 type 無關）+ `coverage.tsv` | §4 W3, F-13/F-14 |
| ops 5 | `discarded_blocks` 含 3 個真 `page_footnote` | **採納**：P1 要求授權 block 的 type 與 item type 相同；`page_footnote`/`table`/`equation` 型 discarded block 永不作為授權來源 | §4 W3 P1 註 |
| ops 6 | IoU 未綁頁碼；書眉每頁幾何相同 | **採納**：A-14 斷言 `pdf_info[k].page_idx==k` + `page_size` 一致；同頁 discarded 文字多重集合對帳 | A-14, F-5 |
| ops 7 | VLM 截斷完全沒被檢查；無 `api_key` 欄位 | **採納**：V1 `finish_reason` + V2 `</table>` 結尾 + `max_tokens=4096` + `completion_tokens` 記錄；`VLMConfig.api_key` | §4 W6, R-4 |
| ops 8 | 無原子性；`--require-idle`；records 存全檔非 diff；fsync | **採納**：`--require-idle` 預設且不可關閉 + 全程輪詢；records 存 pre/post 全檔；兩檔皆 fsync + 目錄 fsync | §4 W7.2, §6.1 |
| ops 9 | 傳輸錯誤寫成 `failed`，`--resume` 跳過 | **採納**：新增 `transport_error` 狀態 + exit 5；`--resume` 會重試 | §3.3, 退出碼, §4 W6 |
| evolve S1 | 刪除 item 讓 `self_ref` 位移（實測 `content_list.json#/6`） | **採納**（結論相同，機制不同）：不刪除、消音（`text=""`）。明確拒絕 `type→page_number` 替代方案並說明理由 | §4 W3, V-3 |
| evolve S2 | 45% 錯配通過；只管 recall 不管多出什麼 | **採納**：同 ops 2，V6 precision ≥0.95、V12 分母下限、V8 鑑別度、V10 結構對帳 | §5.2 |
| evolve S3 | crop 與 pdftotext 共用 rect，rect 錯了兩邊一起錯 | **採納**：C1（`pdftotext -bbox-layout` vs layout spans）、C2（caption）、C3（origin vs source 同 rect 抽字） | §4 W5 |
| evolve S4 | 來源 PDF 路徑寫死是錯的（已被 archive 搬走） | **採納**：A-13 內容定址解析，三候選逐一比 `source_content_hash`；`page_size` 整數截斷 0.4 pt 誤差明列 | A-13, §4 W2, P-4 |
| evolve S5 | layout 背書零資訊；`page_footnote` 在 discarded 裡 | **採納**：同 safety D2 + ops 5 | §4 W3 |
| evolve S6 | 無事務；manifest 可從磁碟重算 → 自癒 | **採納**：`repair-manifest` 子命令，`--resume` 第一步無條件執行；post-condition `is_bundle_valid` | §4 W7.3, A-3 |
| evolve S7 | 最可能的毀滅是操作員 UI 刪檔；標記檔在同一爆炸半徑 | **採納**：放棄 raw_dir 內標記檔；L2 audit cron；正確配方明文；`delete_file=False` 強制 | §6.1, §7.1 L2, §7.3 |
| evolve S8 | 「修補正確」與「索引正確」之間沒被驗證 | **採納**：INDEX-VERIFY（§5.3）+ `INDEX_STALE` 狀態 + 非零退出 | §5.3, X-2/X-3 |
| evolve S9 | 容器內 4 份 lightrag，探針可能探錯 | **採納**：A-01 回報 `lightrag.__file__` + 四份 md5 + `/proc/1` cmdline/PYTHONPATH | A-01, §7.2 U-4 |
| evolve S10 | 三條 hard invariant 恆真，形成假覆蓋；`body_chars` 會恆假 | **採納**：刪掉三條裝飾性 invariant（移到 verify 當跨規則檢查）；換成有方向性的 `suppressed_subset_of_repeated`；W1 修 `parse-check.py` L69 把 header 從 `字元數` 拆出 | §4 W3 invariant 表, §4 W1 |