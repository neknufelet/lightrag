# lightrag-v1

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

| 用途 | 位置 |
|---|---|
| 設定（版控） | 本 repo |
| rag_storage | `/data/rag/lightrag/${WORKSPACE}/rag_storage` |
| 待匯入文件 | `/data/rag/lightrag/${WORKSPACE}/inputs/${WORKSPACE}/` ← 注意多一層 |
| MinerU 解析快取 | `.../inputs/${WORKSPACE}/__parsed__/` ← 貴，務必納入備份 |
| 過程紀錄 | `/data/rag/lightrag/${WORKSPACE}/records/` |
| 語料來源 | `/data/rag/knowledge_bases/*/raw`（不掛進容器） |

執行期資料刻意全部放在 `/data/rag` 底下，因為該路徑已納入 restic 備份 —— Postgres
（`/data/rag/postgres_data`）與 Neo4j（`/data/rag/neo4j_data`）也在其中。解析快取尤其
不能掉：390 份重新解析要 6–10 小時的 MinerU 呼叫。

### 映像用 digest 釘死

`compose.yaml` 指定的是 `@sha256:...` 而非 `:v1.5.5`。標籤可被重推，同一行指令在不同
時間可能拉到不同映像；而後處理腳本全都建立在「LightRAG 如何讀寫 `__parsed__`」這些
假設上，環境默默變動會讓假設失效卻無人察覺。釘 digest 讓升級變成明確的動作。

語料 390 個 PDF、約 2.0 GB，留在 `/data` 的獨立 NVMe，不進 repo。

### 文件要放進 inputs 的 workspace 子目錄

設了 `WORKSPACE` 之後，LightRAG **只掃 `inputs/${WORKSPACE}/`，不掃 `inputs/` 根層**。
放在根層的檔案掃描會回報 `0 discovered` 而且不報錯，很容易誤判成服務壞了。該子目錄由容器
啟動時自動建立。

```bash
cp foo.pdf /data/lightrag/acoustics_v155/inputs/acoustics_v155/
curl -X POST -H "X-API-Key: $KEY" http://100.87.88.7:9621/documents/scan
```

`inputs` 也**不能唯讀掛載** —— 容器啟動時要建上述子目錄，掛 `:ro` 會直接 crash loop。
這是為什麼此處用專屬目錄而非直接掛 `/data/rag/knowledge_bases/*/raw`。

### 儲存後端

沿用既有的 `deeptutor-v4-postgres`（DB `lightrag`，pgvector 0.8.2）與 `deeptutor-v4-neo4j`，
接在 `rag_default` 網路上。**靠 `WORKSPACE` 隔離** —— Postgres 用 workspace 欄位、Neo4j 用節點
標籤，所以多個知識庫可共存於同一組資料庫。

要跑第二個知識庫：複製本目錄為另一個 stack，改 `WORKSPACE` 與 `HOST_PORT` 即可。

## 拆解品質檢查（整批重跑前先用這個）

```bash
./scripts/parse-check.py --details      # 檢查已解析的文件
./scripts/parse-check.py --watch        # 邊解析邊看
```

MinerU 的原始輸出快取在 `inputs/<ws>/__parsed__/<檔名>.mineru_raw/`，所以**解析一結束就能驗，
不必等後面幾十小時的 LLM 抽取**。整批重新 parsing 時先跑這個確認拆得對，再讓 LLM 上工。

檢查項目：掉字、空的文字／表格／公式區塊、整頁無正文、prompt 洩漏。有 ERROR 時 exit 1。

已知會抓到的真實問題：**MinerU 有時偵測到表格區域卻什麼都不產出** —— `table_body` 缺席、
`img_path` 也是空字串，連退而求其次的圖片備份都沒有，該區域內容完全遺失。C Equivalent Networks
是 16/57（28%）。

## 比對工具

```bash
./scripts/compare.sh 'Equivalent' acoustics_v155
```

直接查兩邊資料庫比對舊管線與 1.5.5 對同一份文件的索引結果，不依賴人工記錄的數字。內含已驗證的
掉字偵測器 —— 注意用的是 `(?:\s+[a-z]{1,2}\y){5,}`，**不要**改成兩側都是 `\s` 的版本，那會因為
前一次匹配吃掉後一次的前導空白而永遠回 0。

## 未解問題

`Empty entity name found after sanitization in JSON result` 在 C 上出現 235 次，是 JSON 結構化
輸出吐出空的 entity name 後被丟棄。與掉字**只有部分重疊**（chunk 031/027/051/036/047 有大量空名
但完全沒掉字），所以是獨立問題，開 `MINERU_IS_OCR` 不會解掉。
