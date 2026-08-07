# 工單 `SPEEDUP-2.1-R3` — 修量測設計（第二次 BLOCK 的解鎖條件）

你是 codex terra。上一輪你修好了九項，終審席（sol）第二次判 **BLOCK**，
但**只擋在量測設計那兩條**。這一輪範圍很窄，不要動已經修好的東西。

判定原文：
`/tmp/claude-1000/-home-florian-ghq-github-com-neknufelet-florian-dker/7d2e7c2e-57ae-427d-ab70-6a02b03b6f6b/scratchpad/verdict-r2.txt`
**先讀完**（特別是「順序／cache 控制 — 修得不對」與六點回判的第 1、2、5 點）。

## 為什麼這條非修不可（先理解，否則會修成表面功夫）

llama.cpp 預設開 prompt cache。我們的做法是**拿同一批題目重播多輪**，
所以第二輪起同一題的 prompt 幾乎不用重算 —— 量到的是快取命中，不是吞吐量。
反序跑不能解決：快取是累積的，反序只是換個方向沾光。warm-up 又用了題本的
第一題，等於先幫第一個併發度把快取暖好。

**真實負載剛好相反**：正式抽取時每個 chunk 的 prompt 都不同，快取命中接近零。
所以我們要量的是**冷 prefill 的吞吐**，那才像 390 份跑起來的樣子。

## 必修（只有這四項）

### A. 關掉 prompt cache，並且量得到它有沒有真的關掉

- 請求體加 `"cache_prompt": <bool>`，由新旗標 `--cache-prompt` 控制，
  **預設 `false`**。
- 報告的 `config` 區要記下這個值。
- 每個 run 統計 **`cache_tokens_total`（Σ`timings.cache_n`）** 與
  `cache_hit_n`（題數）。**兩個都要**——上一輪只有題數，分不出
  「命中 1 個 token」與「命中數千 token」。
- **`cache_prompt=false` 卻出現 `cache_tokens_total > 0` ⇒ 這是異常**：
  表格要標警告，並把該 run 標 `valid=false`（理由寫清楚）。
  這條是「探針要在沒人問的時候會響」：如果哪天 llama.cpp 不再理會這個參數，
  我們必須當場知道，而不是拿一份被快取灌水的數字去做決定。
- 表格加一欄顯示 `cache_tokens_total`。

### B. warm-up 不准用題本裡的題

改用**固定的合成 prompt**（例如重複一段與題本無關的文字到約 2,000 字元），
且不得與任何題本題目相同。報告記 `warmup: {"used": true, "source": "synthetic",
"prompt_sha256": …}`。

### C. 順序效應的統計要有方向

`max-min` 把方向丟掉了：100→80 與 80→100 都印同一個 20。改成每個併發度報：

- 每一輪的 `tok_s_aggregate` **全部列出**（不要只給彙總純量）
- `relative_spread` = (max-min)/mean
- `direction`：後面的輪次比前面**快**還是**慢**（用第一輪與最後一輪比，
  明確給正負號或 `faster`/`slower`/`flat`）

表格印一行結論，講清楚「有沒有觀察到順序效應、往哪個方向」。

### D. `/props` 抓不到不得 fail-open

現在抓不到只警告、整體仍可能 exit 0。改成：抓不到 ⇒ 整體 exit 非 0，
並在報告記 `server: {"error": …}`。理由同 A 的最後一段——一份無法自證
「量的是哪顆模型、哪個 build、幾個 slot」的報告，不該長得像一份好報告。

## 順手改一行文件（sol 的第 3 點，判 not-real 但名字會誤導）

`prefill_tok_s`／`decode_tok_s` 是**伺服器端的 pooled rate**（Σtokens÷Σms），
與牆鐘的 `tok_s_aggregate` 是不同的尺。公式本身正確，但表格與 JSON 要註明
這件事，不要讓人以為它們可以互相取代或相加。

## 測試（補這四項，其餘不動）

1. 請求體真的帶 `cache_prompt`，且預設是 `false`。
2. `cache_prompt=false` 但回應的 `timings.cache_n > 0` ⇒ run `valid=false`。
3. warm-up 用的 prompt 不在題本內（比對 sha256）。
4. 順序統計會報方向：造兩輪一快一慢的假資料，`direction` 要正確，
   且反過來時 `direction` 也要跟著反。

## 不要動

- 上一輪已修好的九項（失敗 run invalid＋非零退出、prefill/decode 分開、
  `finish_reason`／截斷、逐題明細、`--out` 覆寫保護、Docker 錯誤標籤、
  slot 警告、seed、`/props` 原樣保存）。
- `--repeat` 的反序機制**保留**（它對線性時間漂移仍有用），只是不再假裝
  它能處理 cache。

## 驗收條件

- `uvx --quiet pytest tests/test_llm_bench.py -q` 綠（**你的 sandbox 連不到
  PyPI 跑不了，這是已知的**——由主線親跑。你只要確保 `py_compile` 過、
  邏輯自洽，並誠實說明哪些沒驗）。
- 三個 `--help` 在無 `.env` 下仍要能印。
- 仍**不必**實跑 `run`。

## 交付格式

最後輸出：① 動了哪些檔 ② A–D 每項一行怎麼修的 ③ 沒驗證到的部分。
