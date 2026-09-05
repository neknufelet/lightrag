# lightrag — 聲學知識庫

**2026-08-07：系統清空了，需求還沒釘死。** 這個檔被砍到只剩「機器關係」與上位規範的
9 條——因為它每開一次 session 就載入一次，舊版 648 行的成本每次都要付，而裡面有一半
描述的是已經不存在的系統（今天實測：連續三處自相矛盾的陳述被 PO 抓到）。

**其餘規則不從這裡讀，等需求釘死之後再決定要不要回來。** 舊版全文在
tag `archive/pre-rebuild-20260807`。

---

## 機器關係

### florian-coder（本機，Tailscale `100.71.26.77`）——工作台

| | |
|---|---|
| repo | `~/ghq/github.com/neknufelet/lightrag` ← **所有編輯與 commit 在這裡** |
| 上位規範 | `~/ghq/github.com/neknufelet/standards`（**只有這台有**） |
| 本機 llama | 容器 `llama-qwen36-moe` :8080，2× RTX 3060。**2026-08-09 起停著，也不再是抽取用 LLM**（抽取改走 DeepSeek，見下方外部服務表）。它自己的 `.env` 在 `deploy/llama-qwen36-moe/.env`（一個鍵 `LLAMA_API_KEY`）。⚠ **它與 LightRAG `.env` 的 `LLM_BINDING_API_KEY` 已不再是同一把**——後者現在是 DeepSeek 的。⚠ **金鑰在容器的命令列上**，`docker inspect` 與 `ps aux` 都看得到——2026-08-08 因此外洩一次，處置見 NEXT 第 4 批；重新啟用前先處理它 |
| 併發參數 | 不寫死，要知道就問伺服器。⚠ **`MAX_TOTAL_TOKENS` 與 slot 的乘除關係只在抽取走本機 llama.cpp 時成立**（每 slot 上限 ＝ `-c` ÷ `--parallel`，`docker logs llama-qwen36-moe \| grep n_slots`；改了併發不重算查詢預算，知識庫會對使用者謊報「找不到」）。**2026-08-09 起抽取走 DeepSeek，這條暫時不適用**——API 的 context 是單一請求的上限，不是所有併發共分的預算。**改回本機就會重新生效，別當它消失了** |
| worker CLI | `codex`、`opencode`（**只有這台有**） |
| git hook | pre-commit 擋 commit 格式（`<type>(<scope>): <subject>`） |
| **沒有** | LightRAG 的 `.env`、跑 LightRAG 的 docker |

### florian-dker（ssh，Tailscale `100.87.88.7`）——部署

| | |
|---|---|
| repo | 同路徑，**唯讀，只 `git pull`**。repo 裡的 `.env` 是指向下一列的 symlink |
| LightRAG 的 `.env` | **只在這台**，2026-08-07 起搬出 repo（刪 repo 不再連帶弄丟秘密）。**路徑不寫死**，跟著 symlink 走：`readlink -f .env`（stack 目錄名 ＝ `WORKSPACE`，換 workspace 就換路徑；寫死 `/opt/stacks/lightrag` 的那一版 2026-08-19 已經不存在）。哪些是秘密、去哪裡拿，看 `.env.example` 開頭那張表；`compat-check` 的 A-30 守著兩邊鍵名一致。⚠ 數鍵用 `^[A-Za-z_][A-Za-z0-9_]*=`；用 `^[A-Z_]+=` 會漏掉含數字的鍵名（`NEO4J` 的 `4`），2026-08-07 因此少算 4 個並寫錯進 commit。⚠ **不要 `source` 它**：`LIGHTRAG_PARSER` 的值含 `;`，shell 會把分號後面當指令 |
| 資料根 | `/data/lightrag` — `records` 與 `checks` 兩個目錄。**份數不寫死**，要知道就 `ls … \| wc -l` |
| 本專案容器 | 由 Dockge 管。**專案名不寫死**，它 ＝ `.env` 的 `WORKSPACE`：`docker ps --filter "label=com.docker.compose.project=$(grep -E '^WORKSPACE=' "$(readlink -f .env)" \| cut -d= -f2)"`。⚠ 寫死 `=lightrag` 的那一版**列不出任何東西**，看起來就像容器全掛了（2026-08-19 實測）。**要判斷健康看「打得到端點」不是「容器在跑」**（compat-check A-27） |
| 別人的容器 | dockge、backrest、roonserver、zotero-pdf2zh、samba、nginx、hbbs/hbbr、vibevoice — **不要碰** |
| GPU | 一張 RTX 2070 8GB，`nvidia-smi` 正常。**本機 embedding 與 rerank（Infinity）就跑在它上面** |

**`/data/rag` 已廢除**（見 ADR-0003），不得再寫入任何東西。

### 外部服務

| 誰 | 做什麼 | 注意 |
|---|---|---|
| DeepSeek 官方 API | **抽取**（`deepseek-v4-flash`），2026-08-09 起 | 金鑰是 `LLM_BINDING_API_KEY`。⚠ **思考必須關掉**：預設開著且 effort=high，會把額度吃在推理上而輸出被安靜截斷（`finish_reason=length`，不報錯）。⚠ **不要設輸出 token 上限**，設了才會製造「安靜被切掉」 |
| OpenAI | **只剩**第二雙眼睛（`gpt-5.6-luna`）。embedding 2026-08-08 已改本機 BGE-M3，重建不再花 API 費用 | 金鑰是 `PP_EYE_B_API_KEY`，**必須單獨設**——舊的 fallback 沿用 embedding 那把，換本機之後就斷了 |
| MinerU 官方 API | PDF 解析 | **token 2026-09-04 到期**，`compat-check` A-21 會在剩 14 天內轉警報 |
| OpenRouter | 眼睛 A（`qwen/qwen3-vl-32b-instruct`，2026-08-09 起）與第三隻眼（只在三方皆異時呼叫） | 必須釘住 provider，否則同一模型 ID 會被路由到不同供應商。⚠ **眼睛 A 沒單獨設會 fallback 成抽取模型**，而 deepseek-v4 不吃 image_url——看圖那隻會靜靜變成看不見圖的 |
| backrest | dker，備份 → rclone 到 Google Drive | rag 相關的兩個排程 PO 已說要關，**還沒關** |

**這張表裡刻意沒有數字。** 鍵數、檔數、容器數、費用都會變，寫死的那一版每次都撐不過
一週——2026-08-07 到 08 之間這幾格全部錯過一輪。要數就跑指令，指令不會過期。

**為什麼要兩台**：coder 上沒有 LightRAG 的 `.env` 也沒有它的 docker，所以「我在 coder
上驗過了」在物理上做不到。凡是關於跑著的系統的陳述，一律附 dker 的實跑輸出。

---

<!-- BEGIN BASELINE SNAPSHOT — baseline_version: 2.1.1 rules_sha256: 41d3304f414a5a12 synced: 2026-09-06 -->
## 藍桶規則（9 條，BASELINE SNAPSHOT，勿手改此區塊）

1. **Read before write**：修改任何檔案前先讀取現有內容，禁止覆蓋未讀的內容。
2. **No silent drops**：任何資料、欄位、邏輯在重構時不得無聲消失；刪除必須明確說明。
3. **Type hints**：Python 函式簽名必須有 type hints；禁止裸 `Any` 作為逃生門。
4. **No print for logging**：使用 `logging` 模組，禁止用 `print` 作為正式 log。
5. **SOLID / single responsibility**：函式和類別只做一件事；超過 50 行的函式先問自己能否拆。
6. **Explicit resource management**：file handle、DB connection、thread 必須用 `with` 或明確 `close()`。
7. **Pathlib over string paths**：路徑全程用 `pathlib.Path`，不靠 `os.path` 字串拼接。
8. **Tests before merge**：新功能必須有對應測試（至少一個 smoke test），無測試的 PR 不得合入主線。
9. **Verify-then-claim（驗證再斷言）**：任何關於「跑著的系統行為／狀態」的陳述（checkpoint、PR、回覆）必須附驗證指令及其輸出（curl／`docker exec`／pytest／實測），不得只靠讀 code 推理。
  未驗證者明確標 `(未驗,推測)`，不混入事實陳述。
  涉及 baked image／容器／部署的系統，須區分「源碼狀態」與「as-built 跑著的狀態」。
  貼出的輸出必須是指令實際輸出的原文；斷言與輸出不符時，以輸出為準、改斷言。
  「附了驗證指令、卻寫下與輸出不符的數字」比沒驗更糟——讀者會因為看到指令而更信任那個假數字（案例：CHANGELOG 2.1.0）。
  引用的數字必須來自可重現的來源（某個 commit、某次指令的輸出），或明確標示是中途狀態。
<!-- END BASELINE SNAPSHOT -->

---
<!-- BEGIN BASELINE SECTION: 提交紀律（Commit-on-done，禁 done-but-uncommitted 累積） — baseline_version: 2.1.0 synced: 2026-09-05 -->
## 提交紀律（Commit-on-done，禁 done-but-uncommitted 累積）

> 目的：杜絕「做完卻放著不提交」在長命共用分支上滾成一團、無人記得歸屬的髒樹（案例：CHANGELOG 2.1.0）。

- 做完即提交（commit-on-done）：任何完成且驗證（tsc／pytest／實測綠）的 gate／工單／明確範圍，當場提成一個範圍隔離的 commit（大型工作線可含多個 commit）。「done 但 uncommitted」是禁止長存的狀態；收尾（wrap-up）不是「攢一堆再一次全提」的時機。
- 開新線前驗乾淨基線：開新 gate／工作線前 `git status` 對該範圍必須乾淨；樹上已有別線的髒，先提交／stash 理清再開工（把「基線不乾淨就 STOP」變事前常規閘，非事後補救）。
- 只顯式 staging：**禁 `git add .`／`git add -A`**；一律列明檔案路徑。共用檔跨多線時用 hunk-stage（`git add -p`／patch），不整檔連帶別線 hunk。**永不提交 `.env`／本機 remote URL／機密。**
- 跨 repo 功能鎖步：一個功能橫跨多 repo（前端＋後端＋worker）時，各 repo 的對應改動同批或緊接著一起提交，不留一半髒；gate 報告記錄各 repo SHA。
- 留髒是逃生門非常態：萬一真須留未提交的完成品過 session，在該專案的狀態交接檔（`docs/next.md` 或該專案慣例的 `STATUS_UPDATE.md`）明記「線 X：done、未提交、檔清單」，讓下個 session 認得，不靠記憶。
- 推出去之後不得 `--amend`（含任何改寫已發布 hash 的操作）：第二個 checkout／CI／協作者可能已 pull 走原 hash，amend + force push 後對方抱著一個遠端不存在的 hash，`pull --ff-only` 直接失敗（案例：CHANGELOG 2.1.0）。
  要補驗證輸出：先驗再提交，或另開 commit 寫「補 <hash> 的實跑輸出」。可行時在遠端鎖 force-push（branch protection），把這條從紀律升級成「會擋下」。
- 復原（真滾成一團時）：read-only 連通性審計把髒檔按 import／call-site 分線（工具可靠度：harness 內 grep-agent ＞ 外部 footprint 猜測），再按依賴序逐條隔離提交。
<!-- END BASELINE SECTION -->

> 本專案補充：上節「第二個 checkout」在本專案就是 dker（見〈機器關係〉）；緊急時 `--no-verify` 可繞過 pre-commit。

## 其他東西在哪

| 要找什麼 | 去哪 |
|---|---|
| 接下來做什麼 | [NEXT.md](docs/NEXT.md) |
| **鐵則 8 條與領域知識** | [docs/hard-rules.md](docs/hard-rules.md) ← 動 `scripts/pp/` 或規則之前必讀 |
| 新環境必須保持什麼樣子 | [docs/rebuild-checklist.md](docs/rebuild-checklist.md) |
| 某個決定為什麼那樣下 | [docs/decisions/](docs/decisions/) |
| 知道但決定不修 | [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md) |
| 遇到沒見過的問題怎麼查 | [docs/judgement-flow.md](docs/judgement-flow.md) |
| 這個東西該放 `docs/` 還是 `cairn/` | [docs/knowledge-routing.md](docs/knowledge-routing.md) |
| 多 worker 分工（draft，未定案） | [docs/workflow.md](docs/workflow.md) |
| 某天發生了什麼 | [cairn/LOG.md](cairn/LOG.md) |

## 溝通

- **先人話、後技術話。** 白話不得省略關鍵技術細節（否則無法驗證），技術不得取代
  白話結論（否則抓不到重點）。純確認豁免。
- **不要堆內部術語**（坑編號、票別、inode 那類）。PO 是決策者不是實作者。
- **每次改完交四行**：改了什麼／沒改什麼／沒驗什麼／會壞什麼。**第二行最重要**——
  「發現了、沒動、也沒講」是 PO 抱怨最多的事。
- **附了驗證指令就要貼真實輸出。** 2026-08-07 犯過一次：附了 grep 指令卻寫了
  與輸出不符的數字。那比「沒驗就斷言」更糟，因為讀者會因為看到指令而更信任那個數字。
