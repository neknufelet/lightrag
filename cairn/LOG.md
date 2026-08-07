# Project Cairn 流水帳

本檔以逆時序記錄實質進展 —— 最新的一則放最上面、緊接在這一行下方。每則保持簡短：
只放摘要與指標，結論沉澱進 `cairn/<topic>.md`。

## 2026-08-07（三）· 規範層：BASELINE 1.9.0 → 2.0.0

- **本專案的事故升格成跨專案規則。** 從 173 條踩坑清單提煉五條提案，請 fable 唯讀評估
  （97k tokens／23 次工具呼叫），四條採納、一條的藥方被它否決。
- **BASELINE 2.0.0**（`standards` 的 `f3f5e30`）：核心第 9 條加強、新增「規則的執行者」
  與「量測紀律」、提交紀律加「不得 amend 已推送」。指紋 `d31afca4…` → `f2d0bcfa…`。
- **上游體檢 11 項全部修完**，其中 **5 項現在是機器在守**（`standards/scripts/self-check.py`
  接在 pre-commit：frontmatter／指紋／範本 snapshot／type 清單／死引用）。
- **根因是「只有 BASELINE 有人維護」**：它改過十次，其餘八個檔自 2026-05-23 遷入 git
  後一個字都沒動 ⇒ 範本出貨「5 條」私貨、版本號凍三個月、引用一個不存在的 skill。
- **PO 定位自己是「系統外審查」** ⇒ 寫進 BASELINE：人的審查不算執行者，
  `沒有人` 不因為「反正會被發現」而降級。
- 本專案側：snapshot 同步兩次、`NEXT.md` 搬到 `docs/`、拆掉 ntfy、解除 Dockge 對 repo
  的 bind mount（那條掛載會讓 UI 的刪除按鈕刪掉 repo 本身）。
- 詳細理由與條文在 `standards/BASELINE.md` 與 `standards/CHANGELOG.md`。
  ⚠ **`cairn/<topic>.md` 仍是 0 個**——今天新長出來的知識（工具層與規範層怎麼分工）
  還沒定案，等 fable 評估後再建 topic，不先寫成要改的東西。

## 2026-08-07（下半）· 清空、砍文件、拆通知

- **dker 清空**：四個容器移除、`/data/lightrag` 只留 `records` 183 檔與 `checks` 32 檔
  （釋放約 2 GB）。凍結點 tag `archive/pre-rebuild-20260807`。
- **repo 砍 9,179 行**歷史文件（5 份文件＋173 條坑清單）。提煉出
  `docs/rebuild-checklist.md` —— 173 條裡只有 13 條在乾淨重建後仍成立，
  **其中 8 條的執行者是「沒有人」且壞掉不報錯**。
- **CLAUDE.md 655 → 115 行**。PO：「開一次就呼叫一次耶」。只留機器關係與藍桶 9 條；
  鐵則與領域知識移到 `docs/hard-rules.md`（沒刪）。每 session 載入從 715 → 164 行。
- **拆掉自架 ntfy**（容器、目錄、`notify.sh`、兩個 OnFailure 備援單元）。
  ⚠ **「誰會報錯」的答案又變回「沒有人」** —— 重建後要先決定警報走哪裡。
- **解除 Dockge 綁定**。dockge 的 compose 有一條把 repo 掛進 `/opt/stacks/lightrag`，
  **UI 的「刪除」會刪掉 repo 本身（含 dker 上唯一的 `.env`）**。移除掛載、重建 dockge、
  驗證 `.env` sha256 逐位元相同（`cb5b4742593d6c96`）、repo 328 個檔一個沒少。
  ⚠ 那個改動在 dker 的 `/opt/stacks/dockge/compose.yaml`，**不在版控**。
- **PO 連續抓到我三個錯誤**，全是「文件說的」與「實際的」不一致：coder 上其實有
  `.env`（llama.cpp 的）、Neo4j 還被寫成現況、workspace 名稱該改。
  加上我自己犯了三次同型錯誤（字串比對沒看內容就下結論）。

## 2026-08-07 · 四件補牆＋一個診斷：規則沒有執行者

- **`/data/rag` 廢除**（PO 定案）。兩處活的依賴改掉：冷備份暫存區搬到
  `/data/lightrag-coldstage`（**不能放資料根底下**，`cp -a "$DB_ROOT/." "$STAGE/"`
  會複製進自己）、`INTAKE_SOURCES` 留空。PO 清掉目錄後 03:28 又出現一個空的
  ——那是備份腳本自己 `mkdir` 的，刪一次建一次。
- **README 備份表三列全錯，方向相反**：打 ❌ 的 postgres／neo4j 每天備兩次，
  打 ✅ 的 `/data/rag/lightrag` 整個不存在，容量還錯一個量級。這張表**連續錯兩次**
  （08-03 之前寫「已納入備份」而沒有；修正後停在舊路徑）。
- **`apply` 加鎖**：`FORCE_REPARSE` 開著時拒絕執行。工單 830 行早就裁決要做，
  一直沒做。判準收斂到 `pp/oracle.py`，`A-07` 改用同一個函式。三條進料路徑
  都收束到 `cmd_apply`，一道鎖擋住全部。
- **`ledger.py summary` 自我停用**：它印「151 項通過」，那些全是 08-04 換掉的
  舊語料；現役 18 份幾乎一格都沒驗。dker 實跑 rc=3，指名 15 張幽靈。
- **不可再生的人工裁定進版控** `verdicts/` 227 檔 1.3 MB（NEXT 那條躺很久的待辦）。
- **決定重建方向的數字**：坑清單 173 條裡 **151 條在乾淨重建後不存在**；
  那 21 條「沒有人守且高優先」的裡面**重建後只剩 2 條**（都是 `.env` 的值）。
  ⇒ 補探針那條路的價值在重建那天歸零。
- **診斷（PO 追問「一套方法」逼出來的）**：`standards/BASELINE.md` 與 Project Cairn
  設計都完整，但**執行者都是「沒有人」**——掃描腳本預設路徑還是 Windows 的 `E:/`、
  沒有排程、standards 自己的 git hook 是空的、9 個 `.md` 零個有 frontmatter、
  `NEXT.md` 799 行（標準 <80）、**我今天 6 個 commit 全部不符合它的 commit 格式**。
  Cairn 只實現了 LOG.md，知識專題文檔 0 個、`Cited.md` 不存在。
  ⇒ 本則之後接三件執行者：LOG 落後檢查（本則就是它逼出來的）、pre-commit、NEXT 瘦身。

## 2026-08-05 · 整本書跑完，文件對齊現況

- **Möser A–R 十八章全部進知識庫**（1,589 chunk、14,226 實體、26,447 關係），
  收件匣清空，一份都沒卡在「等你看」。G–R 那 12 份的公式從一開始就是對的
  ——σ̂ 規則在跑 G 之前就落地了，不像 B/D/E 要事後重跑。
- **全套體檢**：canary 1 秒 ✅／compat-check 124 項 ✅／extract-check 2.7% 可疑率。
  `A-25` 從「驗不了」自動轉回真實判斷（母體長大了），不必改任何一行程式。
- **新機制：`tests/verified-findings.json`**。起因是 PO 指出「需要問就是規則沒寫好」
  ——我問了「這個判定要記到哪」，而那個問題本身就是缺陷訊號。查下去發現
  規則有、路由沒有：六個地方可以放而沒說怎麼選。**同一個查證已經做過兩次**
  （K Muffler 舊語料查過、L Capsules 今天又查一次）。
  解法不是「寫進某個文件」，是**讓檢查工具自己在超標時印出前例**。
- **`AGENTS.md` 補路由表**，判準是「誰在什麼時候需要它」——時機不會吵，分類會。
- **踩到一個雙 checkout 分岔**：先 push `8cf0c0a`、dker pull 走，之後 `--amend`
  補實跑輸出成 `23312c5` 並 force push ⇒ dker 抱著一個遠端已不存在的 hash，
  `pull --ff-only` 直接失敗。驗過兩個 commit 的檔案內容完全一致才 reset 對齊。
  **這次 git 有報錯是運氣**，一般的雙 checkout 分岔是靜靜分家的。
  規則已補進 CLAUDE.md 的「提交紀律」：**推出去之後不得 `--amend`**。
- CLAUDE.md 的「現況」與接地檢查一節更新到 18 份的實測數字；
  NEXT.md 加 2026-08-05 交接節。**舊語料的 20 份／7,211 實體不再可當現況引用。**

## 2026-08-04 · 七條跨專案知識畢業到 Obsidian

- 畢業 7 條 + 1 份索引到 `42_Cairn/lightrag/`，走 WebDAV 直寫，全部逐位元回讀驗證。
- 條目：乾淨的 0 要先當成量錯／先查輸入再查偵測器／探針要在沒人問的時候會響／
  門檻用量的不要用調的／認結構不認字元／對帳要問跑著的系統／設定只活在一台機器上。
- 索引開頭寫明它們是同一件事的七個面：**畫面說的跟實際發生的不一致，而且都不報錯。**
- 前四條來自 `CLAUDE.md` 的鐵則，後三條是 2026-08-04 這一輪長出來的
  （commit `c94d2fe`、`269653b`＋`2e7e2bb`、`42c73ef`＋`5dca4c8`）。
- **上傳時真的踩到自己寫的那條**：〈乾淨的 0〉那篇 PUT 回 `000`——不是 HTTP 碼，
  是 curl 因檔名含空格未編碼而根本沒送出。七個 201 配一個 000，看起來像「大致成功」。
  修 URL 編碼後重驗，八個全 200。

## 2026-08-04 · Project Cairn 初始化

- 初始化 Project Cairn 結構：`AGENTS.md`、`.cairn/config.yaml`、`cairn/LOG.md`。
- 歷史遷移模式：`selective_migrate`。**既有的 4,031 行文件不搬進 `cairn/`** ——
  `docs/precedents-inventory-20260804.md` 已把裁決盤點成 75 條，但抽驗 5 條錯 3 條，
  它自己的結論就是「不能自動匯入」。selective 的範圍只有「跨專案可複用的七條直接畢業」。
- 兩個獨立審查（codex luna xhigh、deepseek v4-pro）都判 **C：只遷移最高信心子集**。
  luna 另外指出 cairn 補的是「agent 查知識」的消費者，**不是「程式查先例表」的消費者**，
  混為一談會產生假完成感 —— 所以機器可讀的先例表仍是未做的事，不因 cairn 落地而消失。
- Obsidian provider 走 **WebDAV 直寫**（vault 在 NAS、本機無掛載亦無 obsidian CLI）。
- 細節見 `AGENTS.md` 與 `.cairn/config.yaml`。
