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
- Fallback base URL: `http://florian-dker:9700`

**9700 不需要認證，所以這個 skill 複製到任何機器都能直接用。**

**位址說明：** 兩個服務都只發佈到 Tailscale 位址（`100.87.88.7`），不綁 `0.0.0.0`。
- 在**伺服器本機**跑的 agent：`florian-dker` 解析成 `/etc/hosts` 的 `127.0.1.1`，
  那裡沒有服務 —— 所以主位址必須用 IP。
- 在**其他機器**跑的 agent：`florian-dker` 是 MagicDNS，指向同一個 Tailscale IP，
  兩者都通；fallback 在 IP 變動時仍能解析。

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
  --data-urlencode "format=md"
```

回傳每張圖一行：`` `別名` 　文件　p頁碼 `` ＋ caption。直接讀 stdout，不用暫存檔也不用 jq。

若某篇的圖要全拿，改用 `doc?format=md` 的「圖片」那一節。

## 跨平台：不要用暫存檔、不要用 jq
所有端點加 `&format=md` 就直接回 Markdown，**指令在四種環境完全一樣**：

| 環境 | `/tmp` | `jq` |
|---|---|---|
| Linux / macOS | 有 | 通常要裝 |
| Git Bash (Windows) | 映射到 LOCALAPPDATA 的 Temp | 要裝 |
| **PowerShell** | **不存在，`-o /tmp/x.json` 直接失敗** | 要裝 |

所以一律用 `curl -s <url>` 讀 stdout，不要 `-o /tmp/...`、不要接 `jq`。


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
