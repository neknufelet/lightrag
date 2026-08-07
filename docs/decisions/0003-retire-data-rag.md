# ADR-0003: 廢除 `/data/rag`，所有東西收進 `/data/lightrag`

* **Status**: Accepted
* **Date**: 2026-08-07
* **Deciders**: PO

---

## Context

2026-08-04 乾淨重建把資料根搬到 `/data/lightrag`，但 `/data/rag` 沒有死透。它同時
承載三件互相獨立的事：

1. 已搬走的舊資料根 `/data/rag/lightrag`（217 MB，`REBUILD-11` 掛著待刪）
2. **冷備份的暫存區** `/data/rag/coldstage`（硬編碼在 `scripts/backup-cold.sh`，
   每天 03:00 複製整個 DB 的落點）
3. DeepTutor 的語料庫 `/data/rag/knowledge_bases`（`INTAKE_SOURCES` 指向它）

於是文件裡同時存在「`/data/rag` 從此與本專案無關」與「不要整個刪掉」兩種說法。
PO 清空該目錄後，**隔天 03:28 它又出現了**——備份腳本自己 `mkdir -p` 建回來的，
而且看起來一切正常。

## Decision

**`/data/rag` 廢除，不得再有任何東西寫進去。** 所有東西在 `/data/lightrag` 底下。

## Rationale

「一個名字承載三件事」是本專案已記載的事故族（兩個 workspace 被併成一列、
容器名寫死）。這類問題的共通形狀是**雙來源、無訊號**。

處置不是「文件寫清楚它有三個用途」，而是**讓那個名字不再存在**——文件會過期，
路徑不會。

| 方案 | 結論 |
|---|---|
| 暫存區搬到 `/data/lightrag-coldstage`（選定） | ✅ 同一顆 NVMe、名字綁 lightrag、不在資料根內 |
| 暫存區搬到 `/data/lightrag/coldstage` | ❌ 腳本做 `cp -a "$DB_ROOT/." "$STAGE/"`，暫存區在資料根裡面會**複製進自己**（每天翻一倍且不報錯）；且 backrest 涵蓋整個 `/data/lightrag`，等於每 6 小時重複上傳 1.6 GB |
| 只刪目錄、不改腳本 | ❌ 已實測失敗：腳本每天把它建回來 |

## Consequences

**正面**
- 資料根只有一個名字，`scripts/pp/paths.py` 的 `DEFAULT_DATA_ROOT` 是唯一推導處
- 順帶修掉 README 備份表的反向錯誤（見 `docs/KNOWN_ISSUES.md` KI-002 的歷史）

**負面 / 需注意**
- `INTAKE_SOURCES` 留空，來源庫掃描功能停用（現在走網頁拖拉上傳）。
  空值是安全的：`intake.py` 過濾空字串，且會明確警告「尚未設定，選片清單不代表來源為空」
- backrest 仍有一個 plan（`rag-snapshot`）每 4 小時對已不存在的
  `/userdata/data/rag/knowledge_bases` 產出快照——**回報成功、內容是空的**。
  那是 DeepTutor 的庫，不歸本專案處置，但這個形狀值得記著
