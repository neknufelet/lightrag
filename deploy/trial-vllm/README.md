---
title: 試驗用的第二個 LightRAG（LLM 指向遠端 vLLM）
date_created: 2026-08-09
date_modified: 2026-08-09
status: draft
kind: sop
supersedes: ""
superseded_by: ""
summary: "同樣的一切，只有 LLM 端點換成 Modal 上的 vLLM。用來比抽出來的圖譜，不是比吞吐。"
---

# 試驗用的第二個 LightRAG

**光比 tok/s 不夠——要比抽出來的東西。** 這個 stack 在不碰正式庫的前提下
從頭跑一次完整流程，讓「vLLM + FP8 抽得跟 llama.cpp + IQ4_XS 一樣好嗎」
變成可以並排看的兩張圖譜。

## 只有一個變數

```
共用   postgres、infinity（embedding + rerank）、work/parsed 的解析成果、
       prompts/ 的抽取規則、LightRAG 映像的同一個 digest
不同   LLM_BINDING_HOST → Modal 的 vLLM
       MAX_ASYNC 2 → 16（vLLM 才吃得下）
```

解析成果共用是刻意的：那一段兩邊完全相同，重跑只會多花 MinerU 的錢，
而且會讓「差異來自哪裡」多一個變數。

## 隔離靠三樣，缺一不可

| | |
|---|---|
| `WORKSPACE=acoustics_vllm` | Postgres 裡另一組資料，不會污染 `acoustics_v2` |
| `HOST_PORT=9631` | 兩個實例同時活著 |
| `RAG_STORAGE_DIR` | ⚠ **最容易漏的一個。** 裡面是 scan_spool（掃描佇列），共用會讓一邊撿到另一邊的掃描工作——**而且不會報錯**，只會是「文件進到錯的庫」 |

## `.env` 怎麼來的

不在 repo 裡。做法是**複製正式的那份，只覆蓋五個鍵**：

```
WORKSPACE / HOST_PORT / RAG_STORAGE_DIR / LLM_BINDING_HOST / LLM_BINDING_API_KEY / MAX_ASYNC
```

其餘（資料庫、embedding、rerank、API 金鑰）原封不動——比的是 LLM 端點，
不是別的。

⚠ 別用 `docker compose config` 檢查：它會把 `.env` 的值全部展開印出來
（`scripts/guard-command.py` 會擋）。

## 用法

```bash
ssh florian-dker 'cd /opt/stacks/lightrag-vllm && docker compose up -d'
# 把要試的 PDF 從 work/parsed 複製進 inputs/acoustics_vllm/，然後
# POST /documents/scan
```

從 `work/parsed` 複製而不是別處：那些正是 bundle 建立時的來源檔，
`is_bundle_valid` 才會通過而跳過 MinerU。

## 比什麼

跑完之後兩個 workspace 各跑一次 `graph-shape.py`，比**節點數、型別分佈、
泛用標籤殘留、大小寫變體**。吞吐已經量過了（見 `deploy/modal-llama/README.md`），
這裡要看的是品質。

## 收攤

```bash
ssh florian-dker 'cd /opt/stacks/lightrag-vllm && docker compose down'
# workspace 的資料留在 Postgres，要清另外用 SQL 刪 workspace='acoustics_vllm'
```
