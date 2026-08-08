---
title: NEXT — 接下來做什麼
date_created: 2026-06-20
date_modified: 2026-08-08
status: living
kind: sop
supersedes: ""
superseded_by: ""
summary: "當前待辦的唯一 SSOT。每條一行，理由與證據外引到 docs/audit-20260808.md。"
---

# NEXT — 接下來做什麼

**做完的項目刪整行，摘要進 [cairn/LOG.md](../cairn/LOG.md)**（BASELINE done 項紀律）。
`tests/test_next_done_ratio.py` 在完成行數追上待辦行數時會紅——那就是該掃的時候。

**一條待辦要能留在這裡，必須寫得出「怎麼知道它做完了」。** 寫不出來的不是待辦，
是願望。理由、證據與做法一律外引，本檔只留一行——
細節見 [docs/audit-20260808.md](audit-20260808.md)（條號對應該檔）。

狀態 legend：`✅完成 / 🔵進行中 / ⬜未起 / ⏸暫停 / ⚠️卡住`

## 狀態總表

| 線 | 狀態 | 卡在哪 |
|---|---|---|
| 一次重新進料（五件事） | ⬜ | 等 PO 同意範圍 |
| 守門機制（四條檢查） | ⬜ | 都是一行判斷，沒人做 |
| 擴到 20 篇 | ⬜ | 先把五件事做完再擴 |
| 上游畢業 | ⬜ | 三條候選，影響所有專案，另開一輪 |

**已收線**：五篇進庫（節點 3,072／邊 4,289／chunk 207）、查詢 token 溢位、
本地 rerank 上線、部署守衛、重開機自動復原、收件匣審核台（`:9710`）。
經過見 [cairn/LOG.md](../cairn/LOG.md)。

## ⬜ 一次重新進料（五件事綁一起做，分開做等於重跑五次）

- ⬜ 抽取時剔除參考文獻（audit 8）。**怎麼驗**：共用實體裡人名機構從 47 個降下來
- ⬜ `Figure N`／`Equation N`／`Table N` 不當實體（audit 6）。**怎麼驗**：泛用標籤節點歸零
- ⬜ `CHUNK_P_SIZE` 2000 → 1000（audit 26）。**怎麼驗**：最長 chunk 從 2,458 token 降到 1,200 以內
- ⬜ embedding 換 BGE-M3（audit 25／26）。**怎麼驗**：`EMBEDDING_DIM=1024`，新向量表有資料
- ⬜ workspace 改名 `acoustic`（audit 12）。**怎麼驗**：容器、目錄、`.env`、kbapi 四處一致
- ⬜ 做完跑那六道題（**要先補中文題**——現有題組全英文，量不到跨語言那件事）

## ⬜ 守門機制（每條都是一行判斷，做一次長期有效）

- ⬜ dker 落後 origin（audit 5）。**怎麼驗**：`git rev-list --count HEAD..origin/master` = 0
- ⬜ `.env` 與 `.env.example` 的設定項目名單比對（audit 13）。**怎麼驗**：diff 只有預期差異
- ⬜ 檢查結果要帶產生它的 commit（audit 11）。**怎麼驗**：`latest.json` 有 hash，過期顯示灰色
- ⬜ `oracle.mineru_options()` 接成自動斷言、`ruff` 掛 pre-commit（audit 第七組）。
  **怎麼驗**：`rebuild-checklist.md` A 節六條各有呼叫端
- ⬜ 部署收斂成一支會自我驗證的腳本（audit 4）。**怎麼驗**：行程啟動時間晚於 HEAD commit

## ⬜ 文件與現況對齊（同一個病：寫死了會變的數字）

- ⬜ 把數字換成量它的指令：CLAUDE.md 三處、README 兩處、`.env.example` 開頭、
  `hard-rules.md` 的 MAX_ASYNC 段、CLAUDE.md 的「dker GPU 壞掉」（已過期）。
  一次做完（audit 12–19、24）。**怎麼驗**：這幾份裡沒有會過期的快照數字

## ⬜ 秘密與外部依賴

- ⬜ 更換外洩過的 `LIGHTRAG_API_KEY` 與 `POSTGRES_PASSWORD`（audit 20、23）
- ⬜ 審核台加「外部依賴」分頁：到期日與餘額（audit 20）。**怎麼驗**：MinerU 到期日看得到
- ⬜ `rotate-secret.sh`，換秘密不必開編輯器（audit 20）
- ⚠️ **MinerU API token 2026-09-04 到期**——到期後解析直接不能跑

## ⬜ 既有的坑

- ⬜ intake 失敗語義分兩種：`failed_admit` 應可退回 `planned` 重試（audit 22）
- ⬜ 服務健康判準改成「打得到端點」——容器在跑不等於服務可用；失敗的容器要
  `--force-recreate` 才救得回來，單純 `up -d` 埠不會綁回來
- ⬜ canary 基準還是舊 20 篇的。語料定下來後 `postprocess.py canary --update`
- ⬜ KI-001 表格結構黏連：掉字 10.6% 裡最大的一族（117 詞）
- ⬜ 2017 那篇還停在「要你決定」——頁面尺寸容差改成 2 點就會自動通過（audit 10）

## ⬜ 上游畢業（standards，影響所有專案）

- ⬜ `test_next_done_ratio.py` 進 `PROJECT_TEMPLATE/`——BASELINE 要求規則有執行者，卻沒出貨執行者
- ⬜ 「不可再生／唯一副本」這類**描述性標籤**也要有執行者
- ⬜ **黑名單不是驗證器**：上游 `self-check.py` 的 `dead_refs` 只認三個寫死的樣式
- ⬜ 五條新通則要不要上升（audit 通則節）：秘密只活在部署目錄且不經過輸出／部署機落後
  版控要有人守／文件不得寫死可量測的數字／檢查結果必須帶版本／**寫好的檢查沒被呼叫等於沒寫**

## ⏸ 暫緩

- ⏸ **`:9621` 要不要對外關掉。** 2026-08-07 決定暫時保留——WebUI 有圖譜瀏覽器
- ⏸ **手動跑一次 `backup-cold.sh`，通過之後把排程開回來**，並同時從 `PAUSED` 移除。
  在它驗過之前不要關 backrest 的熱備份（audit 21）
- ⏸ **backrest 備份 `/data/rag` 的排程可以直接關**——那個目錄已廢除，每 4 小時產空快照
- ⏸ **Qwen3-Reranker**：Infinity 官方映像（0.0.76／0.0.77）內建 transformers 4.49，
  不認得 `qwen3` 架構。要換得自建映像（違反「不 fork 映像」）或改用 vLLM。
  等上游更新，或等 bge-reranker 出現具體不足再評估（audit 26）
- ⬜ 擴到 20 篇（語料要重挑還是照舊，未定）
