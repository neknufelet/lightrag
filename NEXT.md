---
title: NEXT — 接下來做什麼
date_created: 2026-06-20
date_modified: 2026-08-07
status: living
kind: sop
supersedes: ""
superseded_by: ""
summary: "當前待辦的唯一 SSOT。2026-08-07 系統清空，需求還沒釘死，所以這裡只有一件事。"
---

# NEXT — 接下來做什麼

## 狀態：已清空，需求還沒釘死

2026-08-07 把 dker 上的容器與資料全部移除（保留 `records` 183 檔、`checks` 32 檔），
repo 刪掉 9,179 行歷史文件。凍結點在 tag `archive/pre-rebuild-20260807`。

**下一步只有一件：把需求問清楚。** 用 `/grill-me` 拷問，不要直接動工——
這個專案過去的問題就是需求從來沒釘死，一路在補。

釘死之前不要排待辦。釘死之後這裡才會有東西。

## 唯一的技術前置

- [ ] 確認 LightRAG v1.5.6 怎麼設定「用 PostgreSQL 存圖」。發布說明沒寫，
      `LIGHTRAG_GRAPH_STORAGE=PGTableGraphStorage` 是推測 `(未驗)`。
      這件事決定新的 compose 能不能拿掉 Neo4j

## 現在手上有什麼

| | |
|---|---|
| 規則 | `scripts/pp/rules/` 5 支，一份一份文件逼出來的 |
| 工具 | `scripts/` 26 支（`compat-check` 124 項契約斷言是為升級寫的） |
| 人工裁定 | `verdicts/` 227 檔，不可再生，在 GitHub 上 |
| 新環境該長什麼樣 | [docs/rebuild-checklist.md](docs/rebuild-checklist.md) 13 條，8 條沒有執行者 |
| 決策的理由 | [docs/decisions/](docs/decisions/) 4 個 ADR |
| 知道但沒處理的問題 | [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md) |
| 秘密鍵去哪拿 | `.env.example` 開頭（不備份秘密本身） |

其他去處：鐵則／契約／座標 → [CLAUDE.md](CLAUDE.md)；某天發生了什麼 →
[cairn/LOG.md](cairn/LOG.md)。
