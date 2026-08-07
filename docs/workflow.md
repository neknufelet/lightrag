---
title: 執行方針與驗收路由
date_created: 2026-08-07
date_modified: 2026-08-07
status: draft
kind: sop
supersedes: ""
superseded_by: ""
summary: "多 worker 分工與票別路由。PO 2026-08-07 改過分工，但整套流程要在需求釘死之後重新決定要不要用。"
---

# 執行方針與驗收路由

> ⚠️ **draft。** PO 2026-08-07 改過分工（實作走 codex luna、審查回 Claude Opus），
> 但**整套票別流程要不要用，等需求釘死之後再決定**——2026-08-07 一整天完全沒用到任何
> worker，實際有效的迴路是「Claude 做 → PO 看 → PO 指出錯誤」，比六站流程快得多。

## 執行方針與驗收路由

| 角色 | 職責 |
|---|---|
| 你（product owner） | 決策、範圍確認、驗收 |
| Claude（opus，指揮） | 技術決策討論、出單、調度、對抗驗收、docs |
| codex luna -max| code 實作（受工單指派） |
| Claude Opus | 單審與終審 |
| deepseek | 對抗找碴（路徑觸發） |

執行模式：**線性**，不多開平行線。Workflow 是品質工具（對抗驗證、skeptic、
回歸閘），不是人力並行化。

### 一般票（三站＋回程）

```
opus 出單 → codex luna (effort max) 實作 → opus 終審 → 【驗證回程：dker 實跑】
```

### 重票（五站＋回程）

```
fable 設計成單 → opus 單審 → codex luna max 實作
  → deepseek 找碴（碰 pp/rules 或閘門判準時觸發）
  → 終審：opus（追溯 需求→單→diff→輸出 + 驗證）
  → 【驗證回程：dker 實跑】
```

**重票觸發清單（命中任一即重票，不由指揮心證）**

1. 動 `scripts/pp/rules/**` 或任何**閘門判準**（門檻、三態界線、`SYMBOLIC_RATIO`）
2. 動 `compat-check.py` 的 `VERIFY-1-A##` 契約斷言
3. **會改變 canary 基準數字**
4. 動 `.env` 的鍵、`compose.yaml`、或任何部署契約
5. 動既有測試語義或體檢表閘門定義
6. **碰資料**：刪除、`reindex`、`apply --commit`、任何寫進 `/data` 或 DB 的操作
7. diff > 200 行

**有疑義＝重票。** 第 6 條是本專案特有的——這裡的資料操作**不可逆**，
而且沒有備份時代的教訓還很新。

**綁住指揮的兩條**：① 指揮**只能升檔、不得降檔**；判為一般票時必須寫明沒有
命中清單哪一條。② 終審**任一方 BLOCK 即不過**，指揮不得推翻。

**沒有人驗自己**：fable 寫設計⇒不進終審；指揮出單調度⇒不寫設計、不當終審
（終審的 Anthropic 席是**冷啟動分身 opus-cold**）。

### worker 速查與呼叫法

**全部 worker CLI 只在 florian-coder。** dker 上只有 `claude`。

| 角色 | worker | 模型 | 池子 |
|---|---|---|---|
| 指揮／對 PO 窗口 | opus | 本 session | anthropic ⚠ |
| 重票設計成單 | fable | Agent tool subagent | anthropic ⚠ |
| 實作 | codex terra | `gpt-5.6-luna` max| openai |
| 單審＋終審 |  | `gpt-5.6-sol` xhigh | openai |
| 終審 Anthropic 席 | opus-cold | Agent tool **冷啟動** subagent | anthropic ⚠ |
| 對抗找碴 | deepseek | `deepseek/deepseek-v4-pro`（opencode） | deepseek |
| 長文審閱／第二意見 | codex luna | `gpt-5.6-luna` xhigh | openai |

```bash
# 實作（模型必帶，否則吃 ~/.codex/config.toml 的全域預設＝sol）
timeout <N> codex exec -C <repo> -s workspace-write \
  -m gpt-5.6-terra -c model_reasoning_effort="xhigh" \
  -o <scratch>/last.txt "$(cat ticket.md)" </dev/null > <scratch>/run.log 2>&1

# 審查（唯讀）
timeout <N> codex exec -C <repo> -s read-only \
  -m gpt-5.6-sol -c model_reasoning_effort="xhigh" \
  -o <scratch>/verdict.txt "$(cat brief.md)" </dev/null > <scratch>/run.log 2>&1

# 對抗找碴
timeout <N> opencode run -m deepseek/deepseek-v4-pro "<PROMPT>" > <scratch>/out.txt 2>&1
```

⚠ **實測踩過的坑**：① `--ask-for-approval` 在 `codex exec` 不存在。
② 本機 shell 是 zsh，`${PIPESTATUS[0]}` 會靜默吃掉 exit code——用 `${pipestatus[1]}` 或別接 pipe。
③ 兩支的 stdout 都有 ANSI＋banner，機器解析用 `-o <FILE>`。
④ `~/.codex/config.toml` 全域是 `gpt-5.6-sol` ＋ `danger-full-access`，
**不帶 `-m`／`-s` 的呼叫都會是 sol ＋ 全機存取**。
⑤ 審查席要能查證就給它 repo（`-C <repo>`）＋額外材料目錄（`--add-dir`）——
只給摘要它只能回「判不準」，實測第一輪就是這樣。
⑥ **prompt 超過 128 KiB 不能當參數傳，要走 stdin：`codex exec - < prompt.txt`。**
上面那個 `"$(cat ticket.md)"` 的慣用寫法對大題本會死在
`argument list too long`。**不是 `ARG_MAX`**（那是 2 MB），是 Linux 的
**單一參數上限 `MAX_ARG_STRLEN` = 128 KiB**。而且錯誤訊息指向 `timeout`
不是 codex（`run:1: argument list too long: timeout`），很容易誤判成別的問題。
實測 2026-08-03：149,890 字元的題本直接失敗，改 stdin 後正常。

**額度紀律**：Anthropic 池是唯一吃緊的。重活優先擺 OpenAI／DeepSeek 池；
親跑驗證幾乎不花 token（綠的時候只回幾行），貴的是讀 diff 與長推理。

---

