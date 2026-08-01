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
| rag_storage | `/data/lightrag/${WORKSPACE}/rag_storage` |
| 語料來源（唯讀） | `/data/rag/knowledge_bases/${WORKSPACE}/raw` |

語料 390 個 PDF、約 2.0 GB，留在 `/data` 的獨立 NVMe，不進 repo。

### 儲存後端

沿用既有的 `deeptutor-v4-postgres`（DB `lightrag`，pgvector 0.8.2）與 `deeptutor-v4-neo4j`，
接在 `rag_default` 網路上。**靠 `WORKSPACE` 隔離** —— Postgres 用 workspace 欄位、Neo4j 用節點
標籤，所以多個知識庫可共存於同一組資料庫。

要跑第二個知識庫：複製本目錄為另一個 stack，改 `WORKSPACE` 與 `HOST_PORT` 即可。

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
