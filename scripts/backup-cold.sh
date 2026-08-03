#!/usr/bin/env bash
# 索引本體的冷備份：Postgres 與 Neo4j 的**資料目錄**。
#
# 為什麼是冷備份而不是 pg_dump／neo4j-admin：
#   跑著的資料庫，資料目錄裡的檔案是不同時間點的碎片，直接抄回來可能起不來、
#   或起得來但資料是壞的。**停掉之後檔案就一致了**，抄檔案就是有效備份，
#   而且還原只是「停掉、換回目錄、啟動」——不需要任何特殊工具，也不需要
#   一支沒人測過的還原腳本（沒驗過的還原路徑等於沒有備份）。
#   Neo4j 是 community 版，本來就不支援線上實體備份、也不支援 STOP DATABASE
#   （實測 2026-08-03：Unsupported administration command），所以停機不是選擇題。
#
# 為什麼中間要先複製到本地再上傳：
#   停機時間 = restic 上傳時間的話，16.6 GB 傳到 Google Drive 要半小時。
#   先本機複製（實測 896 MB/s，約 20 秒）再啟服務，**停機就與上傳速度脫鉤**，
#   實測總停機約 1 分鐘。
#
# 用法：backup-cold.sh [--keep-stage]
set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
STAGE=/data/rag/coldstage
SRC=(/data/rag/postgres_data /data/rag/neo4j_data)
# 停的順序：先停用它們的，再停資料庫。啟動反過來。
DEPS=(kbapi-acoustics_v2 lightrag-acoustics_v2 deeptutor-v4-worker
      deeptutor-v4-backend deeptutor-v4-frontend)
DBS=(deeptutor-v4-neo4j deeptutor-v4-postgres)
TS=$(date +%Y%m%dT%H%M%S)
FAILED=""

log() { printf '%s  %s\n' "$(date +%H:%M:%S)" "$*"; }
fail() { FAILED="${FAILED}${FAILED:+; }$*"; log "！$*"; }

start_all() {
  # **無論如何都要跑**：半路失敗時最糟的結果是服務停著沒人知道。
  log "啟動服務（反序）"
  for c in "${DBS[@]}"; do docker start "$c" >/dev/null 2>&1 && log "  起 $c"; done
  for i in $(seq 1 40); do
    docker exec deeptutor-v4-postgres pg_isready -U deeptutor >/dev/null 2>&1 && break
    sleep 3
  done
  for c in "${DEPS[@]}"; do docker start "$c" >/dev/null 2>&1 && log "  起 $c"; done
}
trap start_all EXIT INT TERM

# ── 1. 停 ─────────────────────────────────────────────────────────────
log "停服務"
for c in "${DEPS[@]}" "${DBS[@]}"; do
  docker stop -t 30 "$c" >/dev/null 2>&1 && log "  停 $c" || fail "停不掉 $c"
done
[ -n "$FAILED" ] && { log "有容器停不掉，不做複製（資料可能不一致）"; exit 3; }

# ── 2. 本機複製（停機窗只有這一段）───────────────────────────────────
log "複製到 $STAGE"
sudo rm -rf "$STAGE"
sudo mkdir -p "$STAGE"
T0=$(date +%s)
for d in "${SRC[@]}"; do
  sudo cp -a "$d" "$STAGE/" || fail "複製失敗 $d"
done
sudo chmod -R a+rX "$STAGE" 2>/dev/null
T1=$(date +%s)
log "複製完成，耗時 $((T1-T0)) 秒"

# ── 3. 啟回（trap 也會做，這裡先做好縮短停機）─────────────────────
trap - EXIT INT TERM
start_all
log "服務已恢復"

[ -n "$FAILED" ] && { log "複製階段有失敗：$FAILED"; "$REPO_DIR/scripts/notify.sh" \
  "冷備份失敗（服務已恢復）" "$FAILED"; exit 4; }

# ── 4. 驗複本 ────────────────────────────────────────────────────────
# 只驗「有沒有抄到東西」。深度驗證是「還原一份起得來」，那是 BACKUP-3 的事。
for d in "${SRC[@]}"; do
  b=$(basename "$d")
  n=$(sudo find "$STAGE/$b" -type f 2>/dev/null | wc -l)
  sz=$(sudo du -sm "$STAGE/$b" 2>/dev/null | cut -f1)
  log "  $b: $n 個檔、${sz} MB"
  [ "$n" -lt 10 ] && fail "$b 檔數只有 $n，不像完整的資料目錄"
done
[ -n "$FAILED" ] && { "$REPO_DIR/scripts/notify.sh" "冷備份複本可疑" "$FAILED"; exit 5; }

# ── 5. 上傳（服務已在跑，慢沒關係）──────────────────────────────────
# 用 backrest 容器裡的 restic：它已有 rclone 設定與 repo 金鑰，不必在宿主再裝一套。
# backrest 把 /data 唯讀掛成 /userdata/data，所以 $STAGE 在容器內看得到。
log "restic 上傳"
PW=$(docker exec backrest sh -c 'cat /config/config.json' \
     | python3 -c 'import sys,json;d=json.load(sys.stdin);print(next(r["password"] for r in d["repos"] if r["id"]=="rag-db"))') \
     || { fail "讀不到 restic 金鑰"; }
if [ -n "${PW:-}" ]; then
  docker exec -e RESTIC_PASSWORD="$PW" backrest \
    restic -r rclone:gdrive_LIH:restic_rag_db backup \
    --tag cold-db --tag "ts:$TS" --host florian-dker \
    "/userdata${STAGE}" 2>&1 | tail -6 || fail "restic 上傳失敗"
else
  fail "restic 金鑰是空的"
fi

# ── 6. 驗快照真的在 repo 裡，然後才清暫存 ───────────────────────────
# **清理必須在驗證之後**：驗不過就把複本留著，否則這一輪等於什麼都沒有。
if [ -z "$FAILED" ]; then
  got=$(docker exec -e RESTIC_PASSWORD="$PW" backrest \
        restic -r rclone:gdrive_LIH:restic_rag_db snapshots --tag "ts:$TS" --json 2>/dev/null \
        | python3 -c 'import sys,json;print(len(json.load(sys.stdin)))' 2>/dev/null || echo 0)
  if [ "$got" -ge 1 ]; then
    log "快照已在 repo（tag ts:$TS）"
    [ "${1:-}" = "--keep-stage" ] || { sudo rm -rf "$STAGE"; log "暫存已清"; }
  else
    fail "repo 裡找不到剛才那個快照 —— 暫存保留在 $STAGE"
  fi
fi

if [ -n "$FAILED" ]; then
  "$REPO_DIR/scripts/notify.sh" "冷備份失敗" "$FAILED"
  log "FAILED: $FAILED"
  exit 1
fi
log "完成"
