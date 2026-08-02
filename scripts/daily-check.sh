#!/usr/bin/env bash
# 每日斷言：compat-check（契約 + 全部文件）+ canary（規則漂移）。
# 由 systemd timer 呼叫（lightrag-daily-check.timer），也可手動跑。
# 「誰會報錯」的答案從「沒有人」改成這支——所以它自己掛掉也要有人知道：
# service 設 SuccessExitStatus=1，exit 1（檢查紅燈，已自行通知）不觸發 OnFailure，
# 其他非零（腳本本身掛掉）由 OnFailure= 的備援通知接手。
#
# 用法:
#   daily-check.sh              跑檢查
#   daily-check.sh --selftest   只驗通知管道（裝好 app 後跑一次確認收得到）
set -u
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CHECK_DIR=/data/rag/lightrag/checks
cd "$REPO_DIR"
mkdir -p "$CHECK_DIR"

if [ "${1:-}" = "--selftest" ]; then
  scripts/notify.sh "daily-check selftest" "手動觸發的測試警報。收到＝管道正常。"
  echo "已送出，看手機。"
  exit 0
fi

ts=$(date +%Y%m%dT%H%M%S)
fail_msgs=()

python3 scripts/compat-check.py --json \
  > "$CHECK_DIR/compat-$ts.json" 2> "$CHECK_DIR/compat-$ts.err"
rc=$?
case $rc in
  0) ;;
  5) fail_msgs+=("compat-check 軟失敗 (rc=5) → $CHECK_DIR/compat-$ts.json") ;;
  *) fail_msgs+=("compat-check 硬失敗 (rc=$rc) → $CHECK_DIR/compat-$ts.json") ;;
esac

python3 scripts/postprocess.py canary > "$CHECK_DIR/canary-$ts.txt" 2>&1 ||
  fail_msgs+=("canary 規則漂移 (rc=$?) → $CHECK_DIR/canary-$ts.txt")

# --- acoustics_v2 重建（worktree）---
# 用 worktree 自己的 scripts 與 .env 跑：容器名、埠、workspace 全都由那個
# checkout 的 .env 推導。從這裡用 v1 的腳本去驗 v2，會安靜地驗錯對象。
#
# v2 現在 compat-check 與 canary 都跑。canary 原本被關著，理由是「v2 還沒有
# 自己的基準，拿 v155 的去對每天噴假漂移」——2026-08-02 階段 2 的規則實際跑完
# 並 `canary --update` 建了 v2 自己的基準（worktree 的 tests/canary-baseline.json），
# 那個理由消失，所以打開。基準只跟 v2 的資料比，不會再借 v155 的數字。
V2_DIR="${LIGHTRAG_V2_DIR:-$(cd "$REPO_DIR/.." && pwd)/lightrag-v2}"
v2_rc=0
v2_canary_rc=0
v2_detail=""
if [ -d "$V2_DIR/scripts" ]; then
  v2_detail="$CHECK_DIR/v2-compat-$ts.json"
  ( cd "$V2_DIR" && python3 scripts/compat-check.py --json ) \
    > "$v2_detail" 2> "$CHECK_DIR/v2-compat-$ts.err"
  v2_rc=$?
  case $v2_rc in
    0) ;;
    5) fail_msgs+=("v2 compat-check 軟失敗 (rc=5) → $v2_detail") ;;
    *) fail_msgs+=("v2 compat-check 硬失敗 (rc=$v2_rc) → $v2_detail") ;;
  esac

  ( cd "$V2_DIR" && python3 scripts/postprocess.py canary ) \
    > "$CHECK_DIR/v2-canary-$ts.txt" 2>&1
  v2_canary_rc=$?
  [ $v2_canary_rc -eq 0 ] ||
    fail_msgs+=("v2 canary 規則漂移 (rc=$v2_canary_rc) → $CHECK_DIR/v2-canary-$ts.txt")
fi

status=pass
[ ${#fail_msgs[@]} -gt 0 ] && status=fail
printf '{"at":"%s","status":"%s","compat_rc":%d,"detail":"%s","v2_compat_rc":%d,"v2_detail":"%s","v2_canary_rc":%d}\n' \
  "$ts" "$status" "$rc" "$CHECK_DIR/compat-$ts.json" "$v2_rc" "$v2_detail" "$v2_canary_rc" \
  > "$CHECK_DIR/latest.json"

# 保留規則要涵蓋 v2 的檔名，否則 v2-* 只增不減，永遠不會被清掉。
find "$CHECK_DIR" \( -name 'compat-2*' -o -name 'canary-2*' \
                     -o -name 'v2-compat-2*' -o -name 'v2-canary-2*' \) |
  sort | head -n -120 | xargs -r rm --

if [ "$status" = fail ]; then
  scripts/notify.sh "lightrag 每日檢查 FAIL" "$(printf '%s\n' "${fail_msgs[@]}")"
  exit 1
fi
