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
| 抽取用 LLM | 容器 `llama-qwen36-moe` :8080，2× RTX 3060，`--parallel 4`。它自己的 `.env` 在 `deploy/llama-qwen36-moe/.env`（一個鍵 `LLAMA_API_KEY`） |
| worker CLI | `codex`、`opencode`（**只有這台有**） |
| git hook | pre-commit 擋 commit 格式（`<type>(<scope>): <subject>`） |
| **沒有** | LightRAG 的 `.env`、跑 LightRAG 的 docker |

### florian-dker（ssh，Tailscale `100.87.88.7`）——部署

| | |
|---|---|
| repo | 同路徑，**唯讀，只 `git pull`** |
| LightRAG 的 `.env` | **只在這台**（54 個鍵，8 個是秘密。清單在 `.env.example` 開頭） |
| 資料根 | `/data/lightrag` — **現在只剩 `records` 183 檔、`checks` 32 檔** |
| 本專案容器 | **全部移除**（2026-08-07） |
| 別人的容器 | dockge、backrest、roonserver、zotero-pdf2zh、samba、nginx、hbbs/hbbr、vibevoice — **不要碰** |
| 壞的東西 | `nvidia-smi` 是 driver/library mismatch，要在這台用 GPU 會踩到 |

**`/data/rag` 已廢除**（見 ADR-0003），不得再寫入任何東西。

### 外部服務

| 誰 | 做什麼 | 注意 |
|---|---|---|
| OpenAI | embedding（`text-embedding-3-large` @3072）＋第二雙眼睛（`gpt-5.6-luna`） | 每次重建約 US$6 |
| MinerU 官方 API | PDF 解析 | **token 2026-09-04 到期** |
| OpenRouter | 第三隻眼，只在三方皆異時呼叫 | 必須釘住 provider，否則同一模型 ID 會被路由到不同供應商 |
| backrest | dker，備份 → rclone 到 Google Drive | rag 相關的兩個排程 PO 已說要關，**還沒關** |

**為什麼要兩台**：coder 上沒有 LightRAG 的 `.env` 也沒有它的 docker，所以「我在 coder
上驗過了」在物理上做不到。凡是關於跑著的系統的陳述，一律附 dker 的實跑輸出。

---

## 藍桶規則（9 條，BASELINE SNAPSHOT，勿手改此區塊）

> `baseline_version: 2.0.0`　`rules_sha256: f2d0bcfa04c43fb3`　`synced: 2026-08-07`
> （9 條與上游**逐字比對相同，用程式抽出、不手抄**。2.0.0 動了核心第 9 條
> ——加上「貼出的輸出必須是原文、不符時以輸出為準」，所以指紋從
> `d31afca400873b28` 變成現值。指紋算法：
> `grep -E '^[0-9]+\. \*\*' BASELINE.md | sha256sum | cut -c1-16`）

1. **Read before write**：修改任何檔案前先讀取現有內容，禁止覆蓋未讀的內容。
2. **No silent drops**：任何資料、欄位、邏輯在重構時不得無聲消失；刪除必須明確說明。
3. **Type hints**：Python 函式簽名必須有 type hints；禁止裸 `Any` 作為逃生門。
4. **No print for logging**：使用 `logging` 模組，禁止用 `print` 作為正式 log。
5. **SOLID / single responsibility**：函式和類別只做一件事；超過 50 行的函式先問自己能否拆。
6. **Explicit resource management**：file handle、DB connection、thread 必須用 `with` 或明確 `close()`。
7. **Pathlib over string paths**：路徑全程用 `pathlib.Path`，不靠 `os.path` 字串拼接。
8. **Tests before merge**：新功能必須有對應測試（至少一個 smoke test），無測試的 PR 不得合入主線。
9. **Verify-then-claim（驗證再斷言）**：任何關於「跑著的系統行為／狀態」的陳述（checkpoint、PR、回覆）必須附**驗證指令及其輸出**（curl／`docker exec`／pytest／實測），不得只靠讀 code 推理；未驗證者明確標 `(未驗,推測)`，不混入事實陳述。涉及 baked image／容器／部署的系統，須區分「源碼狀態」與「as-built 跑著的狀態」。貼出的輸出必須是指令**實際輸出的原文**；斷言與輸出不符時，**以輸出為準、改斷言**。「附了驗證指令、卻寫下與輸出不符的數字」比沒驗更糟——讀者會因為看到指令而更信任那個假數字（血淚 2026-08-07：grep 當場回 2 而 commit 訊息寫 0；同日稍晚宣稱行數676→115，實測是 445→115，676 不存在於任何 commit）。引用的數字必須來自**可重現的來源**（某個 commit、某次指令的輸出），或明確標示是中途狀態。

---
## 提交紀律（最小版，BASELINE ≥ 1.8.0）

- **做完即提交**：驗證過的範圍當場提隔離 commit，禁「done 但 uncommitted」長存。
- **只顯式 staging**：禁 `git add .`／`-A`；永不提交 `.env` 或金鑰。
- **推出去之後不得 `--amend`。** dker 可能已 pull 走那個 hash，amend + force push
  之後它抱著一個遠端不存在的 hash，`pull --ff-only` 直接失敗。2026-08-05 實測踩過。
- commit 訊息用 `<type>(<scope>): <subject>`，pre-commit 會擋。緊急時
  `--no-verify` 可繞過（知道有這個後門比不知道好）。

## 其他東西在哪

| 要找什麼 | 去哪 |
|---|---|
| 導航（哪個檔放什麼） | [AGENTS.md](AGENTS.md) |
| 接下來做什麼 | [NEXT.md](NEXT.md) |
| **鐵則 8 條與領域知識** | [docs/hard-rules.md](docs/hard-rules.md) ← 動 `scripts/pp/` 或規則之前必讀 |
| 新環境必須保持什麼樣子 | [docs/rebuild-checklist.md](docs/rebuild-checklist.md) |
| 某個決定為什麼那樣下 | [docs/decisions/](docs/decisions/) |
| 知道但決定不修 | [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md) |
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
