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

## 🚨 先修這個，否則下一次重建會讓 LightRAG 連不上資料庫

- ⬜ 把 dker `.env` 的 `POSTGRES_USER` 改回 `deeptutor`
  → `docker exec lightrag-postgres psql -U "$(grep -E '^POSTGRES_USER=' /opt/stacks/lightrag/.env | cut -d= -f2-)" -d lightrag -tAc 'select 1'` 回 `1`

  **現況（2026-08-08 實測）**：`.env` 寫 `POSTGRES_USER=neknufelet`，但資料庫裡
  **只有 `deeptutor` 一個 role**（`select rolname from pg_roles where rolcanlogin`
  只回 deeptutor）。Postgres 只在**第一次建空庫**時依 `POSTGRES_USER` 建 role，
  之後改 `.env` 不會補建。

  **為什麼現在還活著**：跑著的 `lightrag-acoustics_v2` 是 16:15 啟動的，身上帶的
  是舊值 `deeptutor`；`.env` 是 17:58 才改的。**系統能運作純粹因為容器還沒被重建。**

  ⚠ **在改回來之前，不要跑 `docker compose up -d`。** 那會讓 LightRAG 拿
  `neknufelet` 去連一個沒有這個帳號的資料庫。

  為什麼是改 `.env` 而不是在資料庫建帳號：資料與權限都屬於 `deeptutor`，而 `.env`
  那一行只是字串。**動難改的那一邊去遷就好改的那一邊，方向是錯的。**

  這條也是 `compat-check` 的 A-22 與 A-26 現在紅燈的原因（它們照 `.env` 的帳號連）。

## ⛔ 新守門抓到的其餘紅燈，要 PO 決定何時處置

都要**在進料閒置時**做（放行中重啟會讓那篇落到 `failed`，而放行階段的 `failed`
是終點、要整份重解）。**而且要在上面那條修好之後**。

- ⬜ 重建 `lightrag-acoustics_v2` 與 `lightrag-postgres`
  → `deploy-stack.py freshness` 回 0

  兩者的設定與現在的 compose 不符（`docker compose up -d --dry-run` 獨立確認會
  Recreate 這兩台）。
- ⬜ 重啟 `kbapi-acoustics_v2`　→ 同上

  它掛著 `${REPO_DIR}/scripts`，而那些檔今天改過。Python 在行程啟動時就把模組
  載完，所以它跑的是 18 小時前的碼。
- ⬜ 更新 canary 基準　→ `postprocess.py canary --update`

  基準還停在退役的舊語料（教科書 A–R 那組），所以每天報「17 份消失、3 份新增」。
  **與第 3 批的重進料綁在一起做**，否則要更新兩次。
  現在庫裡有幾份不寫死，用指令數：
  `docker exec lightrag-postgres psql -U deeptutor -d lightrag -tAc "select count(*) from lightrag_doc_status where workspace='acoustics_v2';"`

## 型別註解的欠帳（棘輪，清完一個刪一行）

ANN 已對整包開啟，**新寫的碼一定要有型別註解**。下面是既有的欠帳，清單在
`ruff.toml` 的 `per-file-ignores`，共 102 處：

- ⬜ `postprocess.py` 18／`kbapi.py` 17／`entity-merge.py` 14／`test_oracle_secrets.py` 12
- ⬜ `pp/crosscheck.py` 8／`test_gates.py` 7／`test_intake.py` 5／`parse-check.py` 5
- ⬜ `test_deploy_stack.py` 4／`test_canary.py` 4／`pp/rules/latex_fix.py` 4
- ⬜ `pp/oracle.py` 2／`pp/eyes.py` 1／`mineru_common.py` 1
  → 這三個要先決定 `json.loads` 的回傳型別怎麼寫（`Json` 別名還是 `object`），
  **那是設計選擇不是打字**，不要在補註解時順手做掉

## 檢索預算：已改，但品質還沒量

2026-08-08 把三個耦合的值一起改了（圖譜上限砍半、`--parallel` 4→2、
`MAX_TOTAL_TOKENS` 25k→50k）。**量到的是「拿到多少原文」，不是「答案有沒有變好」。**

- ⬜ 用那組題目跑實際回答，比對改前改後　→ 有一份可比的評分，而不只是 token 數
- ⬜ 救回或重寫 `llm-bench.py`　→ 能在現行 `--parallel 2` 下重量吞吐

  `.env.example` 的併發表是 **2026-08-03、`--parallel 4` 時代**的歷史值，而量它的
  工具已於 `7a0414b` 刪除（理由是「前提已經消失」）。**現在沒有辦法重跑那組數字。**
  改了併發卻沒有工具驗證吞吐，等於那個交換只有一半有證據。

## 第 3 批：抽取治本 ＋ 重進料（6 條，改程式＋重抽約兩小時，一起做）

- ⬜ 抽取時剔除參考文獻（audit 8）　→ 共用實體的人名機構從 47 個降下來
- ⬜ `Figure N`／`Equation N`／`Table N` 不當實體（audit 6）　→ 泛用標籤節點歸零
- ⬜ 處置 2017 那篇（audit 10）　→ 頁面尺寸容差改成 2 點就會自動通過
  （現在 `pp/docctx.py:62` 尺寸不一致直接 raise，沒有容差）
- ⬜ 跑實體碎片化流程（audit 7／工單 16，**原本漏在清單外**）
  → `entity-merge.py plan` 產候選 → `review --top 8` 產附原文的審查表 → LLM 看一輪 →
  PO 定案。判準已寫在 `entity-merge.py` docstring，`hard-rules.md` 加一行指過去
- ⬜ 做完跑那 10 題　→ 中文題分數接近英文檔次

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
- **不擴到 20 篇**。2026-08-08 PO 槓掉，語料就是庫裡現有的那些（**份數不寫死**，
  用上面那條 psql 指令量；2026-08-08 當下是 4 篇論文 ＋ `C Equivalent Networks.pdf`）。
- **不上 Qwen3-Reranker**。已由 `BAAI/bge-reranker-v2-m3` 取代並上線（`8ebdc6b`），
  不是「等上游」而是不需要了。
- **`.env` 不要用 `source` 讀**。`LIGHTRAG_PARSER` 的值含 `;`，shell 會把分號後面
  當指令（實測 dker：`*:legacy-R: command not found`）。取值用
  `grep -E '^KEY=' … | cut -d= -f2-`，只要鍵名用 `cut -d= -f1`。
- **llama 的金鑰不換、也不從命令列移走。** 2026-08-08 PO 裁決：「不擔心，本地端而且
  只有我用」。事實記在這裡以免下次重新爭一輪：`llama-qwen36-moe` 把 `--api-key <值>`
  放在容器的 `Cmd` 上，所以 `docker inspect` 與 `ps aux` 都看得到；當天我用
  `docker inspect --format '{{join .Config.Cmd " "}}'` 就把它印進了對話紀錄。
  形狀與 `oracle.py` 當初被修掉的 `-e KEY=VALUE` 相同（值走 argv 而非檔案），
  但**風險面不同**：那台在 Tailscale 內、單人使用，暴露面只有 PO 自己的裝置。
  ⇒ 判準不是「有沒有洩漏路徑」，是**誰在那條路徑上**。
