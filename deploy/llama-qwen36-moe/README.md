---
title: llama-qwen36-moe：怎麼停、怎麼開回來
date_created: 2026-08-09
date_modified: 2026-08-09
status: accepted
kind: sop
supersedes: ""
superseded_by: ""
summary: "2026-08-09 抽取改走 DeepSeek 之後這台就閒著了。停它省電，但復原一定要用 docker start ——同目錄的 compose.yaml 是謄本不是出生證明，用它 up 會是一次沒驗過的部署。"
---

# llama-qwen36-moe：怎麼停、怎麼開回來

**跑在 florian-coder（本機）**，兩張 RTX 3060。2026-08-09 之前它是抽取用的 LLM，
之後抽取改走 DeepSeek 官方 API，這台就閒著了。

---

## ⚠ 復原用 `docker start`，不要用 `docker compose up`

同目錄的 `compose.yaml` 是 2026-08-03 從 `docker inspect` **逐欄謄寫**的現況副本，
**從來沒有被用來啟動過任何容器**。跑著的那個是 `docker run` 起來的，參數只活在
容器自己的 config 裡。

```bash
docker start llama-qwen36-moe      # ✅ 用原本的參數起回來
docker compose up -d               # ⚠ 換啟動路徑＝一次真正的部署，沒驗過
```

⇒ **只要不 `docker rm`，參數就還在。** 停掉不會弄丟任何東西。

---

## 停

```bash
docker stop llama-qwen36-moe
```

## 開

```bash
docker start llama-qwen36-moe
sleep 30
docker ps --filter name=llama-qwen36-moe --format '{{.Names}}\t{{.Status}}'
```

`healthy` 才算起來了。模型 35B、載入要一段時間，剛 `start` 完馬上打會連不上。

## 確認它真的在服務

```bash
docker logs llama-qwen36-moe 2>&1 | grep -m1 n_slots     # 開幾路併發
docker logs --tail 3 llama-qwen36-moe 2>&1 | grep launch_slot_   # 有沒有在收請求
```

⚠ **不要 `docker inspect` 印整條 `Cmd`**：`--api-key` 的值在上面，
`scripts/guard-command.py` 會擋（2026-08-08 因此外洩過一次）。

---

## 停掉之後什麼會壞、什麼不會

| | 影響 |
|---|---|
| 抽取新文件 | ✅ 不受影響 —— 2026-08-09 起走 DeepSeek |
| 查詢（**自帶關鍵詞**） | ✅ 不受影響 —— 那條路 0 次 LLM 呼叫，實測過 |
| 查詢（**沒自帶關鍵詞**） | ❌ **會壞**，2026-08-09 停機後實測：`HTTP 500` |
| 眼睛 A（表格轉錄） | 看設定：`PP_EYE_A_*` 指向 OpenRouter 就不受影響；沒設會 fallback 回 `LLM_BINDING_*` |

⇒ **所以停它之前，先確認 `lightrag-search` skill 有在送 `hl_keywords`／`ll_keywords`。**
回應裡的 `keywords.supplied` 會告訴你。

⚠ **其他專案有沒有打這個埠沒查證過**（`compose.yaml` 的檔頭 2026-08-03 就記著
這件事，至今仍未查）。停之前值得先看一眼有沒有別人在連：

```bash
docker logs --since 10m llama-qwen36-moe 2>&1 | grep -c launch_slot_
```

非 0 表示最近十分鐘還有人在用它 —— 那個人不一定是 lightrag。

---

## 什麼時候會需要開回來

- 想改回本機抽取（`.env` 的 `LLM_BINDING_HOST` 指回 `http://100.71.26.77:8080/v1`）
- 眼睛 A 要用本機那顆（它帶 `--mmproj`，看得見圖）
- 對照量測：拿它當基準跟雲端的比

⚠ 改回本機抽取的話，`.env.example` 裡那段 `-c ÷ --parallel` 的乘除關係**又會生效**
（`MAX_TOTAL_TOKENS` 必須重算）。那段刻意留著沒刪就是為了這一刻。
