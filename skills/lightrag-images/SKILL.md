---
name: lightrag-images
description: Retrieve figures/diagrams from the LightRAG acoustics KB, download them into the Obsidian vault, and return stable wiki-embeds. Use when the user asks for figures, charts, diagrams, original paper figures, or says 抽圖 / 找圖. This skill uses HTTP API directly, never MCP.
---

# LightRAG Images

## Goal
找到相關的圖，**下載進 Obsidian vault**，回傳穩定的 wiki-embed。

下載而不是連結：vault 要能離線看，而且圖片是你之後做語意整合的素材，
必須在本地。連 URL 的話離開 Tailscale 就變成破圖。

## Backend API: direct HTTP only
There is **no MCP layer**.

- Primary base URL: `http://100.87.88.7:9700`
- Fallback base URL: `http://100.87.88.7:9700`

（位址用 IP 而非主機名：這台機器上 `florian-dker` 解析成 127.0.1.1，本機的
agent 用主機名會連不到；IP 兩邊都成立。9700 不需要認證，所以這個 skill
複製到任何機器都能直接用。）
- Auth: none; Tailscale-only.

## Endpoints
- `GET /kb/{ws}/figures?query=<q>&top_k=<n>` — 依查詢找圖，回傳可讀別名與 caption
- `GET /kb/{ws}/images/{別名或雜湊名}` — 圖片本體
- `GET /kb/{ws}/doc/{檔名}` — 某一篇的完整圖片清單（`.figures[]`）

workspace 目前是 `acoustics_v155`。

## 檔名說明
別名格式是 `<文件代號>-p<頁碼>-<序號>.jpg`，例如：

```
c-equivalent-networks-p17-57.jpg
k-muffler-acoustics-p16-75.jpg
```

**一律用別名下載，不要用雜湊名** —— `![[098a9baf2dad….jpg]]` 在 Obsidian 裡沒有任何意義。

## Workflow

### 1. 找圖
```bash
curl -s -m 240 -G "http://100.87.88.7:9700/kb/acoustics_v155/figures" \
  --data-urlencode "query=<主題>" --data-urlencode "top_k=10" \
  -o /tmp/lr_figs.json

jq -r '.figures[] | "\(.alias)\t p\(.page)\t \(.doc)\t \(.caption)"' /tmp/lr_figs.json
```

若某篇的圖要全拿，改用 `doc` 端點的 `.figures[]`。

### 2. 下載進 vault
在 vault 內操作時用 vault 相對路徑。

```bash
mkdir -p "10_Research/LightRAG/assets"
alias="c-equivalent-networks-p17-57.jpg"

curl -s -m 30 -f \
  -o "10_Research/LightRAG/assets/$alias" \
  "http://100.87.88.7:9700/kb/acoustics_v155/images/$alias"
```

`-f` 是必要的 —— 沒有它，404 會被存成一個看起來像圖片的錯誤頁。

### 3. 嵌入
```markdown
![[10_Research/LightRAG/assets/c-equivalent-networks-p17-57.jpg]]
```

有 caption 就寫在圖下方一行，不要塞進 wiki-link 裡（Obsidian 的 `|` 是尺寸參數不是說明）。

## Guardrails
- Do not use MCP tools.
- 預設最多 5 張，不要洗版。
- 不要杜撰檔名、caption、頁碼 —— 全部來自 API 回傳。
- caption 常常是空的（MinerU 對 chart 型別多半沒抽到）。空的就只寫頁碼，不要自己編。
- 找不到圖時：放寬查詢或把 `top_k` 提高一次，然後如實回報，不要硬湊。
- `100.87.88.7` 失敗就換 `florian-dker` 重試一次。
