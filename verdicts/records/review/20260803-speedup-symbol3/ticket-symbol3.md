# 工單 `SYMBOL-3.1` — 量「符號型實體實際被檢索命中幾次」`scripts/symbol-hits.py`

你是 codex terra。這是**一般票**（唯讀查詢，不寫 DB、不改 `.env`、不動閘門判準、
不在 canary 追蹤的八個量裡、預估 diff < 200 行）。

## 先讀

1. `CLAUDE.md`（藍桶 9 條、六條鐵則、「規則分兩類」、常用指令）
2. `NEXT.md` 的 `SYMBOL-1`／`SYMBOL-2` 兩節與「`SYMBOL-3`」那條待辦
3. `scripts/entity-merge.py` —— **特別是檔頭 docstring 與 `cmd_plan()`
   （`scripts/entity-merge.py:163`）與 `Rag`（`:117`）**。這是本票判準的來源。
4. `scripts/extract-check.py` 的 `--dump-symbolic`（`:125` 附近）
5. `tests/symbol1-answer-key.json` 的結構
6. `scripts/mineru_common.py` 的 `load_env` / `add_workspace_arg` 慣例

## 要回答的問題（先看懂再寫）

`SYMBOL-1` 用 50 題人工答案卷把 1,482 個「符號型／驗不了」實體分成三類：
`restated` 27（外推 601–990 個）、`correct` 19、`wrong` 4。

`restated` 的性質是「名字實質就是符號本身」（例 `S Sub 0 N Squared` ＝ 把
S_{0,n}² 唸出來）。它們**不會給出錯誤答案**，只是佔索引空間。

**所以決策卡在一個沒量過的數字：它們實際被檢索命中幾次。**

這正是 `rebuild-plan` 階段 4 對實體碎片化用過的判準——當時量出「254 組
從未出現在任何檢索結果裡」，結論是「254 次不可逆操作換 0 收益 ⇒ 不合併」。
**本票要用同一把尺**，否則今天的結論沒辦法跟那個決策相互比較。

## 交付

1. `scripts/symbol-hits.py`
2. `tests/test_symbol_hits.py`（至少一個 smoke test）

**不要**動其他既有檔案。

### CLI

```
symbol-hits.py --symbolic <FILE> [--answer-key tests/symbol1-answer-key.json]
               [--workspace WS] [--queries 30] [--top-k 40] [--out FILE]
```

- `--symbolic`：`extract-check.py --dump-symbolic` 產出的檔（**必填**）。
  **不要自己重算符號桶**——判準 `SYMBOLIC_RATIO` 的 SSOT 在 `extract-check.py`，
  複製一份出來就會有兩個會漂移的定義。
- `--answer-key`：預設 `tests/symbol1-answer-key.json`。

### 判準（必須與 `entity-merge.py cmd_plan` 逐項相同）

- 查詢種子＝`GET /graph/label/popular?limit=<--queries>`。
  **不要自己編查詢**——`entity-merge.py` 的檔頭寫了理由：編出來的會偏向
  自己想得到的主題，熱門標籤反映的是這個知識庫實際被檢索時的樣子。
- 每個查詢＝`POST /query/data`，body **逐項相同**：
  `{"query": q, "mode": "mix", "only_need_context": true,
    "top_k": <--top-k>, "chunk_top_k": 1}`
  （`chunk_top_k=1` 的理由在 `entity-merge.py:155`：只要實體清單，
  設 0 會被當成「不限制」。）
- 「命中」＝該實體名出現在回傳的 `data.entities[].entity_name`。
  **同一個查詢裡出現兩次算兩格**（我們量的是佔格位，不是有沒有出現過）。

**這三件事要有測試釘住**（見下方「測試」），因為判準一旦與 `entity-merge`
分岔，兩份結論就不能互相比較了，而且分岔不會有錯誤訊息。

### 要輸出的兩個視角（缺一不可）

**視角① 受控對照 —— 答案卷 50 題按 `verdict` 分組**

| verdict | n | 命中總格數 | 有被命中的實體數 | 每實體平均格數 |
|---|---|---|---|---|
| restated | 27 | ? | ?/27 | ? |
| correct | 19 | ? | ?/19 | ? |
| wrong | 4 | ? | ?/4 | ? |

**只看 `restated` 的絕對值判不出東西**——要跟 `correct` 比才知道
「是這一類特別不被檢索到」還是「符號型整桶都不太被檢索到」。
比例要附 Wilson 95% CI（`SYMBOL-1` 用的同一套，n 很小，不附區間會過度解讀）。

**視角② 佔格位 —— 全 1,482 符號桶**

- 總實體格位數（Σ 每個查詢回傳的實體數）
- 其中屬於符號桶的格數與佔比
- 符號桶裡**有被命中**的相異實體數 ／ 1,482
- **從未被命中的相異實體數**（這個數字直接對應階段 4 的「254 組」）

### 三個必須做的健全性檢查（不做會把 0 讀成錯的意思）

1. **母體對得上嗎**：答案卷的 50 個名字、符號桶的 1,482 個名字，
   是否都出現在 `GET /graph/label/list` 裡？**對不上的要單獨列出**——
   一個不在標籤清單裡的實體**永遠不可能被命中**，那個 0 的意思是
   「名字對不上」而不是「不被檢索」。兩者混在一起會得到完全錯誤的結論。
2. **名稱比對用精確比對**，不要正規化。但要**回報**有多少個
   「大小寫或空白不同就對得上」的近似名，讓人知道精確比對漏掉了什麼。
3. **查詢失敗要分開記**（逾時／HTTP／解析），失敗數 > 0 時在輸出明確標示
   「本次統計母體不完整」，不要讓一個少跑了 10 個查詢的結果長得像完整結果。

### 輸出

- stdout：人讀的兩張表 ＋ 一行結論句。
- `--out`：JSON（含 `queries`（實際用到的種子清單）、`entity_slots`、
  兩個視角的原始數字、健全性檢查結果、失敗統計）。
  **`--out` 目標已存在時拒絕覆寫，除非 `--force`**（與 `llm-bench.py` 一致）。

## 約束

- **唯讀**：只打 `/graph/label/list`、`/graph/label/popular`、`/query/data`。
  不得寫 DB、不得改 `.env`、不得碰容器。
- 標準庫以外不得引入依賴（照 `entity-merge.py` 用 `urllib.request`）。
- 藍桶 3（type hints，禁裸 `Any`）、6（`with`）、7（`pathlib`）。
- `scripts/` 的 `print` 是輸出可以用；診斷訊息（重試、失敗）走 `logging`。
- 函式超過 50 行先想能不能拆。
- **`Rag` 那個 client 不要 import `entity-merge.py`**（檔名有連字號，
  import 會很醜，而且那支帶有破壞性的 `apply` 路徑，不該被牽動）。
  自己寫一個最小的唯讀 client，**並在註解寫明它是刻意的重複、
  以及為什麼參數必須與 `entity-merge.py` 保持一致**。

## 測試

1. 請求 body 的參數與 `entity-merge.py` 逐項相同 —— **讀 `entity-merge.py`
   的原始碼把那組字面值比對出來**（`mode`／`only_need_context`／`chunk_top_k`），
   分岔就紅。這條是本票最重要的測試。
2. 同一查詢裡同名實體出現兩次要算兩格（不是去重成一格）。
3. 答案卷裡有名字不在 label list 時，會被列進「對不上」而不是算成 0 命中。
4. 查詢失敗時輸出會標「母體不完整」。
5. `--out` 覆寫保護。

## 驗收條件

- `uvx --quiet pytest tests/test_symbol_hits.py -q` 綠
  （**你的 sandbox 連不到 PyPI 跑不了，這是已知的**，由主線親跑；
  你只要確保 `py_compile` 過、邏輯自洽，並誠實說明哪些沒驗）。
- `--help` 要能在**沒有 `.env`** 的情況下印出（coder 上沒有 `.env`）。
- 你**不必**實跑（要 dker 的服務與 DB），主線在驗證回程親跑。

## 交付格式

最後輸出：① 動了哪些檔 ② 每個公開函式一行說明 ③ 你**沒有**驗證到的部分。
