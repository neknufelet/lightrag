# lightrag

聲學知識庫：[LightRAG](https://github.com/HKUDS/LightRAG) 部署 ＋ MinerU 解析後處理。

## 現在的狀態：重建完成，跑著並在服務

2026-08-07 把跑著的東西全部移除（容器、索引、解析快取），只留下不可再生的人工裁決；
**2026-08-08 重建完成**，LightRAG v1.5.6 ＋ PostgreSQL 同時當四種儲存後端（Neo4j 已
拿掉），embedding 與 rerank 都跑 dker 本機的 Infinity。

**本節刻意不寫份數、容器數、節點數**——那些每週都在變，而寫死的版本每次都撐不過
一週。要知道現況就跑（都在 dker）：

```bash
python3 scripts/compat-check.py            # 57 條契約與環境斷言，0 全過／2 有硬失敗
python3 scripts/deploy-stack.py freshness  # 跑著的是不是最新的碼
docker ps --filter label=com.docker.compose.project=lightrag
docker exec lightrag-postgres psql -U deeptutor -d lightrag -tAc \
  "select count(*) from lightrag_doc_status where workspace='acoustics_v2';"
```

紅綠燈平常不必自己跑：`daily-check.sh` 每天跑一次，結果顯示在審核台 `:9710`。

- 為什麼重建而不是逐條修：[docs/decisions/0004](docs/decisions/0004-rebuild-instead-of-patching.md)
- 新環境必須保持什麼樣子：[docs/rebuild-checklist.md](docs/rebuild-checklist.md)
- 重建前的完整狀態：tag `archive/pre-rebuild-20260807`

**規則、契約、座標在 [CLAUDE.md](CLAUDE.md)**，接下來做什麼在 [NEXT.md](docs/NEXT.md)。

## 兩台機器

| | 角色 |
|---|---|
| **florian-coder** | 工作台。所有編輯、commit、worker CLI 都在這裡。**沒有 `.env`、沒有 docker** |
| **florian-dker** | 部署。唯讀，只 `git pull`。資料在 `/data/lightrag` |

coder 上刻意沒有 `.env` 與 docker——那讓「我在 coder 上驗過了」在物理上做不到。
凡是關於跑著的系統的陳述，一律要附 dker 上的實跑輸出。

## 解析選項：三組實測（重建後仍然成立）

同一份 `C Equivalent Networks.pdf`，只變動一個參數（2026-08-01）：

| 組合 | 真實掉字區塊 | 空表格 | 表格內容量 |
|---|---|---|---|
| vlm + is_ocr | 0 / 208 | 16 / 57 | 86,671 字元 |
| vlm 不含 is_ocr | **45 / 210** | 15 / 57 | — |
| **pipeline + is_ocr** ← 採用 | 1 / 209 | **9 / 57** | **189,430 字元** |

1. **`is_ocr` 必開，且與表格無關。** 關掉會出現 45 個掉字區塊，空表格數卻幾乎不變
   （16 vs 15）——所以表格問題不是 OCR 造成的，開著它沒有代價。
   掉字有幾何規律：43 個裡 40 個是 x-height 字母（a c e g m n o r s u w y），
   上伸部字母幾乎全存活，指向高度／bbox 過濾器。**專挑文字層完好的非掃描 PDF。**
2. **`pipeline` 優於預設的 `vlm`。** 兩者真實掉字都約等於零，但 pipeline 多救回
   7 個表格，內容量是兩倍以上。差異的 7 頁全部是 pipeline 較好，沒有一頁反向。
3. **`language` 無作用。** `ch` 與 `en` 產出 556 個區塊分毫不差。

仍有 **9 個表格區域兩種模型都救不回來**——MinerU 認得出 bbox 卻產不出 `table_body`，
連 `img_path` 都是空的。那是 MinerU 的上限，也是「兩雙眼睛」機制存在的理由。

### 量掉字時務必先剔除數學式

行內 LaTeX 會把字母拆開排版（`\mathrm { i n t e r i o r }`），長得跟掉字一模一樣。
不剔除的話 pipeline 會被誤判成 8 個掉字，實際只有 1 個。`parse-check.py` 已內建處理。

## 還沒解掉的

`Empty entity name found after sanitization in JSON result` 在 C 上出現 235 次——
JSON 結構化輸出吐出空的 entity name 後被丟棄。與掉字**只有部分重疊**，所以是獨立
問題，開 `MINERU_IS_OCR` 不會解掉。重建後要重新量它還在不在。
