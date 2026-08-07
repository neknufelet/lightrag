# ADR-0001: 只用一個 workspace，不開第二個庫

* **Status**: Accepted
* **Date**: 2026-08-05
* **Deciders**: PO

---

## Context

語料要從 Möser 教科書擴充到更多聲學文獻時，出現一個選擇：教科書與論文分兩個
workspace，還是全部進 `acoustics_v2`。

分庫的唯一實質理由會是「只根據教科書回答」這種需求。所以問題變成：LightRAG
能不能在查詢時限定文件範圍。

## Decision

**只用 `acoustics_v2` 一個庫。**

## Rationale

實測 `QueryParam` 的欄位，**沒有任何文件範圍過濾**——只有 `mode`／`top_k`／
`chunk_top_k`／`max_*_tokens`／`hl_keywords`／`ll_keywords`／
`conversation_history`／`user_prompt`／`enable_rerank`／`include_references`。

也就是說「只查某一批文件」在這個版本上**唯一做法是分 workspace**。PO 確認不需要
這個能力，所以分庫的唯一理由消失。

反過來，單一庫拿到 graph RAG 的本體價值：同一個實體出現在教科書與多篇論文時
會**合併成一個節點、帶多個出處**。分庫等於主動放棄這件事。

## Consequences

**正面**
- 跨來源的實體自動合併，檢索品質受益
- 只有一套容器、一套備份、一組體檢數字要顧

**負面 / 需注意**
- 之後若真的需要「只查教科書」，得重建成兩個庫，不能事後切分
- 與 `compose.yaml` 檔頭那段「有了自己的實例，查到別的庫在結構上不可能」**不衝突**：
  那段講的是跨專案隔離（我們的庫與 DeepTutor 的庫混在一起，咬過三次且都不報錯），
  這裡講的是同專案內的內容邊界
