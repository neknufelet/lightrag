---
name: lightrag-search
description: Search the LightRAG acoustics knowledge base (20 parsed papers and textbook chapters) and answer strictly from retrieved context. Use for acoustics questions, claim verification, citation-grounded summaries, or when the user says 查知識庫 / 查論文. This skill uses HTTP API directly, never MCP.
---

# LightRAG Search

## Goal
從聲學知識庫取回有依據的原文，**只用取回的內容**回答。

## Backend API: direct HTTP only
There is **no MCP layer**.

- Primary base URL: `http://100.87.88.7:9700`
- Fallback base URL: `http://florian-dker:9700`
- Auth: none; Tailscale-only.

**為什麼是 9700 而不是 LightRAG 的 9621：** 9621 需要 `X-API-Key`，金鑰只在
伺服器上的 `.env` 裡 —— skill 複製到別台機器就讀不到，會靜默變成 401。
9700 代為保管金鑰並轉發，所以這個 skill 在**任何機器上都能直接用**。

**位址說明：** 兩個服務都只發佈到 Tailscale 位址（`100.87.88.7`），不綁 `0.0.0.0`。
- 在**伺服器本機**跑的 agent：`florian-dker` 解析成 `/etc/hosts` 的 `127.0.1.1`，
  那裡沒有服務 —— 所以主位址必須用 IP。
- 在**其他機器**跑的 agent：`florian-dker` 是 MagicDNS，指向同一個 Tailscale IP，
  兩者都通；fallback 在 IP 變動時仍能解析。


## Endpoint
`GET /kb/{ws}/search?query=<q>&chunks=<n>&chars=<n>&mode=<m>&format=md`

workspace 目前是 `acoustics_v155`。

## Workflow

```bash
curl -s -m 240 -G "http://100.87.88.7:9700/kb/acoustics_v155/search" \
  --data-urlencode "query=<問題>" \
  --data-urlencode "chunks=6" \
  --data-urlencode "chars=12000" \
  --data-urlencode "format=md"
```

輸出直接就是 Markdown：標題是查詢、接著相關實體、再來每個 chunk 一節（標題是來源文件）。
不需要暫存檔，也不需要 `jq`。

## 跨平台：不要用暫存檔、不要用 jq
所有端點加 `&format=md` 就直接回 Markdown，**指令在四種環境完全一樣**：

| 環境 | `/tmp` | `jq` |
|---|---|---|
| Linux / macOS | 有 | 通常要裝 |
| Git Bash (Windows) | 映射到 LOCALAPPDATA 的 Temp | 要裝 |
| **PowerShell** | **不存在，`-o /tmp/x.json` 直接失敗** | 要裝 |

所以一律用 `curl -s <url>` 讀 stdout，不要 `-o /tmp/...`、不要接 `jq`。


### 控制回傳量：用 `chunks` 與 `chars`，不要用 `top_k`

| 參數 | 預設 | 作用 |
|---|---|---|
| `chunks` | 6 | 最多回幾個片段 |
| `chars` | 12000 | 總字元上限，超過就截斷 |

`top_k` 是**圖譜檢索廣度**，不是回傳量，而且對原文的作用**方向相反**：
LightRAG 的 token 總額固定 30,000，圖譜與原文共用；`top_k` 開大，圖譜吃掉的
就多，**原文反而被擠掉**。實測（三個查詢，chunk 數）：

| `top_k` | muffler | porous absorber | room acoustics |
|---|---|---|---|
| 3 | 20 | 20 | 20 |
| 10 | 18 | 20 | 20 |
| 20 | 16 | 18 | 17 |
| 40 | 12 | 16 | 15 |

`mode` 同樣沒有節流效果（mix/local/global/naive 都是 14,000–21,000 tokens）。

**所以要控制量就只調 `chunks` 與 `chars`。** 這兩個由 :9700 處理：`chunks`
下傳成 LightRAG 真正的片段旋鈕，`chars` 在回傳前截斷。它們與 `top_k` 正交
——`top_k` 3/10/20/40 配同一個 `chunks`，拿到的原文完全一樣，只有實體清單長短不同。

一次搜尋預設約 3,000–4,000 tokens；答案不足時把 `chunks` 提到 12、
`chars` 提到 24000 再試一次。要多一點實體當線索時才動 `top_k`。

### mode 怎麼選（影響檢索策略，不影響量）
| mode | 適用 |
|---|---|
| `mix` | 預設。向量 + 圖譜，最穩 |
| `local` | 問某個具體概念的細節 |
| `global` | 跨文件的關聯、比較、綜述 |
| `naive` | 只要關鍵字命中的原文，不要圖譜 |

## 這個 KB 的已知限制（回答時要考慮）
- **羅馬數字下標 I / II / III 常被誤讀**成 `||`、`l`、`1`、`H`。四個獨立的檢查都指向這一點。看到區域下標時要存疑。
- **ρ 有時被讀成 p**，密度與壓力搞混過兩次。
- 方程式抽樣驗證：約 10% 的 MinerU LaTeX 與兩個視覺模型不一致。**引用公式時要說明它未逐條驗證。**
- 表格：`C Equivalent Networks` 有 6 張空表格已由雙模型交叉驗證後補上；其餘文件的空表格仍是空的。

## Output format
1. 直接回答
2. 依據 —— 引用 chunk 原文，標出 `doc`
3. 不確定的地方明講，尤其是公式與符號下標

## Guardrails
- Do not use MCP tools.
- 只用檢索到的內容回答。KB 裡沒有就說沒有，**不要用一般知識補**。
- 不要杜撰文件名、頁碼、公式。
- `100.87.88.7` 失敗就換 `florian-dker` 重試一次。
