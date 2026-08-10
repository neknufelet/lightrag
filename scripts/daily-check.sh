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
  echo "2026-08-07 起沒有通知管道（ntfy 已拆）。紅綠狀態一律看 $CHECK_DIR。" >&2
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

# ── 解析品質：碎字元（2026-08-10 加入）──────────────────────────────────
# `parse-check` 的離開碼只在**掉字**時非 0（WARN 不算），而 2026-08-10 對 257 份
# 實測那個層級是 2/2 全對：抓到的兩份確實有整頁被抽成碎字元
# （`s d s e o a sne a`），成因是 .env.example 記過的「文字層路徑會吃掉
# x-height 字母」，`is_ocr=true` 沒有百分之百擋掉。
# 它的對照源是解析成果自己，不依賴 pdftotext —— 不會被壞掉的文字層騙。
python3 scripts/parse-check.py > "$CHECK_DIR/parse-$ts.txt" 2>&1
parse_rc=$?
if [ "$parse_rc" -ne 0 ]; then
  fail_msgs+=("解析出現碎字元 (rc=$parse_rc) → $CHECK_DIR/parse-$ts.txt")
fi

# ── 漏字比對：**只記錄，不進紅燈**（2026-08-10 加入）────────────────────
# 2026-08-10 對 257 份實測：13 份超標，**逐份查證的 4 份全是假訊號** ——
# 它拿 `pdftotext` 讀的文字層當對照源，而那個證人對雙欄學術論文會自己壞掉
# （浮水印讀成碎片、數學字型讀成 dddd、掃描件黏字、同段落重複輸出）。
#
# **所以它的離開碼不進 fail_msgs。** 讓它天天把紅燈染紅，代價是真的紅燈被淹沒
# —— 那正是本專案在別處一再避開的形狀。判斷交給 `kb-health-check` skill，
# 查過的結論記進 tests/verified-findings.json，工具下次會自己印出來。
python3 scripts/coverage-check.py --json \
  > "$CHECK_DIR/coverage-$ts.json" 2> "$CHECK_DIR/coverage-$ts.err"
coverage_rc=$?

# ⚠ **`extract-check` 刻意不放在每日。** 2026-08-10 實測全庫要一個多小時，
# 而它量的東西（實體接不接得回原文）不會天天變。要跑就在一批進料收尾時跑，
# 或手動：`python3 scripts/extract-check.py --json`。

# ── 部署完整性：systemd 單元有沒有跟 repo 一致 ─────────────────────────
# 這支腳本本身是「誰會報錯」的答案，但**觸發它的 timer 原本不在版控裡**——
# /etc 掉了或有人手改了，腳本還在、排程沒了，看起來一切正常。
# 探針本身要有探針（鐵則 6）。rc: 0 一致／2 缺檔、內容不符、或沒 enabled。
python3 scripts/systemd-units.py verify > "$CHECK_DIR/units-$ts.txt" 2>&1
units_rc=$?
if [ "$units_rc" -ne 0 ]; then
  fail_msgs+=("systemd 單元與 repo 不一致 (rc=$units_rc) → $CHECK_DIR/units-$ts.txt")
fi

# ── 部署一致性：stack 那份 compose 有沒有跟 repo 一致 ──────────────────
# 這支 2026-08-08 之前**沒有任何人呼叫**（deploy-stack.py 檔頭自己寫了「執行者
# 目前是弱的」）。寫好的檢查沒被呼叫，等於沒寫。
python3 scripts/deploy-stack.py verify > "$CHECK_DIR/deploy-$ts.txt" 2>&1
deploy_rc=$?
if [ "$deploy_rc" -ne 0 ]; then
  fail_msgs+=("stack 的 compose 與 repo 不一致 (rc=$deploy_rc) → $CHECK_DIR/deploy-$ts.txt")
fi

# ── 部署新鮮度：跑著的是不是最新的碼 ───────────────────────────────────
# 檔案放對了不代表跑著的是它。2026-08-08 實測 dker 落後 origin 3 個 commit
# （含一個 fix(intake)），而容器 healthy、端點會回應、測試也過 —— 跑舊碼
# **完全沒有外顯症狀**。三條：落後 origin／工作區被手改／容器比它該跑的碼舊。
python3 scripts/deploy-stack.py freshness > "$CHECK_DIR/fresh-$ts.txt" 2>&1
fresh_rc=$?
if [ "$fresh_rc" -ne 0 ]; then
  fail_msgs+=("部署不新鮮 (rc=$fresh_rc) → $CHECK_DIR/fresh-$ts.txt")
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

# 這份結果是**哪一版的碼**產生的。沒有它，一筆過期的紅燈與一筆剛跑出來的紅燈
# 在審核台上長得一模一樣 —— 而處置完全不同（前者要先問「排程還活著嗎」）。
# 「檢查結果要帶上產生它的版本」是要升上游的通則之一。
commit=$(git -C "$REPO_DIR" rev-parse --short HEAD 2>/dev/null || echo unknown)

# coverage_rc 記在這裡但**不影響 status** —— 它是參考值不是判定，理由見上方。
printf '{"at":"%s","status":"%s","commit":"%s","compat_rc":%d,"scan_rc":%d,"units_rc":%d,"deploy_rc":%d,"fresh_rc":%d,"tests_rc":%d,"parse_rc":%d,"coverage_rc":%d,"detail":"%s"}\n' \
  "$ts" "$status" "$commit" "$rc" "$scan_rc" "$units_rc" "$deploy_rc" "$fresh_rc" \
  "$tests_rc" "$parse_rc" "$coverage_rc" "$CHECK_DIR/compat-$ts.json" \
  > "$CHECK_DIR/latest.json"

# 保留最新 120 份。`v2-*` 那組是 CUTOVER 之前雙 checkout 時代留下的**歷史**
# 紀錄（本腳本已不再產生它們），仍列在這裡是為了讓它們也會隨時間被清掉——
# 漏掉的話就是一堆只增不減、永遠不會過期的檔案。
find "$CHECK_DIR" \( -name 'compat-2*' -o -name 'canary-2*' \
                     -o -name 'v2-compat-2*' -o -name 'v2-canary-2*' \
                     -o -name 'scan-2*' -o -name 'units-2*' \
                     -o -name 'deploy-2*' -o -name 'fresh-2*' \
                     -o -name 'parse-2*' -o -name 'coverage-2*' \) |
  sort | head -n -120 | xargs -r rm --

if [ "$status" = fail ]; then
  # 2026-08-07：ntfy 已拆，改寫 stderr —— systemd 會收進 journal。
  # ⚠ 沒有人會被打斷。要知道紅燈只能看 journal 或 $CHECK_DIR。
  printf '%s\n' "${fail_msgs[@]}" >&2
  exit 1
fi
