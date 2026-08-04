# lightrag — 聲學知識庫（LightRAG 1.5.5 部署 ＋ MinerU 解析後處理）

> **上位規範**：`~/ghq/github.com/neknufelet/standards/BASELINE.md`（SSOT，唯一可改源；
> 本次同步自 `baseline_version 1.9.0`，`date_modified 2026-08-03`）。
> **注意：那個 repo 只在 florian-coder 上**，florian-dker 沒有。所以下方
> `BASELINE SNAPSHOT` 是核心規則的**唯讀凍結副本**（含版本戳記）——inline 於此是
> 因為被引用的檔不會自動載入 session context，而這個專案有一半的工作在沒有
> standards repo 的那台機器上進行。**勿手改 snapshot 區塊**；要改規則改 BASELINE
> 並 bump `baseline_version`，再同步本區塊。

---

## 座標與身分（每次開工先確認自己在哪）

這個專案有一半的 bug 來自身分搞混——「兩個 workspace 被併成一列」、
「在 v2 的 checkout 驗到 v155 的容器」、「URL 說 v155 但答案來自 v2」，
全是同一族。所以第一段就把座標釘死。

| 維度 | 值 |
|---|---|
| GitHub repo | `neknufelet/lightrag`（單一） |
| branch | `master`（單一；`rebuild/acoustics-v2` 已於 2026-08-03 合併並完成任務） |
| **工作台** | **florian-coder**：`~/ghq/github.com/neknufelet/lightrag`。所有編輯在這裡。worker CLI（codex／opencode）只有這台有 |
| **部署** | **florian-dker**（Tailscale `100.87.88.7`）：同路徑。**唯讀＋只 `git pull`，禁止直接編輯** |
| 資料／容器 | 只在 florian-dker：`/data/rag/lightrag`（解析快取與裁決紀錄）、`lightrag-acoustics_v2` :9621、`kbapi-acoustics_v2` :9700 |
| 儲存後端 | 只在 florian-dker：`lightrag-postgres`（database `lightrag`）＋ `lightrag-neo4j`，資料在 `/data/lightrag`。**2026-08-03 從 DeepTutor 的共用實例搬出**，兩者都是專用實例（`lightrag-neo4j` 只有 `neo4j`／`system` 兩個 database），不再靠 workspace 欄位與 label 跟別的專案共處 |
| LLM binding | **就是 florian-coder 這台**（Tailscale `100.71.26.77`）的 :8080，容器 `llama-qwen36-moe`（`ghcr.io/ggml-org/llama.cpp:server-cuda`，build 10200／`5f55650a7`，模型 `Qwen3.6-35B-A3B-UD-IQ4_XS`，2× RTX 3060）。**跑的是 `--parallel 4`，啟動 log `n_slots = 4`**（2026-08-03 實測）。舊文件寫「第三台」「單 slot」，**兩個都錯**——它不是第三台機器，slot 也不是 1 |
| workspace | **`acoustics_v2`（唯一）**。`acoustics_v155` 已完全退役，文件裡提到它的地方一律是歷史 |

**為什麼 dker 的 checkout 必須唯讀**：雙 checkout 分岔**不會報錯**，只會靜靜分家，
直到某天數字對不上。這與本專案已記載的「兩個 workspace 漏 SQL 條件」同族——
雙來源、無訊號。要在 dker 現場迭代（例如改規則後反覆跑 canary）是可以的，
但收斂後必須回 coder 走正式流程，不要在 dker 上累積未推的改動。

---

## 藍桶規則（9 條，BASELINE SNAPSHOT，勿手改此區塊）

> `baseline_version: 1.9.0`　`rules_sha256: d31afca400873b28`
> （9 條核心規則與上游逐字比對相同，已用程式驗過。1.9.0 相對 1.8.0 的改動
> 在「工作項目命名規則」那個非核心 section，`rules_sha256` 因此未變。）

1. **Read before write**：修改任何檔案前先讀取現有內容，禁止覆蓋未讀的內容。
2. **No silent drops**：任何資料、欄位、邏輯在重構時不得無聲消失；刪除必須明確說明。
3. **Type hints**：Python 函式簽名必須有 type hints；禁止裸 `Any` 作為逃生門。
4. **No print for logging**：使用 `logging` 模組，禁止用 `print` 作為正式 log。
5. **SOLID / single responsibility**：函式和類別只做一件事；超過 50 行的函式先問自己能否拆。
6. **Explicit resource management**：file handle、DB connection、thread 必須用 `with` 或明確 `close()`。
7. **Pathlib over string paths**：路徑全程用 `pathlib.Path`，不靠 `os.path` 字串拼接。
8. **Tests before merge**：新功能必須有對應測試（至少一個 smoke test），無測試的 PR 不得合入主線。
9. **Verify-then-claim（驗證再斷言）**：任何關於「跑著的系統行為／狀態」的陳述（checkpoint、PR、回覆）必須附**驗證指令及其輸出**（curl／`docker exec`／pytest／實測），不得只靠讀 code 推理；未驗證者明確標 `(未驗,推測)`，不混入事實陳述。涉及 baked image／容器／部署的系統，須區分「源碼狀態」與「as-built 跑著的狀態」。

**第 9 條在本專案有加強版**：源碼在 coder、跑著的系統在 dker，兩者**物理隔離**。
在 coder 跑的任何東西只能證明源碼層；凡是 canary 數字、閘門判定、契約斷言、
容器狀態，一律附 dker 上的實跑輸出。這不是紀律問題，是事實問題——coder 上
連 `.env` 都沒有（不進版控），碰 DB 的腳本在那裡根本跑不起來。

**第 4 條的既有例外**：`scripts/` 是薄 CLI 層，`print` 是它的**輸出**不是 log，
維持現狀。`lib` 性質的模組（`scripts/pp/`）不得用 `print` 做診斷輸出。

---

## 溝通方式（人話＋技術話雙軌，BASELINE ≥ 1.6.0 同步）

- **雙軌（先人話、後技術話）**：有結論或設計判斷的回報一律兩段——①**人話**（白話短句、結論先行、非技術背景也讀得懂的因果）；②**技術話**（精確機制、`file:line`、函式／參數名、數值與單位、驗證指令／輸出）。
- **缺一不可**：白話不得省略關鍵技術細節（否則無法驗證／接手）；技術不得取代白話結論（否則抓不到重點）。純確認／瑣碎回覆豁免。
- 與第 9 條互補（技術話須附驗證），與既有風格相容（短句、結論先行、表格節制、decision 用 yes/no 收斂）。

---

## 提交紀律（Commit-on-done，BASELINE ≥ 1.8.0 同步）

- **做完即提交**：完成且驗證（實跑綠）的閘門／工單／明確範圍當場提隔離 commit；禁「done 但 uncommitted」長存。
- **開新線前驗乾淨基線**：`git status` 對範圍乾淨才開工。
- **只顯式 staging**：禁 `git add .`／`-A`；共用檔 hunk-stage；永不提交 `.env`／金鑰。
- **留髒須記**：真須留髒過 session，於 `NEXT.md` 明記「線 X：done、未提交、檔清單」。

**本專案加一條——跨機鎖步**：commit 只發生在 coder。dker 只 `git pull`。
一個線的生命週期是「coder 改 → commit → push → dker pull → **dker 實跑驗證** →
把輸出貼回 commit 或 NEXT.md」。**驗證輸出沒拿到，那條線就還沒 done。**

---

## 執行方針與驗收路由

| 角色 | 職責 |
|---|---|
| 你（product owner） | 決策、範圍確認、驗收 |
| Claude（opus，指揮） | 技術決策討論、出單、調度、對抗驗收、docs |
| codex terra | code 實作（受工單指派） |
| codex sol／luna | 單審與終審 |
| deepseek | 對抗找碴（路徑觸發） |

執行模式：**線性**，不多開平行線。Workflow 是品質工具（對抗驗證、skeptic、
回歸閘），不是人力並行化。

### 一般票（三站＋回程）

```
opus 出單 → codex terra 實作 → sol 終審 → 【驗證回程：dker 實跑】
```

### 重票（五站＋回程）

```
fable 設計成單 → sol 單審 → codex terra 實作
  → deepseek 找碴（碰 pp/rules 或閘門判準時觸發）
  → 終審雙軌：sol（追溯 需求→單→diff→輸出）＋ opus-cold（親跑驗證）
  → 【驗證回程：dker 實跑】
```

**重票觸發清單（命中任一即重票，不由指揮心證）**

1. 動 `scripts/pp/rules/**` 或任何**閘門判準**（門檻、三態界線、`SYMBOLIC_RATIO`）
2. 動 `compat-check.py` 的 `VERIFY-1-A##` 契約斷言
3. **會改變 canary 基準數字**
4. 動 `.env` 的鍵、`compose.yaml`、或任何部署契約
5. 動既有測試語義或體檢表閘門定義
6. **碰資料**：刪除、`reindex`、`apply --commit`、任何寫進 `/data` 或 DB 的操作
7. diff > 200 行

**有疑義＝重票。** 第 6 條是本專案特有的——這裡的資料操作**不可逆**，
而且沒有備份時代的教訓還很新。

**綁住指揮的兩條**：① 指揮**只能升檔、不得降檔**；判為一般票時必須寫明沒有
命中清單哪一條。② 終審**任一方 BLOCK 即不過**，指揮不得推翻。

**沒有人驗自己**：fable 寫設計⇒不進終審；指揮出單調度⇒不寫設計、不當終審
（終審的 Anthropic 席是**冷啟動分身 opus-cold**）。

### worker 速查與呼叫法

**全部 worker CLI 只在 florian-coder。** dker 上只有 `claude`。

| 角色 | worker | 模型 | 池子 |
|---|---|---|---|
| 指揮／對 PO 窗口 | opus | 本 session | anthropic ⚠ |
| 重票設計成單 | fable | Agent tool subagent | anthropic ⚠ |
| 實作 | codex terra | `gpt-5.6-terra` xhigh | openai |
| 單審＋終審 | codex sol | `gpt-5.6-sol` xhigh | openai |
| 終審 Anthropic 席 | opus-cold | Agent tool **冷啟動** subagent | anthropic ⚠ |
| 對抗找碴 | deepseek | `deepseek/deepseek-v4-pro`（opencode） | deepseek |
| 長文審閱／第二意見 | codex luna | `gpt-5.6-luna` xhigh | openai |

```bash
# 實作（模型必帶，否則吃 ~/.codex/config.toml 的全域預設＝sol）
timeout <N> codex exec -C <repo> -s workspace-write \
  -m gpt-5.6-terra -c model_reasoning_effort="xhigh" \
  -o <scratch>/last.txt "$(cat ticket.md)" </dev/null > <scratch>/run.log 2>&1

# 審查（唯讀）
timeout <N> codex exec -C <repo> -s read-only \
  -m gpt-5.6-sol -c model_reasoning_effort="xhigh" \
  -o <scratch>/verdict.txt "$(cat brief.md)" </dev/null > <scratch>/run.log 2>&1

# 對抗找碴
timeout <N> opencode run -m deepseek/deepseek-v4-pro "<PROMPT>" > <scratch>/out.txt 2>&1
```

⚠ **實測踩過的坑**：① `--ask-for-approval` 在 `codex exec` 不存在。
② 本機 shell 是 zsh，`${PIPESTATUS[0]}` 會靜默吃掉 exit code——用 `${pipestatus[1]}` 或別接 pipe。
③ 兩支的 stdout 都有 ANSI＋banner，機器解析用 `-o <FILE>`。
④ `~/.codex/config.toml` 全域是 `gpt-5.6-sol` ＋ `danger-full-access`，
**不帶 `-m`／`-s` 的呼叫都會是 sol ＋ 全機存取**。
⑤ 審查席要能查證就給它 repo（`-C <repo>`）＋額外材料目錄（`--add-dir`）——
只給摘要它只能回「判不準」，實測第一輪就是這樣。
⑥ **prompt 超過 128 KiB 不能當參數傳，要走 stdin：`codex exec - < prompt.txt`。**
上面那個 `"$(cat ticket.md)"` 的慣用寫法對大題本會死在
`argument list too long`。**不是 `ARG_MAX`**（那是 2 MB），是 Linux 的
**單一參數上限 `MAX_ARG_STRLEN` = 128 KiB**。而且錯誤訊息指向 `timeout`
不是 codex（`run:1: argument list too long: timeout`），很容易誤判成別的問題。
實測 2026-08-03：149,890 字元的題本直接失敗，改 stdin 後正常。

**額度紀律**：Anthropic 池是唯一吃緊的。重活優先擺 OpenAI／DeepSeek 池；
親跑驗證幾乎不花 token（綠的時候只回幾行），貴的是讀 diff 與長推理。

---

## 工作項目命名規則

> 格式規則的 SSOT 是 BASELINE「工作項目命名規則」（≥ 1.9.0）。**本節只做兩件
> 上游要求各專案自己做的事**：① 前綴註冊表（本專案有哪些線）②
> 子程序字母的語意定義（上游明寫「由該線自行定義並在專案 CLAUDE.md 註記」）。

**格式**（摘自 BASELINE 1.9.0，勿在此改規則）

```
<前綴><編號>[.<子步>][-<字母><編號>]

前綴    工作線種類。**大寫 ≥4 字母**的描述性縮寫或全名
編號    該線內單調遞增的 gate／步驟，不回頭、不重用
.<n>    子步：同一個 gate 的細分
-<字母><編號>   子程序：一個 gate 底下平行的驗證程序／分析臂／修正輪
```

**單字母不是不能用，是不能「單獨站著」。** 判準只有一條：**這個 label 單獨
出現時，讀者能不能認出它屬於哪條線。**

- ✅ `VERIFY-1-A25`、`REBUILD-4`、`PPWORK-7`
- ❌ `A-25`、`W7`、`階段 4` 光禿禿站著

實務判準：同一份文件內第一次提及必寫全稱；**跨文件引用一律全稱**
（NEXT.md、commit message、工單標題都算跨文件）。

**本專案的子程序字母**（依上游要求在此定義；未在此註冊的字母不得使用）

| 字母 | 語意 | 用在哪條線 |
|---|---|---|
| `A` | assertion，契約斷言 | `VERIFY-1`（`compat-check.py` 的 26 條） |
| `G` | gate，體檢表閘門 | `VERIFY-3`（`ledger.py` 的 8 個） |
| `R` | round，同一 gate 的第 n 輪 | 各線通用（例：`SYMBOL-1-R2` ＝ 50 題考卷的第二輪） |

**狀態標記**（BASELINE 統一 legend）：`✅完成 / 🔵進行中 / ⬜未起 / ⏸暫停 / ⚠️卡住`。
NEXT.md 頂部要維護「狀態總表」（一行一線：當前 item ＋ 標記）。

**前綴註冊表**

| 前綴 | 工作線 | 範圍 | 狀態 |
|---|---|---|---|
| `REBUILD` | acoustics_v2 乾淨重建（原「階段 0–5」） | `REBUILD-0`…`REBUILD-5` | ✅ 完成 2026-08-03 |
| `CUTOVER` | v2 接手上線＋v155 退役 | `CUTOVER-1`…`CUTOVER-4` | ✅ 完成 2026-08-03 |
| `PPWORK` | 後處理實作工單（原 `W0`–`W12`） | `PPWORK-0`…`PPWORK-12` | 大部分完成 |
| `VERIFY` | 驗證程序 | `VERIFY-1`…（見下） | 常態 |
| `BACKUP` | 備份接線與驗證 | `BACKUP-1`… | 進行中 |
| `SYMBOL` | `is_symbolic` 判準重量（含 50 題考卷） | `SYMBOL-1`… | 待做 |
| `SCANNER` | 封閉掃描器進版控、變常駐探針 | `SCANNER-1` | 待做 |
| `SPEEDUP` | MTP 加速評估 | `SPEEDUP-1` | 待做 |
| `SCALEUP` | 擴量到 390 份 | `SCALEUP-1`… | 待做 |

**`VERIFY` 線的編號**（一支檢查腳本一個號）

| label | 工具 | 子程序 |
|---|---|---|
| `VERIFY-1` | `compat-check.py` | `VERIFY-1-A01`…`A26`（契約斷言，缺號 04/08/09/12/15 是歷史刪除） |
| `VERIFY-2` | `postprocess.py canary` | `VERIFY-2-R1`…`R8`（pages/items/mute/held/ratio/tables_total/repairable/review） |
| `VERIFY-3` | `ledger.py summary` | `VERIFY-3-G1`…`G8`（8 個閘門） |
| `VERIFY-4` | `coverage-check.py` | 解析漏詞 |
| `VERIFY-5` | `extract-check.py` | 接地三態 |
| `VERIFY-6` | `parse-check.py` | 解析品質 |
| `VERIFY-7` | `eq-check.py` | 方程式三票多數決 |
| `VERIFY-8` | `compare-ws.py` | 跨 workspace 對照 |

**`A-##` 在程式裡先不改名。** 它是 `compat-check.py --json` 輸出的 `id` 欄，
`/data/rag/lightrag/checks/` 底下的歷史紀錄以它為鍵，改名會讓歷史無法與新紀錄
對照——而那正是漂移偵測的母體。**正解是輸出多帶一個 `suite: "VERIFY-1"` 欄**，
完整 label 由兩者組出來；人讀的地方（文件、工單）一律寫全稱 `VERIFY-1-A01`。
（這一項本身是 `VERIFY-1` 線的待辦，未做。）

---

## 文件地圖

| 檔案 | 內容 | 什麼時候看 |
|---|---|---|
| **CLAUDE.md**(本檔) | 現況、鐵則、每條規則的證據基礎 | 每次開工 |
| [NEXT.md](NEXT.md) | **待辦與進行中**(含刻意不做的決策與理由) | 每次開工 |
| [.claude/skills/onboard-doc-type/SKILL.md](.claude/skills/onboard-doc-type/SKILL.md) | 接入新文件類型的完整流程與常見誤判 | 要加新 PDF、或 preflight 擋下某份 |
| [docs/judgement-flow.md](docs/judgement-flow.md) | **遇到新問題時的決策程序**：偵測 → 驗偵測器 → 分類 → 叫眼睛 → 判不準怎麼辦 | 發現一個沒見過的問題時 |
| [docs/log_20260803.md](docs/log_20260803.md) | **當日工作日誌**：過程與理由（尤其「查完決定不做」的六項與各自的實測依據） | 想知道某個決定當初為什麼那樣下 |
| [docs/rebuild-plan.md](docs/rebuild-plan.md) | **歷史**：`REBUILD-0`…`REBUILD-5` 的階段、閘門與各階段驗收紀錄；體檢表格式 | 想知道某個數字當初怎麼來的 |
| [docs/postprocess-workorder.md](docs/postprocess-workorder.md) | **歷史**：後處理實作工單 `PPWORK-0`…`PPWORK-12`(原 `W0`–`W12`;舊描述誤記為 W0–W14) | 要動 `scripts/pp/` 之前 |
| [README.md](README.md) | 部署、解析選項實測、**備份現況(哪些有、哪些沒有)** | 環境有問題時 |
| [tests/canary-baseline.json](tests/canary-baseline.json) | 金絲雀基準數字 | 不要手改,用 `canary --update` |

## 七條鐵則

踩過坑換來的。違反前先讀工單。

> **與上面藍桶 9 條的關係**：藍桶是**跨專案**的工程基線（唯讀，改要改
> BASELINE）；這六條是**這個領域**的鐵則，從這個專案的實際事故長出來，
> 只在這裡成立。兩者不衝突也不重疊——藍桶講「怎麼寫程式」，這六條講
> 「處理 MinerU 產物時什麼會靜靜地錯」。兩套都要遵守，沒有優先序問題。

1. **`preflight()` 拒絕,不猜。** 遇到未知型別就停整份文件。
   用不適用的規則硬跑會產生「有產出但產出錯誤」—— 這個專案一路在防的就是它。
2. **消音,不刪除。** `.parsed/` 的 `tables.json` 用 `content_list.json#/6` 這種
   **陣列索引**當 `self_ref`。刪一個項目,其後所有引用靜靜指向別的東西。
3. **LightRAG 的行為用 `pp/oracle.py` 問,不要推測。**
   實測踩過:推測 `chart` 的 `img_path` 會污染索引,查 `_coerce_text` 後發現
   它只讀 `("text","content","body","code_body")`,根本不讀 `img_path`。
4. **先查輸入,再查偵測器,最後才查模型。**
   實測踩過:方程式「三方皆異」看起來像模型都讀不出來,實際是裁圖的垂直
   padding 用了表格的 6 點,把上下鄰居框進圖裡 —— 六個模型對共同部分完全
   一致,只是各自決定轉幾條。改成 1 點後「三方皆異」歸零。
   給模型看的東西不對,再多模型、再好的比對邏輯都沒用。
5. **門檻用量的,不要用調的。** 覺得誤判多時先看**差在哪些具體記號**。
   實測有五次「以為要調門檻」其實是偵測器量錯東西(清單見 SKILL.md)。
6. **探針要在沒人問的時候會響。** 只有指定目標才跑的檢查,防的是「你已經
   懷疑的事」—— 而你已經懷疑的事不需要探針。
   實測踩過:A-16「沒有未知的項目型別」本來就抓得到 `chart`,但單篇檢查被
   `if a.doc:` 關著,而你只會對正在處理的那一份指定。184 個 `chart` 分散在
   11 份文件裡,從專案開始到發現為止**一次都沒被喊過**。
   同理:收合輸出時必須報出「幾項通過未列出」,否則「沒印出來」跟「沒檢查」
   在畫面上長得一樣。
7. **「乾淨的 0」要先當成量錯，不是結論。** 量測工具回報一個漂亮的零
   （0 個命中、0 筆差異、兩組都 0）時，**最可能的解釋是驗證的東西跟真正在跑的
   東西不是同一個**，不是「真的沒有」。
   實測踩過三次，全在 2026-08-03 同一天，全都「看起來像乾淨的結論」：
   - `psql -c` **不展開** `:'var'`，SQL 在測試裡是綠的（測試斷言的是**字串字面**
     有那段），到 dker 實跑當場語法錯。**測到字面，沒測到行為。**
   - 命名規則探針用 `<|>` 分隔格式解析，但 LightRAG 1.5.5 走的是 **JSON 格式**
     ⇒ 控制組與實驗組都解析出 0 個，看起來像「規則沒效」，其實是解析器對不上。
   - `lightrag_entity_chunks` 的欄位是 `chunk_ids`（**陣列**），用單數 `chunk_id`
     join ⇒ 三組實體數全 0，看起來像「內容全掉了」。
   **對策（三支腳本都已照做）**：在工具裡直接寫死「**這個數字若為 0，先當成壞了，
   印出警告，不要輸出結論**」——控制組本來就該重現既有結果，重現不了就是量錯。
   與鐵則 4 同族但不同層：那條講「輸入不對」，這條講「**輸出是空的時候更要懷疑自己**」。

## 常用指令

> **這些全部只在 florian-dker 跑得起來。** 它們要 `.env`（不進版控）、要
> `docker exec` 進容器、要連 Postgres／Neo4j——工作台 coder 上一個都跑不動,
> 會直接噴錯。**這是好事**:它讓「我在 coder 上驗過了」這種自我欺騙在物理上
> 發生不了。凡是這些指令的輸出,一律是驗證回程的產物。
>
> `--workspace` 預設讀 `.env` 的 `WORKSPACE`;**`.env` 沒有就強制要求明確指定**,
> 沒有字面預設值（猜錯的預設不會報錯,只會安靜地對別的庫做事）。

```bash
python3 scripts/parse-only.py                     # 只解析不抽取（規則建立期用這個）
python3 scripts/postprocess.py plan               # 只讀,算出打算改什麼
python3 scripts/postprocess.py plan --details --doc <關鍵字>
python3 scripts/postprocess.py check --doc <關鍵字>   # 兩雙眼睛 + 逐格比對
python3 scripts/postprocess.py canary             # 規則漂移偵測 ← 改規則後必跑
python3 scripts/compat-check.py                   # LightRAG 契約斷言（預設連 20 份文件一起驗）
python3 scripts/compat-check.py --no-docs         # 只驗契約與環境（快）
python3 scripts/compat-check.py --doc <關鍵字>     # 只驗某一份，且逐項列出
python3 scripts/extract-check.py                  # 抽取品質：實體與關係對照原文（三態）
python3 scripts/eq-check.py --n 30                # 方程式：MinerU/qwen/luna 三票多數決
python3 scripts/parse-check.py --details          # 解析品質
```

### 測試

```bash
scripts/run-tests.sh                             # pytest + test_gates.py，單一入口
python3 -m pytest tests/ -q                       # pytest 入口（可單獨除錯）
python3 tests/test_gates.py                       # 自製閘門框架，pytest 不會收集
```

有兩個入口是刻意的：`tests/test_gates.py` 的案例函式以 `t_` 開頭，並由自己的
`case()`／`if __name__ == "__main__"` 執行，所以 pytest 會顯示 `collected 0 items`。
平常用 `scripts/run-tests.sh`，它會依序跑上面兩條指令，任一邊非零就整體失敗；
只有要單獨除錯時才直接跑其中一條。

## 金絲雀:規則漂移偵測

規則是**一份一份文件逼出來的**,每次改動都可能無意間動到別份。手動逐份比對
數字會漏,而漏掉的漂移不會有錯誤訊息。

```bash
python3 scripts/postprocess.py canary            # exit 0 通過 / 2 漂移
python3 scripts/postprocess.py canary --update   # 認可為新基準
```

基準 [tests/canary-baseline.json](tests/canary-baseline.json) **進版控**,
所以規則改動造成的行為變化會直接出現在 `git diff` 裡。

比對這幾個量:`pages` `items` `mute` `held` `ratio` `tables_total`
`repairable` `review`。

**改規則的正確順序:**

1. 改 → 2. `canary`(預期會失敗) → 3. 逐條確認每個漂移都是**想要的**
→ 4. `canary --update` → 5. commit 訊息**說明每個數字為什麼變**

沒說明的數字變動 = 未被察覺的漂移。

實測驗證過金絲雀真的會失敗:門檻 3→20 時它指出 `C: mute 110→101`、
`K: mute 61→48`。(注意 3→5 不會失敗,因為書眉重複次數遠大於 5 ——
**測試本身也要選會咬到的值**。)

## 現況

**唯一的 workspace 是 `acoustics_v2`**(`WORKSPACE` 在 `.env`,不進版控)。
`acoustics_v155` 已於 2026-08-03 完全退役——容器、Postgres 列、Neo4j label、
磁碟目錄全數移除。本檔提到 v155 的地方一律是**歷史**,不是現況。

```
文件      20 份已完成「解析 → 修補 → 抽取」全流程(processed 20/20、failed 0)
          分 4 批索引,每批 5 份;總耗時 3 小時 58 分(61.1/70.1/46.1/61.1 分)
服務      lightrag :9621 查詢(容器 lightrag-acoustics_v2)
          kbapi    :9700 圖片與單篇結構,唯讀(容器 kbapi-acoustics_v2)
          兩者由同一份 compose.yaml + 同一個 checkout 起,埠走 ${HOST_PORT}/${KBAPI_PORT}
skills    lightrag-search / fetch / images —— 全走 :9700,不需認證,任何機器可用
          **URL 的 workspace 打錯會 400**(kbapi 的擋板)——因為 search 端點不看
          URL 的 ws、檔案類端點看,不擋會回一半對的東西且不報錯
索引      7,211 實體、10,500 關係、510 chunk;圖 7,211 節點 / 10,500 邊
          ↑ 來源＝**vdb 列數**(extract-check.py；量測來源容器未在舊紀錄固定，存疑，
          REBUILD-1 修正後需重量)。與下面「歷史對照」列的
          8,010／10,535 **不衝突,是兩把不同的尺**:那邊來源是 LightRAG 自己的
          逐文件計數欄 `lightrag_full_entities.count`(compare-ws.py),同一個實體
          出現在兩份文件會被數兩次。差值 799 實體／35 關係就是跨文件重複。
          **引用數字前先看它是哪一把尺量的。**
接地      可疑率 4.5%(260/5,729 個可判定實體);符號型 1,482 個「驗不了」
          6 份 >5% 標黃(K Muffler 15.1%、00712 11.9%、G Porous 6.4%、01200_6 6.1%、
          2025 5.7%、2023 FEM 5.0%),形狀逐份記在體檢表 —— 全部不是幻覺
格式      Empty entity name 共 1,669 次(第 1 批 477 = 基線),全部帶得到 chunk key
圖        image 371(含 chart 轉入的 184);chunk 裡以 <drawing caption=… path=…/> 出現
          項目數 5,448:text 2,731、equation 1,273、header 514、page_number 353、table 82
解析      pipeline + is_ocr=true + MinerU official
embedding text-embedding-3-large @ 3072 + HNSW_HALFVEC;本輪實際嵌入 4.56M 字元 ≈ US$0.15
兩雙眼睛  qwen3.6-35b-a3b(本機) + gpt-5.6-luna(雲端,$0.20/$1.20 per 1M)
體檢表    20 份 × 8 閘門 = 160 格:通過 151、fail 9、驗不了 0、未設定 0
          fail 9 = 3 份 waiver(41598/C 的 coverage、N Flow 的 equations)
                 + 6 份 extract.grounding >5%
歷史對照  v155 → v2(重建當時量的,v155 已不存在,這組數字**不可能再重現**):
          chunk 512→510、實體 7,968→8,010、關係 10,407→10,535、
          含掉字 chunk 86→27(-69%) ← 來源＝逐文件計數欄,見「索引」列的說明
          最後一次重跑驗證 2026-08-03(退役前),逐位元相同
```

**退役時的實測數字**(2026-08-03,拆除前後各量一次):

| 位置 | v155 移除量 | v2 移除後 |
|---|---|---|
| Neo4j label `acoustics_v155` | 7,191 節點 / 10,373 關係 | v2 7,211 節點,其他專案(`acoustics_books` 72,289 等)未受影響 |
| `lightrag_doc_chunks` | 512 列 | 510 |
| `lightrag_entity_chunks` | 7,191 列 | 7,211 |
| `lightrag_relation_chunks` | 10,373 列 | **10,500** |
| `lightrag_llm_cache` | 2,367 列 | 1,126 |
| `*_3_small_1536d` 三張表 | 148 / 1,135 / 1,812 列(**100% 是 v155**,舊 embedding 模型的遺留) | 全空 |
| 磁碟 `/data/rag/lightrag/acoustics_v155` | 198 MB | — |

`lightrag_relation_chunks` 全表退役前是 **20,873**——那正是本檔接地檢查一節
曾經寫錯的數字。**它從來不是 v2 的關係數,是兩個 workspace 的和。**
拆掉 v155 之後全表剩 10,500,與 `extract-check.py` 的報告一致（該舊量測來源容器未
固定，來源存疑；數字不改）,這件事到此
獨立印證完畢。

**Neo4j 是跨專案共用的**(DeepTutor 的 `Room_Optimizer`、`acoustics_books` 等
都在同一個實例,靠 label 隔離)。動它之前必須先驗兩件事,兩件都驗過才准刪:
① v155 的節點**只有** `acoustics_v155` 一個 label(7,191/7,191);
② 對外跨界關係為 **0**。

## 規則分兩類,不能混在一起

混在一起是設計錯誤 —— 兩類的失效方式完全不同。

### 耐久規則:綁文件領域,換模型仍成立

**改動前先看它有多少份文件的證據。** 只有 1 份的很可能是那份文件的巧合。

| 規則 | 證據 | 狀態 |
|---|---|---|
| 消音 header/footer,不刪除 | 7 份 | 穩 |
| 書眉門檻依頁數 `max(2, min(3, ⌈pages×0.5⌉))` | 7 份 | 穩 |
| 兩雙眼睛**必須不同家族**(同模型的系統性誤讀會原樣重現) | 原理 | 穩 |
| 分歧要**逐格**定位,不用整表純量分數 | 原理 + 1 份 | 穩 |
| `aside_text` 先跑重複/樣板規則,`is_gibberish` 只當單次殘骸的後備 | 2 份 | 穩 |
| 書眉/頁尾數**樣板**(數字抹成 `#`),不數字面字串 | 2 份 | 穩 |
| `chart` 只登記不處理 | 3 份（含一份 50 個 chart） | 穩 |
| 接地檢查要**三態**:符號型 chunk 的未接地是「驗不了」不是「錯」 | 5 份 | 穩 |

### 易腐觀察:綁特定模型,換代即失效

記錄在 [tests/model-observations.json](tests/model-observations.json)。

**這些一律不得寫成流程中的自動裁決規則。** 例如「列數不一致優先採信 luna」——
luna 撐不過半年,換代後那條規則不是變舊,是**變成錯的而且錯得很安靜**:
新模型的失誤型態可能完全相反,但規則還在照舊裁決。

`compat-check.py` 的 **A-23** 比對記錄的模型與 `.env` 現行設定,不一致就 hard FAIL,
逼人重新量測。驗證過它抓得到換代。

模型換掉時的正確做法:

1. 重跑 `postprocess.py check`(舊快取以裁圖 sha 為鍵,不會混到)
2. 重新看圖判定,量新模型錯在哪一類
3. 更新 `model-observations.json` 的 `eye_*`、`measured_on`、`observations`
4. `compat-check.py` 應回綠

`domain_facts` 那一節是例外 —— 那些是文件的性質(羅馬數字下標難讀、
跨頁續表詞彙重疊、文字層表示不了數學),換模型仍然成立,可以累積。

## LightRAG 升級時怎麼辦

**我們沒有改過 LightRAG 一行程式碼。** 後處理改的是磁碟上的 `content_list.json`
與 `_manifest.json`，耦合的對象是「LightRAG 如何讀寫 `__parsed__`」這組**未言明的
契約**，不是它的原始碼。所以升級不會有 patch 衝突，但契約可能悄悄改變。

設定全部在**容器外**：

| 在哪 | 內容 | 版控 |
|---|---|---|
| `.env` | 實際值（含金鑰） | ❌ gitignore，chmod 600 |
| `.env.example` | 每個鍵 + **為什麼設這個值** | ✅ |
| `compose.yaml` | 映像以 digest 釘選 | ✅ |

`.env.example` 才是真正的文件 —— 它記的不是「有這個鍵」，而是「為什麼是這個值」，
例如 `MAX_ASYNC` 底下寫著當初 10 次逾時、1 份文件整份失敗的成因，以及
「真正要提升吞吐得在伺服器端開 `--parallel N`，開了之後 `MAX_ASYNC` 才有意義往上調」。
換機器或換人接手時看那個檔就夠。

**⚠ 2026-08-03 實測到的三方不一致**：伺服器已經開了 `--parallel 4`（`n_slots = 4`），
`.env.example` 寫 `MAX_ASYNC=4`，但 **dker 的 live `.env` 仍是 `MAX_ASYNC=2`**——
也就是 4 個 slot 開著卻只餵 2 路。這是 `SPEEDUP` 線要量的第一件事，別直接改。

**升級的步驟：**

```bash
# 1. 先記下現況
python3 scripts/compat-check.py --json > /tmp/before.json
python3 scripts/postprocess.py canary          # 應為綠

# 2. 改 compose.yaml 的 digest，重建

# 3. 契約有沒有變 —— 這是關鍵
python3 scripts/compat-check.py                # 契約 15 項 + 每份文件 6 項
python3 scripts/postprocess.py canary          # 規則行為有沒有漂移
python3 scripts/parse-check.py                 # 解析品質
python3 scripts/extract-check.py               # 抽取品質
```

`compat-check.py` 就是為升級寫的 —— 它把「後處理依賴的假設」變成可執行的斷言。
文件會過期，斷言不會。任何一項 hard 失敗就**不要動工**，先查契約哪裡變了。

已知的契約點（都有對應斷言）：`critical_file` 是 `content_list.json` 且驗
size+sha256、`_coerce_text` 的欄位順序、sidecar 的 `self_ref` 用陣列索引、
`page_number` 被跳過而 `header`/`footer` 走 fallback 進索引。

新增兩點：

- **A-24 走 `_build_ir_drawing` 的型別集合是 `{image, picture, drawing}`,
  而它讀 `image_caption` / `image_footnote`。** `chart→image` 整條規則就
  站在這兩件事上。哪天 LightRAG 把 `chart` 加進集合,規則就該退休（斷言的
  說明會直接這樣寫）；caption 欄位改名的話,現在的搬動會把 caption 搬丟。
- **A-25 `chunk_top_k` 仍然控制回傳的片段數。** kbapi 的 `chunks` 參數就是
  下傳成它。失效時 `/kb/*/search` 會靜靜回到每次 55–60KB —— 不報錯,只是把
  呼叫端的 context 灌爆,所以每次都真的打一次查詢來驗。
  注意:**空 workspace 上它結構性驗不了**(chunk 數恆 0,`b > a` 不可能成立),
  該讀成「驗不了」而非紅燈 —— 2026-08-02 建 v2 時發現,已三態化。
  **三態化的最終驗證在 2026-08-03 拿到**:v2 索引完 20 份後,同一條斷言
  **自動從「驗不了」轉回真實判斷**(`chunk_top_k=2 → 2 個、=8 → 8 個,
  母體 20 份已索引`),不必改任何一行程式。「母體不足」與「契約壞了」
  被分開之後,兩種狀態各自都會在該響的時候響。
  **不要改用 `max_total_tokens` 收**:它先扣圖譜再給原文,設 8000 時
  `available_chunk_tokens` 變負數,chunk 直接回 0 個且不報錯。
- **A-26 Postgres 與 LightRAG API 回報的文件數一致。** 兩個獨立來源的母體數
  不一致時，視為可能連到不同的資料庫；兩邊都是 0 時回報「驗不了」，不把空庫
  當成硬失敗。
- **同一組 Postgres 裡多個 workspace 共存時,每一句 SQL 都要帶 `workspace`。**
  儲存層靠這個欄位隔離,而兩個 workspace 的 `file_path` 是同一批 PDF 檔名 ——
  漏掉條件時逐份報表會把兩邊的同一份文件**併成一列**,數字看起來完全正常
  (大約兩倍)、不報錯、不會有任何訊號。實測踩過(2026-08-03,extract-check.py
  三句 SQL 全漏):合計實體 14,402 = v155 7,191 + v2 7,211,而且**翻轉了三份
  文件的閘門判定**。上述 extract-check 舊量測的來源容器未固定，來源存疑；數字不改。
  單一 checkout 時代這個 bug 不可觀測 —— 與階段 0 的
  「容器名寫死」同一族,開第二個 workspace 的那一刻才引爆。
  修完的驗證方式:**拿舊 workspace 重跑,要重現歷史數字**(v155 回 3.2%,
  與本檔記載逐位元相同)。

## 待辦

在 [NEXT.md](NEXT.md) —— 本檔只放規則與契約,待辦與進行中的狀態不放這裡。
待辦做完就從 NEXT 刪;過程學到的教訓沉澱回本檔或對應文件,不留屍體。
「刻意不做」的決策記錄也在那裡,動它們之前先讀理由。

排程檢查已存在(2026-08-02 起):`lightrag-daily-check.timer` 每天 08:30 跑
compat-check + canary,紅燈打自架 ntfy(`/opt/stacks/ntfy`,:9800),腳本本身
掛掉走 systemd `OnFailure=` 獨立備援。狀態落地 `/data/rag/lightrag/checks/`。
**「誰會報錯」的答案從「沒有人」改成它。**

第二支排程於 2026-08-03 接上：`lightrag-cold-backup.timer` 每天 03:00 跑
`scripts/backup-cold.sh`。它會**停服務抄目錄**（停機約 75 秒，幾乎全花在容器優雅
關機與健康檢查，本地複製只要 1 秒），但**沒有新的抽取成果就自己跳過、完全不停機**
——判準是資料庫內容指紋不是時鐘。兩支排程各有自己的 `OnFailure=` 備援單元，
且備援**刻意不走 `notify.sh`**：備援不能依賴可能正是故障原因的主路徑。

## 抽取品質:接地檢查

`extract-check.py` 拿每個實體名字去對它來源的 chunk。原理跟 `pdfcrop` 抽文字層
當 ground truth 一樣:**拿產出對來源,不要相信它**。確定性、不呼叫模型、免費。

必須三態。字串比對只對散文有效 —— 表格裡常常只有符號,實測 C 的 chunk-002 是
`<td>G</td><td>$G=I/\Delta U=1/Z$</td>`,完全沒有 `Conductance` 這個字,但模型
抽出 Conductance 是**正確的**:從符號推論概念名稱正是它該做的事。

二態時未接地率與符號密度高度相關、與幻覺無關(散文 0%、論文 3.4%、C 55%)。
分成「接地 / 符號型無法驗證 / 可疑」之後,C 從 55.1% 降到 3.4%,總計 3.7%。

```
acoustics_v2（2026-08-03 重跑，全 20 份；來源＝entity/relation vdb 的列數）
  ⚠ 上列 extract-check 數字的量測來源容器未在舊紀錄固定，來源存疑；數字本身不改，
    待 REBUILD-1 修正後重新量測。
 7,211 實體 → 接地 5,469、符號型 1,482（驗不了）、可疑 260 　可疑率 4.5%
10,500 關係 → 兩端接地 6,780、符號型 3,261、只有一端 349（4.8%）、兩端皆無 110（1.5%）
```

**關係那一列曾經是錯的,而且錯法就是它自己修的那個 bug。** 舊版寫
`20,873 關係 → 12,459 / 7,491 / 689 / 234`,每一項都約是實際的 **2 倍** ——
那是 `extract-check.py` 補上 `workspace` 條件（commit `9ef8026`）**之前**的；這組舊
量測的來源容器未固定，來源存疑，數字不改。
雙重計數。那個 commit 更新了實體那一列,漏了關係那一列,於是「兩個 workspace
被併成一列」的症狀留在文件裡活了下來。**2026-08-03 重跑 `extract-check.py`
定案為上表數值。**

教訓與該 commit 自己寫的契約點同一條:多 workspace 共存時,**修完 SQL 還要
把所有引用舊數字的地方一起重算**——數字沒有錯誤訊息,它只是靜靜地錯著。

**「可疑」不等於「幻覺」——形狀要逐份看過才算量到。** v2 的 260 個可疑
分成兩族,兩族都不是捏造:

| 形狀 | 長相 | 例 |
|---|---|---|
| 符號→概念命名 | 模型替裸符號取描述性名字 | K Muffler `Coefficient Ta`、G Porous `Modified Bessel Function I0` |
| 概念→引用文獻 | 參考文獻條目被拆成實體 | 01200_6 `Journal Of The Acoustical Society Of America`、2025 的作者縮寫名 |

前者是**三態判準的邊界效應**:同一族的東西,散文比例低於
`SYMBOLIC_RATIO=0.35` 的落進「驗不了」,高於的落進「可疑」。所以
K Muffler 15.1%(全庫最高)的分子裡 92 個只有 1 個是引用文獻 ——
**NEXT 記載的 v155 結論「K Muffler 大量概念→引用文獻型」在 v2 母體被推翻**。
要真的降下來得重量 `is_symbolic` 的判準(門檻用量的不要用調的)。

## 兩雙眼睛:為什麼要兩個

實測 C 的 10 張空表格,**沒有哪個模型比較準**,而且錯法互補:

- luna 會**看錯字元**(`S_n`→`S_h`、`p_I`→`p_l`)
- qwen 會**切錯結構**(該分的併、該併的分)
- 兩者都會錯在**羅馬數字下標**(區域 I/II),方向相反

只用其中一個,另一個抓得到的那類錯誤就會靜靜進索引。`pp/eyes.py` 會擋下
「兩雙眼睛是同一個模型」—— 同模型的系統性誤讀會一模一樣地重現,
互相印證等於沒印證。

luna 不接受 `temperature=0`(只允許預設 1),所以**首次轉錄有抽樣變異**;
快取之後才穩定。分歧要重抽一次才知道是真的還是雜訊。

**一致不等於沒有多餘的東西。** 實測(2026-08-02,C #525):qwen 對示意圖格
**捏造外部圖片網址**(`<img src="https://i.imgur.com/…">`)。crosscheck 只回答
「兩眼一不一致」,不回答「多出了什麼」——兩眼剛好都幻覺時會全綠通過。
所以**內容閘門掛在寫入點**(`postprocess.py` 的 `gate_table_html`:單一完整
table、無 `<img>`、無 prompt 洩漏),且自動採用與人工裁定走同一道。
