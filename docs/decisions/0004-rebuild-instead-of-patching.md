# ADR-0004: 乾淨重建，不逐條補探針

* **Status**: Accepted
* **Date**: 2026-08-07
* **Deciders**: PO

---

## Context

`tests/pits.json` 記著 173 條坑，其中 **21 條「沒有人守且高優先」**。原本的方向是
一條一條給它們配探針，並用 `tests/test_pits.py` 擋住這份清單變大。

PO 對這個方向的評語是「挖東牆補西牆」——補完一條會發現兩條，而且每次開工都在
處理「之前寫過、之前沒做」。

## Decision

**走乾淨重建，不逐條補探針。** 重建包含升級到 LightRAG v1.5.6。

## Rationale

坑清單自己有一個 `survives_teardown` 欄位（拆掉重建後這條還存不存在）。算出來的
數字直接決定方向：

| survives_teardown | 條數 |
|---|---:|
| `no`（重建後消失） | **151** |
| `partial` | 8 |
| `yes`（重建後仍存在） | **13** |

而那 21 條 backlog 裡，**重建後只剩 2 條**：`MINERU_IS_OCR` 必須為 true、
`ENTITY_EXTRACTION_USE_JSON` 必須為 true。兩條都只是 `.env` 裡的一個值，
守它們約 10 行。

也就是說**補探針的價值在重建那天歸零**，而重建把 21 條變成 2 條。

升級帶來的三件實質好處（v1.5.6，2026-08-06 發布）：

1. **PGTableGraphStorage** — PostgreSQL 原生圖後端，不再需要 Apache AGE。
   我們的 KV／DocStatus／Vector 早就在 PG，只有 Graph 掛在 Neo4j
   （`LIGHTRAG_GRAPH_STORAGE=Neo4JStorage`）⇒ **Neo4j 可以整個拿掉**：
   少一個容器、540 MB、一套備份、一族「兩個資料庫要對得上」的坑
2. **容器不再以 root 執行**（v1.5.5 已有，我們沒開）⇒ 解決 `REBUILD-2`
   「容器 root 寫 `work/parsed`、宿主改不動」，那是每份新文件都會撞、
   目前靠手動 `chown` 繞過的問題
3. 一批安全修補（檔案上傳路徑穿越、密碼比對、暴力登入、SSRF）

已驗證**沒有會咬到我們的變更**：v1.5.4 把 `delete_entity`／`delete_relation`
從 document API 移到 graph API（breaking），全 repo grep 零命中。

## Consequences

**正面**
- 坑清單從 173 條掉到約 22 條，且每條有明確歸屬
- 少一個資料庫要備份與對帳
- 新結構從標準範本長出來，`STATUS.md`／`CHANGELOG.md`／`docs/decisions/`
  從第一天就在，而不是事後補

**負面 / 需注意**
- **重建等於重新抽取一次**（LLM 跑數小時）。PO 選 A：語料仍是那 18 章，
  先確認新架構正確，不與新語料的版面問題混在一起
- 動手前必須把不可再生的東西抽乾淨。已完成：人工裁定 227 檔進
  `verdicts/`。`.env` 的處置是**不備份秘密，只記錄哪些鍵是秘密、去哪裡拿**
- Neo4j → PG 圖後端**沒有官方遷移路徑的說明**，現階段假設要重新索引
  （這正好與「重新抽取一次」相容）
- v1.5.6 的 release notes **沒有寫出啟用 PGTableGraphStorage 的環境變數名**，
  施工前要去原始碼或文件確認（`LIGHTRAG_GRAPH_STORAGE=PGTableGraphStorage` 是
  推測，未驗）
