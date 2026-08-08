---
title: NEXT — 接下來做什麼
date_created: 2026-06-20
date_modified: 2026-08-08
status: living
kind: sop
supersedes: ""
superseded_by: ""
summary: "待辦清單。一條一行、動詞開頭，箭頭後面是完成的判準。理由外引。"
---

# NEXT — 接下來做什麼

做完的**刪整行**，摘要進 [cairn/LOG.md](../cairn/LOG.md)。
`→` 後面是「怎麼知道做完了」，寫不出來的不算待辦。
理由看 [audit-20260808.md](audit-20260808.md)（`audit N` 指過去），裁決看 [decisions/](decisions/)。

## 先做這三件

1. ⬜ daily-check 加 Infinity 健康檢查　→ `:7997/health` 非 200 轉紅
2. ⬜ 量查詢翻譯的效果（ADR-0005）　→ 中文題分數接近英文檔次
3. ⬜ daily-check 加「dker 落後 origin」（audit 5）　→ `rev-list HEAD..origin/master` = 0

## 抽取規則（改程式＋重進料兩小時，兩件一起做）

- ⬜ 抽取時剔除參考文獻（audit 8）　→ 共用實體的人名機構從 47 個降下來
- ⬜ `Figure N`／`Equation N`／`Table N` 不當實體（audit 6）　→ 泛用標籤節點歸零
- ⬜ 做完跑那 10 題

## 守門機制

- ⬜ 比對 `.env` 與 `.env.example` 的設定項目名單（audit 13）　→ diff 只有預期差異
- ⬜ `latest.json` 加產生它的 commit（audit 11）　→ 過期的紅燈顯示成灰色
- ⬜ `oracle.mineru_options()` 接成自動斷言（audit 第七組）　→ A 節六條各有呼叫端
- ⬜ `ruff` 掛上 pre-commit　→ 藍桶 3–8 有五條被守住
- ⬜ 部署腳本加自我驗證（audit 4）　→ 行程啟動時間晚於 HEAD commit
- ⬜ 加檢查：skill 有沒有照 ADR-0005 做　→ 跨 repo 的規則目前無執行者

## 文件對齊

- ⬜ 把寫死的數字換成量它的指令：CLAUDE.md 三處、README 兩處、`.env.example` 開頭、
  `hard-rules.md` 的 MAX_ASYNC 段、CLAUDE.md 的「dker GPU 壞掉」（audit 12–19、24）

## 秘密與外部依賴

- ⚠️ **MinerU token 2026-09-04 到期**
- ⬜ 更換 `LIGHTRAG_API_KEY` 與 `POSTGRES_PASSWORD`（audit 20、23）
- ⬜ 審核台加「外部依賴」分頁（audit 20）　→ MinerU 到期日看得到
- ⬜ 寫 `rotate-secret.sh`（audit 20）　→ 換秘密不必開編輯器

## 既有的坑

- ⬜ 處置 2017 那篇（audit 10）　→ 頁面尺寸容差改成 2 點就會自動通過
- ⬜ intake 失敗語義拆成兩種（audit 22）　→ `failed_admit` 可退回 `planned`
- ⬜ 服務健康判準改成「打得到端點」　→ 現有檢查抓不到「容器在跑但埠沒綁」
- ⬜ 更新 canary 基準　→ 語料定下來後 `postprocess.py canary --update`
- ⬜ KI-001 表格結構黏連　→ 掉字 10.6% 裡最大的一族（117 詞）
- ⬜ 擴到 20 篇　→ 語料先挑

## 上游畢業（standards）

- ⬜ `test_next_done_ratio.py` 進 `PROJECT_TEMPLATE/`
- ⬜ 「不可再生／唯一副本」這類描述性標籤要有執行者
- ⬜ 修上游 `self-check.py` 的 `dead_refs`（黑名單不是驗證器）
- ⬜ 五條新通則上升：秘密不經過輸出／部署機落後要有人守／文件不寫死可量測的數字／
  檢查結果要帶版本／寫好的檢查沒被呼叫等於沒寫

## ⏸ 暫緩

- ⏸ 手動跑 `backup-cold.sh`，通過再開排程並從 `PAUSED` 移除（audit 21）
- ⏸ 關掉 backrest 備份 `/data/rag` 的排程（那目錄已廢除）
- ⏸ `:9621` 要不要對外關掉（2026-08-07 決定暫留）
- ⏸ Qwen3-Reranker（官方映像的 transformers 不認得 `qwen3`，等上游）（audit 26）
