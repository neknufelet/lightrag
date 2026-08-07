# 工單 `SPEEDUP-2.1-R4` — 第三次 BLOCK 的最低解鎖條件

你是 codex terra。終審席（sol）第三次判 BLOCK，但 A、B、D 都判**已修**，
只剩四件事。**範圍很窄，不要重寫、不要動已修好的部分。**

判定原文：`/tmp/claude-1000/-home-florian-ghq-github-com-neknufelet-florian-dker/7d2e7c2e-57ae-427d-ab70-6a02b03b6f6b/scratchpad/verdict-r3.txt`
**先讀完整份**。

## 必修（四項，sol 明列的最低解鎖條件）

### 1. warm-up 要暖到每一個 slot

現況只送**一題**（雖然已改成 synthetic，題本污染那半已解），
但伺服器有 4 個 slot，一題只會碰到一個。第一個受測併發度因此可能在
未達穩態時被量。

改成：warm-up 以 **`max(--concurrency)` 的併發度**同時送出同一個 synthetic
prompt（送 `max(--concurrency)` 份），全部丟棄不計入任何統計。
報告的 `warmup` 區要記 `concurrency`、`requests`、成功數與 sha256。
warm-up 本身失敗（例如全部逾時）⇒ 整體 exit 非 0，不要默默往下跑。

### 2. 不准用 `max != min` 宣告「有順序效應」

現況 `observed = max != min`，浮點抖動也會被宣告成順序效應。而且只有兩輪，
**本來就分不出漂移與隨機雜訊**。改成：

- 新增 `--order-threshold`（預設 `0.05`）。
  `observed` 只在 `relative_spread > threshold` 時為 true。
- 結論字串要**明說輪數**與它的極限，例如：
  「2 輪、relative_spread 3.1%（門檻 5%）：未觀察到順序效應；
  **兩輪無法分辨漂移與雜訊，要下結論需要 `--repeat` 更多輪**」。
- `relative_spread`、每輪數值、`direction` 全部保留（那些 sol 判已修）。

### 3. 報告加一個「快取重用比例」欄位

**這是本輪最有價值的新資訊**，理由見下方「為什麼」。

- 每個 run 加 `cache_hit_ratio` = `cache_tokens_total / prompt_tokens`
  （分母為 0 時記 `null`，不要除零）。
- 表格加一欄顯示它（百分比）。

### 4. 補三個測試（sol 逐條點名的覆蓋缺口）

- **多題**的 `Σcache_n` 真的有加總（現在的 cache 測試只有一題，證不了加總）。
- **多輪**的結果一路進 JSON 與表格（現在只測 `_order_effects` /
  `_round_concurrency_orders` 這兩個 helper 的回傳值，沒測整路徑）。
- `main()` 在 `/props` 失敗時**回非 0 的退出碼**（現在只測到
  `_run_benchmark()` 回 False）。

## 為什麼要第 3 項（sol 糾正了主線的判斷，你要理解才不會修成裝飾）

主線先前判斷「正式抽取每個 chunk 的 prompt 都不同 ⇒ 快取命中接近零 ⇒
關快取才像真實負載」。**sol 判這只對一半，它是對的**：

llama.cpp 重用的是**共同前綴**，不要求整份 prompt 相同。而 LightRAG 的抽取
prompt 把一大段固定指令放在 chunk 內容**之前**，所以不同 chunk 之間仍共享
很長的前綴 —— 正式跑的時候**是會吃到快取的**。

所以兩種量法都需要，而且用途不同：

| 量法 | 怎麼跑 | 代表什麼 |
|---|---|---|
| 冷 | `--cache-prompt false` | 乾淨的壓力測試與 **MTP A/B 對照組**（每題完整 prefill） |
| 溫 | `--cache-prompt true --repeat 1` | **像真實負載**（每題只打一次，前綴自然重用） |

`cache_hit_ratio` 就是用來讀第二種：它會直接告訴我們正式抽取實際重用了
多少 prompt token。**這不需要新的模式或新的旗標**，現有 CLI 就跑得出來，
你只要把這個比例算出來、印出來。

## 不要動

A（`cache_prompt` 與 cache 統計）、B 的 synthetic warm-up prompt 本身、
D（`/props` 不 fail-open）、prefill/decode pooled rate 的定義註記、
失敗 run invalid＋非零退出、逐題明細、`--out` 覆寫保護、反序排程。

## 驗收條件

- `uvx --quiet pytest tests/test_llm_bench.py -q` 綠（你跑不了，主線親跑）。
- 三個 `--help` 在無 `.env` 下仍可印。
- 仍不必實跑 `run`。

## 交付格式

最後輸出：① 動了哪些檔 ② 四項各一行怎麼修的 ③ 沒驗證到的部分。
