# NEXT — 待辦與進行中

規則與契約在 [CLAUDE.md](CLAUDE.md)（SSOT），重建的階段、閘門與各階段的
驗收紀錄在 [docs/rebuild-plan.md](docs/rebuild-plan.md)。這裡只放「接下來
要做什麼」。**做完就刪**——教訓沉澱回 CLAUDE.md 或 rebuild-plan，不留屍體；
新增時寫清楚證據在哪。

---

## 開新對話直接貼這段

```
⚠️ 先確認工作目錄是 ~/ghq/github.com/neknufelet/lightrag
   （在別處開 session 會載到別的專案的 CLAUDE.md、找不到本檔。
     特別注意 ~/ghq/github.com/neknufelet/florian-dker/ ——
     那個資料夾只有一個 CLAUDE.md，而且是 **AOSR 專案**的，不是這裡的。
     2026-08-04 實際發生過兩次。）

專案 lightrag（聲學知識庫）。我在 florian-coder，透過 ssh 操作 florian-dker。

座標
  repo      ~/ghq/github.com/neknufelet/lightrag（coder，工作台）
            ~/ghq/github.com/neknufelet/lightrag（dker，部署，唯讀只 pull）
            ↑ 2026-08-07 coder 端從 lightrag-v1 改名，兩台自此同路徑，
              也符合 ghq 慣例（目錄名＝remote 的 repo 名）
  GitHub    neknufelet/lightrag
  服務      dker: lightrag-acoustics_v2 :9621、kbapi-acoustics_v2 :9700
            自己的 lightrag-postgres 與 lightrag-neo4j（2026-08-03 從 DeepTutor 搬出）
  資料      **/data/lightrag 是唯一的根**（2026-08-04 乾淨重建後）。
            底下：inbox / library / work/{parsed,crops} / records / inputs/<ws>
                  / rag_storage / checks / postgres / neo4j
            ✅ **/data/rag 已於 2026-08-07 廢除，PO 定案不再牽扯。** 兩處依賴都已改：
              scripts/backup-cold.sh STAGE → /data/lightrag-coldstage
                （**刻意不放在 /data/lightrag 底下**：該腳本做
                 `cp -a "$DB_ROOT/." "$STAGE/"`，暫存區在資料根裡面會複製進自己）
              .env.example INTAKE_SOURCES → 留空（來源庫掃描停用，改走網頁上傳）
            /data/rag/lightrag（REBUILD-11 的 217 MB 舊目錄）已由 PO 清除。
            /data/rag/knowledge_bases（DeepTutor 的）也已不存在。
            ⚠️ 不得再有任何東西寫進 /data/rag —— 舊的 backup-cold.sh 每天會把它
              mkdir 回來，刪一次建一次且看起來一切正常（2026-08-07 實測到 03:28
              又出現一個空目錄）。

先讀 CLAUDE.md 與 NEXT.md。**CLAUDE.md 的「現況」已於 2026-08-05 更新到位**
（18 份、1,589 chunk、14,226 實體），可以直接信任。

規矩重點：
  - 改在 coder、驗在 dker。**驗證輸出沒拿到就還沒 done。**
  - coder 上沒有 .env、沒有 docker，碰 DB 的腳本在那裡跑不起來——這是刻意的。
  - 重票觸發清單見 CLAUDE.md「執行方針與驗收路由」，有疑義＝重票。
  - ⚠ **在 dker 跑任何 `--update`（canary／scan-partial）會弄髒它的 checkout**，
    違反唯讀原則。正確做法：dker 跑 `--update` 產生內容 → 讀出來 →
    `git checkout --` 還原 dker → 在 coder 寫入並 commit → dker pull。

現況：**Möser A–R 十八章已全數進庫**（`SCALEUP-1` ✅ 完成 2026-08-05），
收件匣清空。

**下一步：繼續往 `acoustics_v2` 灌更多聲學文獻。只用一個庫，不開第二個
workspace**（PO 2026-08-05 定案；理由是 `QueryParam` 沒有文件範圍欄位，
而 PO 確認不需要「只查某一批」的能力 —— 詳見下方 08-05 交接節）。

  瀏覽器開 http://100.87.88.7:9710 —— 收件匣／審核台
  **它由 systemd 管著**（`lightrag-intake.service`），開機自啟、已實測驗過。
  沒回應時：`ssh florian-dker 'systemctl status lightrag-intake'`，
  要重起就 `sudo systemctl restart lightrag-intake`。**不要再用手動 nohup**
  —— 那會跟 systemd 搶 9710 埠。

  進料：把 PDF 丟進 `/data/lightrag/inbox/`（或直接拖到網頁上傳），
  流程是 只解析 → 看審核卡片 → clean 就放行、不 clean 就停在「等你看」。

  ⚠ 舊版這裡寫「每放行一份要先 `chown -R florian:florian work/parsed`」——
  **2026-08-05 跑完 18 份完全沒做過這動作，不需要**。原因未查（可能是重建後
  路徑或 uid 對上了）。真的撞到權限再說，別預防性地 chown。

2026-08-05 這一輪的成果（全部有實測輸出，別重做）：
  語料       Möser A–R 十八章全數進庫：1,589 chunk、14,226 實體、26,447 關係
  規則       ∂ 誤讀四種寫法已修（全母體 190 處）；canary 基準 18 份全納入
  體檢       canary ✅／compat-check 124 項 ✅／extract-check 可疑率 2.7%
             4 份標黃，其中 3 份已查證不是幻覺（結論在 tests/verified-findings.json，
             extract-check 超標時會自己印出來）
  部署       七個 systemd 單元進版控（deploy/systemd/），intake 改走 systemd，
             **已實測重開機自己回來**；daily-check 每天比對 /etc 與 repo
  知識       Project Cairn 已 init，七條跨專案知識畢業到 Obsidian 42_Cairn/lightrag/
  文件       NEXT.md 清掉 294 行已完成項，搬進 docs/log_20260803.md 的歸檔節

2026-08-04 凌晨的乾淨重建（全部有實測輸出，別重做）：
  索引重建   postgres/neo4j 資料目錄清空重建 → 11 張表（不是 14，
             那 3 張 *_3_small_1536d 是舊 embedding 模型的殭屍表，順帶清掉）
  路徑遷移   DATA_ROOT → /data/lightrag，19 處路徑組合集中到 scripts/pp/paths.py
  前端       scripts/intake.py（1783 行、純標準函式庫、:9710）
  兩份文件   TD_DG method_CH7（CLI 流程）、CH3（走審核台）
             2 docs / 5 chunks / 103 實體 / 102 關係，接地可疑率 0.0%
  閘門       G1 清空／G2 結構／G3 備份／G4 bug／G6 前端／G7 端到端 全綠
  基準重置   canary 與 scan-partial 都重置為 2 份（舊 20 份的基準已退場）
  排程       兩個 timer 已恢復，daily-check 實跑 status=pass

**這批是「做完並驗過」，與 08-03 那批「查完決定不做」性質不同。**
過程紀錄在 `$RECORDS/REBUILD-20260804.md`（在 /data，已在備份範圍）。
```

## ⚡ 2026-08-07：第一批四件落地（先讀這節）

**全部有 dker 實跑輸出。** commit `7593e51`／`1dccf79`／`dd1ba8d`＋`ledger` 那個。

| 做了什麼 | dker 驗證輸出 |
|---|---|
| `/data/rag` 斷根：冷備份暫存區 → `/data/lightrag-coldstage`、`INTAKE_SOURCES` 留空 | `STAGE 在 DB_ROOT 底下嗎 = False`（必須是 False，否則 `cp -a` 會複製進自己） |
| README 備份表換成實測現況（原本三列全錯，方向相反） | plan `lightrag-snapshot` paths=`/userdata/data/lightrag` 每 6 小時；冷備份最新 `6bfca80c` 08-07 03:01 |
| `apply` 在 `FORCE_REPARSE` 開著時拒絕執行 | 真容器旗標 `''` → `force_reparse_is_on()=False` → 放行（正確）；`A-07 hard ok` |
| `ledger.py summary` 母體脫節時自我停用 | `rc=3`「已停用：現役 18 份，其中 15 張體檢表的文件已不存在」 |
| 不可再生的人工裁定進版控 `verdicts/`（227 檔 1.3 MB） | 守衛 `tests/test_verdicts.py` 4 案例綠 |

**砍掉一件**：原清單的「容器掛載點 inode 探針」——PO 判定不合理（那是在補
`rm -rf` bind mount 來源目錄造成的下游問題，正解是「永遠不刪那個目錄，要清就清裡面」
一句規矩，不需要每天跑的程式；且要乾淨重建的話它更沒價值）。實測四個掛載點目前全部對齊。

### ⬜ 等 PO 決定才能動的三件

1. **backrest 關排程的順序。** PO 要關 `rag-snapshot`（在備一個已不存在的路徑）與
   `lightrag-snapshot`。⚠ 後者**是現在唯一在保護 `work/parsed` 與 `records` 的東西**：
   冷備份的跳過判準是 Postgres 抽取指紋，「只解析、還沒放行」的新解析快取不會觸發它。
   建議順序：先把冷備份判準改成「DB 有變**或**解析快取有變」→ 驗它真的會因為解析成果
   而跑 → 再關那兩個排程。**只能關排程，不能停 backrest 容器**（冷備份借用容器裡的
   restic 與金鑰上傳）。另三個 plan 是 Obsidian／Zotero／Calibre，不得一起關。
2. **`archive-ledger.py --move`**（歸檔那 15 張幽靈體檢表）。碰資料，等授權。
   版控副本已在 `verdicts/records/ledger/`，所以歸檔不會失去任何東西。
3. **「其他全部刪除」**（`work/parsed` 307 MB、裁圖與轉錄快取 41 MB 等，共約 350 MB）。
   不可逆。人工裁定已進 git，所以刪除本身安全，但**刪掉解析快取等於接受下次要重跑
   6–10 小時的 MinerU**。要不要刪取決於是否真的走乾淨重建。

## ⚡ 2026-08-05：整本書跑完，文件已對齊（先讀這節）

**A–R 十八章全部進知識庫，收件匣清空。** 這一輪之後 CLAUDE.md 的「現況」是準的。

```
文件      18 份、1,589 chunk、全部 processed、failed 0
索引      14,226 實體、26,447 關係
接地      可疑率 2.7%（舊語料是 4.5%）
體檢      canary 1 秒 ✅（18 份全數納入基準）
          compat-check 124 項 ✅（hard 0、soft 0、驗不了 0）
          extract-check ⚠ 4 份 >5%，但逐份查過**都不是幻覺**
排程      三個 systemd 單元進版控，daily-check 每天比對 /etc 與 repo
```

**這一輪長出來的機制（都已上線並實跑驗過）**

- **`∂` 誤讀修正**：MinerU 把偏微分讀成四種錯寫法，全母體 190 處。錨點認**結構**
  不認字元 —— 同族的 `\hat{c}` 有 3 處是真的 ĉ，認字元會毀資料。B/D/E 已重新索引。
- **`tests/verified-findings.json`**：「哪份文件的哪個指標查過、結論是什麼」。
  `extract-check` 超標時**自己印出來**，不要求任何人記得去哪裡找。
  數字偏離查證當時 >50% 時改說「要重查」，不再回報舊結論。
- **systemd 七個單元進版控**（`deploy/systemd/`），`scripts/systemd-units.py`
  render／install／verify 共用同一個渲染器。intake 改走 systemd，**已實測重開機自己回來**。
- **重啟恢復問索引的現實**：在途 job 不再一律標 failed，改成問 LightRAG 的狀態。
- **`reindex` 自己收尾**：把 PDF 搬回 work/parsed 並驗 inputs 淨空。
- **Project Cairn 已 init**，七條跨專案知識畢業到 Obsidian `42_Cairn/lightrag/`。
  既有的 CLAUDE.md／NEXT.md／docs/ **一個字都沒搬**（理由見 AGENTS.md）。

**下一步 PO 已指定：繼續往 `acoustics_v2` 灌更多聲學文獻。**

**只用一個庫，不開第二個 workspace（PO 2026-08-05 定案）。** 判準是實測出來的：
`QueryParam` **沒有任何文件範圍的欄位**（只有 mode／top_k／chunk_top_k／
max_*_tokens／hl_keywords／ll_keywords／conversation_history／user_prompt／
enable_rerank／include_references）——所以「只根據教科書回答」這種需求，
**唯一做法是分 workspace**。PO 確認不會有這種需求，所以一個庫。

一個庫的好處是 graph RAG 的本體：同一個實體出現在教科書與多篇論文時會合併成
一個節點、帶多個出處，**那比幾個孤立節點強**。分庫等於主動放棄這件事。

⚠ **注意這與 `compose.yaml` 檔頭那段「有了自己的實例，查到別的庫在結構上
不可能」不衝突**。那段講的是**跨專案**（我們的庫與 DeepTutor 的庫混在一起，
咬過三次且每次都不報錯）。現在全部是自己的聲學內容，那個風險不存在。

拆分 LLM／VLM（`PP_EYE_A_*`）與換抽取模型（DeepSeek／Modal）
**暫緩，PO 2026-08-05 明確表示先不做**。

**唯一沒處置的發現**：L Capsules 的關係層「只有一端對得到」15.0%（全庫 3.0%），
成因是書本章節交叉引用被抽成關係（`Chapter 20 → Vol. III`）。不是錯，但對檢索
沒有價值。**要先量它有沒有真的被撈出來過再決定**——前例是實體碎片化那次，
254 組從未出現在任何檢索結果，最後判定不做（不可逆操作換 0 收益）。
已記在 `tests/verified-findings.json` 的 note 欄。

---

## ⚡ 2026-08-04 這一輪（壓縮上下文前寫的交接，先讀這節）

### 審核台已上線可用

**http://100.87.88.7:9710** —— 這是現在唯一該用的進料方式。

    丟檔案到 /data/lightrag/inbox/（或在網頁上拖拉上傳）
      → 網頁上按「只解析」（約 30 秒）
      → 看審核卡片：clean 就按放行，不過就跳過
      → 放行後自動修補 → 索引

畫面由上而下就是流程：收件匣 → 解析中 → 等你看 → 卡住的 → 處理中 →
已進知識庫 → 失敗。預設只展開「等你看」，其餘收起來、限高捲動。

**不要再用 `postprocess.py prepare`** —— 它會把 PDF 留在 `inputs/`，
審核台下次放行時會被正確擋下（實測撞過一次）。兩條路不要混用。

### 索引已清空，等 PO 自己選 PDF 重跑

PO 2026-08-04 決定清空重來。`DELETE /documents` 已執行，索引 0/0/0/0、
Neo4j 0 節點、審核台狀態全清。`inbox/` 備了 TD_DG method 的 CH3、CH7 兩份，
**PO 說要自己選 PDF**，不要的話畫面上可以刪。

保留未動：`records/`（人工裁決，不可再生）、`work/crops/`（裁圖與轉錄快取）。

### 已完成並提交

    732781b  REBUILD-1/3  檢查工具不再讀 DeepTutor 的舊資料庫；新增 A-26
                          用 API 與 SQL 兩個獨立來源交叉比對文件母體
    83b8464  REBUILD-2/5  docker exec 帶宿主 uid/gid（不再產生 root 檔案）
    1cd47cf  REBUILD-4/7  失敗的進料看得見、能重置；intake 進 compose
    e777bda  ——           審核台前端重做（拖拉上傳、摺疊、對帳、連知識庫）
    4c0fbea  REBUILD-6/8/9 run-tests.sh 單一入口、token 到期會變紅、體檢表歸檔

### ⬜ 還沒做完的

- [ ] **`REBUILD-10`：CLAUDE.md 還停在重建前**（路徑、現況、數字全過期）。
      workflow 第五站沒跑到。**這是最該先做的**——CLAUDE.md 是 SSOT，
      現在它說的話有一半是錯的。
- [ ] **終審沒跑**（codex sol，第六站）。這一輪六個 commit 沒有經過獨立審查。
- [ ] **`exit 2` 不是錯誤訊息**：intake 把 parse-only 的退出碼存進 job.json 的
      error 欄，真正的原因（例如「來源檔不存在」）只在 `run.log` 裡。
      失敗看得見了，但**看得見不等於說得清楚**——要把子行程輸出帶進 error。
- [ ] **intake 沒進 systemd**：`compose.yaml` 已經有它，但實際跑的是手動
      `setsid nohup`。**dker 重開機不會自己起來。**
- [ ] `archive-ledger.py` 寫好了但**還沒在 dker 上跑過**（舊 20 張體檢表還在，
      `ledger.py summary` 會報一堆已不存在文件的 fail）。
- [ ] 舊目錄 `/data/rag/lightrag`（217 MB）還沒刪。records 與 crops 已 sha256
      驗證複製完成，留著是保險。

### ✅ 已由 PO 實測驗證（不必再驗）

- 拖拉上傳：log 有 `收到上傳 A Conventions.pdf（71625 bytes）`、HTTP 201
- 收件匣刪除：PO 刪掉了 CH7 與 CH3 兩份
- 失敗看得見：解析失敗時它確實出現在「失敗」節

### 🔧 PO 實測連續咬出的六個缺陷（都已修並部署）

一份**索引成功的文件**被報成 failed，追下去是六個環環相扣的問題：

1. **`rm -rf` 打斷 bind mount** —— 我清空索引時刪掉 `work/parsed` 目錄本身，
   容器仍綁在舊 inode，宿主寫的檔案容器看不到且不報錯。
   **清內容用 `rm -rf <dir>/*`，目錄本身留著。**
2. **`returned` 不在任何 section** —— 按「跳過」之後檔案還在 inbox、job 也在，
   但畫面完全看不到。加「已跳過」節與「放回收件匣」。
3. **按「只解析」畫面毫無反應** —— 檔案跑進預設收起來的「解析中」節。
   現在有東西在跑的節自動展開，列上顯示「送去 MinerU 解析 · 45 秒」。
   ⚠ 刻意不做百分比進度條：MinerU 是黑箱，**假進度條會讓「卡住」看起來像「快好了」**。
4. **`A-25` 只擋 0 份文件，沒擋 chunk 不足** —— 整庫 1 個 chunk 時
   `top_k=2→1、=8→1`，`b > a` 結構性不可能成立。已三態化。
5. **soft 失敗被當成流程失敗** —— `compat-check` 的 exit 5 是 soft，
   而 soft 的定義就是「值得知道但不該擋」。文件因此被誤判 failed。
6. **計數問錯對象** —— 「已處理」問 job 狀態，但 job 會跟現實脫節；
   對帳又排除「本站有紀錄的」，於是那份文件兩邊都漏掉，計數說 0 而庫裡有 1 份。
   改成問**知識庫的現實**。

**共通形狀**：每一個都是「畫面說的」與「實際發生的」不一致，而且都不報錯。

### 📍 現在的即時狀態

索引有 **1 份**（`A Conventions.pdf`，32 實體 24 關係），`inbox/` 有 5 份待挑。

⚠ **有一個殘留的 failed job**（就是被誤判的那份）。文件本身已經成功索引，
所以**不要重跑**（會重複）。在網頁上按它的「放回收件匣」，再從收件匣刪掉即可。
清掉之後「不是這裡送的」應該歸零 —— 那個欄位不是 0 就表示有人繞過審核台。

### ⚠ 這一輪學到的（不要重犯）

1. **兩條線同時動同一個 repo，靠工單約束沒有用。** 我在工單裡明令
   「不得碰 scripts/intake.py」，但 codex 用了全域的 git 還原操作，
   把我未提交的前端改動整個清掉。**要併行就用 git worktree 隔離，
   否則就不要併行。**
2. **codex 驗證完要收尾。** 它為了證明 `run-tests.sh` 會抓到失敗，在
   `test_gates.py` 加了一個 `TEMP deliberate fail`，驗完忘了拿掉，
   測試就這樣紅著被交出來。驗收時要跑一次測試才會發現。
3. **不要用 `cmd | tail` 取 `$?`** —— 取到的是 tail 的退出碼。我差點把
   canary 的失敗誤判成通過。CLAUDE.md 只記了 zsh 的 `PIPESTATUS`，
   但任何接 pipe 的量測都有這個問題。
4. **絕對不要 `rm -rf` 一個 bind mount 的來源目錄。** 清空索引時我對
   `/data/lightrag/work/parsed` 下了 `rm -rf` 再 `mkdir`，於是容器裡的掛載
   還綁在被刪掉的舊 inode 上——**宿主寫進去的檔案容器完全看不到，而且不報錯**。
   症狀是 PO 傳的第一份文件解析失敗，訊息只有「來源檔不存在」。
   要清內容就 `rm -rf <dir>/*`，**目錄本身留著**；真的刪了就要
   `docker compose up -d --force-recreate <service>` 重新綁定。
   （驗法：宿主寫一個 probe 檔，`docker exec ... cat` 讀得到才算通。）
5. **`exit 2` 不是錯誤訊息。** intake 把 parse-only 的退出碼當成 error 存進
   job.json，真正的原因「來源檔不存在」只在 `run.log` 裡。失敗看得見了
   （REBUILD-4 做到了），但**看得見不等於說得清楚**——要把子行程的輸出
   帶進 error 欄位。
6. **前端的文案要用使用者的話。** PO 問「選片是甚麼意思」——那是我造的詞。
   同一件事在流程裡曾有「待審核／待放行／待確認」三個名字。

---

## 狀態總表

label 格式與字母語意見 [CLAUDE.md](CLAUDE.md)「工作項目命名規則」。
legend：`✅完成 / 🔵進行中 / ⬜未起 / ⏸暫停 / ⚠️卡住`

| 線 | 當前 item | 狀態 |
|---|---|---|
| `REBUILD` | `REBUILD-5`（驗收與切換） | ✅ |
| `CUTOVER` | `CUTOVER-4`（v155 退役） | ✅ |
| `BACKUP` | — | ✅ **全線完成 2026-08-03**：`-1` 檔案備份／`-2` 索引冷備份／`-3` 還原演練通過（數字逐項對上）／`-4` 排程已接（每日 03:00，無新抽取成果則跳過）。還原點 1 → **3** |
| `SCANNER` | `SCANNER-1`（∂ 誤讀探針接進 daily-check） | ✅ 完成 2026-08-03（commit `f637aea`，基準 `tests/scan-partial-baseline.json` 進版控） |
| `SYMBOL` | — | ⏸ **全線無在跑項目**：`-1`／`-2`（不掃）／`-3`／`-4`（不修）✅ 已定案；`-5`（改 prompt）第一版實測反效果**暫緩**；`-3.1`（量測工具）**停在未過審**，數字只當線索 |
| `VERIFY` | `VERIFY-1`（`compat-check` 加 `suite` 欄） | ⬜ 常態線。2026-08-05 全套體檢：canary ✅／compat-check 124 項 ✅／extract-check 2.7% 可疑率 |
| `PPWORK` | `PPWORK-12` 之後無新項 | ✅ 大部分完成，殘項見「其他待辦」 |
| `SPEEDUP` | `SPEEDUP-2`（`MAX_ASYNC` 2→4） | ✅ **已改並實測驗證**（PO 2026-08-03 拍板降檔為一般票）。`SPEEDUP-2.1`／`SPEEDUP-3` ✅；`SPEEDUP-1`（MTP）⏸ **PO 判不划算，不做**——理由見下 |
| `SCALEUP` | `SCALEUP-1`（Möser A–R 全書） | ✅ **完成 2026-08-05：18 份全數進庫**，走 :9710 審核台，一份都沒卡在「等你看」 |
| `REBUILD` | `REBUILD-1`…`REBUILD-11` | 🔵 殘項見下方專節。**`REBUILD-10`（文件對齊現況）✅ 完成 2026-08-05** |

---

## 現況（2026-08-03）

**acoustics_v2 已接手上線，acoustics_v155 已完全退役。** 重建的階段 0–5 全部
完成：0–3 經主線獨立驗收，切換與退役於 2026-08-03 執行完畢並實測驗證。

```
唯一的庫  acoustics_v2
checkout  ~/ghq/github.com/neknufelet/lightrag（單一，無 worktree、無 v1/v2 分身）
服務      lightrag :9621（容器 lightrag-acoustics_v2）
          kbapi    :9700（容器 kbapi-acoustics_v2）—— 三個 skill 全走這裡
儲存      lightrag-postgres（database `lightrag`）＋ lightrag-neo4j，2026-08-03 從
          DeepTutor 共用實例搬出，資料在 /data/lightrag（postgres 622 MB、neo4j 2.1 GB）。
          lightrag-neo4j 只有 neo4j／system 兩個 database ＝ 專用實例，不再跨專案共用
內容      20 份 processed / 0 failed、7,211 實體、10,500 關係、510 chunk、可疑率 4.5%
排程      lightrag-daily-check.timer   每天 08:30 跑 compat-check + canary
          lightrag-cold-backup.timer   每天 03:00 冷備份（沒有新抽取成果就跳過不停機）
          兩者紅燈都打自架 ntfy（/opt/stacks/ntfy :9800），腳本自己掛掉各有 OnFailure 備援
警報      **2026-08-03 端到端驗過送達**：兩條路徑各發一則測試，伺服器收下
          （22:39:48，優先度 4／5），**PO 確認手機收到**。兩條路徑刻意獨立——
          備援不走 notify.sh，因為備援不能依賴可能正是故障原因的主路徑。
          ⚠ 「送達手機」這一段**沒有任何自動檢查驗得到**，只能靠人實際發一次確認。
v155      已不存在。Neo4j label、Postgres 列、磁碟目錄、容器全部移除，數字見 CLAUDE.md
```

> **備份**：兩條都已接上（2026-08-03）。① `/data/rag/lightrag`（含 `__parsed__`
> 與 `records/`）走 backrest plan `lightrag-snapshot`，每 6 小時，**並驗過能還原**。
> ② 索引本體（`/data/lightrag` 的 Postgres＋Neo4j）走 `scripts/backup-cold.sh`
> 冷備份。在此之前 ① 一直沒有備份而文件宣稱有——詳見下方「接上備份」。
> **還原演練 `BACKUP-3` 已於 2026-08-03 通過**（拉回雲端快照、起臨時 DB、數字逐項對上）。
> **仍缺的是冷備份的排程**——實測發現索引本體目前只有**一個**還原點，同節有處置。

> **今天的裁決材料**：`SPEEDUP` 與 `SYMBOL-3` 兩條線的工單與終審判定全文
> （15 份，含 fable 的設計單、sol 的五份判定）存在
> `$RECORDS/review/20260803-speedup-symbol3/`——**在 `/data`、已在備份範圍內**。
> 本檔引用它們一律用 `$RECORDS/…`，不要寫成 `/tmp` 的 session 路徑（一清就死）。

> **路徑約定**：本檔寫 `$RECORDS/…` 一律指
> `/data/rag/lightrag/acoustics_v2/records/`——**在 `/data`，不在 git**
> （已在 backrest 範圍內）。寫成相對路徑會被誤讀成 repo 內的檔案。

**體檢表**（`$RECORDS/ledger/`，工具 `scripts/ledger.py summary`）：
160 格全滿，通過 151、fail 9、驗不了 0。
9 個 fail 全部已查明並記錄，**沒有一個是未知問題**：

| fail | 份數 | 已查明的性質 |
|---|---:|---|
| `parse.coverage` | 2 | **waiver 放行**：41598 7.0% 全為 chart 圖例軸標（政策性遺失）；C 10.5% 主要是黏字假訊號與圖說標籤，全修也只到 8.0%，是 MinerU 上限 |
| `pp.equations` | 1 | N Flow：#1410 單處已知缺陷（見下） |
| `extract.grounding` | 6 | **全部查過不是幻覺**，分兩族：符號→概念命名、概念→引用文獻（見下） |

**waiver 的 provenance**：三份 waiver（41598／C 的 `parse.coverage`、N Flow 的
`pp.equations`）由**主線於 2026-08-02 裁決「准進階段 3」**，原文追加在體檢表的
note 欄（`$RECORDS/ledger/`），不是口頭放行。要翻案先讀那三則 note。

---

## 2026-08-04 乾淨重建後的待辦（**新對話優先看這節**）

依嚴重度排序。全部有實測證據，過程在 `$RECORDS/REBUILD-20260804.md`。

### 🔴 必修

- [ ] **`REBUILD-1`：檢查工具讀的是 DeepTutor 的舊資料庫。**
      `extract-check.py:37` 預設 `PP_PG_CONTAINER=deeptutor-v4-postgres`、
      `compat-check.py:262` **硬編**同一個字串、`compare-ws.py:59` 同型。
      `.env` 沒設那個變數所以全部吃預設值。實測對照：
      `lightrag-postgres` 有 2 份（我們的）、`deeptutor-v4-postgres` 有 20 份
      （舊的，最後更新 2026-08-02 17:47）。
      **「從 DeepTutor 搬出」只是複製，舊庫從來沒刪**，而工具一直讀舊的那個。
      兩邊資料相同時看不出來——清空一邊才暴露。CLAUDE.md 開篇說的「雙來源、無訊號」。
      ⇒ 三處改成從 `.env` 讀、預設 `lightrag-postgres`；**再加一條斷言**確認
      連到的容器與 `WORKSPACE` 屬於同一套（鐵則 6：探針要在沒人問的時候會響）。
      ⇒ 順帶決定 `deeptutor-v4-postgres` 裡那 20 份 `acoustics_v2` 要不要刪。
      工單已寫好：`scratchpad/ticket-fixes.md`（含缺陷 B）。

- [ ] **`REBUILD-2`：容器以 root 寫 `work/parsed`，宿主 postprocess 改不動。**
      每一份新文件都會撞，目前靠手動 `sudo chown -R florian:florian
      /data/lightrag/work/parsed` 繞過。實測撞過兩次（CLI 流程一次、審核台一次）。
      根本解法待評估：① compose 給 lightrag 加 `user: "1000:1000"`（最乾淨，
      但要驗 LightRAG 在非 root 下能否啟動）② 解析後自動 chown ③ setgid 目錄。
      ⚠ 舊結構下 `__parsed__` 的檔案 owner 是 florian，**查清楚舊結構為什麼是
      florian，那可能就是解法**。

### 🟡 該修

- [ ] **`REBUILD-3`：canary／compat-check 在母體為 0 時硬失敗而非「驗不了」。**
      `find_bundles()` 空集合直接 `sys.exit()`。空庫狀態下 daily-check 會天天
      紅燈打 ntfy——`judgement-flow.md:219`「假警報會讓人開始忽略警報」。
      **正解已有先例**：`A-25` 對「空 workspace 上 `chunk_top_k` 驗不了」已三態化。
      （目前有 2 份文件所以暫時不會觸發，但下次清空又會。）

- [ ] **`REBUILD-4`：intake 的 failed job 是死路且畫面上看不見。**
      `/api/state` 五節都不含 failed 的 job；admit／return／parse 三條路都拒絕它；
      只能手動刪 `/data/lightrag/intake/jobs/<id>/`。而且 `job.json` 裡有正確的
      `error` 欄位，卻沒被 `/api/jobs/<id>` 序列化出去（`reasons`／`details` 都是空陣列）。
      ⇒ 加 failed 區、顯示 error、提供「重置為候選」。

- [ ] **`REBUILD-5`：假綠測試。** `postprocess.py:337-339` 讀 `parsed.stderr`，
      但 `subprocess.run` 沒帶 `capture_output`，該分支**永遠不會執行**；
      而 `tests/test_prepare.py:64` 捏了假的 `CompletedProcess` 去測它。
      鐵則 7 那一族。二選一：讓分支真的有用，或拿掉分支與假測試。
      同檔另一項：`cmd_reindex` 的 scan 沒有 `_scan_was_skipped_pipeline_busy`
      守衛（**pre-existing**，來自 `3346e451`，不是這次的回歸）。

- [x] **`REBUILD-6`：測試環境。** 兩台原本都沒有 pytest，所以既有測試
      **從來沒被執行過**（藍桶第 8 條形同虛設）。已在 coder 裝 pytest 9.1.1。
      ⇒ 已新增 `scripts/run-tests.sh`，依序跑 pytest 與 `python3 tests/test_gates.py`；
      任一邊非零即失敗，並已接進 `daily-check.sh`。測試紅燈沿用既有 `exit 1`
      通知路徑，腳本本身缺失仍走 systemd `OnFailure`。

- [ ] **`REBUILD-7`：intake 尚未進 compose**，重開機不會自己起來。
      目前是手動 `setsid nohup` 跑的。

### 🟢 記著就好

- [x] **`REBUILD-8`：MinerU token 2026-09-04 到期**（查時剩 31.7 天）。
      `compat-check` 的 `A-21` 已改為 soft 級別；剩餘天數低於 14 天（含過期）會
      讓 `daily-check` 紅燈，並在 JSON 中留下門檻與到期 timestamp。

- [x] **`REBUILD-9`：舊體檢表要歸檔。** 已新增 `scripts/archive-ledger.py`：以當前
      workspace 的 `lightrag_doc_status` 為索引母體，預設 dry-run，只有加 `--move`
      才移動到 `records/ledger-archive-<YYYYMMDD>/` 並寫 README。只移動 `.pdf.json`
      體檢表，`records/review/` 的 7 項耐久規則證據留在原位。**本台未執行實際
      `/data` 歸檔**，需由主線在 dker 先 dry-run、確認清單後再加 `--move`。

- [ ] **`REBUILD-10`：CLAUDE.md 還停在重建前。** 路徑（`/data/rag/lightrag`）、
      現況（20 份文件、7,211 實體）、`extract-check` 的數字全部過期。
      ⚠ 引用 `extract-check` 數字的地方要標明**量測來源容器**——見 `REBUILD-1`，
      那些數字很可能量的是 DeepTutor 的庫。

- [x] **`REBUILD-11`：舊目錄 `/data/rag/lightrag` 已由 PO 清除** ✅ 2026-08-07。
      整個 `/data/rag` 都清了（含 DeepTutor 的 `knowledge_bases`）。
      ⚠ backrest 的 `rag-snapshot` plan 仍每 4 小時對那個已不存在的路徑產出快照
      ——**回報成功但內容是空的**。那不是本專案的庫，處置見上方待決定第 1 項。

---

## 立刻要做的（新對話從這裡接）

- `SYMBOL-1`（50 題考卷）✅ 完成 2026-08-03 —— 過程與數字見 [docs/log_20260803.md](docs/log_20260803.md#已歸檔的完成項)
- `SYMBOL-3`（restated 處置）✅ PO 2026-08-03 拍板選 ② —— 同上
- `SYMBOL-2`（模型判 1,482 個）✅ 實驗完成 2026-08-03，**決策未下** —— 同上
## `BACKUP` — 接上備份

**兩條都接上了（`BACKUP-1`／`BACKUP-2` ✅），缺的是還原演練與排程。**
2026-08-03 查證：文件宣稱 `/data/rag` 在 restic 備份範圍，
**那是假的**——backrest 當時只涵蓋 `/data/rag/knowledge_bases`（DeepTutor 的庫）。
假的安全宣稱比沒有宣稱更危險，因為你會照著它做決定。

- [x] **`/data/rag/lightrag` 已接上**（plan `lightrag-snapshot` → repo `rag-db`，
      cron `30 */6 * * *`，保留 14 日／8 週／3 月）。backrest 容器早就把 `/data`
      唯讀掛成 `/userdata/data`，所以不用改掛載、不用重建容器。
      **已驗過能還原**：首份快照 `f2d40c9f`（203.198 MiB／3,118 檔），
      `restic restore` 取回 `records/` 的 73 個檔，**sha256 逐位元與現役相同**。
- [x] 修掉 `.env.example` 與 README 裡「restic 備份範圍」的假宣稱

- `BACKUP-2`（索引本體冷備份）✅ 完成 2026-08-03 —— 同上
- `BACKUP-3`（還原演練）✅ 通過 2026-08-03 —— 同上
## 其他待辦

### 資料層（v2）

- [ ] **六份接地 >5% 的處置**。已查明**不是幻覺**，分兩族：
      **符號→概念命名**（K Muffler 15.1%、00712 11.9%、G Porous 6.4%）——
      K Muffler 的 92 個可疑裡**只有 1 個**是引用文獻型，其餘是傳遞矩陣的
      裸符號被命名（`Coefficient Ta`、`Matrix GA`、`H12 Parameter`）。
      **這推翻了 v155 時代「大量概念→引用文獻」的歸因**，根因是
      `SYMBOLIC_RATIO=0.35` 把同一族切成兩半，一半進「驗不了」一半進「可疑」。
      **調門檻前先照鐵則 5「看差在哪些具體記號」。**
      G Porous 6.4% 是**同一件事的 Bessel 版**（`Modified Bessel Function I0`
      這類裸符號被取描述性名字），不是另一個病因。
      **材料＝那 120 個名字，全在體檢表的 note 欄**（`$RECORDS/ledger/`）——
      要重量 `is_symbolic` 直接讀那份，不必重跑。
      **概念→引用文獻**（01200_6 6.1%、2025 5.7%、2023 FEM 5.0%）——
      作者縮寫名、期刊全名 vs 原文縮寫。
- [ ] **C 的羅馬數字下標族維持不修**（v155 47 個可疑 → v2 C 剩 14 個，重驗過）：
      `Region I/II/III`、`Mechl` 同一族，對應 `model-observations.json` 的
      domain_fact「羅馬數字下標難讀」——**兩雙眼睛方向相反地都會錯**，
      不是抽取器的問題。列在這裡是因為它會一直出現在可疑清單上，
      **看到它不必再查一次**。
- [ ] **N Flow #1410**（式 27，p59）`\mathbf{\overline{\partial}}^{2}`：
      overbar 被 MinerU 掛到 ∂ 上（應為系綜平均的範圍，Proudman 四階相關），
      同一式旁邊就有讀對的 `\frac{\partial^2}{\partial t^2}`。
      **屬整條重轉錄不屬換記號**，所以 `pp.equations` 對 N Flow 維持 fail。
- [ ] `eq-check` 三票多數決還沒對 v2 跑過（∂ 族已用裁圖定案了結，
      這項現在的用途是方程式的一般性品質，不急）
- [ ] C 的 `\times` 誤讀還有 6 處未修：`e^{-\gamma_{n,v}\times}` 型。
      同一個成因——座標 x 被讀成乘號，裁圖 `t373` 上寫的是 `e^{-γ_n x}`——
      但**位置不同**（在指數裡，不是下標），不在已授權的錨點內。
      **不一起放寬的理由：規則一次只放寬一條，否則漂移是哪一條造成的分不出來。**
- [ ] **C 的 91 個「bbox 未覆蓋」詞往哪裡併，尚未裁決**（歸因見
      `$RECORDS/review/c-uncovered-words.md`）：19 個 `continued` 續表標籤、
      19 個表格標題行、53 個在 p33／p51 兩頁（MinerU 整塊發成 image、
      caption 是 OCR 亂碼）。前兩類位置固定、字面單一，機械可修，但
      **會增加項目數**，與鐵則 2「項目數不得改變」衝突（sidecar 的 `self_ref`
      是陣列索引），只能併進既有 item 的 caption——**併到哪個 item 要先裁決**。
      第三類比照 p64 `#540` 逐塊人工裁定。全修 → 10.5% 降到 8.0%，**仍高於 5%**，
      所以這項不影響 waiver 成立與否，但未決的裁決本身不該消失。
- [ ] 首頁的期刊／會議資訊（`Paper ID #8776`、`©American Society…`）
      只在第 0 頁出現一次，重複與樣板規則都抓不到。要處理需要新訊號
      （限第 0 頁 ＋ 版權標記），但只有 1 份文件的證據，先不動

### 工具層

- [ ] `retrieval-check.py` 的框架對 v2 已過期：docstring 還寫著
      「目前索引裡 19 份是未經處理的」，而且**頭條數字是假訊號**——
      它報 0.57%／55% chunk 含雜訊，實際命中集中在單字元消音字串
      （`d` 9,059 次、`C` 385）與同時是真標題的書眉。
      真正該看的量是**相異雜訊字串數 670（v155）→ 13（v2）**，
      按這個量**消音確實生效**。
      **兩條出路，擇一**：① 給它一個新問題（現在這個已經被消音解掉了）；
      ② 讓它改報相異字串數而不是命中率。不動它就等於留一個永遠亮紅的假訊號。
- [x] **裁決材料進版控** ✅ 完成 2026-08-07。整份進了 `verdicts/`（227 檔 1.3 MB），
      不只抽「定案」節——文字檔全部加起來才 1.3 MB，抽節的成本高於收益，
      而且抽錯就沒有原文可回溯。裁圖（`records/review/crops` 1.5 MB）留在 `/data`。
      同步指令與權威歸屬寫在 `verdicts/README.md`，守衛是 `tests/test_verdicts.py`。
- [ ] `cmd_apply` 的批次原子性已實作並用注入失敗測過，但**新的機械規則對
      canary 是隱形的**（它的計數不在被追蹤的八個量裡）——內容變動型的規則
      需要自己的漂移偵測
- [ ] **實體碎片化在 v2 還沒量**（rebuild-plan 階段 4「量了才修」的殘留）。
      下面「刻意不做」那條的 388／254／51／8 全是**舊庫 v155 的數字**，
      v2 的對應數字一個都沒有。不合併的結論目前**借的是舊母體**——
      要嘛在 v2 重量一次確認結論仍成立，要嘛把那條改寫成「依 v155 證據暫緩」。
- [ ] **「qwen 系統性切錯列」還缺第二份樣本**：命中率約 1/15，目前只有一份
      有空表格的文件當證據。**一份證據的觀察是那份文件的巧合**（CLAUDE.md
      「規則分兩類」的判準），所以它現在只能留在 `model-observations.json`
      的易腐觀察，不得升格成裁決規則。要升格得先找到第二份。

### 效能（擴量前）

- [ ] **`SPEEDUP-1` MTP 加速評估 —— 三關已查兩關，`SPEEDUP-1` 原本的兩個前提都被實測推翻**
      （2026-08-03 在 coder 上實查；**這台就是 `100.71.26.77`**，llama.cpp 跑在這裡）：

      **關卡① GGUF 有沒有 MTP 權重 —— ❌ 沒有，定案。** 直接解析 GGUF 表頭
      （不是 `strings` 猜的：`strings` 掃到的 `mtp`／`draft` 全是 tokenizer 詞表）：
      `Qwen3.6-35B-A3B-UD-IQ4_XS.gguf` 有 **733 個張量、`blk.0`–`blk.39`、
      `nextn`／MTP 相關 0 個**（arch `qwen35moe`、`block_count 40`）。
      MTP 頭應該在 `blk.40.nextn.*`。**要用 MTP 就得換檔**——HF 上有保住 MTP 頭的
      同階量化（`unsloth/Qwen3.6-35B-A3B-MTP-GGUF`、
      `localweights/Qwen3.6-35B-A3B-MTP-IQ4_XS-GGUF` 等），不是重新轉檔才有。

      **關卡② 顯存 —— 很緊，未驗。** 2× RTX 3060 共 24 GiB，目前已用 21.4 GiB
      （free：GPU0 805 MiB、GPU1 1,601 MiB）。MTP 頭是 Q8_0 約 0.5–1 GiB 量級
      `(未驗,推測)`，換檔後塞不塞得下要實測。

      **關卡③ 驗證不是相信 —— 原本的判準已被實測推翻，要改寫。**
      原文寫「同一個 chunk 開關各跑一次，比對輸出是否逐字相同」當無損判準。
      **2026-08-03 實測：不開 MTP、`temperature=0`、固定 seed，輸出在不同併發度
      下就已經 `0/8` 逐字相同**（連續批次改變批次組成 ⇒ 浮點累加順序變）。
      所以「逐字相同」在併發環境**結構性不成立**。可行的替代：
      **固定 `--concurrency 1` 比對**（實測 c=1 是決定性的，兩輪 `completion_tokens`
      都是 14,266），或改用非逐字的判準。tok/s 那半不變，且**要看
      `decode_tok_s`**——MTP 只加速生成段，用牆鐘 `tok_s_aggregate` 會被 prefill 稀釋。

      **前提壞掉之一：「強制 `n_parallel=1` 對我們免費」不成立。**
      伺服器現在跑 `--parallel 4`（啟動 log `n_slots = 4`、`n_ctx_slot = 32768`），
      不是文件寫的單 slot。開 MTP＝把 4 個 slot 降成 1 個，而 390 份抽取正是
      併發批次負載。上游對 `n_parallel=1` 的強制我們**尚未在 build 10200 親驗**
      `(未驗,推測，來源＝下方參考連結)`。

      **前提壞掉之二：旗標名稱已改。** build 10200（`5f55650a7`）的列舉是
      `--spec-type none,draft-simple,draft-eagle3,draft-mtp,draft-dflash,…`
      ——是 **`draft-mtp`** 不是 `mtp`。`--spec-draft-n-max` 預設就是 3。

      **旁證（不是我們的實測）**：同為 Ampere＋同一顆 A3B MoE 的公開 benchmark
      （RTX 3090、`UD-Q4_K_XL`）在 llama.cpp 上**所有非 MTP 的投機變體都是負收益**：
      baseline 135.7 tok/s、ngram-mod −4%、ngram-cache −13%、classic draft −11%、
      DFlash −44.6%；作者明說是單流結果、**不能外推到併發批次**。
      ⇒ 不需要換檔的 `ngram-*` 那條便宜路線，先驗期望值就偏低。
      https://github.com/thc1006/qwen3.6-speculative-decoding-rtx3090

      **我們自己的基準（從現役 server log 撿的，非受控）**：4 slot 併發下
      tg 約 50–62 tok/s／slot、prompt eval 600–1,130 tok/s。
      **受控基準還沒建**——沒有它，任何 A/B 都沒有尺。

      參考：https://ai-coding.wiselychen.com/llama-cpp-mtp-merged-local-llm-2x-speedup/

      **⏸ PO 2026-08-03 拍板：MTP 與 vLLM 都不做。理由是 `SPEEDUP-2` 量出來的
      新事實 —— GPU 在 c=4 已接近飽和**（c=4→c=8 只 +4.6%，曲線壓平）。
      投機解碼的收益來自「單流解碼時算力閒著」，而**批次吃的是同一塊 headroom**，
      我們已經用併發吃掉了。用實測的 server 端 decode 速率估：

      | 情境 | 單題 decode | 併發 | 等效總 decode |
      |---|---:|---:|---:|
      | c=1（現況） | 77 tok/s | 1 | 77 |
      | **c=4（現況）** | 35 tok/s | 4 | **≈140** |
      | MTP ＋ 強制 c=1（樂觀 1.7×） | ≈131 tok/s | 1 | **≈131** |

      ⇒ **MTP 單流跑到最好，大約就是四路併發已經有的水準**，代價是 19.4 GB
      下載、換模型檔、顯存只剩 2.4 GB、還要照 `A-23` 重新量測模型觀察。
      **唯一的翻盤條件**：若 build 10200 的 `draft-mtp` 其實**沒有**強制
      `n_parallel=1`（旗標從 `mtp` 改名成 `draft-mtp` 說明實作動過），
      疊在 4 路併發上才可能真贏。驗法很便宜（起測試伺服器讀 log 的 `n_slots`），
      但要先下載 19.4 GB 且顯存不夠同時跑兩個伺服器。
      **vLLM 不做**：MTP 實作確實較好（同硬體 +27.5% decode），但 24 GB 顯存
      吃緊、GGUF 支援是實驗性的、兩張 3060 無 NVLink 走 PCIe 的 tensor parallel
      對 MoE 常是負收益，而且整條契約要重驗——**基礎設施搬遷換個位數百分比**。

### `SPEEDUP-4` — gleaning 佔比　🔵 已量一輪，**不足以下永久裁決**（2026-08-03）

每個 chunk 被 LLM 讀兩次：① 初次抽取 ②「補抓遺漏或描述錯誤」。
原假設是「補抓多半重工或撈渣，砍掉可省一半」。**實測推翻了這個假設**，
但第二意見（luna）指出證據撐不起「不要砍」這個永久結論。

**量到的**（dker，母體＝`lightrag_llm_cache` 的 1,019 筆 `extract`）：

```
            呼叫數  輸出字元佔比  抽出實體  每次實體   符號型佔比
initial      510      60.3%      6,372     12.5      14.8%
gleaning     509      39.7%      3,912      7.7      24.9%   ← 1.69 倍
邊際（458 個兩輪都可解析的 chunk）：
  補抓抽出 3,439 個名字 → 第一輪已有 227（6.6%）、真正新增 3,212（93.4%）
  新增裡符號型 878、非符號型 2,334
```

**⚠ 這些數字有五個已知弱點（luna 逐條指出，主線接受）**：

1. **「非符號型＝有用」只是弱代理。** 專案自己定義符號型是「驗不了」不是失敗；
   50 題樣本裡符號型有 38% 是正確概念推論，且 `restated` 實測會被檢索命中。
2. **分類母體對不上。** `--dump-symbolic` 是從**最終 VDB** 分類（已過解析、去重、
   跨 chunk 合併），卻被拿來標**原始 cache 輸出**。
3. **完全沒量關係。** gleaning 同時補 entities 與 relationships，可能補的是
   「兩個已存在實體之間的邊」——只數名字會漏掉它真正的價值。
4. **「同 chunk 內是新名字」≠「最終索引多一個節點」。** 2,334 很可能高估
   （跨 chunk 合併會吃掉一部分；大小寫不敏感比對可能把別名／下標變體算成新的）。
5. **字元佔比不是時間佔比。** 該用 completion tokens；gleaning 把第一輪內容放進
   歷史，prefill 成本不同（且本庫 prompt 前綴分岔、快取幾乎命不中）。
   可能超過 40% 也可能就是 40%，**沒量就不能斷言**。

**現階段的結論（採 luna 的措辭）**：原始快取顯示 gleaning 產生大量新候選，
**足以擋掉盲砍**，但尚未完成 parser-aware／merge-aware／relation-aware／
query-aware 的 A/B，**不足以永久封殺 selective gleaning**。

- [ ] 真要定案，缺的量測是：用實際 parser 重播、比對**最終 unique 節點與邊**的增量、
      量 `prompt_tokens`／`completion_tokens` 與 prefill/decode 時間、
      以及固定查詢集下的檢索品質 A/B。
- [x] **✅ 已查：64 筆（6%）`return_value` 不是合法 JSON —— 內容沒有掉。**

      成因是 **`Invalid \escape`**：模型在描述裡寫 LaTeX（`\gamma`、`\frac`），
      **反斜線在 JSON 裡是非法轉義**。內容與格式天生衝突，不是模型亂答。

      **決定性的比對**（`$RECORDS/review/20260803-speedup-symbol3/invalid_json_audit.py`）
      不是「JSON 合不合法」，是「該 chunk 在索引裡還有沒有實體」：

      ```
      兩輪都合法   458 chunk   9,581 實體   平均 20.9   （其中 7 個 0 實體）
      壞一輪        40 chunk   1,140 實體   平均 28.5   （0 個 0 實體）
      兩輪都壞      12 chunk     259 實體   平均 21.6   （0 個 0 實體）
      ```

      ⇒ **壞 JSON 的 chunk 實體不但沒少、還更多**。LightRAG 的 parser 比
      `json.loads` 寬容，那 64 筆都進了索引。方向也合理：**輸出越豐富越容易寫到
      LaTeX，也越容易有很多實體**——「JSON 壞」與「內容豐富」正相關。

      ⚠ **但這回頭修正了 `SPEEDUP-4` 的數字**：那些統計把這 64 筆當 0 或直接排除，
      而它們比平均更豐富。initial 有 41 筆壞、gleaning 只有 22 筆
      ⇒ **initial 被低估得更多 ⇒ gleaning 的相對貢獻被高估**。
      （luna 當時預測了這個偏差存在但「不能由筆數判斷方向」——現在可以了。）

      ⚠ **給未來寫工具的人**：任何用嚴格 `json.loads` 去讀這批快取的工具，
      **會靜靜漏掉 6% 而且是最豐富的那 6%**。主線今天就踩了兩次。

- [x] **`SPEEDUP-2.1`：受控吞吐基準工具**（`scripts/llm-bench.py`，commit `580a6f1`
      ＋ `3299ee9`）。四輪終審才過，每輪擋掉一個會產生錯數字的缺陷；判定原文四份。
      題本走 `$RECORDS/bench/`（含論文原文，不進 git）。

- [x] **`SPEEDUP-2`：`MAX_ASYNC` 2 → 4 —— ✅ 已改並驗證（2026-08-03）。**

      dker `.env` 改 `MAX_ASYNC=2` → `4`（備份 `.env.bak-20260803-maxasync`），
      `docker compose up -d lightrag` recreate（**`restart` 不會重讀環境變數**）。
      驗證輸出：健康檢查 5 秒轉 healthy、容器內 `printenv MAX_ASYNC` → `4`、
      `/health` `status=healthy pipeline_busy=False core_version=1.5.5`、
      kbapi :9700 HTTP 200、索引完整 510 chunk／7,211 實體／10,500 關係。
      **PO 拍板降檔為一般票**（單一數值、可逆、已有實測支撐）。
      ⚠ **真正的 4 路併發要到下一次抽取才會被實際行使**——目前只驗到
      「設定已生效、服務健在」，吞吐改善本身 `(未驗,推測)` 直到 `SCALEUP-1`。

      **量測結果**（2026-08-03，coder 實跑；報告在 `$RECORDS/bench/`，
      題本 `fixture-8.json` sha `7bfaf16d…`，伺服器 `b10200-5f55650a7`、
      `total_slots=4`、`cache_prompt=false`、`max_tokens=4096`、`trunc=0`、
      兩輪反序）：

      | 併發 | tok/s（R1／R2） | 相對 c=2 | p50 延遲 |
      |---:|---|---:|---:|
      | 1 | 67.83／68.01 | 0.82× | 25 s |
      | **2（現況）** | 84.01／81.82 | — | 32／40 s |
      | **4** | 107.47／105.44 | **+28%** | 60／64 s |
      | 8 | 110.03／112.85 | +34% | 97／110 s |

      **結論：2 → 4 買到約 +28% 吞吐；4 → 8 只再多 4.6%，但 p50 延遲從 62 s
      漲到 104 s。建議調到 4，不要調到 8。** `LLM_TIMEOUT=600` 對 c=4 有餘裕。

      **票別＝重票**（觸發清單 #4「動 `.env` 的鍵」）。改動本身可逆，
      但要走五站。順帶修 `.env.example`（寫 4）與 live `.env`（是 2）的不一致。

      **粗估效益**：現有 20 份抽取花 3 小時 58 分（`MAX_ASYNC=2`）。若照 +28%
      線性外推，390 份的抽取段從約 77 小時降到約 60 小時 `(未驗,推測——
      chunk 組成不同、且抽取不是唯一成本)`。

- [ ] **`SPEEDUP-2` 的三個副產物**（實測換來的，動它們之前先讀）：

      1. **`--repeat 2` 四個併發度全部是第 2 輪較慢**（c=2 達 6.2%，超過 5% 門檻）。
         方向一致而非隨機，像熱漂移或累積負載。**兩輪分不出漂移與雜訊**，
         要下結論得加輪數。
      2. **輸出在不同併發度下不逐字相同（`0/8`）**，即使 `temperature=0` ＋ 固定 seed。
         連續批次會改變批次組成 ⇒ 浮點累加順序變 ⇒ token 選擇分岔。
         **但 `--concurrency 1` 是決定性的**（兩輪 `completion_tokens` 都是 14,266）。
      3. **prompt cache 在真實負載幾乎吃不到**：拿伺服器沒見過的 8 題（`fixture-8b`，
         與舊題本 0 重疊）開快取跑，`cache_tokens_total = 0`、命中率 **0.0%**。
         原因是這批 prompt 的**全域共同前綴只有 11 個字元**（`---Task---\n`）——
         LightRAG 的抽取 prompt 有多種型別（初次抽取／gleaning），型別不同時
         前綴立刻分岔；同型別的兩兩共同前綴約 1,812 字元，佔平均 prompt 的 ~11%。
         ⇒ **冷測（關快取）就是這個負載的代表性量法**，不必另外做溫測校正。
         ⚠ 但**基準工具自己的前一輪會污染快取**：同一批題目重跑並開快取時
         量到 99.9% 命中，那是殘影不是真實。**A/B 一定要用沒跑過的題本。**

- [ ] **`SPEEDUP-3`：llama-server 的啟動設定沒有落檔。** 它是 `docker run` 起來的
      （`restart: unless-stopped`、掛 `~/ghq/models:/models`），**沒有 compose、
      沒有 systemd unit、repo 裡 grep 不到任何呼叫者**——參數只活在容器的 config 裡。
      任何 A/B 都要重啟它，容器一旦被 `docker rm` 掉，現行參數就沒了。
      **做實驗之前先把現況固化成檔**（含 image digest），否則回不去。
- [ ] **TurboQuant 不適用**（查過了）：它是 Google 的 KV cache 量化，
      實作在 vLLM + Triton 不是 llama.cpp，而且針對長脈絡場景——
      我們是一次一個 chunk，12 GiB 裡塞滿的是模型權重不是 KV cache
- [ ] 這台主機（100.87.88.7）的 `nvidia-smi` 壞了：
      `Driver/library version mismatch`，驅動更新但核心模組還是舊的。
      不影響現況（llama.cpp 在 100.71.26.77），但要在這台用 GPU 會踩到

### 擴量到 390 份（等上面收斂）

- [ ] 新期刊／新版面預期會冒出新型態，照
      `.claude/skills/onboard-doc-type/SKILL.md` 走，預期幾輪介入後穩定
- [ ] **解析階段議題**：表格結構黏連（`<td rowspan=2>ResistorCapacitorCoil</td>`
      ——三個詞塞一格沒有分隔符）。**內容沒有掉，掉的是分隔符**，後果是
      檢索 `Resistor` 配不到。**這一類佔 C 的 table 漏詞 72%**，是最大的一族。
      無法在後處理層修：要救必須重排表格結構＝整表換掉，與「定點補格、
      現值一個字不動」互斥。屬 MinerU 上限，該在解析階段解（MinerU 選項／版面規則）。
      同輪的另一半 `\mathsf{t a n h}` 逐字母排版**已了結**，走機械正規化
      2,399 段（commit `32276f9`，20 份／679 項）

---

## 刻意不做（決策記錄，動它之前先讀理由）

- **實體碎片化的長尾不合併**：51 組被檢索到的裡只有 8 組浪費 ≥2 格（已併），
  另 254 組從未出現在任何檢索結果——254 次不可逆操作換 0 收益。
- **23 處 `\mathsf{P}` 不碰**：P 在語料裡多義（ρ₀c₀ 的 ρ、ρ_P 的下標、
  空間點 P₂、矩陣 [P]、#1056 壓力波動方程的 p），沒有便宜可靠的訊號能分開。
- **`\hat{c}`／`\bar{c}` 不機械套**：#957 同一條式子裡兩義（一處是 ∂、
  一處是 c̄），與 `\mathsf{P}` 完全同型。已逐條定案，不得寫成規則。
- **C 的 69 個空 text 項不回填**：它們是跨頁段落的續行佔位，正文早被 MinerU
  併進前一頁的項目，**不造成漏字**。（41598 #41 曾被誤判成「單一空段落」，
  全母體掃描後才發現是 69 個同型且都不是洞——歸因只在同區域內比對會看不到
  被併到上一頁的鄰居。）
- **N Flow #1135／#1518 不動**：看圖後確定不是「式子吞散文」，是**符號說明
  清單被整片判成 `equation`**——型別判錯、無母體可修。coverage 那半已由
  偵測器 v2 了結。
- **K Muffler #277 不改**：`eq_similar` 誤報——`\begin{array}` 的排版結構被
  算成差異，MinerU 是對的且多帶著 `\tag{13}`。

---

## 工作方式（交接用）

- **分工**：主線（大模型）只做規劃、文檔、裁決與**獨立驗收**；執行類工作
  （部署、改程式、跑流程）一律開 Opus 子代理，附精確工單（要讀哪些文檔、
  約束、驗收條件）。**執行者的「自稱完成」不算數**——每一輪都由主線親自
  重跑關鍵指令驗收，這一路抓到過執行者漏報與歸因錯誤。
- **停損**：這次階段 2 的後半花了三小時追兩份文件的最後 1%，換回 39 個詞而
  閘門仍然不翻。**有問題 ≠ 值得修，先量代價再排序**（judgement-flow 第 8 節）。
- **審計軌跡**在 `$RECORDS/`：
  `ledger/`（每份文件的三態體檢表）、`review/`（裁決材料，每份都有
  「建議／依據／信心」與主線的「定案」節）、`review/crops/`（裁圖）。
- **常用驗收指令**（在 v2 worktree 跑）：
  ```bash
  python3 scripts/compat-check.py          # 契約 + 資料層，135 項
  python3 scripts/postprocess.py canary    # 規則漂移
  python3 scripts/ledger.py summary        # 體檢表總表
  python3 scripts/coverage-check.py        # 解析漏詞（--doc 篩單份）
  python3 scripts/extract-check.py         # 接地三態（--workspace 可指舊庫）
  python3 scripts/compare-ws.py <關鍵字> acoustics_v155 acoustics_v2
  ```
