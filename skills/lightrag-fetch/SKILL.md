---
name: lightrag-fetch
description: Pull the full structure of one specific document from the LightRAG acoustics KB — headings, tables, equations, figure list. Use when the user names a paper/chapter and wants its contents, structure, equations, or an overview rather than a cross-document search. This skill uses HTTP API directly, never MCP.
---

# LightRAG Fetch

## Goal
拿**單一篇**的結構化內容：章節、表格、方程式、圖片清單。

跟 `lightrag-search` 的分工：search 是跨文件找片段，fetch 是鎖定一篇看全貌。
不知道要哪一篇時先 search，看到 `file_path` 再 fetch。

## Backend API: direct HTTP only
There is **no MCP layer**.

- Primary base URL: `http://100.87.88.7:9700`
- Fallback base URL: `http://florian-dker:9700`

**9700 不需要認證，所以這個 skill 複製到任何機器都能直接用。**

**位址說明：** 兩個服務都只發佈到 Tailscale 位址（`100.87.88.7`），不綁 `0.0.0.0`。
- 在**伺服器本機**跑的 agent：`florian-dker` 解析成 `/etc/hosts` 的 `127.0.1.1`，
  那裡沒有服務 —— 所以主位址必須用 IP。
- 在**其他機器**跑的 agent：`florian-dker` 是 MagicDNS，指向同一個 Tailscale IP，
  兩者都通；fallback 在 IP 變動時仍能解析。

- Auth: none; Tailscale-only.

（9700 是 `kbapi.py`，補 LightRAG 沒有的唯讀端點。查詢仍走 9621。）

## Endpoints
- `GET /kb/{ws}/docs` — 有哪些文件、各有幾張圖
- `GET /kb/{ws}/doc/{檔名}` — 單篇結構

workspace 是 `acoustics_v2`。

**打錯 workspace 會回 400，不會靜靜回錯庫的答案。** 這道擋板是必要的：
`search` 端點不看 URL 裡的 workspace（它走 `.env` 指定的 LightRAG），
但檔案類端點看——兩者對同一個 URL 的解讀不一致，不擋就會回一半對的東西。

## Workflow

```bash
# 1. 先看有哪些文件
curl -s -m 30 "http://100.87.88.7:9700/kb/acoustics_v2/docs?format=md"

# 2. 取某一篇（檔名有空格，用 -G --data-urlencode 讓 curl 自己編碼）
curl -s -m 60 -G "http://100.87.88.7:9700/kb/acoustics_v2/doc/C Equivalent Networks.pdf" \
  --data-urlencode "format=md"
```

回傳的 Markdown 分四節：章節、表格（標「已修補」）、方程式、圖片（別名 + caption）。

## 跨平台：不要用暫存檔、不要用 jq
所有端點加 `&format=md` 就直接回 Markdown，**指令在四種環境完全一樣**：

| 環境 | `/tmp` | `jq` |
|---|---|---|
| Linux / macOS | 有 | 通常要裝 |
| Git Bash (Windows) | 映射到 LOCALAPPDATA 的 Temp | 要裝 |
| **PowerShell** | **不存在，`-o /tmp/x.json` 直接失敗** | 要裝 |

所以一律用 `curl -s <url>` 讀 stdout，不要 `-o /tmp/...`、不要接 `jq`。


## 回傳裡的品質欄位
- `tables[].repaired: true` — 這張表是空的、已由雙模型交叉驗證後補上。可信度較高。
- `tables[].repaired: false` 且 caption 有內容但表格是空的 — **那張表的內容遺失了**，不要假裝它有資料。

## 注意
`doc` 端點**不回全文**。N Flow Acoustics 有 66,000 字元，塞進 context 只會擠掉別的。
要正文請用 `lightrag-search` 針對章節標題再查一次。

## Guardrails
- Do not use MCP tools.
- 不要杜撰章節、方程式、頁碼。
- 引用方程式時提醒使用者：MinerU 的 LaTeX 抽樣驗證有約 10% 與視覺模型不一致。
- `100.87.88.7` 失敗就換 `florian-dker` 重試一次。
