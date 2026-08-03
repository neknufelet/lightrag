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

# ── SCANNER-1：∂ 誤讀探針（2026-08-03 加入）────────────────────────────
# 這是「新符號誤讀」唯一的偵測手段：漏字檢查抓不到它（誤讀不刪字，覆蓋率永遠
# 100%）、preflight 也抓不到（型別沒變）—— 它可以完全安靜地進索引。
# rc: 0 與基準相同／2 漂移／3 沒有基準檔（未設定，不是通過也不是失敗）。
python3 scripts/scan-partial.py > "$CHECK_DIR/scan-$ts.txt" 2>&1
scan_rc=$?
case $scan_rc in
  0) ;;
  2) fail_msgs+=("∂ 誤讀探針漂移 (rc=2) → $CHECK_DIR/scan-$ts.txt") ;;
  3) fail_msgs+=("∂ 誤讀探針【沒有基準檔】(rc=3) —— 未設定不是通過，去建基準") ;;
  *) fail_msgs+=("∂ 誤讀探針掛了 (rc=$scan_rc) → $CHECK_DIR/scan-$ts.txt") ;;
esac

# 2026-08-03 CUTOVER：這裡原本有第二段，去 ../lightrag-v2 那個 worktree 再跑一次
# compat-check 與 canary。worktree 已收掉、acoustics_v155 已退役，現在只有一個
# checkout、一個 workspace，上面那一段就是全部。
#
# 刪掉而不是留著讓 `if [ -d ]` 靜靜跳過 —— 那個 if 會讓「worktree 沒了」與
# 「檢查跑過了」在報表上長得一樣（鐵則 6）。將來真要同時顧兩個庫，正確做法
# 是讓這支腳本吃一份明確的 workspace 清單，而不是猜隔壁目錄存不存在。

status=pass
[ ${#fail_msgs[@]} -gt 0 ] && status=fail
printf '{"at":"%s","status":"%s","compat_rc":%d,"scan_rc":%d,"detail":"%s"}\n' \
  "$ts" "$status" "$rc" "$scan_rc" "$CHECK_DIR/compat-$ts.json" \
  > "$CHECK_DIR/latest.json"

# 保留最新 120 份。`v2-*` 那組是 CUTOVER 之前雙 checkout 時代留下的**歷史**
# 紀錄（本腳本已不再產生它們），仍列在這裡是為了讓它們也會隨時間被清掉——
# 漏掉的話就是一堆只增不減、永遠不會過期的檔案。
find "$CHECK_DIR" \( -name 'compat-2*' -o -name 'canary-2*' \
                     -o -name 'v2-compat-2*' -o -name 'v2-canary-2*' \
                     -o -name 'scan-2*' \) |
  sort | head -n -120 | xargs -r rm --

if [ "$status" = fail ]; then
  scripts/notify.sh "lightrag 每日檢查 FAIL" "$(printf '%s\n' "${fail_msgs[@]}")"
  exit 1
fi
