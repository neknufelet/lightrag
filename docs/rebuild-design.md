---
title: 重建設計 — 一篇打通全程
date_created: 2026-08-07
date_modified: 2026-08-07
status: accepted
kind: spec
supersedes: ""
superseded_by: ""
summary: "新部署的設計。定位是原料供應站，範圍是用 C Equivalent Networks.pdf 一篇打通全程。十個決定全部經過拷問，附推翻掉的三條。"
---

# 重建設計 — 一篇打通全程

**這份是「新部署長什麼樣」的裁決，不是實作計畫。** 實作步驟另外寫。

**它刻意不繼承 repo 裡上一輪的提案。** 量出來的數字（MinerU 三組對照、掉字型態、
關係欄位被拒收）留下；沒驗過的想法（版本號、拿不拿掉 Neo4j、埠號、workspace 命名）
全部重新問過一次。`docs/rebuild-checklist.md` 的 13 條仍然成立，那份講的是外部的東西
必須保持什麼樣子，與本份不衝突。

---

## 1. 這套系統是什麼

**聲學文獻的原料供應站。** 它不下結論、不做綜述——思考由 Obsidian 裡的 agent 做，
知識庫的工作是把乾淨的原料遞過去。

**唯一的消費者是 Obsidian 裡的 agent**，走 HTTP 打三個 skill。人不直接查。

這個定位是本份最重要的一條，因為它決定了「什麼叫做得好」：**原料乾淨、可追溯、
拿得到**，而不是「答案漂亮」。

### 三種取用型態，地位相同

| | 給它什麼 | 回什麼 | 拿來幹嘛 | 走不走 LightRAG |
|---|---|---|---|---|
| **跨篇發現** | 一個主題（例：MPP 微穿孔吸音） | 哪幾篇碰到、各自的原文片段 | 決定要細看哪幾篇 | **走**（向量＋圖譜） |
| **單篇原料** | 一個檔名 | 章節、表格、方程式、圖片清單 **＋ 可分節的正文** | 建自己的 LLM wiki | **不走**，直接讀解析產物 |
| **找圖** | 一個主題 | 圖的別名＋caption，可下載進 vault | 拓展想法 | 查詢走，檔案不走 |

**「跨篇發現」不是問答。** 它的工作是告訴你哪幾篇碰過這個題目，不是給你一段總結。
消費者拿到片段之後自己判斷。

### 明確不做

- entity/relation 圖譜端點（問過，不需要）
- 自動綜述、自動回答
- 給人直接使用的介面
- 20 篇全灌、入庫自動化、警報管道（都不在這一輪）

---

## 2. 範圍：一篇打通

**只做 `C Equivalent Networks.pdf` 一篇，從 PDF 到三種型態都取得到。**

選它的理由有三個，缺一不可：

1. **10 個真正不可再生的人工裁定全在它身上**，所以它同時就是裁定對位的試跑
2. 它是 2026-08-01 三組解析實測的基準文件（209 區塊、9/57 空表格、189,430 字元），
   新舊有數字可對
3. 它的已知難點最密集——羅馬數字下標、`\times` 誤讀、表格結構黏連全部在它身上

**手動分步跑，每步留輸出。** 不做狀態機、不做自動化。要擴到 20 篇時再談，
而且那時候已經知道哪幾步真的會卡。

---

## 3. 元件與邊界

```
                 ┌─────────────────────────────────────────┐
  PDF ──────────▶│ MinerU（官方 API）                        │
                 │ is_ocr=true, model_version=pipeline      │
                 └───────────────┬─────────────────────────┘
                                 │ content_list.json ＋ images/
                                 ▼
                 ┌─────────────────────────────────────────┐
                 │ 後處理 scripts/pp/                        │
                 │  rules/ 四支機械規則                       │
                 │  兩雙眼睛（表格／方程式）→ 三方皆異才叫第三隻眼 │
                 └───────────────┬─────────────────────────┘
                                 │ 修補寫回 content_list.json
                    ┌────────────┴────────────┐
                    ▼                         ▼
      ┌───────────────────────┐   ┌─────────────────────────┐
      │ LightRAG              │   │ 唯讀 API 層               │
      │ 抽實體與關係（本機 LLM） │◀──│ docs / doc / 正文 / 圖片   │
      │ 四種儲存全在 Postgres   │   │ ＋ 代持 API key 轉發查詢    │
      └───────────────────────┘   └────────────┬────────────┘
                                                │ HTTP
                                                ▼
                                  三個 skill ／ Obsidian 的 agent
```

### 邊界：誰負責什麼

| 元件 | 只做一件事 | 不做 |
|---|---|---|
| MinerU | PDF → 結構化區塊 | 不修正自己的錯 |
| `scripts/pp/` | 修補解析產物，寫回 `content_list.json` | 不碰 LightRAG、不重寫第二份 LightRAG 行為 |
| LightRAG | 向量 ＋ 圖譜檢索 | 不知道表格、方程式、圖片的存在 |
| 唯讀 API 層 | 補 LightRAG 沒有的端點、代持金鑰 | 不寫入、不修補、不下結論 |
| 三個 skill | 呼叫端點、把結果交給 agent | 不做 MCP、不用一般知識補答案 |

**唯讀 API 層不是薄代理。** 五個端點裡有三個完全不碰 LightRAG——它們直接讀解析產物。
拿掉這層，「單篇原料」與「找圖」兩個用途直接消失。

---

## 4. 十個決定

### D1　skill 凍契約，不凍位址

**端點路徑與回傳格式不變；IP、埠、workspace 名稱可以改。**

三個 SKILL.md 目前寫死了 IP 14 次、埠 17 次、workspace 8 次。要求「一行不改」等於
凍結上一輪的部署拓樸——那是拿舊架構替新架構做決定。

skill 裡累積的**使用知識全數保留**：`top_k` 對回傳量的反直覺行為、別名格式、
`curl -f` 的必要性、PowerShell 沒有 `/tmp`。那些跟後端無關。

### D2　單篇正文從 `content_list.json` 渲染

**新增端點：預設回整篇 markdown，加參數只回某一節。**

不能用 MinerU 原本那份 `.md`。`scripts/pp/apply.py` 第 349 行：

> 涵蓋範圍：要改的對象只有 content_list.json 與 _manifest.json 兩個檔

**所有修補只寫進 `content_list.json`。** 送 MinerU 的原始 markdown 出去，等於送出
一份表格又變回空的、LaTeX 沒修、雜訊沒消的版本——而且看起來完全正常。

現況的洞：`doc` 端點不回正文（自己註解寫「要全文請用 search 定位」），而 `search`
**不能鎖定單篇**。所以「建某一篇的 wiki」現在踩在一個沒有保證的動作上。

### D3　圖譜留下，但必須有可驗的斷言

留的理由是「拓展想法」——找出用了同一手法但沒寫那個詞的篇。

**代價要講清楚**：圖譜是整個系統最貴、最會錯的部分，而它只服務三種型態裡的一種。

**斷言是留它的前提**，因為最惡毒的失敗長這樣：`ENTITY_EXTRACTION_USE_JSON` 沒開時，
本機模型的關係記錄只吐 4/5 欄位，LightRAG **100% 拒收**——症狀是「實體正常、關係 0」。
畫面有東西、查詢有回應、看起來全部正常，但圖是空的。

**第一次跑出來的數字就是基準**，因為舊的量測基準已經不存在（見 §7）。

### D4　三層降噪規則全帶

| 層 | 帶什麼 | 實測依據 |
|---|---|---|
| 解析 | `MINERU_IS_OCR=true`、`MINERU_MODEL_VERSION=pipeline` | 關掉 `is_ocr` 出現 45 個掉字（43 個裡 40 個是 x-height 字母）；用預設 `vlm` 有 16/57 表格全空，`pipeline` 只有 9/57 且內容量兩倍以上 |
| 後處理 | `scripts/pp/rules/` 四支 | 一份一份文件逼出來的 |
| 抽取 | `ENTITY_EXTRACTION_USE_JSON=true`、`EMBEDDING_SEND_DIM` | 前者見 D3；後者不設會在索引寫入時才失敗，錯誤訊息不指向根因 |

### D5　人工裁定：163 個重生，10 張表對位

**`verdicts/README.md` 說 173 個檔案不可再生，實際只有 10 個是。**

| | 數量 | 誰產生的 | 真的不可再生？ |
|---|---|---|---|
| `*.html` | 10 | 人看著裁圖一格一格打 | **是** |
| `*.txt` | 163 | 檔頭寫「機械套用」，來自 `scripts/pp/rules/latex_fix.py`（該檔第 1 行：「三個**機械**的 LaTeX 修補：位置錨定、零例外可驗、**不呼叫模型**」） | 否，重跑規則就有 |

**163 個不搬舊檔，重跑規則重生。** 搬舊檔反而把可再生的東西綁回索引，平白製造風險。

**10 張表用頁碼對位。** `review.md` 每項記了索引＋頁碼（`## #390　第 29 頁`），
裁圖檔名 `t390-29.png` 也把兩者編進去了。

⚠ 這是必要的，因為鐵則第 8 條：重解析同一份 PDF 拿到的不是同一份東西，MinerU 對表格
的辨識不可重現，**而裁定的檔名就是陣列索引**（`373.html` ＝ 第 373 項），沒有第二個
對位線索。索引錯位不會報錯，它會安靜地把 A 表的內容補進 B 表。

**最壞情況是重判 10 張表。** 這個風險小到不值得為它改變計畫。

### D6　本機抽取；只有後處理找外援

| | 誰做 | 找不找外援 |
|---|---|---|
| 實體與關係抽取 | 本機 LLM，量很大 | **不找**。每個 chunk 都找外援等於整批雲端跑 |
| 表格轉錄／方程式正確性 | 本機 ＋ 雲端兩雙眼睛 | **找**。不一致才判，三方皆異（約 13%）才叫第三隻眼 |

外援機制已經蓋好，而且擋得住「找了同一家的外援」——`scripts/pp/eyes.py`：

```python
def assert_distinct(eyes_: list[Eye]) -> None:
    """多數決前的前提檢查。家族重複時投票會失真 —— 一個血統投兩票。"""
```

⚠ **這是一條跨機依賴。** 本機模型跑在 coder（2× RTX 3060），dker 的 `nvidia-smi` 是壞的
（KI-013，driver/library mismatch）。所以 dker 要抽取得跨 Tailscale 打回 coder，
**coder 睡著入庫就停在那裡**。這在上一輪沒被當成問題，因為兩台大概都開著。

⚠ 本機模型會捏造內容：57 張表裡 24 張生出 `<img>`，8 張附不存在的 imgur 網址，雲端那眼
0 張。**但那是表格轉錄量到的，抽實體關係時會不會也編，沒有人量過。**

要量它的工具**已經存在**，是 `scripts/extract-check.py`——它做的事就是把抽出來的每個
實體名拿回原文搜一次，搜不到的標可疑。它自己的說明講得最清楚：

> 數量好看不代表內容對 —— **1,135 個實體可能全是幻覺，計數一模一樣**。

所以試跑不必新寫檢查，把這支接上就好。

### D7　四種儲存全進 Postgres，刪掉 Neo4j

現況已經有三種在 Postgres，只剩圖在 Neo4j。上游 `env.example` 原文：

```
LIGHTRAG_GRAPH_STORAGE options: NetworkXStorage, Neo4JStorage, PGGraphStorage,
PGTableGraphStorage, MongoGraphStorage, MemgraphStorage, OpenSearchGraphStorage
```

`PGTableGraphStorage` 把圖存在普通表格＋JSONB 裡，**不需要 Apache AGE 擴充**，
stock PostgreSQL 14+ 就能跑。

**兩個但書**：

1. 上游那組效能數字（p50 39ms vs 1,099ms）比的是 **PGTableGraphStorage vs
   PGGraphStorage（AGE 版）**，**不是**跟 Neo4j 比。不得引用成「比 Neo4j 快」。
2. ~~選定的映像版本有沒有這個選項未驗~~ **2026-08-07 已驗，問映像本人**：

```
$ docker run --rm --entrypoint sh ghcr.io/hkuds/lightrag:v1.5.6 -c \
    'python -c "from lightrag.kg import STORAGE_IMPLEMENTATIONS as S
                print(S[\"GRAPH_STORAGE\"][\"implementations\"])"'
['NetworkXStorage', 'Neo4JStorage', 'PGGraphStorage', 'PGTableGraphStorage',
 'MongoGraphStorage', 'MemgraphStorage', 'OpenSearchGraphStorage']
```

同一條指令對 **v1.5.5** 跑，清單裡**沒有** `PGTableGraphStorage`。而 `compose.yaml`
原本釘的 digest `206579ab…` 經 dker 逐字元核對**就是 v1.5.5**——所以升級到 v1.5.6
是這個決定的必要條件，不是順便。新 digest `ab23a9c8…`，v1.5.5 映像已從 dker 移除。

### D8　不 fork、不 build 自己的映像；要加的東西插在旁邊

**官方映像原封不動拉下來，額外功能一律用「旁邊再起一個容器 ＋ 把程式碼掛進去」。**

現成的例子就是唯讀 API 層——它不是自建映像，是官方 `python:3.12-slim`：

```yaml
kbapi:
    image: python:3.12-slim
    command: ["python", "/app/scripts/kbapi.py", "--port", "9700"]
    volumes:
      - ./scripts:/app/scripts:ro
```

`compose.yaml` 裡的原話：「只用 Python 標準函式庫，所以直接掛官方 slim 映像跑腳本，
**不需要自己建映像**。」

**價值在升級的時候**：官方出新版就改一行 digest，沒有「我們的 patch 要 rebase」
這件事。今天從 v1.5.5 換到 v1.5.6 就是改一行。反過來說，任何「這個功能得改
LightRAG 的程式碼才做得到」的需求，都要先當成設計錯誤重新想。

### D9　部署走 Dockge，但 repo 是 SSOT

`/opt/stacks/lightrag/compose.yaml` 是 repo 那份的**副本**，部署動作把它複製過去。
模式與 `deploy/systemd/*.service` → `/etc/systemd/system/` 相同（`systemd-units.py
install`），維護的人只要理解一次。要有一條斷言比對兩邊的 sha256，漂了就紅。

**兩個不可以：**

- **`/opt/stacks/lightrag/` 不可以是指向 repo 的 bind mount。** 2026-08-07 之前是，
  結果 Dockge UI 的「刪除」按鈕會刪掉 repo 本身（宿主上那是空目錄，容器裡看到的是
  repo）——連 dker 上唯一的 `.env` 一起沒。
- **stack 目錄的 compose.yaml 不可以是指回 repo 的 symlink。** Dockge UI 可以編輯
  compose，寫下去就是改到 dker 的 checkout，下次 `git pull --ff-only` 直接失敗。

**另外：`.env` 要搬出 git checkout。** 它現在住在 repo 目錄裡，所以「刪掉 repo」
與「弄丟所有秘密」是同一個動作。搬到 stack 目錄之後這條連動就斷了。

### D10　設計文件放 `docs/` 直接底下

`scripts/standards-check.py` 的治理範圍是 `REPO.glob("docs/*.md")`，**不是 `docs/**/*.md`**。
放進次目錄會靜靜逃掉 frontmatter 檢查。

---

## 5. 資料流：一篇走完的樣子

1. **解析**　PDF → MinerU（釘死兩個參數）→ `content_list.json` ＋ `images/`
2. **驗來源**　用 `records/ledger/*.json` 的 `pdf_sha256` 確認是同一個檔
3. **量基準**　項目總數、表格數與位置、空表格數、掉字數（**先剔除數學式**，
   行內 LaTeX 會把字母拆開排版，長得跟掉字一模一樣）
4. **機械規則**　`pp/rules/` 四支跑過，163 個 LaTeX 修正在此重生
5. **對位裁定**　10 張表按頁碼對位；對不上的**明確報出來**，不猜
6. **兩雙眼睛**　剩下的空表格走交叉比對，三方皆異才叫第三隻眼
7. **入庫**　LightRAG 抽實體與關係（本機 LLM）→ 四種儲存全進 Postgres
8. **驗圖**　關係數、實體數、實體名可在原文找到的比例
9. **驗端點**　三個 skill 的五＋一個端點逐一打過

---

## 6. 錯誤處理：什麼情況要停

沿用鐵則第 1 條——**`preflight()` 拒絕，不猜**。用不適用的規則硬跑會產生
「有產出但產出錯誤」，那是這個專案一路在防的東西。

| 情況 | 動作 |
|---|---|
| 未知型別、頁面尺寸不一致、`source_content_hash` 對不上 | **停整份文件**，不部分處理 |
| 裁定索引對不上 | **報出是哪幾張**，不套用，不猜 |
| 關係數是 0 | **紅燈**，不當成「這篇沒有關係」 |
| 某個量測回報漂亮的 0 | 先當成量錯（鐵則第 7 條）。三次踩過，每次都「看起來像乾淨的結論」 |
| 映像不支援 `PGTableGraphStorage` | 退回 Neo4j，記進 KNOWN_ISSUES |

---

## 7. 測試與驗證

### 這一輪的成功判準

1. **三個 skill 只改位址設定就能跑通**，端點語意與回傳格式不變
2. **關係數不是 0**；空表格不比 9/57 多；掉字接近 0（剔除數學式後）
3. **10 張表的裁定對得上位**，或明確報出對不上的是哪幾張
4. 「丟這篇 PDF 進去 → 三種型態都取得到它」是一條**留有輸出、可重跑**的路徑

### ⚠ 沒有可對照的基準

舊的解析產物**不存在了**，dker 上實測：

```
$ ssh florian-dker 'ls /data/lightrag/; ls /data/lightrag/work'
checks
records
ls: cannot access '/data/lightrag/work': No such file or directory
```

git 裡也刻意沒有（`verdicts/README.md`：解析快取 307 MB 不進版控）。
**所以「新舊比對」這個選項不存在**，第一次跑出來的數字就是基準。
引用 2026-08-01 那組數字時必須標明它來自舊環境。

### 每一步都要留輸出

手動跑的意義就在這裡。沒有留下輸出的步驟等於沒跑過——鐵則第 6 條：
收合輸出時必須報出「幾項通過未列出」，否則「沒印出來」跟「沒檢查」在畫面上長得一樣。

---

## 8. 已知風險

| 風險 | 為什麼會咬人 |
|---|---|
| **coder 睡著入庫就停** | 跨機依賴（D6），而且不會有錯誤訊息，只是卡著 |
| **本機模型抽實體時可能捏造** | 表格轉錄已證實會編（24/57），抽取層沒量過 |
| **重解析後表格辨識不可重現** | 鐵則第 8 條。裁定綁索引，錯位不報錯 |
| **映像可能不支援 PGTableGraphStorage** | 未驗。實作第一步就要驗 |
| **MinerU API token 2026-09-04 到期** | 到期後解析直接不能跑 |
| **羅馬數字 I/II/III 換模型也解不掉** | 四個獨立檢查、四個層次都指向它 |
| **沒有警報管道** | ntfy 已拆。紅燈會落地，但沒有東西會打斷人 |

---

## 9. 這一輪之後

不在本份範圍，但已知要處理：擴到 20 篇、入庫自動化、警報管道、
`scripts/pp/oracle.py` 的 `mineru_options()` 接上（現在全 repo 零呼叫端，
接上之後 `rebuild-checklist` 的 A 節六條就有執行者）。

寫進 [docs/NEXT.md](NEXT.md)，不寫在這裡——這份是裁決，不是待辦。
