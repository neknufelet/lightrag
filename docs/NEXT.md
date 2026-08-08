---
title: NEXT — 接下來做什麼
date_created: 2026-06-20
date_modified: 2026-08-08
status: living
kind: sop
supersedes: ""
superseded_by: ""
summary: "待辦清單，依收尾批次排序。一條一行、動詞開頭，箭頭後面是完成的判準。理由外引。"
---

# NEXT — 接下來做什麼

做完的**刪整行**，摘要進 [cairn/LOG.md](../cairn/LOG.md)。
`→` 後面是「怎麼知道做完了」，寫不出來的不算待辦。
理由看 [audit-20260808.md](audit-20260808.md)（`audit N` 指過去），裁決看 [decisions/](decisions/)。

**2026-08-08 起依收尾批次排序**，順序是 PO 定的：守門先上線（後面每一批才有東西驗）→
文件對齊 → 動抽取 → 秘密 → 剩下的坑 → 上游 → **備份排最後**（PO：「東西都弄完、
資料庫都建好再來開始備份」）。

---

## ⛔ 新守門抓到三個紅燈，要 PO 決定何時處置

第 1 批的檢查一上線就抓到東西。都不緊急，但都要**在進料閒置時**做
（放行中重啟會讓那篇落到 `failed`，而放行階段的 `failed` 是終點、要整份重解）。

- ⬜ 重建 `lightrag-acoustics_v2` 與 `lightrag-postgres`
  → `deploy-stack.py freshness` 回 0

  兩者的設定與現在的 compose 不符（`docker compose up -d --dry-run` 獨立確認會
  Recreate 這兩台）。指令：在 `/opt/stacks/lightrag` 跑 `docker compose up -d`。
- ⬜ 重啟 `kbapi-acoustics_v2`　→ 同上

  它掛著 `${REPO_DIR}/scripts`，而那些檔今天改過。Python 在行程啟動時就把模組
  載完，所以它跑的是 18 小時前的碼。

## 第 2 批：文件對齊（2 條）

- ⬜ 把寫死的數字換成量它的指令：CLAUDE.md 三處、README 兩處、
  `hard-rules.md` 的 MAX_ASYNC 段、CLAUDE.md 的「dker GPU 壞掉」（audit 12–19、24）
  → grep 不到寫死的鍵數／容器數／篇數
- ⬜ 加檢查：skill 有沒有照 ADR-0005 做　→ 跨 repo 的規則目前無執行者
- ⬜ 清掉 139 處缺型別註解，然後把 `ANN` 加進 `ruff.toml`　→ `ruff check --select ANN` 為 0
  （藍桶 3。純量的問題，可以分批清）
- ⬜ 分出「哪些檔是 CLI 入口」，再對其餘檔啟用 `T20`　→ 非入口檔的 `print` 為 0
  （藍桶 4。336 處裡絕大多數是 CLI 的正常輸出不是拿 print 當 log，
  所以不能整包開——要先有「入口」的定義）

**CLAUDE.md 已知寫錯的兩處**（2026-08-08 實測）：說「本專案容器全部移除」，實際
`lightrag-acoustics_v2`、`lightrag-infinity`、`kbapi-acoustics_v2`、`lightrag-postgres`
四個在跑；說 `.env` 54 個鍵 6 個秘密，實際 60 個鍵 7 個秘密。

## 第 3 批：抽取治本 ＋ 重進料（6 條，改程式＋重抽約兩小時，一起做）

- ⬜ 抽取時剔除參考文獻（audit 8）　→ 共用實體的人名機構從 47 個降下來
- ⬜ `Figure N`／`Equation N`／`Table N` 不當實體（audit 6）　→ 泛用標籤節點歸零
- ⬜ 處置 2017 那篇（audit 10）　→ 頁面尺寸容差改成 2 點就會自動通過
  （現在 `pp/docctx.py:62` 尺寸不一致直接 raise，沒有容差）
- ⬜ 跑實體碎片化流程（audit 7／工單 16，**原本漏在清單外**）
  → `entity-merge.py plan` 產候選 → `review --top 8` 產附原文的審查表 → LLM 看一輪 →
  PO 定案。判準已寫在 `entity-merge.py` docstring，`hard-rules.md` 加一行指過去
- ⬜ 做完跑那 10 題　→ 中文題分數接近英文檔次
- ⬜ 更新 canary 基準　→ `postprocess.py canary --update`（語料已定在現有 9 篇）

## 第 4 批：秘密與外部依賴（3 條）

- ⬜ 寫 `rotate-secret.sh`（audit 20）　→ 換秘密不必開編輯器
- ⬜ 更換 `LIGHTRAG_API_KEY` 與 `POSTGRES_PASSWORD`（audit 20、23）
  → 舊值失效、服務起得來（`POSTGRES_PASSWORD` 目前只有 8 字）
- ⬜ 審核台加「外部依賴」分頁（audit 20）　→ MinerU 到期日、各家餘額看得到

**MinerU token 2026-09-04 到期，但已經有執行者**：`compat-check.py:368` 的 A-21
（soft），剩 14 天內讓 daily-check 轉警報。分頁是讓它「看得到」，不是唯一防線。

## 第 5 批：剩下的坑（3 條）

- ⬜ 量查詢翻譯的效果（ADR-0005）　→ 中文題分數接近英文檔次
- ⬜ intake 失敗語義拆成兩種（audit 22）　→ `failed_admit` 可退回 `planned`
- ⬜ KI-001 表格結構黏連　→ 掉字 10.6% 裡最大的一族（117 詞）

## 第 6 批：上游畢業（standards，4 條）

- ⬜ `test_next_done_ratio.py` 進 `PROJECT_TEMPLATE/`（該目錄目前沒有任何 `.py`）
- ⬜ 「不可再生／唯一副本」這類描述性標籤要有執行者
- ⬜ 修上游 `self-check.py` 的 `dead_refs`（黑名單不是驗證器，見該檔 152 行）
- ⬜ 六條新通則上升（BASELINE 目前 2.0.0）：秘密不經過輸出／部署機落後要有人守／
  文件不寫死可量測的數字／檢查結果要帶版本／寫好的檢查沒被呼叫等於沒寫／
  **改了 A 讓 B 安靜失效的相依要有人守**（第二雙眼睛那條就是這樣斷的）

## 第 7 批：備份（2 條，PO：資料庫都建好再開始）

- ⬜ 手動跑 `backup-cold.sh`，通過再開排程並從 `PAUSED` 移除（audit 21）
- ⬜ 關掉 backrest 備份 `/data/rag` 的排程（那目錄已廢除，見 ADR-0003）

## ⏸ 暫緩

- ⏸ `:9621` 要不要對外關掉（2026-08-07 決定暫留）

---

## 已知但刻意不做

- **不改 workspace 名稱**（`acoustics_v2` → `acoustic`）。2026-08-08 裁決：功能上只是
  字串，但要動 `backup-cold.sh` 的容器名、`systemd-units.py` 的預設值、三個 skill 的
  8 處 URL、三個測試檔。波及面大、價值低。
- **不擴到 20 篇**。2026-08-08 PO 槓掉，語料定在現有 9 篇。
- **不上 Qwen3-Reranker**。已由 `BAAI/bge-reranker-v2-m3` 取代並上線（`8ebdc6b`），
  不是「等上游」而是不需要了。
- **`.env` 不要用 `source` 讀**。`LIGHTRAG_PARSER` 的值含 `;`，shell 會把分號後面
  當指令（實測 dker：`*:legacy-R: command not found`）。取值用
  `grep -E '^KEY=' … | cut -d= -f2-`，只要鍵名用 `cut -d= -f1`。
