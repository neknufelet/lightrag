# NEXT — 待辦與進行中

規則與契約在 [CLAUDE.md](CLAUDE.md)（SSOT），重建的階段、閘門與各階段的
驗收紀錄在 [docs/rebuild-plan.md](docs/rebuild-plan.md)。這裡只放「接下來
要做什麼」。**做完就刪**——教訓沉澱回 CLAUDE.md 或 rebuild-plan，不留屍體；
新增時寫清楚證據在哪。

---

## 開新對話直接貼這段

```
專案 lightrag（聲學知識庫）。我在 florian-coder，透過 ssh 操作 florian-dker。

座標
  repo      ~/ghq/github.com/neknufelet/lightrag-v1（coder，工作台）
            ~/ghq/github.com/neknufelet/lightrag（dker，部署，唯讀只 pull）
  GitHub    neknufelet/lightrag-v1（尚未改名，計畫改成 lightrag，卡在 gh 未登入）
  服務      dker: lightrag-acoustics_v2 :9621、kbapi-acoustics_v2 :9700
            自己的 lightrag-postgres 與 lightrag-neo4j（2026-08-03 從 DeepTutor 搬出）
  資料      /data/lightrag（DB）＋ /data/rag/lightrag（解析快取與裁決紀錄）

先讀 CLAUDE.md 與 NEXT.md，兩份都是 2026-08-03 大改過的。
CLAUDE.md 前半是治理層（座標、藍桶 9 條、雙軌溝通、提交紀律、驗收路由、命名規則），
後半是原本的六條鐵則與現況。

規矩重點：
  - 改在 coder、驗在 dker。**驗證輸出沒拿到就還沒 done。**
  - coder 上沒有 .env、沒有 docker，碰 DB 的腳本在那裡跑不起來——這是刻意的。
  - 重票觸發清單見 CLAUDE.md「執行方針與驗收路由」，有疑義＝重票。

下一步照 NEXT.md 的狀態總表。最優先：
  BACKUP-3  還原測試——目前只驗了「快照存在」，沒驗「還原出來起得來」
  SYMBOL-3  先量 restated 那 600–990 個實體實際被檢索命中幾次，再決定動不動
```

## 狀態總表

label 格式與字母語意見 [CLAUDE.md](CLAUDE.md)「工作項目命名規則」。
legend：`✅完成 / 🔵進行中 / ⬜未起 / ⏸暫停 / ⚠️卡住`

| 線 | 當前 item | 狀態 |
|---|---|---|
| `REBUILD` | `REBUILD-5`（驗收與切換） | ✅ |
| `CUTOVER` | `CUTOVER-4`（v155 退役） | ✅ |
| `BACKUP` | `BACKUP-2`（Postgres／Neo4j 的 dump） | 🔵 `BACKUP-1`（`/data/rag/lightrag`）已完成並驗過還原 |
| `SCANNER` | `SCANNER-1`（封閉掃描器進版控） | ⬜ 最優先的工程項 |
| `SYMBOL` | `SYMBOL-3`（restated 怎麼處置） | 🔵 `SYMBOL-1`／`SYMBOL-2` ✅ 完成（答案卷＋三組實驗進版控）；`SYMBOL-2` 的**決策**未下 |
| `VERIFY` | `VERIFY-1`（`compat-check` 加 `suite` 欄） | ⬜ 常態線，只在有待辦時列 |
| `PPWORK` | `PPWORK-12` 之後無新項 | ✅ 大部分完成，殘項見「其他待辦」 |
| `SPEEDUP` | `SPEEDUP-1`（MTP 加速評估） | ⬜ 擴量前做 |
| `SCALEUP` | `SCALEUP-1`（390 份） | ⬜ 等上面收斂 |

---

## 現況（2026-08-03）

**acoustics_v2 已接手上線，acoustics_v155 已完全退役。** 重建的階段 0–5 全部
完成：0–3 經主線獨立驗收，切換與退役於 2026-08-03 執行完畢並實測驗證。

```
唯一的庫  acoustics_v2
checkout  ~/ghq/github.com/neknufelet/lightrag（單一，無 worktree、無 v1/v2 分身）
服務      lightrag :9621（容器 lightrag-acoustics_v2）
          kbapi    :9700（容器 kbapi-acoustics_v2）—— 三個 skill 全走這裡
內容      20 份 processed / 0 failed、7,211 實體、10,500 關係、510 chunk、可疑率 4.5%
排程      lightrag-daily-check.timer 每天 08:30 跑 compat-check + canary，
          紅燈打自架 ntfy（/opt/stacks/ntfy :9800），腳本自己掛掉走 systemd OnFailure 備援
v155      已不存在。Neo4j label、Postgres 列、磁碟目錄、容器全部移除，數字見 CLAUDE.md
```

> **備份**：`/data/rag/lightrag`（含 `__parsed__` 與 `records/`）已於 2026-08-03
> 接上 backrest（plan `lightrag-snapshot`，每 6 小時），**並驗過能還原**。
> 在此之前它一直沒有備份，而文件宣稱有——詳見下方「接上備份」。
> **索引本體（Postgres 15 GB／Neo4j 1.6 GB）目前仍無備份**，同節有處置。

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

## 立刻要做的（新對話從這裡接）

### `SYMBOL-1` — 50 題考卷：判「驗不了」那桶健不健康　✅ 完成 2026-08-03

**結論：這桶子不是幻覺問題，是【檢索價值】問題。**

母體 1,482 個「符號型／驗不了」實體，seed=20260803 取排列前 50，由主線逐題
讀來源 chunk 原文親手標。答案卷進版控：[tests/symbol1-answer-key.json](tests/symbol1-answer-key.json)。

| 判定 | 50 題 | 外推到 1,482（Wilson 95%，含有限母體修正） |
|---|---:|---|
| `correct` 從符號推論出真概念 | 19（38%）| 386–765 個 |
| **`restated` 名字實質就是符號本身** | **27（54%）** | **601–990 個** |
| `wrong` 與來源不符 | 4（8%）| 48–277 個 |
| `unjudgeable` 讀了也判不出 | 0 | — |

**NEXT.md 原本把問題設成二選一（正確推論 vs 垃圾），實際上主要族群是第三種。**
`restated` 不是錯、不會給出錯誤答案——它們只是**永遠不會被檢索命中**。
例：`Nn,v, (II)`（同一格的列標題就寫著「Mode norms in (II)」，真概念名就在旁邊
沒被用）、`S Sub 0 N Squared`（把 S_{0,n}² 唸出來）、`Variable X`、`Gamma Constants`
（命名的是希臘字母，而 Γ 在該處是傳播常數、隨頻率變，叫 constant 還輕微誤導）。

**四個 `wrong` 的性質不同，處置也不同：**

- `Density Fluctuation`（N Flow）：整個 chunk 對 density/rho/ρ 命中 **0 次**，
  原文用的是 `Π'=ln(p'/p₀)`，是**壓力**擾動。模型靠領域先驗補的。
- `Mechanical Resistance`（C）：該段講的是互易網路（Z→Z_r=r²/Z*），沒有機械阻。
- `Impedance Mismatch Matrix`（2017 Metadiffusers）：原文是 transfer matrix，
  「阻抗失配矩陣」是不存在的物件。
- **`Brota Parameters`（G Porous）：根因不在模型。** 原文寫 `BroT's parameters`
  ——那是 **`Biot` 被 OCR 弄壞**（P/Q/R 是 Biot 多孔彈性理論的標準參數）。
  模型忠實抄了壞掉的專有名詞。**這一類要往上游修，不是修抽取。**

**同族的上游污染在 `restated` 裡也很多**：`Z0 V11x`（`v_{I|x}` 的 `I|` 被讀成 `11`）、
`P11 Function`（`p_{II}` 的羅馬數字 II 被讀成 11）、`Axial Wavenumber L A`
（`Γ_a` 的 Γ 被讀成 L）。**這些與已記載的 domain_fact「羅馬數字下標難讀」同源。**

**這 50 題不能說的話**：樣本涵蓋 6 份文件，另外 9 份（共 30 筆、佔母體 2%）
未抽到，本結論不涉及它們。逐文件數字（C n=27、K n=9、N n=7、G n=5、其餘 n=1）
樣本太小，只看形狀不看比例——但 **N Flow 的 7 題有 6 題 correct、0 題 restated**，
與 C 的 27 題有 18 題 restated 形成明顯對比，值得後續查是「散文密度高的文件
抽得比較好」還是抽樣巧合。

**抽樣可延伸**：用固定種子的排列取前綴，日後擴到 100 題時**前 50 題不必重標**。

### 由 `SYMBOL-1` 長出來的新待辦

- [ ] **`SYMBOL-3`：`restated` 要不要處置，怎麼處置。** 這是本項最大的產出。
      600–990 個實體不會傷害正確性，但佔索引空間且永遠不被命中；擴到 390 份
      會變成數千個。選項：① 不動（成本最低，接受浪費）② 抽取 prompt 要求
      「若同格／鄰近有概念名，優先用它」③ 事後偵測並合併。**動之前先量
      『它們實際被檢索命中幾次』**——rebuild-plan 階段 4 對實體碎片化用的就是
      這個判準（254 組從未被檢索到 → 254 次不可逆操作換 0 收益）。
- [ ] **`SYMBOL-4`：OCR 污染的實體要不要回頭修。** `Brota`／`V11x`／`P11`／`L A`
      都是上游解析錯誤被忠實抄進索引。與 `SCANNER-1`（封閉掃描器）同源——
      那條線防的是「新符號誤讀」，這條是「已經進索引的舊誤讀」。

### `SYMBOL-2` — 用模型判那 1,482 個　✅ 實驗完成 2026-08-03（決策未下）

拿 `SYMBOL-1` 的 50 題當考卷，`gpt-5.6-luna` 跑三組。結果進版控：
[tests/symbol2-results.json](tests/symbol2-results.json)。

| 組 | 脈絡 | 推理 | 與人工一致 | 95% CI | `wrong` 召回 | `wrong` 誤報 |
|---|---|---|---:|---|---|---:|
| A | 截斷 700 字元 | low | 32/50 (64%) | [50, 76] | 3/4 | 6 |
| B | 完整 chunk | low | 36/50 (72%) | [58, 83] | 1/4 | 6 |
| C | 完整 chunk | **xhigh** | **41/50 (82%)** | [69, 90] | 2/4 | **0** |

**主線原本的預測被推翻。** NEXT.md 寫「主線的預測是『普通＋加大脈絡』會贏……
多給脈絡通常比多給推理有效，而且便宜得多」。實測：加脈絡 +8pp（A→B，
McNemar p=0.34 不顯著），**在脈絡之上再加推理又 +10pp**（B→C，p=0.23 不顯著；
但 A→C p=0.012 顯著）。**推理的貢獻不小於脈絡。** 那個前例（`X a` 拉長脈絡就
解決）不能外推到這個任務。

**但一致率不是該用的指標。** 真正要問的是「能不能撈出該人工看的那些」：

- **C 組零誤報**，但只召回 2/4。
- **A∪B 的聯集召回 4/4**，代價是撈出 12/50（24%）、誤報 8。
- **多數決反而更差**（召回 2/4、誤報 4）——因為三組抓到的是**不相交的子集**，
  投票把各自的獨門命中投掉了。這條要記住：**這個任務不能用多數決做 ensemble。**

**模型最擅長的是 `restated`**：C 組 27 題判對 24。那是母體的最大宗（54%），
而且是**結構性**判斷（名字是不是就是符號本身），不太需要領域推理——
這也暗示 `SYMBOL-3` 也許用便宜得多的手段就能量。

**部分分歧是題目的問題不是模型的問題。** `J0 Function`、`Transmission Component Ta`、
`Integral Operation` 三題模型判 `correct` 我判 `restated`——`correct`/`restated`
的界線是我畫的，這幾題本來就在線上（我在答案卷裡對 #22 就寫了「介於兩者之間，取嚴」）。
要把這條線變成可自動化的判準，**得先把 rubric 寫得比現在硬**。

**NEXT.md 警告的陷阱沒有出現**：三組都完整作答 50/50，沒有空字串、沒有預算耗盡。

**成本**：A 的 log 53 KB、B 159 KB、C 163 KB；C 約 4–5 分鐘，B 約 1 分鐘。

- [ ] **`SYMBOL-2` 的決策還沒下**：要不要拿 A∪B 去掃全部 1,482？那會撈出約
      350 個要人看（24%），其中約七成是誤報。**先想清楚撈出來要做什麼**——
      若處置是「刪掉或改名」，那 8/12 的誤報率會讓人不敢動手。
      另一條路：既然模型最會判 `restated`，就**只用它做 `SYMBOL-3` 的量測**
      （量有多少、集中在哪），不拿它當閘門。

## `BACKUP` — 接上備份

**已完成一半。** 2026-08-03 查證：文件宣稱 `/data/rag` 在 restic 備份範圍，
**那是假的**——backrest 當時只涵蓋 `/data/rag/knowledge_bases`（DeepTutor 的庫）。
假的安全宣稱比沒有宣稱更危險，因為你會照著它做決定。

- [x] **`/data/rag/lightrag` 已接上**（plan `lightrag-snapshot` → repo `rag-db`，
      cron `30 */6 * * *`，保留 14 日／8 週／3 月）。backrest 容器早就把 `/data`
      唯讀掛成 `/userdata/data`，所以不用改掛載、不用重建容器。
      **已驗過能還原**：首份快照 `f2d40c9f`（203.198 MiB／3,118 檔），
      `restic restore` 取回 `records/` 的 73 個檔，**sha256 逐位元與現役相同**。
- [x] 修掉 `.env.example` 與 README 裡「restic 備份範圍」的假宣稱

### 還沒接的：索引本體

| 路徑 | 大小 | 備份 |
|---|---|---|
| `/data/rag/lightrag` | 210 MB | ✅ 已接 |
| `/data/rag/postgres_data`（**7,211 實體／10,500 關係／向量都在這**） | 15 GB | ❌ **無** |
| `/data/rag/neo4j_data`（圖） | 1.6 GB | ❌ **無** |

- [ ] **Postgres 的備份要用 `pg_dump`，不能複製資料目錄。** 跑著的 PG 資料目錄
      直接檔案複製出來是**不一致的快照**，還原時可能起不來——而且失敗會發生在
      你最需要它的時候。做法：定時 `docker exec deeptutor-v4-postgres pg_dump`
      到某個路徑，再讓 backrest 備那個路徑。
      **注意這個 PG 是與 DeepTutor 共用的**（15 GB 不全是我們的），
      要嘛只 dump `lightrag` 這個 database，要嘛跟那邊一起規劃。
- [ ] Neo4j 同理，用 `neo4j-admin database dump`。同樣是共用實例
      （`acoustics_books`、`Room_Optimizer` 等六個庫在裡面）。
- [ ] **算一次「全毀要多久重建」**再決定要做到什麼程度。目前已知：
      `__parsed__` 重解析 6–10 小時（已有備份，不必重跑）、抽取 3 小時 58 分、
      嵌入 4.56M 字元 ≈ US$0.15。**人工裁決那部分重跑也回不來**，但它在
      `records/` 裡，已經備份到了。

---

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
- [ ] **裁決材料進版控**。今天的定案（∂ 族白名單、C 補格、為什麼某些東西
      刻意不碰）寫在 `$RECORDS/review/` 底下，
      **2026-08-03 起真的有備份了**（在那之前這句是空話），但仍**不在 git**——
      三個月後問「為什麼 `\mathfrak{O}` 在白名單上」，答案存在但不在版控裡、
      不會出現在任何 diff。
      建議把各檔的**「定案」節**抽出來進 git，龐大的原始材料與裁圖留在 `/data`
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

- [ ] **MTP 加速評估**：`--spec-type mtp --spec-draft-n-max 3`。
      `Qwen3.6-35B-A3B`（就是我們跑的那顆）**原生支援**，實測 1.7–2.5×。
      它「強制 `n_parallel=1`」的限制**對我們免費**——llama.cpp 本來就只有
      1 個 slot（所以 `.env` 的 `MAX_ASYNC=2`，再高只會排隊撞逾時）。
      抽取吐的是結構化 JSON，格式可預測，草稿接受率應該偏高。
      三關按順序：①那顆 GGUF（`Qwen3.6-35B-A3B-UD-IQ4_XS`）**有沒有帶
      MTP 權重**——很多量化轉檔會把 MTP 頭丟掉；②顯存，GPU0 只剩 0.67 GiB；
      ③**驗證不是相信**——同一個 chunk 開關各跑一次，比對輸出是否逐字相同
      （貪婪解碼下應該無損，但要驗）＋實際 tok/s。輸出若有差就不只是加速，
      是換了模型行為，要照 A-23 那套重新量測模型觀察。
      **價值在 390 份擴量時**，抽取是那時的時間大宗。
      參考：https://ai-coding.wiselychen.com/llama-cpp-mtp-merged-local-llm-2x-speedup/
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
