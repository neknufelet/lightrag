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

KEEP_STAGE=0; FORCE=0; STAGE_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --keep-stage) KEEP_STAGE=1 ;;
    --force)      FORCE=1 ;;
    --stage-only) STAGE_ONLY=1 ;;
    *) echo "未知參數：$arg（可用 --keep-stage --force --stage-only）" >&2; exit 2 ;;
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
#
# 三個 `BACKUP_*` 環境變數只是為了**能測**：這支會停容器、會 rm -rf，唯一能安全
# 驗證它的方式是在 tmp 底下拿假的 docker／sudo 跑一遍。預設值就是正式路徑，
# 正式環境不設它們（`tests/test_backup_restore_point.py`）。
STAGE=${BACKUP_STAGE_DIR:-/data/lightrag-coldstage}
# 戳記跟著資料根走 —— 與 Python 那邊的 `paths.backup_stamp` 同一個定義。
STAMP=$DB_ROOT/.backup-cold.stamp
# 跳過的條件除了「指紋沒變」之外還要不要確認目錄還在？每日那條不用（它的暫存
# 本來就會在上傳成功後被刪掉），還原點那條要 —— 見下面。
SKIP_NEEDS_DIR=0

# ── --stage-only：只做到本機複本，不上傳（2026-08-10 加）───────────────────
# **還原點是本機那份複本，不是 Google Drive 上那份。** 要「回到這一批之前」，
# 要的是「停掉、換回目錄、啟動」——而那只需要本機的複本。上傳到 Google Drive
# 防的是火災跟整台機器沒了，跟「我放錯檔案想退回去」是兩件事。
#
# 為什麼要分開：進料按下「全部開始」時會叫這支建還原點，而 2026-08-10 實測
# **restic 上傳要 38 分鐘**。等它等於讓使用者盯著「還原點建立中」半小時，
# 解析完全不動 —— 而那半小時買到的東西（異地副本）對這個用途一點用都沒有。
#
# ⚠ **用不同的目錄**：每日那次會 `rm -rf` 自己的暫存區，共用的話你的還原點
# 會在當晚 04:00 被蓋掉。
# ⚠ **不寫每日那個指紋**：它的意思是「這個狀態已經上傳到 restic 了」。stage-only
# 沒有上傳，寫了會讓當晚那次誤以為已經備過而跳過 —— 那正是這個開關最不該犯的錯。
#
# ⚠⚠ **用自己的戳記，而且跳過之前要確認目錄還在**（2026-08-10 修，血淚見下）：
# 一開始這裡共用每日那個戳記，結果是「還原點永遠建不出來」。因為每日備份上傳
# 成功之後會 `rm -rf` 掉本機暫存 —— 戳記還在，複本沒了。常態長這樣：
#
#     04:00  備份 → 上傳成功 → 寫戳記 → 刪本機複本
#     10:00  放 PDF、按全部開始 → 指紋沒變 → 跳過 ⇒ 本機還原點不存在
#
# 兩種模式問的是不同的問題：每日問「這個狀態上傳過了嗎」，還原點問「本機現在
# 有沒有一份可以換回去的複本」。**同一個戳記答不了兩個問題。**
if [ "$STAGE_ONLY" = "1" ]; then
  STAGE=${BACKUP_RESTOREPOINT_DIR:-/data/lightrag-restorepoint}
  STAMP=$STAGE.stamp
  SKIP_NEEDS_DIR=1
fi
# 停的順序：先停用它們的，再停資料庫。啟動反過來。
DEPS=(kbapi-acoustics_v2 lightrag-acoustics_v2)
# 2026-08-07 起只有 Postgres —— 圖換成 PGTableGraphStorage，Neo4j 整個移除。
DBS=(lightrag-postgres)
TS=$(date +%Y%m%dT%H%M%S)
FAILED=""

# ── 同時只准跑一支 ──────────────────────────────────────────────────────
# 這支會**停容器**。兩份同時跑的話，第二份會在第一份正在複製時把服務停掉、
# 或第一份的 `start_all` 把第二份要停的容器啟回來 —— 而複製出來的東西是不是
# 一致的沒有人知道。2026-08-10 差點踩到：每日排程的上傳還在跑（38 分鐘），
# 而進料的還原點正要觸發第二次。
LOCK=${BACKUP_LOCK:-/tmp/lightrag-backup-cold.lock}
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "已經有一支冷備份在跑（$LOCK）—— 這次不跑" >&2
  exit 6
fi

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
elif [ "$SKIP_NEEDS_DIR" = "1" ] && [ ! -d "$STAGE" ]; then
  # 戳記是那份複本的收據，不是複本。目錄不見了就得重建，別相信收據。
  log "指紋 $NOW_FP 沒變，但 $STAGE 不在 —— 重建還原點"
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
# **排除 `models/`**（2026-08-10，PO 裁決）。那是 HuggingFace 的權重快取
# （BGE-M3 與 reranker），11G 裡佔 6.4G，而 Infinity 啟動時會自己重新下載 ——
# 備份它只是把停機窗與上傳時間拉長，換到一個隨時可以重建的東西。
#
# 這不是「省空間」的最佳化：2026-08-10 實測第一次上傳 11G **62 分鐘還沒傳完**，
# 撞到 systemd 的一小時上限被砍。扣掉 models 之後剩約 4.6G。
#
# ⚠ 用 rsync 而不是 `cp -a` 之後再刪：後者會先花時間抄那 6.4G 再刪掉，
# 停機窗一點都沒有變短。
log "複製到 $STAGE（排除 models/，那是可重下的權重快取）"
# **先撕掉收據再動目錄**：複製抄到一半失敗的話，留著的是一份半殘的複本；
# 舊戳記還在就會讓下一次跳過，然後拿那份半殘的當還原點。
[ "$SKIP_NEEDS_DIR" = "1" ] && sudo rm -f "$STAMP"
sudo rm -rf "$STAGE"; sudo mkdir -p "$STAGE"
T0=$(date +%s)
sudo rsync -a --exclude='models/' "$DB_ROOT/" "$STAGE/" || fail "複製失敗"
sudo chmod -R a+rX "$STAGE" 2>/dev/null
T1=$(date +%s)
log "複製完成，$((T1-T0)) 秒"

# ── 3. 啟回（trap 也會做，這裡先做好縮短停機）─────────────────────
trap - EXIT INT TERM
start_all
log "服務已恢復"
[ -n "$FAILED" ] && { echo "冷備份失敗（服務已恢復）：$FAILED" >&2; exit 4; }

# ── 4. 驗複本 ────────────────────────────────────────────────────────
# 只驗「有沒有抄到東西」。深度驗證是「還原一份起得來」——那是 BACKUP-3。
for sub in postgres; do
  n=$(sudo find "$STAGE/$sub" -type f 2>/dev/null | wc -l)
  log "  $sub: $n 個檔"
  [ "$n" -lt 10 ] && fail "$sub 只有 $n 個檔，不像完整的資料目錄"
done
[ -n "$FAILED" ] && { echo "冷備份複本可疑：$FAILED" >&2; exit 5; }

# ── 5. 上傳（服務已在跑，慢沒關係）──────────────────────────────────
# 用 backrest 容器裡的 restic：它已有 rclone 設定與 repo 金鑰，不必在宿主再裝
# 一套、也不必把金鑰複製到第二個地方。/data 已唯讀掛成 /userdata/data。
#
# **金鑰從 stdin 進，不走命令列。** `docker exec -e RESTIC_PASSWORD=…` 會讓密碼
# 出現在 `ps` 輸出裡，這台機器上任何使用者都看得到（2026-08-03 實際踩到）。
if [ "$STAGE_ONLY" = "1" ]; then
  # 收據最後才開：目錄驗過了（上面第 4 段）才敢說「這個指紋有複本」。
  if [ -n "$NOW_FP" ]; then
    printf '%s\n' "$NOW_FP" > "$STAMP" && log "還原點指紋已記錄（$NOW_FP）"
  fi
  log "還原點已建立：$STAGE"
  log "  還原方式：停掉容器 → 把這個目錄的內容覆蓋回 $DB_ROOT → 啟動"
  log "  ⚠ 這份**不含 models/**（可重下的權重快取）——還原時不要整個目錄換掉，"
  log "     否則 models/ 會一起不見；用覆蓋的方式，或先把 models/ 留著"
  log "  （--stage-only：不上傳、不碰每日那個指紋，異地副本由每日 04:00 那次負責）"
  exit 0
fi

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
  echo "冷備份失敗：$FAILED" >&2
  log "FAILED: $FAILED"
  exit 1
fi
log "完成"
