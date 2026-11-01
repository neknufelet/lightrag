# lightrag — 聲學知識庫

> 共用原則（先看再動、驗證再講…）和寫程式、提交的規則，在每家 agent 自動載入的全域規則檔（正本在 AI_TOOLS；寫程式那段的正本是 coding_rules 的 `CORE.md`），這裡不重複，只寫本專案特有的事。
> 同層的 `CLAUDE.md` 只有一行 `@AGENTS.md`，讓 Claude 也讀本檔。不要在 `CLAUDE.md` 寫東西。

**2026-08-07：系統清空了，需求還沒釘死。** 這個檔只留「機器關係」這類每次開工都要知道的事
——因為它每開一次 session 就載入一次，舊版 648 行的成本每次都要付，而裡面有一半
描述的是已經不存在的系統（當天實測：連續三處自相矛盾的陳述被 PO 抓到）。

**其餘規則不從這裡讀，等需求釘死之後再決定要不要回來。** 舊版全文在
tag `archive/pre-rebuild-20260807`。

---

## 機器關係

### florian-coder（Tailscale `100.71.26.77`）——2026-10-14 起不放本專案

| | |
|---|---|
| 本專案的東西 | **沒有了**。repo、Claude 記憶都已搬到 dker 並從這台刪除（2026-10-14）。這台仍是其他專案（aosr、choras…）的工作台，`standards` 也還在 |
| 本機 llama | **2026-10-14 移除**（容器 `llama-qwen36-moe` 與 llama.cpp 映像；模型資料夾早已是空的）。2026-08-09 起抽取就改走 DeepSeek。部署設定 `deploy/llama-qwen36-moe/` 同日從 repo 刪除，不再使用（要找回看 git 歷史）|
| 併發參數 | 不寫死，要知道就問伺服器。⚠ **`MAX_TOTAL_TOKENS` 與 slot 的乘除關係只在抽取走本機 llama.cpp 時成立**（每 slot 上限 ＝ `-c` ÷ `--parallel`，`docker logs llama-qwen36-moe \| grep n_slots`；改了併發不重算查詢預算，知識庫會對使用者謊報「找不到」）。**2026-08-09 起抽取走 DeepSeek，這條暫時不適用**——API 的 context 是單一請求的上限，不是所有併發共分的預算。**改回本機就會重新生效，別當它消失了** |

### florian-dker（Tailscale `100.87.88.7`）——工作與部署，2026-10-14 起本專案只在這台

| | |
|---|---|
| repo | 編輯在 `~/ghq/github.com/neknufelet/lightrag`。**跑著的是另一份 clone** `/opt/stacks/rag_acoustic/app`（＝ `.env` 的 `REPO_DIR`）：`lightrag-intake`／`daily-check`／`cold-backup` 三個 systemd 單元、LightRAG 容器的 `prompts/`、kbapi 容器的 `scripts/` 都讀它。它只由 `deploy-stack.py release` 更新，而且只拿已推上 origin 的 commit——**在編輯區存檔不會上線**（2026-10-14 起；之前編輯區就是線上）。兩份裡的 `.env` 都是指向下一列的 symlink |
| 共用原則、寫程式的規則 | 全域規則檔（各家 agent 自動載入，正本 AI_TOOLS；寫程式那段正本 coding_rules）。舊的 `standards` 已封存（2026-11-01） |
| worker CLI | `codex`、`opencode` |
| git hook | pre-commit 擋 commit 格式（`<type>(<scope>): <subject>`），2026-10-14 才在這台裝上——在那之前這台的 commit 都沒被擋過 |
| LightRAG 的 `.env` | **只在這台**，2026-08-07 起搬出 repo（刪 repo 不再連帶弄丟秘密）。**路徑不寫死**，跟著 symlink 走：`readlink -f .env`（stack 目錄名 ＝ `WORKSPACE`，換 workspace 就換路徑；寫死 `/opt/stacks/lightrag` 的那一版 2026-08-19 已經不存在）。哪些是秘密、去哪裡拿，看 `.env.example` 開頭那張表；`compat-check` 的 A-30 守著兩邊鍵名一致。⚠ 數鍵用 `^[A-Za-z_][A-Za-z0-9_]*=`；用 `^[A-Z_]+=` 會漏掉含數字的鍵名（`NEO4J` 的 `4`），2026-08-07 因此少算 4 個並寫錯進 commit。⚠ **不要 `source` 它**：`LIGHTRAG_PARSER` 的值含 `;`，shell 會把分號後面當指令 |
| 資料根 | `/data/lightrag` — `records` 與 `checks` 兩個目錄。**份數不寫死**，要知道就 `ls … \| wc -l` |
| 本專案容器 | 由 Dockge 管。**專案名不寫死**，它 ＝ `.env` 的 `WORKSPACE`：`docker ps --filter "label=com.docker.compose.project=$(grep -E '^WORKSPACE=' "$(readlink -f .env)" \| cut -d= -f2)"`。⚠ 寫死 `=lightrag` 的那一版**列不出任何東西**，看起來就像容器全掛了（2026-08-19 實測）。**要判斷健康看「打得到端點」不是「容器在跑」**（compat-check A-27） |
| 別人的容器 | dockge、backrest、roonserver、zotero-pdf2zh、samba、nginx、hbbs/hbbr、vibevoice — **不要碰** |
| GPU | 一張 RTX 2070 8GB，`nvidia-smi` 正常。**本機 embedding 與 rerank（Infinity）就跑在它上面** |

**`/data/rag` 已廢除**（見 ADR-0003），不得再寫入任何東西。

**改了 kbapi（`scripts/kbapi.py`，:9700）的網址、參數、回傳格式，或改了 workspace 名**，同一批要改 `AI_TOOLS/skills/common/` 的 `lightrag-search`／`lightrag-fetch`／`lightrag-images`。它們是每台機器呼叫 :9700 的說明書，住 AI_TOOLS 的理由見 `docs/knowledge-routing.md`〈skill 放哪〉。執行者：pre-commit 的 `kbapi-skill-reminder`，改到 `scripts/kbapi.py` 時印提醒，等級「會印警告」，不擋。

### 外部服務

| 誰 | 做什麼 | 注意 |
|---|---|---|
| DeepSeek 官方 API | **抽取**（`deepseek-v4-flash`），2026-08-09 起 | 金鑰是 `LLM_BINDING_API_KEY`。⚠ **思考必須關掉**：預設開著且 effort=high，會把額度吃在推理上而輸出被安靜截斷（`finish_reason=length`，不報錯）。⚠ **不要設輸出 token 上限**，設了才會製造「安靜被切掉」 |
| OpenAI | **只剩**第二雙眼睛（`gpt-5.6-luna`）。embedding 2026-08-08 已改本機 BGE-M3，重建不再花 API 費用 | 金鑰是 `PP_EYE_B_API_KEY`，**必須單獨設**——舊的 fallback 沿用 embedding 那把，換本機之後就斷了 |
| MinerU 官方 API | PDF 解析 | **token 2026-09-04 到期**，`compat-check` A-21 會在剩 14 天內轉警報 |
| OpenRouter | 眼睛 A（`qwen/qwen3-vl-32b-instruct`，2026-08-09 起）與第三隻眼（只在三方皆異時呼叫） | 必須釘住 provider，否則同一模型 ID 會被路由到不同供應商。⚠ **眼睛 A 沒單獨設會 fallback 成抽取模型**，而 deepseek-v4 不吃 image_url——看圖那隻會靜靜變成看不見圖的 |
| backrest | dker，每日 05:30 備份整個 `/data` 到 NAS；`/data/lightrag/postgres` 不在裡面，靠每日 04:00 的冷備份（`lightrag-cold-backup.timer` → NAS `Learning_DB/lightrag-coldstage`）。細節見 `/opt/stacks/docs/backup.md` | rag 專用的舊排程已全部移除（2026-10-27 查） |

**這張表裡刻意沒有數字。** 鍵數、檔數、容器數、費用都會變，寫死的那一版每次都撐不過
一週——2026-08-07 到 08 之間這幾格全部錯過一輪。要數就跑指令，指令不會過期。

**為什麼 2026-10-14 收成一台**：原本分兩台是為了讓 coder 上「驗過了」在物理上做不到，
但「驗證再講」要的實跑輸出全在 dker，於是實際上 dker 自己做了 73 次 commit，文件與現實分家。
凡是關於跑著的系統的陳述，仍然一律附實跑輸出。


## 提交（本專案補充）

通用的提交規則（做完就提交、只列路徑、推上去不改寫、跨 repo 記 SHA）在全域規則檔。這裡只補本專案的：

- 「推上去之後別人可能已經拿走」的那份，在本專案就是部署 clone `/opt/stacks/rag_acoustic/app` 與 GitHub 上的 origin（見〈機器關係〉）。改寫已推的 hash，部署那份的 `pull --ff-only` 會直接失敗。
- 完成品真的要留著不提交過 session，在 `docs/NEXT.md` 明記「線 X：done、未提交、檔清單」，讓下個 session 認得，不靠記憶。
- 真的滾成一團時：先唯讀地按 import／call-site 把髒檔分線，再按依賴順序逐條提交。
- 緊急時 `--no-verify` 可繞過 pre-commit。

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
