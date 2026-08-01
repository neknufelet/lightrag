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

**為什麼是 9700 而不是 LightRAG 的 9621：** 9621 需要 `X-API-Key`，而金鑰只在
伺服器上的 `.env` 裡 —— skill 複製到別台機器就讀不到，會靜默變成 401。
9700 這支服務代為保管金鑰並轉發，所以這個 skill 在**任何機器上都能直接用**，
金鑰也不會散落在各台機器的檔案裡。

（位址用 IP 而非主機名：這台機器上 `florian-dker` 解析成 127.0.1.1，
本機的 agent 用主機名會連不到；IP 兩邊都成立。）

## Endpoint
`GET /kb/{ws}/search?query=<q>&top_k=<n>&mode=<m>`

workspace 目前是 `acoustics_v155`。

## Workflow

```bash
curl -s -m 240 -G "http://100.87.88.7:9700/kb/acoustics_v155/search" \
  --data-urlencode "query=<問題>" \
  --data-urlencode "top_k=10" \
  --data-urlencode "mode=mix" \
  -o /tmp/lr_search.json

jq -r '.chunks[] | "[\(.doc)]\n\(.content[0:500])\n"' /tmp/lr_search.json
jq -r '.entities | join(", ")' /tmp/lr_search.json
```

### mode 怎麼選
| mode | 適用 |
|---|---|
| `mix` | 預設。向量 + 圖譜，最穩 |
| `local` | 問某個具體概念的細節 |
| `global` | 跨文件的關聯、比較、綜述 |
| `naive` | 只要關鍵字命中的原文，不要圖譜 |

`top_k` 預設 10。不夠再提到 20 重試**一次**，不要一開始就開大 —— context 會被灌爆。

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
