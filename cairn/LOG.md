# Project Cairn 流水帳

本檔以逆時序記錄實質進展 —— 最新的一則放最上面、緊接在這一行下方。每則保持簡短：
只放摘要與指標，結論沉澱進 `cairn/<topic>.md`。

## 2026-08-08（二）· 收件匣審核台上線

- **`intake.py` 對新架構是活的**：22 個測試通過、實跑起得來、端點全通，
  `/api/state` 的 `convergence.processed: 1` 認得我們灌的那篇。已 `enable --now`，
  開機會自己回來（`:9710`）。
- **早上把它分類成「入庫自動化的狀態機、這輪用不到」是錯的。** 它是**收件匣／
  進料審核台**——拖 PDF 進去、看候選狀態走完管線。而且它的流程把修補排在送進索引
  之前，**正好擋住「拖進 LightRAG WebUI 會跳過後處理」那個問題**。
- **它刻意不進 compose，理由寫在單元檔裡且值得記住**：審核台會呼叫 `postprocess.py`，
  而 `oracle.py` 靠 `docker exec` 問容器。容器裡要做這件事就得掛 docker socket ——
  而它是**對外開埠、接受檔案上傳**的網頁服務。**給它 docker socket 等於誰打進來誰就
  有整台機器。**
- **又抓到一句自己寫的誤導訊息**：`install --only` 印「檔案已寫入但沒有 enable：…」，
  但清單裡的 `lightrag-stack.service` 上一輪就 enable 了 —— 同一句話涵蓋「這次沒動」
  與「現在是停用的」兩個完全不同的狀態。改成逐一查真實狀態再講。
- 現在的單元狀態：`stack` 與 `intake` enabled，兩個排程仍 disabled（等警報管道的裁決）。

## 2026-08-08· 重開機自動復原修好並驗過（零人工介入）

- **`lightrag-stack.service` 裝上、第二次重開機實測通過**：`ExecStartPre` 等到 Tailscale
  位址、`ExecStart` 拉起 stack，12/12 容器回來、埠綁上、節點 1,239 邊 1,995、端點全通。
  **判準是「重開之後不碰它，服務自己好」**，不是「重開之後我修好了」。
- **`systemd-units.py install` 加 `--only`**：原本會無條件啟用整個 ENABLE 清單，
  包含兩個「等警報管道決定之後才開」的 timer 與 intake。為了裝一個新單元順手開三個
  沒講好的東西，那是「順手做了沒講」。跳過的會明確印出來。
- **dker 裝了 pytest**，109 個測試第一次在那台真的跑過（之前 daily-check 每天報
  「測試失敗」，實際是根本沒跑）。
- 前一則寫的「不用真的重開機也能驗完」**被同一天的實測推翻**，更正寫在
  [testing-restart-policy.md](testing-restart-policy.md)：把大測試拆成小測試時，
  要問**拆掉的縫裡有什麼**——這次縫裡正好就是缺陷。

## 2026-08-07（九）· 補洞：deploy 守衛、自動復原、一個說謊的訊號

- **`deploy-stack.py`**：repo 的 compose 與 Dockge stack 那份不得漂移。verify/diff/install，
  比對與安裝共用同一個讀取實作（理由同 `systemd-units.py`）。dker 實測一致，
  `sha256:d434673f3e6df381`。⚠ 執行者仍弱——只有人跑它時才執行。
- **自動復原：殺程序過、重開機不過。** 從宿主殺容器主程序 → `RestartCount` 0→1、
  47 秒後 healthy、資料完好。我據此寫下「不用真的重開機也能驗完」——**那句是錯的**，
  PO 授權後真的重開，露出一個殺程序測不到的缺陷（見下一條）。
  過程中兩次假警報的方法論寫進 [testing-restart-policy.md](testing-restart-policy.md)。
- **重開機我們的服務不會回來（真缺陷）**：`failed to bind host port 100.87.88.7:9621:
  cannot assign requested address`。開機時 docker 比 tailscale 早起，而我們刻意綁
  Tailscale 位址（`:9700` 完全沒有認證，綁 `0.0.0.0` 等於知識庫在區網裸奔）。
  綁定失敗是**啟動失敗不是程序死亡**，restart policy 救不了。同機別人的 10 個容器全綁
  `0.0.0.0`，所以只有我們踩到。修法：`lightrag-stack.service`，`ExecStartPre` 等位址
  真的出現（`After=tailscaled` 不夠，那只保證 unit 起了不保證位址已指派）。
- **`docker compose up -d` 救不回失敗的容器，要 `--force-recreate`。** 這條最陰險：
  `docker compose ps` 顯示 `running`、`docker port` 卻是**空的**，外面完全連不上。
  我因此誤判過一次「服務已救回」。**`ps` 說 running 不等於服務可用。**
- **抓到一個一直在說謊的訊號**：dker 的 daily-check 輸出「測試失敗：pytest rc=1」，
  但那不是測試失敗，是**那台根本沒裝 pytest**。兩件完全不同的事長成同一句話，
  紅燈落在 `/data/lightrag/checks/` 沒人看得懂——而排程停用、沒有警報，也沒人去看。
  `run-tests.sh` 改成先問裝了沒，沒裝就說「驗不了」並回 exit 3（回 0 會讓「只驗一半」
  看起來像「全部通過」）。
- ⚠ **dker 不能跑 pytest 這件事還沒解**，只是不再說謊。要裝要 PO 決定。
- commit 訊息寫錯一次測試數（109 vs 實際 108+1 skip），**push 前發現，用 amend 改掉**
  ——推出去之後就只能追加了。

## 2026-08-07（八）· 一篇打通全程完成，關係數 1,995

- **抽取 40 分鐘跑完，節點 1,239 / 邊 1,995。** 設計 D3 的斷言「關係數不是 0」以最大
  差距通過——邊比節點多，是健康的圖，不是一袋沒有連線的名詞。
- **後處理有效**：空表格 9 → 1、修補 73 項、消音 146 項（`_pp_original_*` 可還原）。
  `doc` 端點回傳時看得到「已修補」標記。
- **D6 那個沒人量過的問題有答案**：本機模型抽實體關係時**沒有捏造**。可疑 3.0% 逐一
  看內容，全是「自己加型別前綴」（`Coefficient B0`）與 KI-003 的羅馬數字誤讀。
  它在表格轉錄會編 imgur 網址，在抽取層不會——**兩層行為不同，不能互相推論**。
- **五個端點全通**，三個 skill 一行沒改就能用。
- **掉字 10.6% 維持 fail，但那是重現**：歷史 10.5%（381/3629）vs 今天 383/3629，
  差 2 個詞。成因 2026-08-02 已逐詞歸因完。
- **補上一個沒接的執行者**：`verified-findings.json` 的規則寫「檢查工具在指標超標時
  **自動印出**已查證紀錄，不要求任何人記得去哪裡找」，但只有 `extract-check` 接了，
  `coverage-check` 沒有。我因此又查了一次 ledger——正是那條規則要防的事。已接上並補
  前例，實測會印。
- **`.env` 從五份收到一份**：repo 那份刪除、`/data` 的 8/4 備份與 repo 裡兩份 8/3 備份
  刪除，只剩 `/opt/stacks/lightrag/.env` 與一條指過去的 symlink。
- **`intake.py` 早上分類錯了**：我當它是「入庫自動化的狀態機」說這輪用不到，實際它是
  **收件匣／進料審核台**（:9710 的網頁，拖 PDF 進去、看候選狀態走完管線）。它的流程
  把修補排在送進索引之前，正好解決「拖進 LightRAG WebUI 會跳過後處理」那個問題。
  決定：先有基準再接，接之前拿它的測試對新架構跑一次看壞在哪。

## 2026-08-07（七）· 解析重跑，人工裁定 10/10 對得上

- **解析 43 秒、556 個項目、`is_bundle_valid` 通過**。基準數字全中：項目 556（基準 556）、
  表格 57（57）、空表格 9（9）。
- **10 個不可再生的人工裁定全部對得上**——索引仍是 `table`，頁碼與 `review.md` 記的
  一致。**鐵則第 8 條警告的錯位沒有發生**，重判成本是零（早上估的最壞情況是重判 10 張）。
  ⚠ 一份文件的證據，擴到 20 篇時每份都要重驗。
- **先驗 PDF 的 sha256 再談索引**：`1c7dcb0e1de0393c` 與 ledger 記的一致。順序不能顛倒——
  不是同一份檔案的話，索引對得上也沒有意義。
- **`.env` 搬家踩出一個靜默失敗**：`mineru_common.load_env()` 在檔案不存在時**回空字典
  不報錯**，所有腳本會拿到「沒有任何設定」繼續跑。先用 symlink 接回（刪 repo 只刪連結，
  不碰秘密本體），`load_env` 該改成大聲失敗——已列進 NEXT。
- **`EMBEDDING_SEND_DIM` 缺席是對的**：它管截斷，而 `EMBEDDING_DIM=3072` 等於
  `text-embedding-3-large` 的原生維度，不需要截斷。`rebuild-checklist` 寫成無條件必要，
  那個寫法會誤導，要改成有條件的。

## 2026-08-07（六）· 系統起來了：v1.5.6、圖進 Postgres、Dockge stack

- **`PGTableGraphStorage` 從推測變成實跑**。三層都驗過：映像清單有它 → 啟動 log
  `[acoustics_v2] PGTableGraphStorage initialized` → Postgres 裡真的建出
  `lightrag_graph_nodes` 與 `lightrag_graph_edges`。擴充只有 `plpgsql`＋`vector`，
  **沒有 age**，確認不需要 Apache AGE。13 張表全在同一個庫。
- **v1.5.5 沒有這個選項**（問映像本人），而 compose 原本釘的 digest 就是 v1.5.5——
  升級是必要條件不是順便。v1.5.5 映像已從 dker 移除。
- **三個容器 healthy**：lightrag（1.5.6）、postgres、kbapi。`:9700` 與 `:9621` 都回應。
- **`.env` 搬出 git checkout** → `/opt/stacks/lightrag/.env`。刪 repo 不再連帶弄丟秘密。
  順帶清掉死鍵 `NTFY_URL`（ntfy 今天拆了，全 repo 零讀取端）。現在 54 鍵。
- **數錯一次並更正**：`^[A-Z_]+=` 配不到含數字的鍵名（`NEO4J` 的 `4`），少算 4 個，
  錯的數字進了 `e39d6d4`。用追加更正不 amend——已推送。
- **kbapi 的定位釐清**：它不是薄代理，是**兩個 skill 的唯一來源**——LightRAG 沒有
  「這篇有哪些表格／公式／圖」的端點，那些資料在 MinerU 產物裡，它從沒讀過。
  PO 當初做它的主因是「只開一個埠」，但 `:9621` 一直也開著，**目標其實沒達成**；
  暫時保留（WebUI 有圖譜瀏覽器），決定寫進 NEXT。
- ⚠ **庫是空的，抽取一次都沒跑過。** 「能建表」不等於「能寫入」。

## 2026-08-07（五）· 清理 coder

- **刪掉六個前提已消失的檔**（約 1,960 行）：`compare-ws.py`（比較對象 v155 不存在了）、
  `llm-bench.py`＋測試（選型已定案）、`mathpix-test.py`＋`pp/mathpix.py`（第三隻眼實測
  選的是 MiMo）、`askrag.py`。不搬 `archive/` 目錄——歷史在 git 與 tag 裡。
- **`archive-ledger.py` 原本也在清單上，查證後撤回**：重建後庫裡只有 1 份文件、
  成績單有 20 張，19 張立刻脫節，而 `ledger.py` 那時會拒絕輸出總表並叫人跑這支。
  **清單靠自述判斷不夠，要查誰在引用它。**
- **skill 定位裁決**：三個 lightrag skill 住 `AI_TOOLS/skills/common/`，repo 副本刪除。
  判準不是「是不是本專案專屬」，是**誰用它**——Obsidian 的 agent 不在這個 repo 底下。
- **修掉一個每個 session 都在說的謊**：`lightrag-search` 的 `description` 寫
  「20 parsed papers」，那個庫已移除。`description` 是強制載入的，所以每次開場都灌一次
  假前提。三個 skill 都加上「重建中、連不上就如實說」（`AI_TOOLS` 的 `2c75ace`）。
- **`verdicts/README.md` 更正**：不再說 173 個全部不可再生，見
  [irreproducible-claims.md](irreproducible-claims.md)。
- **設計文件更正**：`extract-check.py` 早就在做「實體名能不能在原文找到」的檢查，
  原本寫成待做。
- **新長出三條上游畢業候選**，寫進 `docs/NEXT.md`，不在這一輪做。
- commits：`7a0414b` `b0c8d7d` `c7186f5`。

## 2026-08-07（四）· 重建需求釘死、文件治理收口

- **需求拷問完成，裁決在 `docs/rebuild-design.md`**（八個決定）。定位是「原料供應站」：
  不下結論，把乾淨原料交給 Obsidian 的 agent。範圍縮到 `C Equivalent Networks.pdf`
  一篇打通，手動分步跑。
- **拷問推翻了草稿自己的三條假設**：skill「一行不改」等於凍結舊拓樸（改成凍契約不凍
  位址）、`doc` 端點根本不回正文而 `search` 不能鎖定單篇（新增分節正文端點）、
  227 個「不可再生」實際只有 10 個。
- **第一個 topic note 誕生**：[irreproducible-claims.md](irreproducible-claims.md)。
  Cairn 的核心機制第一次被啟用——上一則還寫著「仍是 0 個」。
- **文件治理**：`AGENTS.md` 72 行 → 8 行純指標（上游範本本來就是一行 `# See CLAUDE.md`，
  是本專案偏離了）；獨有內容進 `docs/knowledge-routing.md`；`NEXT.md` 補 BASELINE 1.4.0
  要求的狀態總表與 mermaid 進度圖。**兩份導航表已各缺對方的項目**，後果是用 codex 的人
  從來不會被告知有 8 條鐵則。
- **兩支執行者掛上 pre-commit**：LOG 不得落後於 git、NEXT 的 done 不得追上待辦。
  原本 `test_log_freshness.py` 的執行者是 dker 的 timer，實測 `systemctl list-timers`
  只剩 apt-daily 兩個——規則有、執行者沒了。
- commits：`ffe7d12` `7b0cc58` `e2cfdc8` `7e16abf`。

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
