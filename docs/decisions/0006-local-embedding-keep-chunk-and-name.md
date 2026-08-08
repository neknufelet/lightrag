# ADR-0006: embedding 本地化；chunk 大小與 workspace 名稱維持不動

* **Status**: Accepted
* **Date**: 2026-08-08
* **Deciders**: PO

---

## Context

2026-08-08 四篇論文進庫後，手上同時有四個可以調的旋鈕：embedding 模型、
embedding 維度、`CHUNK_P_SIZE`、workspace 名稱。**沒有任何一個有實測依據**，
只有印象（「1024 維太小」「3-small 勉強可以用」「換 embedding 很貴」）。

所以先量再決定。量法與完整數據在 `cairn/retrieval-tuning.md`，這裡只記裁決。

## Decision

**三件事一起定案：**

1. **embedding 換成本地 `BAAI/bge-m3` @1024**（跑 dker 的 2070，Infinity 服務）
2. **`CHUNK_P_SIZE` 維持 2000**，不砍到 1000
3. **workspace 維持 `acoustics_v2`，不改名**

## Rationale

### 一、embedding 換本地：理由不是品質，是依賴

品質是平手。五個變體並排量過（`3-large` 的 3072／1536／1024、`bge-m3@1024`、
`3-small@1536`），差異全在雜訊範圍內；再用第二個 workspace 並排跑 10 題
（含 4 道中文），逐題判定平手 5、實驗組勝 3、對照組勝 2。

**所以理由只能是別的**：少一個外部服務、少一把會過期的金鑰、不按次計費。
（錢不是理由——現在的規模全部重算約 85 萬 token，十美分上下。）

**維度的疑慮解除**：`3-large` 的 3072／1536／1024 三者無差異，證明
「1024 太小」不成立。模型作者出貨 MRL 截斷功能，本身就說明尾巴那些維度
帶的資訊很少。

### 二、`CHUNK_P_SIZE` 維持 2000：付兩倍換不到東西

並排實測：砍到 1000 讓 chunk 從 207 變 405（**抽取成本 +96%**，而每個 chunk
都要跑一次 LLM），節點只多 17%、邊多 20%，檢索品質在雜訊範圍內。

節點沒有跟著翻倍的原因：同一段內容切成兩半之後，兩半抽出來的實體大量重複，
重複的會合併。

⇒ **每次進料貴一倍，換不到可量測的東西。**

### 三、workspace 不改名：波及面大、價值低

`_v2` 這個後綴難看，但**功能上只是一個字串**。改它要動：

| 位置 | 內容 | 漏改的後果 |
|---|---|---|
| `scripts/backup-cold.sh:53` | `DEPS=(kbapi-acoustics_v2 lightrag-acoustics_v2)` | **停錯容器或什麼都沒停** |
| `scripts/systemd-units.py` | 兩處把 `"acoustics_v2"` 當預設值 | 落到錯的 workspace |
| 三個 skill（`AI_TOOLS`） | 8 處 `/kb/acoustics_v2/` URL | 全部打到不存在的庫 |
| `tests/` 三個檔 | 固定值 | 測試紅 |
| `.env` | `WORKSPACE=` | —— |

⇒ **五個地方、一個漏掉就是新的坑，換一個純美觀的改善。** 不划算。

（若日後仍要改，前置條件是先做「workspace 名稱只准出現在 `.env`」的檢查，
否則同樣的散落會再發生一次。）

## Consequences

- **換 embedding 很便宜，這點與直覺相反且值得記住。** chunk 沒動 ⇒ 抽取快取
  （452 筆）全部命中 ⇒ 207 個 chunk 的抽取 **45 秒**走完，只有向量真的重算。
  對照：實驗組因為改了 `CHUNK_P_SIZE`，快取全落空、抽了兩小時。**差 160 倍。**
  ⇒ 之後要試別的 embedding 模型，成本是幾分鐘，不是半個下午。
- **退路不需要備份檔**：舊的 OpenAI 向量表沒有被刪（表名含模型與維度，是不同的表），
  改回 `.env` 三個值再重掃即可。
- **新的單點**：Infinity 掛掉會讓 embedding 與 rerank **同時**失效，
  而目前沒有任何檢查在看它。已列入 `docs/NEXT.md`。
- **外部依賴從四個減到三個**：OpenAI 只剩第二雙眼睛，加上 MinerU 與 OpenRouter。

## 被推翻的推論（留著，免得下次再想一遍）

- **「五件事綁成一次重新進料」是錯的。** 原本要把換 embedding、改 chunk、改提示詞、
  改名綁一起做以節省重跑次數。PO 問「不是要保留舊的才能比嗎」才發現：三件事
  同時做會改變 chunk 本身，舊向量對應的是不同文字，**根本不可比**。
  正解是開第二個 workspace 並排跑，對照組全程不動。
- **「換 embedding 很貴」是錯的印象。** 見上面的 45 秒。

## 相關

- 量測方法與完整數據：`cairn/retrieval-tuning.md`
- 查詢翻譯（同一輪的另一個裁決）：ADR-0005
