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
- Fallback base URL: `http://100.87.88.7:9700`

（位址用 IP 而非主機名：這台機器上 `florian-dker` 解析成 127.0.1.1，本機的
agent 用主機名會連不到；IP 兩邊都成立。9700 不需要認證，所以這個 skill
複製到任何機器都能直接用。）
- Auth: none; Tailscale-only.

（9700 是 `kbapi.py`，補 LightRAG 沒有的唯讀端點。查詢仍走 9621。）

## Endpoints
- `GET /kb/{ws}/docs` — 有哪些文件、各有幾張圖
- `GET /kb/{ws}/doc/{檔名}` — 單篇結構

workspace 目前是 `acoustics_v155`。

## Workflow

```bash
# 1. 先看有哪些文件
curl -s -m 30 "http://100.87.88.7:9700/kb/acoustics_v155/docs" | jq -r '.documents[].doc'

# 2. 取某一篇（檔名要 URL encode）
curl -s -m 60 -G "http://100.87.88.7:9700/kb/acoustics_v155/doc/C Equivalent Networks.pdf" \
  --data-urlencode "" -o /tmp/lr_doc.json

jq '{doc, items, tables: (.tables|length), equations: (.equations|length), figures: (.figures|length)}' /tmp/lr_doc.json
jq -r '.headings[] | "p\(.page)  \(.text)"' /tmp/lr_doc.json
jq -r '.equations[] | "p\(.page) #\(.index)  \(.latex)"' /tmp/lr_doc.json
```

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
