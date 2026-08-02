#!/usr/bin/env bash
# 發警報到自架 ntfy（/opt/stacks/ntfy，手機 app 訂閱 http://100.87.88.7:9800 的 lightrag 主題）。
# 用法: notify.sh <標題> [內文...]
# NTFY_URL 從 .env 讀（沒設就用本機預設）。所有排程檢查的失敗都必須經過這裡——
# 通知管道只負責打斷人，紅綠狀態一律另外落地在 /data/rag/lightrag/checks/。
set -u
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
NTFY_URL="$(grep -s '^NTFY_URL=' "$REPO_DIR/.env" | cut -d= -f2-)"
NTFY_URL="${NTFY_URL:-http://127.0.0.1:9800/lightrag}"

title="${1:?用法: notify.sh <標題> [內文]}"
shift || true

curl -fsS --max-time 10 -H "Title: $title" -H "Priority: high" \
  -d "${*:-}" "$NTFY_URL" >/dev/null
