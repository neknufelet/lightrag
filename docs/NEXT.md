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

收尾批次順序是 PO 定的：守門先上線 → 文件對齊 → 動抽取 → 秘密 → 剩下的坑 →
上游 → **備份排最後**。第 1、2 批已完成（見 LOG）。

---

## 🔴 從這裡開始：重抽跑完了嗎

**2026-08-08 21:10 啟動全面重抽**（5 份；2017 那篇要另外處理，見下）。
新的抽取規則第一次生效，約 2.5 小時。

**第一件事：確認它結束了、而且沒失敗。**

```bash
ssh florian-dker 'tail -30 /data/lightrag/records/reindex-20260808.log'
ssh florian-dker 'docker exec lightrag-postgres psql -U deeptutor -d lightrag -tAF"|" \
  -c "select status, count(*) from lightrag_doc_status where workspace='"'"'acoustics_v2'"'"' group by 1;"'
# 綠燈：5 份都是 processed，沒有 failed
```

### 然後比對基準 —— 這是這次重抽的驗收

```bash
ssh florian-dker 'cd ~/ghq/github.com/neknufelet/lightrag && \
  python3 scripts/graph-shape.py --compare /data/lightrag/records/graph-shape-before-reextract.json'
```

重抽**之前**的數字（已存檔，重抽後補不回來）：

| 指標 | 之前 | 目標 | 對應規則 |
|---|---|---|---|
| 節點總數 | 3,137 | **不能崩掉** | 規則太嚴讓圖譜變空也是失敗 |
| 泛用標籤節點 | 96 | **0** | 2a（`Figure 3`／`Equation 5`／`Table 2`） |
| person／organization | 793 | 大幅下降 | 1（參考文獻的作者與機構） |
| 只差大小寫的組 | 89 | **0** | 3（`Region II` vs `Region Ii`） |

⚠ **「節點總數不能崩掉」跟其他三條一樣重要。** 三條規則都是在**減少**東西，
過頭了就是把真內容一起砍掉——那不會報錯，只會讓答案變差。

### 比對完之後，依序做這四件

- ⬜ 蓋上規則雜湊　→ `extraction-profile.py check` 回 0

  ```bash
  ssh florian-dker 'cd ~/ghq/github.com/neknufelet/lightrag && python3 scripts/extraction-profile.py stamp'
  ```
  **這一步不能拖。** 沒有它，之後新進的文件用新規則、舊的用舊規則，圖譜混著
  兩代而沒有紅燈。現行規則雜湊是 `sha256:c2f2d394efb14a2d51b4cae7e07a73bc`。

- ⬜ 把 2017 那篇放進去　→ 文件數變 6，`graph-shape` 節點數再增加

  它現在卡在審核台的 `failed`（放行時 `inputs/` 還有殘留而中止；殘留已清掉）。
  狀態機不能從 `failed` 直接回 `planned`，只能 reset → 重新解析 → 放行，
  **要再付一次 MinerU 解析**。這正是第 5 批「intake 失敗語義」那條要修的東西。

  ```bash
  # 走 /api/reset → /api/parse → /api/admit，或直接在審核台 :9710 操作
  ```

- ⬜ 更新 canary 基準　→ `postprocess.py canary` 回 0

  ```bash
  ssh florian-dker 'cd ~/ghq/github.com/neknufelet/lightrag && python3 scripts/postprocess.py canary --update'
  ```
  現在基準還停在退役的舊語料（教科書 A–R 那組），每天報「17 份消失、3 份新增」。
  **必須在重抽之後才做**，否則要更新兩次。

- ⬜ 重量檢索預算　→ 原文段裡的參考文獻佔比從 10% 降下來

  ```bash
  ssh florian-dker 'cd ~/ghq/github.com/neknufelet/lightrag && python3 scripts/context-budget.py'
  ```
  重抽前：四題各 20 段原文，其中 6/80 段（token 的 10%）是參考清單。
  消音之後應該接近 0——**那是「參考文獻消音」這條規則唯一的驗收方式**。

## 第 3 批剩下的（重抽驗收通過之後）

- ⬜ 跑實體碎片化流程（audit 7／工單 16）
  → `entity-merge.py plan` 產候選 → `review --top 8` 產**附原文**的審查表 →
  LLM 看一輪 → PO 定案

  **必須在重抽之後跑**，重抽會改變候選清單。重抽前的數字：225 組重複、其中
  177 組從來沒被檢索到、真正值得看的 48 組、浪費 4.3% 的實體格位。
  規則 3（不套標題大小寫）應該會先消掉其中一大類，剩下的才是要人判斷的。
  ⚠ 合併**不可逆**。判準寫在 `entity-merge.py` docstring：不是「長得像就合併」，
  是「這組真的出現在檢索結果裡、而且浪費了多少格位」。

- ⬜ 跑那 10 題　→ 中文題分數接近英文檔次
  （這也是「調預算有沒有讓答案變好」的唯一驗收，見下一節）

## 檢索預算：已改，但品質還沒量

2026-08-08 把三個耦合的值一起改了（圖譜上限 6000+8000→3000+4000、
`--parallel` 4→2、`MAX_TOTAL_TOKENS` 25k→50k）。原文段數 5–9 → **20（餵滿
`CHUNK_TOP_K`）**。但**量到的是「拿到多少原文」，不是「答案有沒有變好」。**

- ⬜ 用那組題目跑實際回答，比對改前改後　→ 有一份可比的評分，而不只是 token 數
- ⬜ 救回或重寫 `llm-bench.py`　→ 能在現行 `--parallel 2` 下重量吞吐

  `.env.example` 的併發表是 **2026-08-03、`--parallel 4` 時代**的歷史值，而量它的
  工具已於 `7a0414b` 刪除。**現在沒有辦法重跑那組數字**，等於那個交換只有一半有證據。

## 從第 2、3 批檢討出來的規範（見 [review-20260808](review-before-reextract-20260808.md)）

三條已經有執行者了（`scripts/guard-command.py` ＋ `.claude/settings.json`）：
秘密整包輸出、管線後面的 `$?`、直接讀或 source `.env`。**還沒有執行者的：**

- ⬜ 「有權威來源時不得自己重算」　→ 升上游 BASELINE
  （2026-08-08 四次：容器要不要重建、設定雜湊、chunk token 數、實體型別查錯表。
  自己算的全錯，而且**錯的方向都是「看起來沒問題」**）
- ⬜ 「不要寫死 localhost」要有執行者　→ grep 得到就紅
  （`.env.example` 早就寫了這條，而當天新寫的腳本照樣違反）
- ⬜ 「文件不得寫死可量測的數字」要有執行者　→ 不能只靠人記得
  （第 2 批正在根治這個病，而我同一天又犯了一次）
- ⬜ 「啟發式的結果不得直接當數字報」　→ 至少要有一個權威訊號覆驗
  （當天三次：年份密度估 40%（實際 10%）、殘留偵測誤判正文、chunk token 估 600
  （實際 1,818））

## 型別註解的欠帳（棘輪，清完一個刪一行）

ANN 已對整包開啟，**新寫的碼一定要有型別註解**。既有欠帳共 102 處，清單在
`ruff.toml` 的 `per-file-ignores`：

- ⬜ `postprocess.py` 18／`kbapi.py` 17／`entity-merge.py` 14／`test_oracle_secrets.py` 12
- ⬜ `pp/crosscheck.py` 8／`test_gates.py` 7／`test_intake.py` 5／`parse-check.py` 5
- ⬜ `test_deploy_stack.py` 4／`test_canary.py` 4／`pp/rules/latex_fix.py` 4
- ⬜ `pp/oracle.py` 2／`pp/eyes.py` 1／`mineru_common.py` 1
  → 這三個要先決定 `json.loads` 的回傳型別怎麼寫（`Json` 別名還是 `object`），
  **那是設計選擇不是打字**，不要在補註解時順手做掉

## 第 4 批：秘密與外部依賴（3 條）

- ⬜ 寫 `rotate-secret.sh`（audit 20）　→ 換秘密不必開編輯器
- ⬜ 更換 `LIGHTRAG_API_KEY` 與 `POSTGRES_PASSWORD`（audit 20、23）
  → 舊值失效、服務起得來（`POSTGRES_PASSWORD` 目前只有 8 字）
- ⬜ 審核台加「外部依賴」分頁（audit 20）　→ MinerU 到期日、各家餘額看得到

**MinerU token 2026-09-04 到期，但已經有執行者**：`compat-check.py` 的 A-21
（soft），剩 14 天內讓 daily-check 轉警報。分頁是讓它「看得到」，不是唯一防線。

## 第 5 批：剩下的坑（3 條）

- ⬜ 量查詢翻譯的效果（ADR-0005）　→ 中文題分數接近英文檔次
- ⬜ intake 失敗語義拆成兩種（audit 22）　→ `failed_admit` 可退回 `planned`

  **2026-08-08 為此付了兩次 MinerU 解析**：2017 那篇在「放行」這一步失敗（環境
  問題，已修好），但狀態機把它和「解析失敗」歸為同一種 `failed`，唯一的回復路徑
  是 reset，而 reset 會刪掉解析產物。失敗在哪一步應該決定要退回哪裡。
- ⬜ KI-001 表格結構黏連　→ 掉字 10.6% 裡最大的一族（117 詞）

## 第 6 批：上游畢業（standards，4 條）

- ⬜ `test_next_done_ratio.py` 進 `PROJECT_TEMPLATE/`（該目錄目前沒有任何 `.py`）
- ⬜ 「不可再生／唯一副本」這類描述性標籤要有執行者

  2026-08-08 差點出事：`C Equivalent Networks.pdf` 在 `work/parsed` 沒有副本，
  審核台的訊息說「搬到 library 不要直接刪 —— 那可能是唯一副本」，而那句話是對的。
- ⬜ 修上游 `self-check.py` 的 `dead_refs`（黑名單不是驗證器，見該檔 152 行）
- ⬜ 七條新通則上升（BASELINE 目前 2.0.0）：秘密不經過輸出／部署機落後要有人守／
  文件不寫死可量測的數字／檢查結果要帶版本／寫好的檢查沒被呼叫等於沒寫／
  改了 A 讓 B 安靜失效的相依要有人守／**有權威來源時不得自己重算**

## 第 7 批：備份（2 條，PO：資料庫都建好再開始）

- ⬜ 手動跑 `backup-cold.sh`，通過再開排程並從 `PAUSED` 移除（audit 21）
- ⬜ 關掉 backrest 備份 `/data/rag` 的排程（那目錄已廢除，見 ADR-0003）

## ⏸ 暫緩

- ⏸ `:9621` 要不要對外關掉（2026-08-07 決定暫留）

---

## 這次收尾新增的工具（下一個對話會用到）

| 工具 | 回答什麼問題 |
|---|---|
| `scripts/graph-shape.py` | 抽取規則有沒有奏效（節點／標籤／人名／大小寫變體） |
| `scripts/extraction-profile.py` | 圖譜是用哪一版規則建的、跟現行一不一致 |
| `scripts/context-budget.py` | 查詢的 token 預算實際花到哪 |
| `scripts/deploy-stack.py freshness` | 跑著的是不是最新的碼（含 systemd 服務） |
| `scripts/guard-command.py` | 執行前擋下已知會出事的指令形狀 |

**共同的原則：不要自己算，去問做決定的那一方。** 這五支都是那個原則的實作
（問 compose、問 tokenizer、問 LightRAG 的解析器、問 systemd），因為
2026-08-08 每一次自己重算都算錯了。

## 已知但刻意不做

- **不改 workspace 名稱**（`acoustics_v2` → `acoustic`）。功能上只是字串，但要動
  `backup-cold.sh` 的容器名、`systemd-units.py` 的預設值、三個 skill 的 8 處 URL、
  三個測試檔。波及面大、價值低。
- **不擴到 20 篇**。2026-08-08 PO 槓掉，語料就是庫裡現有的那些（**份數不寫死**，
  用 psql 量）。
- **不上 Qwen3-Reranker**。已由 `BAAI/bge-reranker-v2-m3` 取代並上線（`8ebdc6b`）。
- **不做符號變體正規化**（`Z_Mi`／`ZMi`／`Z Mi`）。要模型替數學符號自創正規寫法，
  是錯誤代價最高又最難發現的地方——寫錯成「看起來合理但不是論文用的」符號，
  沒有人看得出來。那類留給重抽後的審查表用原文逐組判斷。
- **不做單複數正規形**。實際候選清單裡根本沒有這種案例（audit 當時的例子已不存在）。
- **`.env` 不要用 `source` 讀**。`LIGHTRAG_PARSER` 的值含 `;`，shell 會把分號後面
  當指令。取值用 `grep -E '^KEY=' … | cut -d= -f2-`。（已有執行者：`guard-command.py`）
- **llama 的金鑰不換、也不從命令列移走。** 2026-08-08 PO 裁決：「不擔心，本地端而且
  只有我用」。事實記著以免重新爭一輪：`--api-key <值>` 在容器的 `Cmd` 上，
  `docker inspect` 與 `ps aux` 都看得到。形狀與 `oracle.py` 當初修掉的
  `-e KEY=VALUE` 相同，但**風險面不同**：那台在 Tailscale 內、單人使用。
  ⇒ 判準不是「有沒有洩漏路徑」，是**誰在那條路徑上**。
