# 工單 `SPEEDUP-2.1-R2` — 依終審意見修 `scripts/llm-bench.py`

你是 codex terra。上一輪你交的 `scripts/llm-bench.py` + `tests/test_llm_bench.py`
被終審席（sol）判 **BLOCK**。這一輪修它，**不要重寫**，也不要動別的檔。

判定原文在 `/tmp/claude-1000/-home-florian-ghq-github-com-neknufelet-florian-dker/7d2e7c2e-57ae-427d-ab70-6a02b03b6f6b/scratchpad/verdict.txt`，**先讀完整份**。

## 這支工具是幹嘛的（先對齊目的，否則會修錯方向）

它的數字要決定兩件事：① dker 的 `MAX_ASYNC` 要不要從 2 調到 4；
② 要不要換一顆帶 MTP 頭的 GGUF（19.4 GB）。sol 的核心判斷是
**現在的數字不能撐這兩個決定**。所以這輪的目標不是「補功能」，是
**讓每一個印出來的數字都能被信任，或明確標成不可用**。

## 必修（阻斷級，逐項都要有對應測試）

### A. 失敗的 run 必須自我標記為不可用

現況：`_run_once()` 用「成功題的 completion tokens ÷ 整輪 wall_s」算
`tok_s_aggregate`，`latency_p50`／`max` 又只取成功題 ⇒ 有逾時時數字被稀釋
卻長得很正常。

- 每個 run 加 `"valid": bool` 與 `"invalid_reason": str | None`；
  `errors.total > 0` ⇒ `valid=false`。
- 表格那一列要**明顯**標出（例如整列後面加 `⚠ INVALID`），不是只在 JSON 裡。
- 有任何 run `valid=false` ⇒ `main()` 回傳非 0。
- `latency_p50`／`latency_max` 旁邊要記 `success_n`，讓人看得出分母是誰。

### B. 分開量 prefill 與 decode（**這一條對 MTP 評估最重要**）

MTP 加速的是**生成段**，不是讀 prompt 那段。用整段 wall clock 量，MTP 的效果
會被 prompt eval 稀釋，可能得到「MTP 沒用」的假結論。

llama.cpp 的 `/v1/chat/completions` 回應帶 `timings` 物件
（`prompt_n`、`prompt_ms`、`predicted_n`、`predicted_ms`、`cache_n`）。
現在整個丟掉。要：

- 逐題保存 `timings`。
- 每個 run 另外報 `prefill_tok_s`（Σ`prompt_n` ÷ Σ`prompt_ms`）與
  `decode_tok_s`（Σ`predicted_n` ÷ Σ`predicted_ms`）——**這兩個是伺服器端
  計時，與牆鐘的 `tok_s_aggregate` 是不同的尺，兩個都要，不要互相取代。**
- `timings` 欄位若不存在（版本差異）不得整支炸掉：記 `timings_available: false`
  並在表格註明，其餘照跑。

### C. 截斷要抓得到

不讀 `finish_reason` ⇒ 撞 `max_tokens=2048` 被截斷仍算成功，tok/s 卻是假的
（生成被硬切）。逐題記 `finish_reason`，每個 run 統計 `truncated_n`；
`truncated_n > 0` 要在表格標出。**截斷不必然使 run invalid**（那是題本設定問題，
不是量測失敗），但一定要看得見。

### D. 順序與 prompt cache 效應

現況固定 1→2→4→8 依序重播同一批 prompt，llama.cpp 有 prompt cache ⇒
後跑的併發度可能沾光。要：

- 加 `--repeat N`（**預設 2**）。第 1 輪照 `--concurrency` 給的順序，
  第 2 輪**反序**。報告記每輪的順序，並對同一併發度報跨輪的
  `tok_s_aggregate` 差異（`max-min`）。**差異大就是順序效應的證據**，
  要在表格印一行結論。
- 整個掃描開始前先送一題 warm-up（不計入任何統計），報告記 `warmup: true`。
- 逐題記 `timings.cache_n`；每個 run 統計 `cache_hit_n`（`cache_n > 0` 的題數），
  不為 0 要標出。

### E. Provenance：報告要能證明「量的是哪一顆模型」

換成 MTP GGUF 之後，`--model` 這個 alias 不會變，報告本身必須能分辨。
開跑前打伺服器的 `/props`（llama.cpp 有這個端點，回 `model_path`、
`build_info`、`n_ctx`、`n_parallel` 等），把回來的東西原樣收進報告的
`server` 欄位。**打不到 `/props` 不得靜默跳過**：記 `server: {"error": ...}`
並在表格印警告。報告另外要記 `max_tokens`、`request_timeout_s`、
`concurrency`、`repeat`、`fixture` 路徑與 `fixture_sha256`。

### F. 逐題明細要留

只存 aggregate ⇒ 無法定位 outlier、無法重算共同成功母體。
報告加 `items` 陣列：每題的 `id`、`concurrency`、`round`、`latency_s`、
`prompt_tokens`、`completion_tokens`、`finish_reason`、`timings`、
`output_sha256`、`error_type`。

### G. 兩個小的

- `--out` 目標已存在時**拒絕覆寫**，除非加 `--force`。（fixture 與 run 都要。）
- `_extract_rows()` 的錯誤訊息：`docker exec` 失敗時要講清楚是
  **「找不到容器 X —— 這裡把 .env 的 `POSTGRES_HOST` 當成容器名用」**，
  不要一律說成「psql 失敗」。sol 判這條 real。

## 不必修（sol 判 not-real，別浪費時間）

- 抽樣種子與生成種子共用：本票無實害。
- `--concurrency` 含 8 而伺服器只有 4 slot：排隊本來就是飽和測試的一部分，
  end-to-end latency 本來就該含排隊，可以同表比較。
- 決定性比對「悄悄退出母體」：已有 `comparable` 與總題數當分母，不算靜默。

## 測試（藍桶第 8 條，這輪要補厚）

現有 4 個測試沒有覆蓋成功回應的解析。至少補：

1. 成功回應解析（含 `timings`、`finish_reason`、`usage`）——用假的 HTTP 回應，
   **不要真的打網路**。
2. 有 timeout 時 run 被標 `valid=false` 且 `main()` 回非 0。
3. `finish_reason="length"` 被算進 `truncated_n`。
4. `timings` 缺席時不炸、`timings_available=false`。
5. `--out` 已存在時拒絕覆寫、加 `--force` 才寫。
6. `--repeat 2` 的第二輪順序是反的（可只測產生順序的純函式）。

## 驗收條件（已依實況修正）

- **測試指令改成 `uvx --quiet pytest tests/test_llm_bench.py -q`**。
  上一輪寫 `python3 -m pytest` 是我出單的錯：coder 上 `python3` 與 `uv run`
  都沒有 pytest（sol 與主線各自親跑確認）。**請在 `tests/test_llm_bench.py`
  的 docstring 第一行寫明這個跑法**，免得下一個人再踩。
- 三個 `--help` 仍要能在**沒有 `.env`** 的情況下印出說明。
- `run --help` 的說明要寫明：**這會佔滿伺服器的 slot，跑之前確認 dker 沒有
  在跑索引**（上一輪工單有寫，你漏了，sol 判 real）。實際開跑前也要在 stderr
  印一次同樣的警告（含 host、題數、併發度、輪數）。**不要加互動確認**——
  這支會在非互動環境跑。
- 你**仍然不必**實跑 `run`（會佔滿 slot），由主線在驗證回程親跑。

## 交付格式

最後輸出：① 動了哪些檔 ② 上面 A–G 每項一行「怎麼修的」
③ 你**沒有**驗證到的部分（誠實列出）。
