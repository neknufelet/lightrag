#!/usr/bin/env bash
# 冷備份：把整個 ${LIGHTRAG_DB_ROOT} 抄進 restic。
#
# 2026-08-03 之前這件事很麻煩：我們的資料寄住在 DeepTutor 的 Postgres 與 Neo4j
# 裡，靠 workspace 欄位與 label 跟別人分開。那時要「只備我們的」得用 pg_dump
# （因為 Postgres 的 global／pg_xact／pg_wal 是全叢集共用的，只抄我們那個
# base/<oid> 目錄還原不回來），Neo4j 更是連目錄層級都分不開。
#
# 搬到自己的實例之後，這裡就只剩一個目錄。**這是把儲存獨立出來最直接的好處。**
#
# 為什麼要停機：跑著的資料庫，資料目錄裡的檔案是不同時間點的碎片，抄回來可能
# 起不來、或起得來但資料是壞的。停掉之後檔案就一致，抄檔案就是有效備份，
# 而且還原只是「停掉、換回目錄、啟動」——不需要任何特殊工具，也不需要一支
# 沒人測過的還原腳本（沒驗過的還原路徑等於沒有備份）。
#
# 為什麼中間要先複製到本地再上傳：停機時間 = restic 上傳時間的話，傳到
# Google Drive 要很久。先本機複製（實測 896 MB/s）再啟服務，**停機就與上傳
# 速度脫鉤**。
#
# 用法：backup-cold.sh [--keep-stage] [--force]
#
# **沒有新的抽取成果就不跑**（2026-08-03 加）：這支會停服務，而停機是它唯一真正的
# 成本——restic 是內容去重的，重複上傳同樣的資料只增加 0 位元組（實測：兩份快照
# `restic diff` 回 0 new / 0 removed）。所以「閒著也每天停一次」是純浪費。
# 判斷依據是**資料庫的內容指紋**，不是時鐘；`--force` 可強制跑。
set -uo pipefail

KEEP_STAGE=0; FORCE=0
for arg in "$@"; do
  case "$arg" in
    --keep-stage) KEEP_STAGE=1 ;;
    --force)      FORCE=1 ;;
    *) echo "未知參數：$arg（可用 --keep-stage --force）" >&2; exit 2 ;;
  esac
done

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
DB_ROOT=$(grep -E '^LIGHTRAG_DB_ROOT=' "$REPO_DIR/.env" 2>/dev/null | cut -d= -f2)
DB_ROOT=${DB_ROOT:-/data/lightrag}
# 暫存區。**刻意不放在 $DB_ROOT 底下**，儘管它是 lightrag 的東西：
# 下面第 3 段是 `cp -a "$DB_ROOT/." "$STAGE/"`，STAGE 在 DB_ROOT 裡面就會把
# 暫存區複製進自己（每天翻一倍，而且不報錯）。順帶第二個理由：backrest 的
# lightrag-snapshot plan 涵蓋整個 /data/lightrag，放裡面等於每 6 小時重複
# 上傳一份 1.6 GB 的複本。
#
# 2026-08-07 從 /data/rag/coldstage 搬來。PO 定案「/data/rag 廢除，不再牽扯」，
# 而舊值會讓這支腳本每天 mkdir -p 把那個目錄重建出來 —— 刪一次它建一次，
# 且看起來一切正常（實測：PO 清掉 /data/rag 之後，03:28 又出現一個空目錄）。
STAGE=/data/lightrag-coldstage
STAMP=/data/lightrag/.backup-cold.stamp
# 停的順序：先停用它們的，再停資料庫。啟動反過來。
DEPS=(kbapi-acoustics_v2 lightrag-acoustics_v2)
DBS=(lightrag-neo4j lightrag-postgres)
TS=$(date +%Y%m%dT%H%M%S)
FAILED=""

log() { printf '%s  %s\n' "$(date +%H:%M:%S)" "$*"; }
fail() { FAILED="${FAILED}${FAILED:+; }$*"; log "！$*"; }

start_all() {
  # **無論如何都要跑**：半路失敗時最糟的結果是服務停著沒人知道。
  log "啟動服務（反序）"
  for c in "${DBS[@]}"; do docker start "$c" >/dev/null 2>&1 && log "  起 $c"; done
  for i in $(seq 1 40); do
    docker exec lightrag-postgres pg_isready >/dev/null 2>&1 && break
    sleep 3
  done
  for c in "${DEPS[@]}"; do docker start "$c" >/dev/null 2>&1 && log "  起 $c"; done
}
trap start_all EXIT INT TERM

# ── 0. 有沒有新東西？沒有就別停機 ──────────────────────────────────
# 指紋**不帶 workspace 條件**是刻意的：這支備份的是整個實例的目錄，
# 指紋就該涵蓋整個實例。（與其他工具「每句 SQL 都要帶 workspace」的規則不衝突，
# 那條防的是「兩個 workspace 被併成一列」，這裡要的正好是全部。）
# 讀不到指紋時**照跑不誤**（fail-open 往「有備份」那邊倒）。
fingerprint() {
  printf '%s\n' "select
      (select count(*) from lightrag_doc_status)      || ':' ||
      (select count(*) from lightrag_doc_chunks)      || ':' ||
      (select count(*) from lightrag_entity_chunks)   || ':' ||
      (select count(*) from lightrag_relation_chunks) || ':' ||
      coalesce((select max(updated_at)::text from lightrag_doc_status), '-');" \
  | docker exec -i lightrag-postgres psql -U "${POSTGRES_USER:-deeptutor}" \
      -d "${POSTGRES_DATABASE:-lightrag}" -tAqX -f - 2>/dev/null | tr -d '[:space:]'
}

NOW_FP=$(fingerprint)
if [ -z "$NOW_FP" ]; then
  log "讀不到資料庫指紋（PG 沒起來？）—— 照跑，寧可多備一份"
elif [ "$FORCE" = "1" ]; then
  log "指紋 $NOW_FP；--force，照跑"
elif [ -f "$STAMP" ] && [ "$NOW_FP" = "$(tr -d '[:space:]' < "$STAMP")" ]; then
  log "沒有新的抽取成果（指紋未變：$NOW_FP）"
  log "上次備份：$(date -r "$STAMP" '+%Y-%m-%d %H:%M' 2>/dev/null || echo 未知)"
  log "跳過 —— 不停機。要強制備份加 --force"
  trap - EXIT INT TERM
  exit 0
fi

log "備份根目錄 $DB_ROOT（$(sudo du -sh "$DB_ROOT" 2>/dev/null | cut -f1)）"

# ── 1. 停 ─────────────────────────────────────────────────────────────
log "停服務"
for c in "${DEPS[@]}" "${DBS[@]}"; do
  docker stop -t 60 "$c" >/dev/null 2>&1 && log "  停 $c" || fail "停不掉 $c"
done
[ -n "$FAILED" ] && { log "有容器停不掉，不做複製（資料可能不一致）"; exit 3; }

# ── 2. 本機複製（停機窗只有這一段）───────────────────────────────────
log "複製到 $STAGE"
sudo rm -rf "$STAGE"; sudo mkdir -p "$STAGE"
T0=$(date +%s)
sudo cp -a "$DB_ROOT/." "$STAGE/" || fail "複製失敗"
sudo chmod -R a+rX "$STAGE" 2>/dev/null
T1=$(date +%s)
log "複製完成，$((T1-T0)) 秒"

# ── 3. 啟回（trap 也會做，這裡先做好縮短停機）─────────────────────
trap - EXIT INT TERM
start_all
log "服務已恢復"
[ -n "$FAILED" ] && { "$REPO_DIR/scripts/notify.sh" "冷備份失敗（服務已恢復）" "$FAILED"; exit 4; }

# ── 4. 驗複本 ────────────────────────────────────────────────────────
# 只驗「有沒有抄到東西」。深度驗證是「還原一份起得來」——那是 BACKUP-3。
for sub in postgres neo4j; do
  n=$(sudo find "$STAGE/$sub" -type f 2>/dev/null | wc -l)
  log "  $sub: $n 個檔"
  [ "$n" -lt 10 ] && fail "$sub 只有 $n 個檔，不像完整的資料目錄"
done
[ -n "$FAILED" ] && { "$REPO_DIR/scripts/notify.sh" "冷備份複本可疑" "$FAILED"; exit 5; }

# ── 5. 上傳（服務已在跑，慢沒關係）──────────────────────────────────
# 用 backrest 容器裡的 restic：它已有 rclone 設定與 repo 金鑰，不必在宿主再裝
# 一套、也不必把金鑰複製到第二個地方。/data 已唯讀掛成 /userdata/data。
#
# **金鑰從 stdin 進，不走命令列。** `docker exec -e RESTIC_PASSWORD=…` 會讓密碼
# 出現在 `ps` 輸出裡，這台機器上任何使用者都看得到（2026-08-03 實際踩到）。
log "restic 上傳"
PW=$(docker exec backrest sh -c 'cat /config/config.json' \
     | python3 -c 'import sys,json;d=json.load(sys.stdin);print(next(r["password"] for r in d["repos"] if r["id"]=="rag-db"))' 2>/dev/null)
if [ -z "${PW:-}" ]; then
  fail "讀不到 restic 金鑰"
else
  printf '%s' "$PW" | docker exec -i backrest sh -c '
    RESTIC_PASSWORD=$(cat) exec restic -r rclone:gdrive_LIH:restic_rag_db backup \
      --tag lightrag-db --tag "ts:'"$TS"'" --host florian-dker /userdata'"$STAGE" \
      2>&1 | tail -6 || fail "restic 上傳失敗"
fi

# ── 6. 驗快照真的在 repo 裡，然後才清暫存 ───────────────────────────
# **清理必須在驗證之後**：驗不過就把複本留著，否則這一輪等於什麼都沒有。
if [ -z "$FAILED" ]; then
  got=$(printf '%s' "$PW" | docker exec -i backrest sh -c '
          RESTIC_PASSWORD=$(cat) exec restic -r rclone:gdrive_LIH:restic_rag_db \
            snapshots --tag "ts:'"$TS"'" --json' 2>/dev/null \
        | python3 -c 'import sys,json;print(len(json.load(sys.stdin)))' 2>/dev/null || echo 0)
  if [ "${got:-0}" -ge 1 ]; then
    log "快照已在 repo（tag ts:$TS）"
    # 指紋只在「快照確定進了 repo」之後才落地。順序反過來的話，上傳失敗會讓
    # 下一次誤以為已經備過而跳過 —— 那正是這個開關最不該犯的錯。
    if [ -n "$NOW_FP" ]; then
      printf '%s\n' "$NOW_FP" > "$STAMP" && log "指紋已記錄（$NOW_FP）"
    fi
    [ "$KEEP_STAGE" = "1" ] || { sudo rm -rf "$STAGE"; log "暫存已清"; }
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
