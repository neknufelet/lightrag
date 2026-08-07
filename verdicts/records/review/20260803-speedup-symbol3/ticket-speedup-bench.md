# 工單 `SPEEDUP-2.1` — 受控吞吐基準工具 `scripts/llm-bench.py`

你是 codex terra，本專案唯一的實作者。這是**一般票**（唯讀量測工具，不動資料、
不動閘門判準、不改 `.env`、不碰 canary 追蹤的八個量）。

## 先讀（不要跳過，這個專案的規則都是踩坑換來的）

1. `CLAUDE.md` —— 特別是「藍桶規則 9 條」「座標與身分」「常用指令」「六條鐵則」。
2. `NEXT.md` —— 「效能（擴量前）」整節，`SPEEDUP-1`/`-2`/`-3` 的實測結論。
3. `scripts/mineru_common.py` —— `load_env()` 與 `add_workspace_arg()` 的慣例，
   照用，不要自己重寫讀 `.env` 的邏輯。
4. `scripts/entity-merge.py` 的 `Rag` class（`scripts/entity-merge.py:117`）——
   HTTP 呼叫的風格範本（`urllib.request`，不引入新依賴）。
5. `deploy/llama-qwen36-moe/compose.yaml` —— 被量測的那台伺服器的完整參數。

## 背景（為什麼要這支）

要決定 390 份擴量前怎麼加速，但**現在沒有尺**：

- 伺服器開著 4 個 slot（`--parallel 4`，啟動 log `n_slots = 4`），
  dker 的 live `.env` 卻是 `MAX_ASYNC=2` —— 4 個 slot 只餵 2 路。
- MTP 那條路要求 `n_parallel=1`，與併發**方向相反**，兩條互斥。

沒有受控基準，任何 A/B 都只能講感覺。這支就是那把尺，之後 MTP 換檔 A/B 也用它。

## 要交付什麼

1. `scripts/llm-bench.py` —— 兩個子命令。
2. `tests/test_llm_bench.py` —— 至少一個 smoke test（藍桶第 8 條）。

**不要**碰其他既有檔案。**不要**接進 `daily-check.sh`，**不要**做成閘門
（tok/s 會隨 GPU 溫度與別的負載自然抖動，做成閘門只會製造假紅燈 —— 這與
鐵則 6 不衝突：探針要在沒人問的時候會響，但這個量沒有穩定的「該響」門檻）。

### 子命令 `fixture` —— **只在 florian-dker 跑得起來**（要 DB）

從 `lightrag_llm_cache` 撈真實的抽取請求當負載。**不要自己編 prompt**：
編出來的 prompt 長度與結構都不像真的，量出來的 tok/s 沒有意義。

```
llm-bench.py fixture --n 8 --out <PATH> [--workspace WS] [--seed 20260803]
```

- 來源：`select id, original_prompt, return_value, chunk_id from lightrag_llm_cache
  where workspace = %s and cache_type = 'extract'`（**每一句 SQL 都要帶
  `workspace` 條件** —— CLAUDE.md 記載過漏掉會把兩個 workspace 併成一列）。
- 抽樣：**固定種子的排列取前綴**，與 `tests/symbol1-answer-key.json` 同款
  （`sampling` 欄位寫的那套）。這樣日後 `--n` 加大時，前面的題不會換掉。
- 輸出 JSON：`{"generated_from", "workspace", "seed", "n", "items": [
  {"id", "chunk_id", "prompt", "reference_output", "prompt_chars", "output_chars"}]}`
  外加整個 `items` 的 `sha256`（**基準要能證明兩次跑的是同一份題本**）。
- 母體現況（2026-08-03 實測，供你判斷合理值）：`extract` 1,019 筆，
  prompt 平均 15,742 字元／最大 67,062，輸出平均 5,042 字元。
- **輸出路徑不要預設進 repo**：題本含論文原文，`$RECORDS`（`/data/rag/lightrag/
  <ws>/records/`）才是它的家。`--out` 必填。

### 子命令 `run` —— **在 florian-coder 跑**（llama.cpp 在這台）

```
llm-bench.py run --fixture <PATH> [--host http://100.71.26.77:8080]
                 [--concurrency 1,2,4,8] [--max-tokens 2048] [--out <PATH>]
```

- 對 `POST {host}/v1/chat/completions` 發，`Authorization: Bearer <key>`。
  金鑰來源：`--api-key`，或 `LLAMA_API_KEY` 環境變數。**不要**去讀
  `deploy/llama-qwen36-moe/.env`（那是部署設定，不是工具的設定來源）。
- 請求體：`{"model": <--model，預設 "qwen3.6-35b-a3b">, "messages":
  [{"role":"user","content": prompt}], "temperature": 0, "seed": <固定>,
  "max_tokens": <--max-tokens>, "stream": false}`。
  **`temperature=0` 是刻意的**：貪婪解碼下同輸入應得同輸出，這是之後 MTP
  「加速有沒有改變行為」那一關的判準基礎。
- 每個併發度都跑**同一組** prompt（題本全部），否則不公平。
- 併發用 `concurrent.futures.ThreadPoolExecutor`，**不要**引入 asyncio/aiohttp
  或任何新依賴（這個 repo 全程只用標準庫）。
- 每個併發度之間要有短暫間隔讓伺服器排空（例如 5 秒），並在輸出裡記下來。

**要量的（缺一不可）**

| 量 | 怎麼算 |
|---|---|
| `wall_s` | 該併發度整輪的牆鐘時間 |
| `completion_tokens` | 各回應 `usage.completion_tokens` 加總 |
| `prompt_tokens` | 同上加總 |
| `tok_s_aggregate` | `completion_tokens / wall_s` ← **這是主結論** |
| `latency_p50` / `latency_max` | 單一請求的秒數 |
| `errors` | 失敗數與型別（逾時要與 HTTP 錯誤分開記） |
| `output_sha256` | 每題輸出的 sha256 |

**決定性比對（重要，不要省）**：同一題在不同併發度下的 `output_sha256`
是否相同？不同就代表併發本身會改變輸出，那是比 tok/s 更重要的發現，
輸出裡要有一行明確講「N/M 題跨併發度逐字相同」。
另外與題本的 `reference_output` 比對**只當參考不當判定**——那些是
`MAX_ASYNC=2` 時代、採樣參數未知的舊快取，不相同不代表錯。

- 輸出 JSON（`--out`，預設印到 stdout）：含 `host`、`model`、`fixture_sha256`、
  `started_at`（由呼叫端傳入或用 `time.time()`，不要假裝有時區智慧）、
  每個併發度一筆 `runs`，以及一段人讀的表格印在 stdout。

## 約束（違反即退單）

- **唯讀**：不得寫任何 DB、不得改 `.env`、不得重啟或改動任何容器。
- 藍桶 3：**所有函式簽名要有 type hints，禁止裸 `Any`**。
- 藍桶 6：HTTP 連線與檔案都用 `with`。
- 藍桶 7：路徑一律 `pathlib.Path`。
- 藍桶 4 的既有例外：`scripts/` 是薄 CLI 層，`print` 是它的**輸出**，可以用；
  但診斷訊息（重試、逾時）走 `logging`。
- 標準庫以外**不得引入任何依賴**（`psycopg`／`asyncpg` 除外，且僅限 `fixture`
  子命令——照 `scripts/extract-check.py` 現有的連線方式，不要自己發明）。
- 單一函式超過 50 行先想能不能拆（藍桶 5）。

## 驗收條件

1. `python3 scripts/llm-bench.py --help`、`... fixture --help`、`... run --help`
   三個都要能印出說明**而不要求 `.env` 存在**（在 coder 上沒有 `.env`；
   `mineru_common.add_workspace_arg` 的 docstring 記載過 2026-08-03 sol 抓到的
   同型 bug：讀不到 `.env` 時連明確給參數都救不了）。
2. `python3 -m pytest tests/test_llm_bench.py -q` 綠。
3. `run` 在**題本不存在**時給明確錯誤，不是 traceback。
4. 你**不必**實際跑 `run`（會佔滿伺服器 slot，由主線在驗證回程親跑）。
   但 `fixture` 的 SQL 與抽樣邏輯要有單元測試（可用假資料）。

## 交付格式

改完後在最後輸出：① 動了哪些檔 ② 每個公開函式一行說明
③ 你**沒有**驗證到的部分（誠實列出，這比宣稱全綠有用）。
