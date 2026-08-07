# lightrag

以 [LightRAG](https://github.com/HKUDS/LightRAG) 1.5.5 取代自製 RAG 管線的部署設定。
由 Dockge 管理，設定進版控，執行期資料留在 `/data`。

## 為什麼換

舊的自製管線有兩個已證實的問題（2026-08-01 實測 `C Equivalent Networks.pdf`）：

| 指標 | 舊管線 | LightRAG 1.5.5 |
|---|---|---|
| chunks | 347 | 58 |
| 含 AI 評註的 chunk | 244（70%） | **0** |
| 被丟棄的正文 | 22,886 字元 | **0** |
| entities | 3,411 | 779 |
| relations | 10,241 | 1,289 |

舊管線把文件正文當成重複內容丟棄，實際進索引的是 LLM 對版面區塊生成的評註 —— 每 1 字元原文
生出約 19 字元評註。實體因此混入 `ConflictResolutionProtocols`、`Page 3 Marker` 這類從評註和
版面結構挖出來的雜訊。

實體與關係數大幅下降是預期的：不再對表格、圖片、頁碼生成假實體。但**該輪數據不可作為品質基準**，
因為當時未開 `MINERU_IS_OCR`（見下）。

## 解析選項：三組實測

同一份 `C Equivalent Networks.pdf`，只變動一個參數（2026-08-01）：

| 組合 | 真實掉字區塊 | 空表格 | 表格內容量 |
|---|---|---|---|
| vlm + is_ocr | 0 / 208 | 16 / 57 | 86,671 字元 |
| vlm 不含 is_ocr | **45 / 210** | 15 / 57 | — |
| **pipeline + is_ocr** ← 採用 | 1 / 209 | **9 / 57** | **189,430 字元** |

三個結論：

1. **`is_ocr` 必開，且與表格無關。** 關掉會出現 45 個掉字區塊；空表格數卻幾乎不變
   （16 vs 15），所以表格問題不是 OCR 造成的，開著它沒有代價。
2. **`pipeline` 優於預設的 `vlm`。** 兩者真實掉字都約等於零，但 pipeline 多救回 7 個表格，
   表格內容量是兩倍以上。差異的 7 頁全部是 pipeline 較好，沒有一頁反向，所以不必合併兩次解析。
3. **`language` 無作用。** `ch` 與 `en` 產出 556 個區塊分毫不差。

仍有 **9 個表格區域兩種模型都救不回來** —— MinerU 認得出 bbox 卻產不出 `table_body`，
連 `img_path` 都是空的，沒有任何備援。這是 MinerU 本身的上限，`enable_table` 已經是 true。

### 量掉字時務必先剔除數學式

行內 LaTeX 會把字母拆開排版（`\mathrm { i n t e r i o r }`），長得跟掉字一模一樣。
不剔除的話 pipeline 會被誤判成 8 個掉字，實際只有 1 個。`parse-check.py` 已內建處理。

## 兩個不能關的設定

`.env.example` 裡有註解，這裡再說一次，因為兩者都是踩過坑才知道的：

**`MINERU_IS_OCR=true`** — MinerU 的文字層路徑會靜默吃掉字母，且**專挑文字層完好的非掃描 PDF**
（掃描檔本來就走 OCR，反而沒事）。掉字有幾何規律：43 個掉字裡 40 個是 x-height 字母
（a c e g m n o r s u w y），上伸部字母（b d f h k l t）幾乎全存活，指向高度／bbox 過濾器。
實測 `C Equivalent Networks` 有 27.6% 的 chunk、1,660 個掉字片段。`model_version=vlm` 無效。

**`ENTITY_EXTRACTION_USE_JSON=true`** — 本機 4-bit 模型的關係記錄只吐 4/5 個欄位，LightRAG 1.5
會全數拒收。實測不開是 38 entities + **0 relations**，開了之後格式錯誤歸零。

## 佈署

```bash
cp .env.example .env       # 填入密鑰，chmod 600
docker compose up -d
```

Dockge UI（http://localhost:5001）也能直接管理 —— 本目錄被 bind mount 進 dockge 容器的
`/opt/stacks/lightrag-v1`，設定見 `/opt/stacks/dockge/compose.yaml`。用 bind mount 而非
symlink，因為 symlink 的目標在 dockge 容器內不存在會斷鏈。

### 路徑配置

**唯一的資料根是 `/data/lightrag`**（`.env` 的 `DATA_ROOT`，程式端的單一事實來源是
`scripts/pp/paths.py` 的 `DEFAULT_DATA_ROOT`）。

| 用途 | 位置 |
|---|---|
| 設定（版控） | 本 repo |
| rag_storage | `/data/lightrag/rag_storage` |
| 待匯入文件 | `/data/lightrag/inputs/${WORKSPACE}/` ← 子目錄由容器啟動時自己建 |
| MinerU 解析快取 | `/data/lightrag/work/parsed` ← 貴（6–10 h）。容器內映射成 `inputs/${WORKSPACE}/__parsed__` |
| 裁圖與轉錄快取 | `/data/lightrag/work/crops` |
| 過程紀錄／裁決 | `/data/lightrag/records` ← 不可再生 |
| 收件匣／審核台 | `/data/lightrag/inbox`、`/data/lightrag/intake` |
| 體檢結果 | `/data/lightrag/checks` |
| 索引本體 | `/data/lightrag/postgres`、`/data/lightrag/neo4j`（`.env` 的 `LIGHTRAG_DB_ROOT`） |

> ⚠️ **`/data/rag` 已於 2026-08-07 廢除，不得再新增任何東西到那裡。**
> 它曾經同時放著三種東西（已搬走的資料根、冷備份暫存區、DeepTutor 的語料庫），
> 那正是這個專案反覆踩到的「一個名字承載多件事」。現在暫存區在
> `/data/lightrag-coldstage`，`INTAKE_SOURCES` 留空。
> **`scripts/backup-cold.sh` 原本每天會把 `/data/rag` 重新 `mkdir` 出來**——刪一次
> 建一次，而且看起來一切正常，所以那一行必須跟著改，不能只刪目錄。

### 備份現況（2026-08-07 在 dker 實測）

| 路徑 | 大小 | 備份 |
|---|---|---|
| `/data/lightrag/work/parsed`（MinerU 解析快取） | 307 MB | ✅ 每 6 小時 |
| `/data/lightrag/records`（裁決紀錄） | 8.1 MB | ✅ 每 6 小時 |
| `/data/lightrag/postgres`（**索引本體**） | 1.1 GB | ✅ 每 6 小時 ＋ 每天 03:00 |
| `/data/lightrag/neo4j`（圖） | 540 MB | ✅ 每 6 小時 ＋ 每天 03:00 |

兩條路徑的分工：

- **每 6 小時**：backrest 的 plan `lightrag-snapshot`，涵蓋整個 `/data/lightrag`，
  不停服務。對**不會變動的檔案**（解析快取、裁決紀錄）這樣就是有效備份。
- **每天 03:00**：`scripts/backup-cold.sh` 停掉容器再複製，然後上傳（tag `lightrag-db`）。
  資料庫必須這樣備——跑著的資料目錄複製出來是不同時間點的碎片，還原可能起不來。
  還原演練 `BACKUP-3` 已於 2026-08-03 通過。

> ⚠️ **一個仍然存在的缺口**：冷備份的跳過判準是 Postgres 的抽取指紋
> （`backup-cold.sh` 的 `fingerprint()`），所以「只解析、還沒放行索引」的新解析快取
> **不會觸發它**。那批檔案目前只靠 backrest 那條每 6 小時的熱抄保護。
> 解析快取尤其不能掉：整批重新解析要 6–10 小時的 MinerU 呼叫。

> **這張表的歷史**：它曾經連續錯兩次，方向相反。2026-08-03 之前寫「已納入 restic
> 備份」而實際上沒有（假的安全宣稱）；修正之後又停在舊路徑不動，於是到 2026-08-07
> 變成**打 ❌ 的兩列其實每天備兩次、打 ✅ 的那個目錄整個不存在**。
> 教訓是同一條：**備份宣稱必須對照 dker 上的實際排程設定，不能照抄文件。**

### 映像用 digest 釘死

`compose.yaml` 指定的是 `@sha256:...` 而非 `:v1.5.5`。標籤可被重推，同一行指令在不同
時間可能拉到不同映像；而後處理腳本全都建立在「LightRAG 如何讀寫 `__parsed__`」這些
假設上，環境默默變動會讓假設失效卻無人察覺。釘 digest 讓升級變成明確的動作。

語料 390 個 PDF、約 2.0 GB，留在 `/data` 的獨立 NVMe，不進 repo。

### 文件要放進 inputs 的 workspace 子目錄

設了 `WORKSPACE` 之後，LightRAG **只掃 `inputs/${WORKSPACE}/`，不掃 `inputs/` 根層**。
放在根層的檔案掃描會回報 `0 discovered` 而且不報錯，很容易誤判成服務壞了。該子目錄由容器
啟動時自動建立。

> **現在的正路是審核台**（http://100.87.88.7:9710）：PDF 丟進 `/data/lightrag/inbox/`
> 或直接在網頁上拖拉上傳 → 按「只解析」→ 看審核卡片 → 放行。
> **不要再用 `postprocess.py prepare`**：它會把 PDF 留在 `inputs/`，審核台下次放行時
> 會被正確擋下（實測撞過一次）。兩條路不要混用。下面這段是 CLI 流程的存底。

```bash
cp foo.pdf /data/lightrag/inputs/acoustics_v2/
python3 scripts/postprocess.py prepare --workspace acoustics_v2
python3 scripts/postprocess.py prepare --workspace acoustics_v2 --commit
```

`prepare --commit` 固定依序做「解析 → 修補 → 掃描」。**不要直接呼叫
`/documents/scan`**：scan 會把解析與實體抽取綁在一起；先掃描再修補會讓之後的
reindex 再抽取一次。修補必須在 scan 前完成，才能讓每份文件只抽取一次。

`inputs` 也**不能唯讀掛載** —— 容器啟動時要建上述子目錄，掛 `:ro` 會直接 crash loop。
這是為什麼此處用 `DATA_ROOT` 底下的專屬目錄，而不是直接掛某個外部語料庫的來源目錄。

### 儲存後端

使用本專案專用的 `lightrag-postgres`（DB `lightrag`，pgvector 0.8.2）與
`lightrag-neo4j`，接在 `rag_default` 網路上。兩者不再與 DeepTutor 共用；查詢仍以
`WORKSPACE` 作為本專案的資料邊界。

要跑第二個知識庫：複製本目錄為另一個 stack，改 `WORKSPACE`、`HOST_PORT`
與 `KBAPI_PORT` 即可。三個埠都走 `.env`，compose.yaml 不必改。

**不要用 `profiles:` 停用某一邊的 kbapi。** 2026-08-02 曾這樣做，理由是當時
9700 寫死。但 profile 停用的是**檔案**不是 checkout，而 compose.yaml 進版控、
被多個 checkout 共用 —— 分支一合併回主線，主線也會拿到那一行，下次
`docker compose up -d` 就不會起 kbapi，:9700 靜靜消失且不報錯。埠參數化才是解。

## 拆解品質檢查（整批重跑前先用這個）

```bash
./scripts/parse-check.py --details      # 檢查已解析的文件
./scripts/parse-check.py --watch        # 邊解析邊看
```

MinerU 的原始輸出快取在 `inputs/<ws>/__parsed__/<檔名>.mineru_raw/`，所以**解析一結束就能驗，
不必等後面幾十小時的 LLM 抽取**。整批重新 parsing 時先跑這個確認拆得對，再讓 LLM 上工。

檢查項目：掉字、空的文字／表格／公式區塊、整頁無正文、prompt 洩漏。有 ERROR 時 exit 1。

已知會抓到的真實問題：**MinerU 有時偵測到表格區域卻什麼都不產出** —— `table_body` 缺席、
`img_path` 也是空字串，連退而求其次的圖片備份都沒有，該區域內容完全遺失。以採用的 pipeline
模型計，C Equivalent Networks 是 10/57。

判斷表格是否為空**必須剝掉 HTML 標籤再看**：MinerU 會產出 `<table><tr><td></td></tr></table>`
這種空殼，字串非空但內容為零。

2026-08-01 抽樣 10 份（5 個 KB 各 2 份）顯示這是**教科書特有問題**：8 份期刊論文共 20 張表格
全部正常，失敗只出現在教科書（C 的 10 張、J Duct Acoustics 的 2 張，合計 12/71）。

## 給 CLI agent 查詢：askrag

```bash
askrag "mechanical impedance"                  # 預設 hybrid，回傳檢索脈絡
askrag --mode local --json "sound power"       # 結構化輸出給程式解析
askrag --answer "what is acoustic impedance?"  # 要 LightRAG 直接生成答案
askrag --docs                                  # 列出已索引文件
```

安裝：`ln -sf $PWD/scripts/askrag.py ~/.local/bin/askrag`。真身在 repo（進版控），
PATH 上是 symlink，所以改一處三個 agent 同時生效。

**為什麼不是 MCP**：CLI agent 本來就有 shell，「怎麼呼叫」只需要一行指示。
**為什麼不是 Ollama 相容端點**（`/api/chat`）：那個端點是為了假扮成 Ollama 給只會講
Ollama 協定的 app 用，回傳的是生成好的答案；agent 要的是原始脈絡，自己判斷。所以
預設走 `/query/data`，拿 entities / relationships / chunks / references。

**限制**：這是本機腳本，只服務跑在這台機器上的 agent。Mac／Windows 上的 agent 要用
遠端 MCP（streamable-HTTP 傳輸，掛在 mcpjungle 後面），見下。

### 跨機器：遠端 MCP

stdio 傳輸的 MCP 需要每台機器各自安裝 server，Windows／Mac／Linux 的路徑與設定格式
不同，這是「MCP 跨平台很痛」的來源。**streamable-HTTP 傳輸沒有這個問題** —— server
只跑在這台機器，客戶端拿到的就是一個 URL。

本機已有現成範本可照抄：`/opt/stacks/mcp-servers/deeptutor/mcp_obsidian_server.py`
（FastMCP 包 HTTP API）與 `run_http.py`（`mcp.run(transport="streamable-http")`），
以及 mcpjungle 這個 MCP gateway（已在 host network 的 :8080 提供 `/mcp`）。

## 比對工具

```bash
python3 scripts/compare-ws.py 'Equivalent' <ws-a> <ws-b>
python3 scripts/compare-ws.py '' <ws-a>                    # 空關鍵字＝全部文件；第二個 ws 預設讀本 checkout .env
```

直接查資料庫比對兩個 workspace 對同一份文件的索引結果，不依賴人工記錄的數字（記錄會抄錯、會
過期，抄錯時沒有任何訊號）。量 chunks／entities／relations／含掉字 chunk 四個數。內含已驗證的
掉字偵測器 —— 注意用的是 `(?:\s+[a-z]{1,2}\y){5,}`，**不要**改成兩側都是 `\s` 的版本，那會因為
前一次匹配吃掉後一次的前導空白而永遠回 0。

前身 `compare.sh` 已退役（階段 1）：它把向量表名寫死成 `text_embedding_3_small_1536d`，
3-large 遷移後 entities/relations 兩列恆空。改從 `lightrag_full_entities.count` /
`lightrag_full_relations.count` 取數之後這個問題消失。

## 未解問題

`Empty entity name found after sanitization in JSON result` 在 C 上出現 235 次，是 JSON 結構化
輸出吐出空的 entity name 後被丟棄。與掉字**只有部分重疊**（chunk 031/027/051/036/047 有大量空名
但完全沒掉字），所以是獨立問題，開 `MINERU_IS_OCR` 不會解掉。
