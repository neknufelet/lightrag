---
title: NEXT — 接下來做什麼
date_created: 2026-06-20
date_modified: 2026-08-07
status: living
kind: sop
supersedes: ""
superseded_by: ""
summary: "當前待辦的唯一 SSOT。只放「還要做什麼」，做完就刪整行——證據天生在 git。"
---

# NEXT — 接下來做什麼

**只放待辦。** 做完就刪整行，不留劃掉線與證據 dump（那是 799 行的來源）。上限 80 行。

其他東西的去處：鐵則／契約／座標 → [CLAUDE.md](CLAUDE.md)；某個決定為什麼那樣下 →
[docs/decisions/](docs/decisions/)；知道但決定不修 → [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md)；
某天發生了什麼 → [cairn/LOG.md](cairn/LOG.md)；檢查超標時的前例 → `tests/verified-findings.json`（工具自己印）。

## 狀態

主線是**乾淨重建 ＋ 升級到 v1.5.6**（[ADR-0004](docs/decisions/0004-rebuild-instead-of-patching.md)）：
坑清單 173 條裡 151 條在重建後不存在，逐條補探針的價值在重建那天歸零。

| 線 | 當前 | 狀態 |
|---|---|---|
| `REBORN` | `REBORN-1` 抽乾淨不可再生的 | 🔵 |
| `GUARD` | `GUARD-2` standards-check | 🔵 |
| `SCALEUP` | 擴到 390 份 | ⏸ 等重建 |

---

## `REBORN` — 乾淨重建（主線）

- [ ] **`REBORN-1`：抽乾淨不可再生的。** 人工裁定 227 檔 ✅、PDF 有副本 ✅。
      **缺 `.env`**——不備份秘密，只記「哪 7 個鍵是秘密、去哪拿」進 `.env.example`
- [ ] **`REBORN-2`：填空題。** 13 條活下來的坑裡 7 條是 `.env` 的值（`MINERU_IS_OCR`／
      `ENTITY_EXTRACTION_USE_JSON`／`EMBEDDING_DIM`＋`SEND_DIM`／digest／`KBAPI_PORT`／
      `PP_EYE_C_PROVIDER`／裁圖快取鍵）⇒ 產出新環境該長什麼樣＋每項的執行者
- [ ] **`REBORN-3`：確認 `PGTableGraphStorage` 的環境變數名。** release notes 沒寫，
      `LIGHTRAG_GRAPH_STORAGE=PGTableGraphStorage` 是推測 `(未驗)`
- [ ] **`REBORN-4`：重建。** 新 compose（**拿掉 neo4j**）、新 `.env`、乾淨資料根。
      PO 選 A：語料仍是那 18 章，不與新語料的版面問題混在一起
- [ ] **`REBORN-5`：驗收。** `compat-check` 124 項＋canary＋`extract-check`；
      順帶驗 non-root 容器是否解決「root 寫 `work/parsed`」

## `GUARD` — 給規則配執行者

- [x] `GUARD-1`：LOG 落後檢查（`tests/test_log_freshness.py`）＋ pre-commit 擋 commit 格式
- [ ] **`GUARD-2`：`standards-check`。** 掃 frontmatter、必要檔案、行數上限，
      接進 `daily-check`。做完那張「標準要求 vs 現況」的落差表每天自己出現一次
- [ ] **`GUARD-3`：修上游。** `standards/scripts/scan_projects.py` 的預設路徑還是
      Windows 的 `E:/`，且沒有任何排程——它從來沒自動跑過
- [ ] **`GUARD-4`：把「誰會發現」四級升格進 `BASELINE.md`。** 那是本專案唯一被實證
      有效的機制（坑清單＋消費者測試），而它不在標準裡。判準：任何規則進 BASELINE
      前先回答「違反時誰會發現」，答不出來就不准進——連 BASELINE 自己都適用

## ⬜ 等 PO 決定

- [ ] **backrest 那兩個排程**（`rag-snapshot` 備空目錄、`lightrag-snapshot`）。只能關
      排程不能停容器（冷備份借用容器裡的 restic）；另三個 plan 是 Obsidian／Zotero／Calibre
- [ ] **`archive-ledger.py --move`**（15 張幽靈體檢表）。副本已在 `verdicts/`，不會失去東西
- [ ] **350 MB 可再生的要不要刪**（`work/parsed` 等）。代價是重跑 6–10 小時解析

## 重建後仍然要做的

- [ ] `REBUILD-3`：canary／compat-check 母體為 0 時硬失敗而非「驗不了」（**重建必遇空庫**）
- [ ] `REBUILD-5`：假綠測試——`postprocess.py` 讀 `parsed.stderr` 卻沒帶 `capture_output`，分支永不執行，而 `test_prepare.py` 捏假物件測它
- [ ] intake 的 `exit 2` 不是錯誤訊息（真正原因只在 `run.log`，要帶進 `error` 欄）
- [ ] 六份接地 >5%：要降下來得**重量 `is_symbolic` 判準**（門檻用量的）。材料＝體檢表 note 欄那 120 個名字
- [ ] `C` 的 91 個「bbox 未覆蓋」詞併進哪個 item 的 caption，尚未裁決
- [ ] `eq-check` 三票多數決還沒對 v2 跑過
- [ ] `retrieval-check.py` 頭條數字是假訊號。擇一：給它新問題，或改報相異雜訊字串數（v155 670 → v2 13）
- [ ] 實體碎片化在 v2 還沒量（KI-006 借的是 v155 母體）
- [ ] 「qwen 系統性切錯列」缺第二份樣本（一份證據是巧合）
- [ ] 內容變動型規則對 canary 是隱形的（計數不在被追蹤的量裡）
- [ ] `SPEEDUP-3`：llama-server 啟動參數只活在容器 config 裡，`docker rm` 就沒了
- [ ] `SPEEDUP-4`：gleaning 定案缺 parser／merge／relation-aware 的 A/B 與 `completion_tokens`
- [ ] `SCALEUP`：擴到 390 份。新版面照 `.claude/skills/onboard-doc-type/SKILL.md` 走
