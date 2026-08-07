# 工單 `SYMBOL-3-R2`：`symbol-hits.py` 重票修正（終審 BLOCK 補正）

> 背景一句話：這支工具的數字要拿去下 `SYMBOL-3` 的決策（600–990 個 `restated` 實體動不動），
> 且日後要當「改抽取 prompt 前後」的對照器。前一輪以一般票收線、416 行 diff 未走重票，
> 終審 BLOCK。本單即重票補正：修健全性閘門、補 provenance、換掉假綠測試、修統計呈現。
> R2 = 同一 gate 第二輪（字母語意見 CLAUDE.md 命名規則）。

## 目標

把 `scripts/symbol-hits.py` 從「會算數字的報告器」改成「敢擋人的量測儀」：

1. 輸入不一致、母體對不上、查詢缺漏時**以非零 exit code 擋下**，不印可比較結論。
2. JSON 報告可完整稽核：每個數字都能回溯到「哪個查詢、哪個實體、哪一格」。
3. 判準一致性測試從「AST 讀 3 個常數」升級為「兩支程式實際執行的請求與計數逐項對照」。
4. 統計呈現誠實：普查不掛 CI、差值附差值的 CI、estimand 白紙黑字寫進輸出。
5. 保持與 `entity-merge.py cmd_plan` **同一把尺**——查詢參數、種子來源、計數語義一項不改。

## 先讀什麼（依序）

1. `CLAUDE.md`——藍桶 9 條、六條鐵則（特別是鐵則 6「探針要在沒人問的時候會響」）、「規則分兩類」。
2. `NEXT.md` 的 `SYMBOL-1`／`SYMBOL-2` 兩節——這些數字是本工具服務的決策脈絡。
3. `scripts/symbol-hits.py`（本票標的，287 行）。
4. `scripts/entity-merge.py` 檔頭 docstring、`Rag`（:117）、`cmd_plan()`（:163）——**判準 SSOT，一行都不准動**。
5. `tests/test_symbol_hits.py`（現有 5 測，部分要改寫）。
6. `tests/symbol1-answer-key.json` 頂部 metadata 與 `scripts/extract-check.py` 的 `--dump-symbolic` 寫出區塊（約 :174–:186）——健全性閘門要驗的欄位就是這兩份的欄位。

## 必修項

### 必修 1：兩段式健全性閘門（報告 → 擋板）

**為什麼**：終審指出三個「健全性檢查」全是報告不是擋板——label 對不上仍 exit 0、
`answer_key_not_in_symbolic` 算了從未印出或使用、輸入 metadata（`workspace`／`population`／`n`）全被丟掉不驗。
沉默縮小的分母比錯的分母更危險。

**怎麼改**——閘門分兩段，exit code 定義如下並寫進 docstring 與 `--help`：

| exit | 意義 |
|---|---|
| 0 | 量測完成且全部閘門通過 |
| 2 | 輸入／用法錯誤（argparse、pre-flight 失敗、`--out` 已存在無 `--force`、labels/popular 端點取不到） |
| 3 | 量測階段閘門未過（label 覆蓋缺漏、非預期查詢失敗）——報告照印照寫（`health.ok=false`），但**不印結論句** |

**Pre-flight（打任何網路之前，失敗 → `SymbolHitsError` → exit 2）**：

- `workspace` 三方一致：`--workspace` == symbolic dump 的 `workspace` == answer key 的 `workspace`。
- symbolic dump：`generated_from == "extract-check.py --dump-symbolic"`；`counts.entities == len(entities)`。
- answer key：`n == len(items)`；`tally` == 實算各 verdict 計數；`population == symbolic dump 的 counts.entities`
  （population 對不上＝答案卷抽樣的不是這份母體，兩份輸入不同世代）。
- **`answer_key names ⊆ symbolic names`**：差集非空即失敗，逐名列印。這就是終審點名「算了不用」的
  `answer_key_not_in_symbolic`，從欄位升格為擋板。
- `BIND_ADDR`／`HOST_PORT` 在 env 缺任一 → 失敗。**刪掉現在的字面預設 `100.87.88.7`／`9621`**
  （`_ReadOnlyRag.__init__:45`）——與 `add_workspace_arg` docstring 同一條原則：猜錯的預設不報錯，只安靜打錯服務。

**量測閘門（exit 3）**：

- **label 覆蓋，在跑 30 個查詢之前判**：取得 `/graph/label/list` 後立即檢查 answer key 與 symbolic
  全部名字都在 labels 裡（精確比對）；有缺即列印全部缺名＋near matches、寫報告、exit 3，
  **不再花 30 次 LLM 關鍵詞抽取**。缺名代表 dump 過期或 workspace 錯，正解是重產 dump，不是縮分母。
- **非預期查詢失敗數 == 0**（定義見必修 2）。有失敗照原樣印「母體不完整」區塊、exit 3。

閘門結果全部落 JSON：`health.gates = [{id, status: "pass"|"fail", detail}]`、`health.ok`。
閘門 id 用描述性名（`workspace_consistent`、`answer_key_subset_of_symbolic`、`labels_cover_symbolic`、
`queries_complete`…）。列印遵守鐵則 6 收合規則：通過時印「閘門 N/N 通過」，失敗逐條全列。
`"exact_matching": true` 這個假檢查結果刪除，改為方法描述子 `"name_matching": "exact"`。
near matches ≤10 個時終端全列，不再只印數量。

**怎麼驗**：測試要求 T6–T9；dker 演練見驗收條件 3。

### 必修 2：`C0` 這類結構性失敗要分類，不是擋也不是忽略

**為什麼**：熱門標籤裡 `C0` 只有 2 字元，`/query/data` 要求 ≥3，每次必 400——
`entity-merge.py` 踩同一個。若「任何查詢失敗」都 exit 3，工具**永遠紅**，
就是 NEXT.md 對 `retrieval-check.py` 說的「永遠亮紅的假訊號」，閘門會被習慣性無視。
但也不能靠 pre-filter 跳過不打——那會讓本工具的 HTTP 行為偏離 `cmd_plan`（它有打、被 400、跳過）。

**怎麼改**：照打不誤（與 `cmd_plan` 行為逐項相同）。`QueryFailure` 加 `code: int | None` 欄位；
probe 迴圈中，`HTTP 400 且 len(seed) < 3` 分類為 `known_short_seed`——記錄於
`query_execution.known_short_seed`（含種子名與 detail）、印在健全性區塊，**不觸發閘門**。
其餘一切失敗（timeout、network、parse、其他 http）觸發 `queries_complete` 閘門。
記帳恆等式：`requested == succeeded + known_short + unexpected_failures`，寫進報告並在測試裡斷言。

**怎麼驗**：T8。

### 必修 3：Provenance——每個數字可回溯

**為什麼**：終審指出現在無法稽核「那 5 個被命中的 restated 是誰、被哪個查詢命中、是不是種子自撞」——
主線是繞路自己算的。要改寫決策的數字必須自帶審計軌跡。

**怎麼改**——JSON 報告補齊（`schema_version: 2`，破壞舊格式是刻意的，舊報告是 BLOCK 前證據不需相容）：

```
schema_version, generated_from, generated_at_utc（timezone.utc ISO8601）,
git_commit（subprocess `git -C <REPO> rev-parse HEAD`，失敗時 "unknown"，不得因此中斷）,
workspace,
service:  { host, label_count, labels_sha256 }     ← sha256(sorted labels 以 "\n" join 的 UTF-8)
inputs:   { symbolic:   { path, sha256, workspace, entities },
            answer_key: { path, sha256, population, n, seed, tally } | null }
config:   { requested_queries, top_k, seed_source: "popular" | "file:<sha256>" }
estimand: （必修 4 的固定字串）
queries:  [全部種子，含失敗的]
per_query:[{ index, seed, entities: [回傳順序、重複保留] }]   ← 只含成功查詢
query_execution: { requested, succeeded, known_short_seed: [...], failures: [...] }
view_1_answer_key | null, view_2_symbolic_bucket,
hits:     { answer_key: [50 列全列，含 0 命中：{name, verdict, hit_slots, hit_queries: [{query_index, slots}]}],
            symbolic_hit_map: {name → {hit_slots, query_indices}}（只列 ≥1 命中者；0 命中可由輸入檔差集導出）}
health:   { ok, name_matching, gates, near_matches, seed_overlap }
```

- `seed_overlap`：answer key 名字 ∩ 種子、symbolic 名字 ∩ 種子（精確比對），各列名單與計數。
  種子自撞問題從「繞路人工查」變成報告原生欄位；配合 `hit_queries` 可直接看出某實體是否只被自己的種子命中。
  **不是閘門**（母體與熱門標籤重疊是資料性質不是錯誤），但終端必印。
- **單一來源**：`view_1`／`view_2`／`hits` 的所有聚合數字必須由 `per_query` 記錄用同一個函式導出，
  不得在 probe 迴圈裡另外累加一份（現在 `entity_slots`／`symbolic_slots` 就是迴圈裡另算的——改掉）。

**怎麼驗**：T10（自洽性：從報告的 `per_query` 獨立重算聚合值，斷言相等）。

### 必修 4：統計呈現——estimand、普查去 CI、差值補 CI、結論句模板

**為什麼**：終審四類指摘中最重要的一類。`hit/1482` 是固定探針下的**普查**，Wilson CI 用錯不確定性來源；
兩組各自 CI 重疊被讀成「沒有差異」；23–24% 被說成「吃掉四分之一檢索脈絡」而它只是
API 回傳實體條目的佔比。下一個讀報告的人會拿錯的話去下決策。

**怎麼改**：

- **`estimand` 區塊**（JSON ＋ 終端報告開頭都要，固定字串照抄）：

  ```
  probe_set:    "固定探針普查：/graph/label/popular 前 N 個標籤（或 --seeds-file 重播），
                 mode=mix、top_k=40、chunk_top_k=1——與 entity-merge.py cmd_plan 同一把尺"
  population:   "extract-check.py --dump-symbolic 的符號型實體全集（本次 N 個）"
  exact:        "view_2 全部數字是本探針集下的普查確值，不附 CI"
  estimated:    "view_1 各 verdict 組命中率：由 50 題隨機樣本（seed=20260803 排列前綴）外推到
                 該 verdict 子母體『在本探針集下』的命中率；Wilson 95%，無 FPC（子母體大小未知，偏保守）"
  not_valid_for:
    - "使用者查詢流量下的命中率或脈絡佔比（探針＝熱門標籤，非真實流量；已知會被少數大文件壟斷，
       見 docs/rebuild-plan.md 階段 4）"
    - "context/token 佔比（格位＝API 回傳實體條目數，未計 description、關係、chunk、token）"
    - "『兩組沒有差異』的結論（小樣本；看差值區間寬度）"
  ```

- **view_2（全桶）**：刪掉 `hit_entity_wilson_95`。普查確值：`hit_entities`、`never_hit_entities`、
  `symbolic_slots`、佔比（欄位改名 `entity_entry_share`）。
- **view_1（答案卷各組）**：保留各組 Wilson CI（估計對象重新標定如上），另新增：

  ```
  difference_restated_minus_correct:
    { p_restated, p_correct, diff, newcombe_95: [lo, hi] } | null（任一分母為 0）
  ```

  Newcombe（1998 method 10 / MOVER）公式，直接用既有 `_wilson`：
  `d = p1 − p2`；`lo = d − sqrt((p1−l1)² + (u2−p2)²)`；`hi = d + sqrt((u1−p1)² + (p2−l2)²)`，
  其中 `(l1,u1)`、`(l2,u2)` 為兩組 Wilson 界。只做 restated−correct 這一對（決策相關的那一對）；
  其他配對可從 JSON 自行算，不進印出。**不做 Fisher exact**（理由見異議節 3）。
- **結論句模板**（照抄，僅代入數字；禁止出現「脈絡」「context」「四分之一」「沒有差異」「等價」）：
  1. 若 restated 命中數 ≥1：「『restated 永遠不會被檢索命中』不成立：本探針集（N 個成功查詢）下
     27 個 restated 有 X 個被命中。」（=0 時印命中 0，不下全稱斷言。）
  2. 「restated − correct 命中率差 = D pp，Newcombe 95% 區間 [L, U] pp；
     本樣本無法偵測小於此區間寬度量級的差異，也無法排除區間內的大差異。」
  3. 「本探針集下 API 回傳的實體格位中，符號桶佔 X%（格位＝實體條目數；
     未計 description／關係／chunk／token；探針＝熱門標籤，非使用者流量）。」

  現在那句「以同一批熱門標籤查詢可直接比較」刪除。

**怎麼驗**：T11–T12（印出內容測試：禁用語不出現、模板句條件性出現、view_2 無 wilson 鍵）。

### 必修 5：判準一致性測試改「執行級對照」

**為什麼**：現測只 AST 讀 3 個常數。`cmd_plan` 明天改種子端點、去重、改預設值，五測仍全綠——
終審判為部分假綠。「同一把尺」的證據必須來自兩支程式**實際執行**的行為對照。

**怎麼改**：見「測試要求」T1–T5。實作端配合項：`main()` 內的 `_ReadOnlyRag` 必須經模組層名稱建構
（`_ReadOnlyRag(env)`，不 inline import），讓測試能以 monkeypatch 注入假 client 走完 `main()` 全路徑。

### 必修 6：對照器模式（`SYMBOL-3` 改 prompt 前後要能比）

**為什麼**：PO 已拍板 `SYMBOL-3` 走「改抽取 prompt」，本工具是前後對照器。改 prompt 後的語料
熱門標籤會變，探針跟著漂，前後數字就不是同一把尺量的。

**怎麼改**：

- `--seeds-file <path>`：JSON 陣列（或含頂層 `queries` 陣列的舊報告物件——方便直接重播上一次的探針）。
  與 `--queries` **互斥**（argparse mutually exclusive group）。使用時 `config.seed_source = "file:<sha256>"`，
  終端必印：「本次探針為重播固定種子，非本庫當前熱門標籤；與 entity-merge plan 的探針不同批」。
  預設仍是 `popular`（與 `cmd_plan` 同源）。
- `--no-answer-key`：跳過 view_1 與 answer key 相關閘門（`view_1_answer_key: null`、`hits.answer_key` 省略、
  結論句 1／2 不印），只做全桶普查。新語料還沒有對應答案卷時的合法跑法——
  population 閘門會逼使用者在「附上匹配的答案卷」與「顯式宣告不用」之間二選一，不允許沉默錯配。

**怎麼驗**：T13。

### 必修 7：結構整理（藍桶）

- `_measure` 現在 32 行，加了 per_query 記錄與閘門後必超 50 行——**先拆**：
  建議 `_preflight()`（輸入一致性）→ `_gate_labels()`（覆蓋檢查）→ `_run_probes()`（只跑查詢、回 per_query＋失敗分類）→
  `_aggregate()`（由 per_query 導出兩個 view 與 hits）→ `_assemble_report()` → `_print_report()`；
  `main()` 只做編排與 exit code。每個函式 ≤50 行。
- 全部函式帶 type hints，禁裸 `Any`（沿用現有 `object` 風格即可）；診斷走 `logging`（現有 `LOG.warning` 模式），
  報告本文用 `print`（本專案 `scripts/` 的既有例外）；檔案 I/O 一律 `with`＋`pathlib`（現狀已符合，維持）。
- 新增 import 僅限標準庫：`hashlib`、`math`、`datetime`、`subprocess`（只用於 `git rev-parse`，失敗不中斷）。

## 不要動什麼

- **`entity-merge.py` 一行都不動。** 它是判準 SSOT，測試對它唯讀。它的字面 host 預設同病，但那是另一張單（已記異議節 5）。
- **`extract-check.py`、`mineru_common.py` 不動。** 發現需要改就寫進回報，不自作。
- **判準本身不動**：`/graph/label/popular` 種子來源與順序、`mode=mix`、`only_need_context=true`、
  `top_k` 預設 40、`chunk_top_k=1`、回傳重複實體保留（同名兩次算兩格）、失敗查詢跳過不中斷——
  **一項都不准「順手改良」**，包括不得去重、不得排序實體、不得改打其他端點。
- **唯讀鐵律**：只打 `/graph/label/list`、`/graph/label/popular`、`/query/data` 三個端點。
  **不打 `/health`**（服務快照用 label 指紋代替）。不寫 DB、不碰 `.env`、不碰容器；
  除 `--out` 指定的檔案外不寫任何東西。
- `tests/symbol1-answer-key.json`、`tests/symbol2-results.json` 不動。
- 不引入標準庫以外的依賴。
- 不改 `NEXT.md`／`CLAUDE.md`（主線收線時更新）。

## 測試要求

改寫 `tests/test_symbol_hits.py`。既有 5 測的意圖保留（重複計格、缺名分列、母體不完整、`--force`），
配合新 schema 調整；純 AST 三常數那條**由 T1 取代**。新測全部離線（monkeypatch `urllib.request.urlopen`
或注入假 Rag），`entity-merge.py` 以 `importlib` 從路徑載入（同現有 `_module()` 手法，模組名 `entity_merge`）。

| # | 測試 | 斷言 |
|---|---|---|
| T1 | 請求執行級對照 | monkeypatch urlopen，分別呼叫 `entity_merge.Rag.entities_for(q, 40)` 與 `symbol_hits._ReadOnlyRag.entities_for(q, 40)`，捕捉 (method, path, 解析後 body)——**兩支逐項相等**。killed mutant：`cmd_plan` 改任何請求欄位即紅 |
| T2 | 種子端點與順序 | 兩支 `popular(7)` 的 URL 相同；餵固定假清單，兩支回傳皆順序保留、不去重、不排序 |
| T3 | 重複／空名處理對照 | 假回應 entities 含 `[A, A, ""]`，兩支回傳**相同**清單 `[A, A]` |
| T4 | 預設值對照 | AST 讀 `entity-merge.py` main() 中 plan 子命令 `--queries`／`--top-k` 的 `default=` 字面值，與 `symbol-hits` parser 實際解析出的預設相等（AST 在此只讀字面預設，是輔證不是主證） |
| T5 | `cmd_plan` 計數對照 | monkeypatch `entity_merge.Rag` 為假 client（一個查詢含重複實體、一個查詢 raise）、`entity_merge.DATA_ROOT`→tmp_path，跑 `cmd_plan`；讀其寫出 JSON 的 `entity_slots`，與 `symbol_hits` 在等價假資料下的 `entity_slots` 相等，且兩支都在失敗查詢後繼續 |
| T6 | pre-flight 閘門 | workspace 三方不一致、`tally` 不符、`population` 不符、answer key ⊄ symbolic——各 case exit 2、訊息含具體欄位／名字、**未發出任何網路請求**（monkeypatch urlopen 設為必炸即可證明） |
| T7 | label 覆蓋閘門 | 假 labels 缺一個 symbolic 名 → exit 3、缺名印出、**`entities_for` 未被呼叫**（省 30 次查詢那條）、`--out` 時報告仍寫出且 `health.ok == false`、結論句不出現 |
| T8 | 失敗分類 | `QueryFailure(code=400)` 且種子長度 <3 → `known_short_seed`、exit 0；同 400 但種子長度 ≥3 → 閘門 fail、exit 3；timeout → exit 3。斷言 `requested == succeeded + known_short + failures` |
| T9 | host 無字面預設 | env 缺 `BIND_ADDR` 或 `HOST_PORT` → exit 2，訊息點名缺的鍵 |
| T10 | 聚合自洽 | 假資料跑完後，從報告 `per_query` 用測試自己寫的獨立迴圈重算 `entity_slots`、`symbolic_slots`、各組 `hit_slots`／`hit_entities`，與報告聚合欄位全部相等 |
| T11 | 統計欄位 | `view_2` 無任何 wilson 鍵；`difference_restated_minus_correct` 存在且 `newcombe_95` 包含 `diff`；兩組對調後 `diff` 變號、區間端點對稱互換；一組分母 0 → null；全命中 vs 全未中的極端 case 界限合理（lo ≤ diff ≤ hi、界限在 [−1, 1]） |
| T12 | 印出紀律 | 假資料完整跑：印出含 estimand 區塊與三句模板；不含「脈絡」「四分之一」「可直接比較」；restated 命中 0 的 case 不印「不成立」句 |
| T13 | 對照器模式 | `--seeds-file`（陣列與舊報告兩種形狀）生效、`seed_source` 記 `file:<sha256>`、重播警語印出、與 `--queries` 併用被 argparse 拒絕；`--no-answer-key` 時 `view_1` 為 null、answer key 閘門不跑 |

**結構性限制，工單明講**：實作者的 sandbox **連不到 PyPI**，`uvx --quiet pytest` 在你那裡跑不起來或不可信——
**你的「測試綠」在本專案結構性驗不了，不得寫成事實**。你可以跑 `python3 -m py_compile` 與純標準庫的
自查腳本；測試由主線在 coder 親跑，其輸出才算數（藍桶 9：未驗標 `(未驗)`）。

## 驗收條件

1. **coder**：主線親跑 `uvx --quiet pytest tests/test_symbol_hits.py -q` 全綠，輸出入檔。
2. **dker 實跑**（主線執行；zsh 注意：exit code 用 `; echo EXIT=$?` 不接 pipe）：
   - 正常跑 60 種子＋`--out`：`EXIT=0`（若當前熱門標籤仍含 `C0`，它應出現在 `known_short_seed` 而非閘門失敗）；
     貼 estimand 區塊與三句結論。
   - JSON 抽查：`per_query` 筆數 == succeeded；用一行 python 從 `per_query` 重算 `entity_slots` 與報告相等；
     `hits.answer_key` 50 列全在；`seed_overlap.answer_key` 印出（依主線先前人工查證應為空——不空即是發現，逐名附證）。
   - 壞輸入演練（**用 symbolic dump 的副本改壞，不碰原檔**）：改掉一個名字 → 預期 pre-flight 或 label 閘門非零 exit、名字被印出。
   - `--out` 已存在無 `--force` → `EXIT=2`。
3. **數字連續性**：60 種子下 view_2 的普查數字（此前實測：命中 498/1,482、佔比 23.1%）應與前版一致；
   若有差異，逐項用新 provenance（`per_query`）歸因並寫明。重跑穩定性依賴 LightRAG 的查詢關鍵詞快取 `(未驗,推測)`——
   若不穩定，本身就是要記錄的發現。
4. **終審環境注記**：sol 若親跑 pytest 需 `-s workspace-write --add-dir ~/.cache/uv`（前輪唯讀環境拿不到 uv cache lock，
   導致無第二次獨立 pytest 輸出——這次調度先把路鋪好）。
5. diff 走重票五站；`deepseek` 找碴是否觸發由指揮依路徑清單判（本票不碰 pp/rules，預期不觸發）。

## 交付格式

- 只改兩個檔案：`scripts/symbol-hits.py`、`tests/test_symbol_hits.py`。**只顯式 staging 這兩個檔**；不自行 commit——
  主線驗證回程完成後才提交（本專案跨機鎖步：coder 改 → 主線驗 → commit → push → dker pull → 實跑）。
- 回報必附：①「必修項 → diff 位置」對照表（必修 1–7 逐項）；② 每個列印數字語義變動的清單
  （哪些欄位改名、哪些 CI 移除，為什麼）；③ 你未能驗證的事項清單（至少含 pytest）；④ 你對本單的異議（若有）。

## 設計者的異議與判斷

逐條獨立評估過終審四類指摘，結論與差異如下：

1. **票級（終審 §1）**：同意，無異議。本單即程序補正，不需在 code 層做任何事。
2. **健全性（終審 §2）**：同意方向，但補一個終審未展開的反面風險——若「任何查詢失敗」都擋，
   `C0` 這種結構性短種子會讓工具**永遠紅**，重演 NEXT.md 記載的 `retrieval-check.py`「永遠亮紅的假訊號」，
   閘門將被習慣性無視（鐵則 6 的反面）。故設計為分類擋板（必修 2）：已知結構性失敗記錄不擋、其餘一律擋。
   這是收斂不是反對。另外我把 label 覆蓋檢查移到查詢**之前**（終審未要求）：失敗時省 30 次 LLM 關鍵詞抽取，
   且「母體錯了還跑完全程」本來就不該發生。
3. **統計（終審 §4）**：大部分同意——view_2 普查去 CI、報差值與差值 CI、estimand 顯式化，全採。
   兩點保留：
   - **「Wilson CI 用錯不確定性來源」不適用於 view_1。** 答案卷是母體 1,482 的固定種子隨機排列前綴；
     固定探針下每實體命中與否是確定的，隨機性在「誰被抽進樣本」。所以組內命中率的 CI 有正當的估計對象
     （該 verdict 子母體**在本探針集下**的命中率），保留但重新標定、不加 FPC（子母體大小未知，Wilson 無 FPC 偏保守）。
     終審該句對 view_2 成立，對 view_1 是過度概括。
   - **Fisher exact 不內建。** 終審引 Fisher p≈1.00 是為了駁「CI 重疊＝無差異」，不是要求工具算 p 值；
     Newcombe 差值區間已把「偵測不到差異、也排除不了大差異」表達成估計形式，p 值只會誘導
     「p=1 ⇒ 無差異」這種本票正要根除的誤讀。
   - 終審的樣本量計算（275/verdict 等）屬未來研究設計，不進工具；工具的責任止於把區間寬度誠實印出。
4. **假綠測試（終審「判準與假綠」節）**：同意。改為執行級對照（T1–T5），其中 T5 直接跑 `cmd_plan` 本體
   對照計數——這是「整把尺相同」目前離線可得的最強證據。誠實標界限：live 服務端行為（API 端是否去重等）
   測試蓋不到，由 dker 實跑與數字連續性檢核（驗收 3）補位。
5. **本席額外發現（終審未點）**：
   - `_ReadOnlyRag.__init__:45` 對 `BIND_ADDR`／`HOST_PORT` 落字面預設，違反本專案「猜錯的預設不報錯」原則
     （`mineru_common.add_workspace_arg` docstring 就是同一條的 workspace 版）。本票修 `symbol-hits.py` 側（必修 1）；
     **`entity-merge.py:119` 同病但不在本票範圍**，請主線記回 `NEXT.md`。
   - 報告無時間戳、無服務指紋——已併入必修 3。
   - 0 個成功查詢時 `symbolic_slot_share` 會印 0.0% 而非 N/A（`max(entity_slots,1)` 掩蓋）——新閘門下此路徑
     一律 exit 3，不再有機會印出誤導值。
   - 前輪終審無法獨立重跑 pytest（uv cache lock）是**調度層**問題不是 code 問題，已寫進驗收 4 供指揮鋪路。
