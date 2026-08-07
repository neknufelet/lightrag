---
title: 知識與文件放哪 — 路由判準
date_created: 2026-08-07
date_modified: 2026-08-07
status: accepted
kind: governance
supersedes: "AGENTS.md（2026-08-07 之前的版本，該檔已縮成純指標）"
superseded_by: ""
summary: "「這個東西該放哪」的唯一判準。從 AGENTS.md 搬出來——那個檔要縮成純指標，內容不得無聲消失。"
---

# 知識與文件放哪

**為什麼從 `AGENTS.md` 搬出來**：`AGENTS.md` 自己第 6 行寫著「只放路標，不重複規則——
同一條規則有兩個地方就會漂移，而漂移不報錯」，但它自己就長出了第二份導航表，而且
2026-08-07 實測**兩份已經各缺對方的項目**（`AGENTS.md` 沒有 `docs/hard-rules.md`，
`CLAUDE.md` 沒有 `docs/judgement-flow.md`）。後果是：用 codex／opencode 的人只讀
`AGENTS.md`，**從來不會被告知有那 8 條鐵則**——而鐵則自己標著「動 `scripts/pp/` 之前必讀」。

所以 `AGENTS.md` 縮成純指標，判準搬到這裡。**這是唯一的一份。**

## 上位規範在哪

上位規範是 `~/ghq/github.com/neknufelet/standards/BASELINE.md`（**只在 florian-coder**，
dker 沒有）。它的 9 條核心規則已 inline 在 `CLAUDE.md`，其餘 section 沒有——
所以 commit 格式、文件 frontmatter 這類規則要去上游看，或跑 `scripts/standards-check.py`。

## `cairn/` 還是 `docs/`？判準是「知識還是資產」

**這一條存在的理由**：2026-08-07 PO 問「LOG 在 `cairn/`、NEXT 在 `docs/`，這一定會出事」。
判準原本沒寫下來，所以他必須問——而**需要問就是規則沒寫好**。

判準來自 Cairn 自己的 maintenance 規則：「工程資產留在 `cairn/` 外面，只有**關於**資產的
知識可以進 `cairn/`」。

| 是什麼 | 放哪 | 例 |
|---|---|---|
| **資產**：程式或流程會消費它 | `docs/`、`tests/`、程式樹 | `docs/NEXT.md`（待辦）、`docs/rebuild-checklist.md`（契約）、`docs/KNOWN_ISSUES.md`、`tests/*.json`（基準）、設計文件 |
| **知識**：為什麼這樣做、踩了什麼坑、可複用的模式 | `cairn/` | `cairn/LOG.md`（時間軸）、`cairn/<topic>.md`（當前真相） |
| **一次性的裁決＋當時的理由**（凍結，不改） | `docs/decisions/` | ADR。與 `cairn/<topic>.md` 的差別：ADR 是快照，topic 是會就地更新的當前真相 |

所以 `LOG.md` 在 `cairn/`、`NEXT.md` 在 `docs/` **不是矛盾**——一個是知識、一個是資產。
**設計文件也是資產**（實作會照著它做），所以進 `docs/`，不進 `cairn/`。

真正會出事的是「同一類東西兩個地方」。**本專案已踩五次**：文件地圖兩份、版本史兩份、
commit type 三處、導航表兩份（2026-08-07 發現）、三個 lightrag skill 在 repo 與
`AI_TOOLS/skills/common/` 各一份（2026-08-07 發現，當時內容仍逐位元相同）。

⚠ **`cairn/<topic>.md` 截至 2026-08-07 是 0 個。** Cairn 的核心機制（結論沉澱成當前
真相）從來沒被啟用過，只有流水帳在跑。而 maintenance 規則明說「LOG 只放摘要與指標，
結論放 topic」——本專案一直反過來做。

## Cairn 的維護規則（做完事之後要做的）

規則本體在 `project-cairn` skill 的 `references/maintenance.md`。**這裡是它在本專案的
落地版**——之前它沒有落地在任何一個檔案裡，只存在於 skill 內，所以沒被讀到過。

- **每有實質進展，在 `cairn/LOG.md` 最上面加一則**（逆時序，最新在上，每則 ≤ 20 行）：
  發生了什麼、決定了什麼、細節的指標。執行者是 `tests/test_log_freshness.py`。
- **出現穩定的結論、決策、教訓或可複用模式時，更新或建立 `cairn/<topic>.md`。**
  踩過的坑進對應 topic note 的教訓區，`contains` 加上 `lesson`。
  **不要開一個大雜燴的 `PITFALLS.md`**——沒有 topic note 就建一個。
- **LOG 不放長結論。** LOG 只放摘要與指標，結論住在 topic note 裡。
- **更正舊結論就地改 topic note，並在 LOG 加一條指向該次修訂的指標。** 不得無聲覆蓋。
- **工程資產留在 `cairn/` 外面**，只有關於資產的知識可以進去（見上一節的判準）。

## 知識往哪去

**判準是「誰在什麼時候需要它」，不是「它屬於哪一類」。** 分類會吵，時機不會。

| 什麼時候會需要 | 放哪 | 誰會發現沒做 |
|---|---|---|
| 每次開工都要知道 | `CLAUDE.md` | 沒有人 |
| 決定下一步時 | `docs/NEXT.md` | `standards-check` 檢查行數上限 |
| 想知道某天發生了什麼 | `cairn/LOG.md` | `tests/test_log_freshness.py`（落後 git 超過一天就紅） |
| **下次跑同一支檢查、看到同一個數字時** | `tests/verified-findings.json` | 工具自己在超標時印出前例 |
| 換個領域也成立 | 畢業到 Obsidian `42_Cairn/lightrag/`（WebDAV 直寫） | 沒有人 |

**第四列最容易漏，漏掉的代價是重複查證。** 實例：同一個接地率的形狀查過兩次
（`K Muffler` 一次、`L Capsules` 一次）。沒有那一格會有第三次。

## 只有兩種東西保證會被讀到

**「放哪裡」跟「會不會被讀到」是兩件事。** 會自動載入的只有三個：`CLAUDE.md`
（Claude Code 每次開 session）、`AGENTS.md`（codex／opencode）、以及被觸發的 skill
（連同它的 `description`）。**`docs/` 底下沒有任何東西會自動被讀。**

所以要確定一份東西真的生效，只有兩條路：

1. **搬進自動載入的檔**——代價是每次開 session 都付它的長度。這就是 `CLAUDE.md`
   被砍到只剩 9 條的原因。
2. **寫成程式會檢查的斷言**——違反時有東西會紅。

其餘都是希望，不是保證。這就是 `docs/rebuild-checklist.md` 結尾那句判準的另一面：
**「任何規則要進規則區，先回答『違反時誰會發現』。答不出來就不算規則。」**

## 需要問，就是規則沒寫好

**「這個要記嗎／記到哪裡？」這個問題本身就是缺陷訊號。** 正確反應是補這條路由規則，
然後照著做——不是問一次、做一次、下次再問一次。

同理適用於任何反覆出現的判斷：同一個問題問過兩次，缺的不是答案，是規則。

## 動手前

- 先判斷使用者要的是「討論」還是「直接改」。說「先看一下／先評估」時給分析，
  不要直接重寫正式文件。
- 修正過去的判斷用追加更正，不要無聲覆蓋。
- 未確認的判斷不得寫成既成事實。
