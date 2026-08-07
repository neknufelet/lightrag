# lightrag — AI 協作者的路標

**規則、契約、跨機座標全部在 [CLAUDE.md](CLAUDE.md)。先讀那個。**

這個檔存在的唯一理由：codex／opencode 這類 CLI 讀 `AGENTS.md`，不讀 `CLAUDE.md`。
所以這裡**只放路標，不重複規則**——同一條規則有兩個地方就會漂移，而漂移不報錯。

| 要找什麼 | 去哪 |
|---|---|
| 鐵則、契約、座標、常用指令 | [CLAUDE.md](CLAUDE.md) |
| 接下來做什麼 | [NEXT.md](NEXT.md) |
| 某個決定為什麼那樣下 | [docs/decisions/](docs/decisions/) |
| 新環境必須保持什麼樣子 | [docs/rebuild-checklist.md](docs/rebuild-checklist.md) |
| 知道但沒處理的問題 | [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md) |
| 遇到沒見過的問題怎麼查 | [docs/judgement-flow.md](docs/judgement-flow.md) |
| 某天發生了什麼 | [cairn/LOG.md](cairn/LOG.md) |

上位規範是 `~/ghq/github.com/neknufelet/standards/BASELINE.md`（**只在 florian-coder**，
dker 沒有）。它的 9 條核心規則已 inline 在 CLAUDE.md，其餘 section 沒有——
所以 commit 格式、文件 frontmatter 這類規則要去上游看，或跑 `scripts/standards-check.py`。

## 知識往哪去

**判準是「誰在什麼時候需要它」，不是「它屬於哪一類」。** 分類會吵，時機不會。

| 什麼時候會需要 | 放哪 | 誰會發現沒做 |
|---|---|---|
| 每次開工都要知道 | `CLAUDE.md` | 沒有人 |
| 決定下一步時 | `NEXT.md` | `standards-check` 檢查行數上限 |
| 想知道某天發生了什麼 | `cairn/LOG.md` | `tests/test_log_freshness.py`（落後 git 超過一天就紅） |
| **下次跑同一支檢查、看到同一個數字時** | `tests/verified-findings.json` | 工具自己在超標時印出前例 |
| 換個領域也成立 | 畢業到 Obsidian `42_Cairn/lightrag/`（WebDAV 直寫） | 沒有人 |

**第四列最容易漏，漏掉的代價是重複查證。** 實例：同一個接地率的形狀查過兩次
（`K Muffler` 一次、`L Capsules` 一次）。沒有那一格會有第三次。

## 需要問，就是規則沒寫好

**「這個要記嗎／記到哪裡？」這個問題本身就是缺陷訊號。** 正確反應是補這條路由規則，
然後照著做——不是問一次、做一次、下次再問一次。

同理適用於任何反覆出現的判斷：同一個問題問過兩次，缺的不是答案，是規則。

## 動手前

- 先判斷使用者要的是「討論」還是「直接改」。說「先看一下／先評估」時給分析，
  不要直接重寫正式文件。
- 修正過去的判斷用追加更正，不要無聲覆蓋。
- 未確認的判斷不得寫成既成事實。
