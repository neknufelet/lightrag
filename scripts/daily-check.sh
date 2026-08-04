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
#
# REBUILD-6：測試入口的非零是檢查紅燈（exit 1），不是 daily-check 腳本故障；
# 這樣測試失敗會沿用既有通知路徑。入口檔缺失等腳本本身故障仍會在執行前掛掉，
# 交給 systemd OnFailure。
set -u
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CHECK_DIR=/data/lightrag/checks
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

# ── 部署完整性：systemd 單元有沒有跟 repo 一致 ─────────────────────────
# 這支腳本本身是「誰會報錯」的答案，但**觸發它的 timer 原本不在版控裡**——
# /etc 掉了或有人手改了，腳本還在、排程沒了，看起來一切正常。
# 探針本身要有探針（鐵則 6）。rc: 0 一致／2 缺檔、內容不符、或沒 enabled。
python3 scripts/systemd-units.py verify > "$CHECK_DIR/units-$ts.txt" 2>&1
units_rc=$?
if [ "$units_rc" -ne 0 ]; then
  fail_msgs+=("systemd 單元與 repo 不一致 (rc=$units_rc) → $CHECK_DIR/units-$ts.txt")
fi

# ── REBUILD-6：單一測試入口───────────────────────────────────────────────
# run-tests.sh 內會依序跑 pytest 與自製的 test_gates.py；pytest 不會收集後者，
# 因此兩者缺一不可。測試失敗屬於檢查紅燈，讓本支以 exit 1 通知；不要把它誤當
# 成 daily-check 自身掛掉而走 OnFailure。
if [ ! -x scripts/run-tests.sh ]; then
  echo "daily-check: 找不到可執行的 scripts/run-tests.sh" >&2
  exit 2
fi
scripts/run-tests.sh > "$CHECK_DIR/tests-$ts.txt" 2>&1
tests_rc=$?
if [ "$tests_rc" -ne 0 ]; then
  fail_msgs+=("測試入口失敗 (rc=$tests_rc) → $CHECK_DIR/tests-$ts.txt")
fi

# 2026-08-03 CUTOVER：這裡原本有第二段，去 ../lightrag-v2 那個 worktree 再跑一次
# compat-check 與 canary。worktree 已收掉、acoustics_v155 已退役，現在只有一個
# checkout、一個 workspace，上面那一段就是全部。
#
# 刪掉而不是留著讓 `if [ -d ]` 靜靜跳過 —— 那個 if 會讓「worktree 沒了」與
# 「檢查跑過了」在報表上長得一樣（鐵則 6）。將來真要同時顧兩個庫，正確做法
# 是讓這支腳本吃一份明確的 workspace 清單，而不是猜隔壁目錄存不存在。

status=pass
[ ${#fail_msgs[@]} -gt 0 ] && status=fail
printf '{"at":"%s","status":"%s","compat_rc":%d,"scan_rc":%d,"units_rc":%d,"tests_rc":%d,"detail":"%s"}\n' \
  "$ts" "$status" "$rc" "$scan_rc" "$units_rc" "$tests_rc" "$CHECK_DIR/compat-$ts.json" \
  > "$CHECK_DIR/latest.json"

# 保留最新 120 份。`v2-*` 那組是 CUTOVER 之前雙 checkout 時代留下的**歷史**
# 紀錄（本腳本已不再產生它們），仍列在這裡是為了讓它們也會隨時間被清掉——
# 漏掉的話就是一堆只增不減、永遠不會過期的檔案。
find "$CHECK_DIR" \( -name 'compat-2*' -o -name 'canary-2*' \
                     -o -name 'v2-compat-2*' -o -name 'v2-canary-2*' \
                     -o -name 'scan-2*' -o -name 'units-2*' \) |
  sort | head -n -120 | xargs -r rm --

if [ "$status" = fail ]; then
  scripts/notify.sh "lightrag 每日檢查 FAIL" "$(printf '%s\n' "${fail_msgs[@]}")"
  exit 1
fi
