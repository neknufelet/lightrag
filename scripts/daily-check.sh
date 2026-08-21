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

# ── 跑哪一個 python（2026-08-17 起）───────────────────────────────────────
# `uv sync` 建出來的環境。**不要 fallback 到系統 python3** —— 那台上沒有
# PyMuPDF，切章相關的東西會 ImportError，而「跑了但用錯環境」比「沒跑」更難查。
# 底下的腳本用 `sys.executable` 開子行程，所以只要這裡對，整條鏈都對。
PY="$REPO_DIR/.venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "daily-check: 找不到 $PY —— 這台還沒跑過 \`uv sync\`。" >&2
  echo "  這不是檢查紅燈，是環境沒建起來。裝法：cd $REPO_DIR && uv sync --frozen" >&2
  exit 2
fi

if [ "${1:-}" = "--selftest" ]; then
  echo "2026-08-07 起沒有通知管道（ntfy 已拆）。紅綠狀態一律看 $CHECK_DIR。" >&2
  exit 0
fi

ts=$(date +%Y%m%dT%H%M%S)

# ── 紅燈語意：這一支只負責「跑」與「記下離開碼」，不判「算不算失敗」──────────
# 判準全部在 scripts/check-levels.py（擋流程的紅／提醒的紅／驗不了）。
# 分開是因為原本的「任何非零都是失敗」讓 status 天天是 fail，其中一盞
# （tests 在 dker 上永遠回 3 ＝ 這台沒有 node）**永遠不會綠**，而 2026-08-16
# 真的紅燈 fresh_rc=2「跑著的是舊碼」就埋在那一片紅裡沒有人看出來。
# 判準只有那一份，審核台橫幅也讀它 —— 兩邊各寫一份會打架而且沒人會發現。

"$PY" scripts/compat-check.py --json \
  > "$CHECK_DIR/compat-$ts.json" 2> "$CHECK_DIR/compat-$ts.err"
compat_rc=$?

# ⚠ 離開碼要**先存進變數**再判斷。原本寫成 `cmd || fail_msgs+=(… $? …)`，
# 那個 rc 沒有被留下來，於是 latest.json 裡**根本沒有 canary 這一欄** ——
# canary 紅了只會出現在 stderr（進 journal），任何讀 latest.json 的人都看不到。
# 2026-08-16 實測到：那天 canary 是紅的，而 latest.json 看起來只有四個紅燈。
"$PY" scripts/postprocess.py canary > "$CHECK_DIR/canary-$ts.txt" 2>&1
canary_rc=$?

# ── SCANNER-1：∂ 誤讀探針（2026-08-03 加入）────────────────────────────
# 這是「新符號誤讀」唯一的偵測手段：漏字檢查抓不到它（誤讀不刪字，覆蓋率永遠
# 100%）、preflight 也抓不到（型別沒變）—— 它可以完全安靜地進索引。
# rc: 0 與基準相同／2 漂移／3 沒有基準檔（未設定，不是通過也不是失敗）。
# ⚠ 它回 3（沒有基準檔）在 check-levels.py 裡**刻意留在「擋」那一態**，跟
# tests 的 3 不同 —— 那不是「這台驗不了」，是「有人要去建一份基準」，做得完。
"$PY" scripts/scan-partial.py > "$CHECK_DIR/scan-$ts.txt" 2>&1
scan_rc=$?

# ── 解析品質：碎字元（2026-08-10 加入）──────────────────────────────────
# `parse-check` 的離開碼只在**掉字**時非 0（WARN 不算），而 2026-08-10 對 257 份
# 實測那個層級是 2/2 全對：抓到的兩份確實有整頁被抽成碎字元
# （`s d s e o a sne a`），成因是 .env.example 記過的「文字層路徑會吃掉
# x-height 字母」，`is_ocr=true` 沒有百分之百擋掉。
# 它的對照源是解析成果自己，不依賴 pdftotext —— 不會被壞掉的文字層騙。
#
# **2026-08-17：它從「擋」降成「提醒」**（NEXT 的「每日體檢分不出擋流程的紅與
# 提醒的紅」那一條，以及新庫設計文件第一層的裁決「尺不改，但紅燈只印警告不擋」）。
# 實跑母體 317 份：OK 32／WARN 283（89%）／ERROR 2 —— 它量的是**語料內容**，
# 不是系統壞掉，而 ERROR 那兩份是修得動的個案，不該讓整張儀表板天天紅。
"$PY" scripts/parse-check.py > "$CHECK_DIR/parse-$ts.txt" 2>&1
parse_rc=$?

# ── 漏字比對：**只記錄，不進紅燈**（2026-08-10 加入）────────────────────
# 2026-08-10 對 257 份實測：13 份超標，**逐份查證的 4 份全是假訊號** ——
# 它拿 `pdftotext` 讀的文字層當對照源，而那個證人對雙欄學術論文會自己壞掉
# （浮水印讀成碎片、數學字型讀成 dddd、掃描件黏字、同段落重複輸出）。
#
# **所以它是「提醒的紅」不是「擋流程的紅」。** 讓它天天把紅燈染紅，代價是真的
# 紅燈被淹沒 —— 那正是本專案在別處一再避開的形狀。判斷交給 `kb-health-check`
# skill，查過的結論記進 tests/verified-findings.json，工具下次會自己印出來。
# ⚠ 2026-08-17 起它**不再是被靜靜丟掉**：check-levels.py 明確標成 warn 並印出來。
# 原本「算進 latest.json 但不算 status」的做法看不出是刻意的還是漏掉的。
"$PY" scripts/coverage-check.py --json \
  > "$CHECK_DIR/coverage-$ts.json" 2> "$CHECK_DIR/coverage-$ts.err"
coverage_rc=$?

# ⚠ **`extract-check` 刻意不放在每日。** 2026-08-10 實測全庫要一個多小時，
# 而它量的東西（實體接不接得回原文）不會天天變。要跑就在一批進料收尾時跑，
# 或手動：`python3 scripts/extract-check.py --json`。

# ── 部署完整性：systemd 單元有沒有跟 repo 一致 ─────────────────────────
# 這支腳本本身是「誰會報錯」的答案，但**觸發它的 timer 原本不在版控裡**——
# /etc 掉了或有人手改了，腳本還在、排程沒了，看起來一切正常。
# 探針本身要有探針（鐵則 6）。rc: 0 一致／2 缺檔、內容不符、或沒 enabled。
"$PY" scripts/systemd-units.py verify > "$CHECK_DIR/units-$ts.txt" 2>&1
units_rc=$?

# ── 部署一致性：stack 那份 compose 有沒有跟 repo 一致 ──────────────────
# 這支 2026-08-08 之前**沒有任何人呼叫**（deploy-stack.py 檔頭自己寫了「執行者
# 目前是弱的」）。寫好的檢查沒被呼叫，等於沒寫。
"$PY" scripts/deploy-stack.py verify > "$CHECK_DIR/deploy-$ts.txt" 2>&1
deploy_rc=$?

# ── 部署新鮮度：跑著的是不是最新的碼 ───────────────────────────────────
# 檔案放對了不代表跑著的是它。2026-08-08 實測 dker 落後 origin 3 個 commit
# （含一個 fix(intake)），而容器 healthy、端點會回應、測試也過 —— 跑舊碼
# **完全沒有外顯症狀**。三條：落後 origin／工作區被手改／容器比它該跑的碼舊。
"$PY" scripts/deploy-stack.py freshness > "$CHECK_DIR/fresh-$ts.txt" 2>&1
fresh_rc=$?
# ⚠ 2026-08-17 這一盞真的抓到東西：`lightrag-intake.service` 08-14 啟動、載入的
# 4 個檔 08-16 23:35 改過，**跑著的是舊碼**（前一晚才接上的接地檢查與 graph-clean
# 根本沒在跑）。它埋在天天都在的一片紅裡，這正是要把三態分開的理由。

# ── REBUILD-6：單一測試入口───────────────────────────────────────────────
# run-tests.sh 內會依序跑 pytest 與自製的 test_gates.py；pytest 不會收集後者，
# 因此兩者缺一不可。測試失敗屬於檢查紅燈，讓本支以 exit 1 通知；不要把它誤當
# 成 daily-check 自身掛掉而走 OnFailure。
#
# ⚠ **rc=3 不是失敗。** run-tests.sh 自己的定義：「跑得動的都通過了，但這台
# 驗不了全部」（dker 沒有 node，zotero-plugin 的檔名測試沒跑）。它至少從
# 2026-08-13 起每天都是 3 —— 天天把 status 染成 fail 的就是這一盞。
# check-levels.py 把它標成 `unverified`：既不是通過也不是失敗，但**照樣印出來**。
if [ ! -x scripts/run-tests.sh ]; then
  echo "daily-check: 找不到可執行的 scripts/run-tests.sh" >&2
  exit 2
fi
scripts/run-tests.sh > "$CHECK_DIR/tests-$ts.txt" 2>&1
tests_rc=$?

# ── 實地演習：紅燈自己會不會亮（2026-08-21 加入）──────────────────────────
# **火災警報器的測試鈕是按在裝好的大樓裡，不是工廠裡。** 上面每一支檢查都有
# 單元測試，但單元測試餵的是替身 —— 而 `7d4a878`（金絲雀的比對函式在路徑搬家中
# 丟失）那種病，替身不會跟著搬家一起壞，源碼「能」紅而跑著的那份根本沒在比。
# `4a6e533`（基準被清空）更直接：那是**資料操作**，當天任何 pytest 都全綠。
#
# 演習用真的那一支指令、在暫存資料根上餵一個故意弄壞的情境，看它會不會紅。
# ⚠ 它**不碰真的語料**（`PP_DATA_ROOT` / `--root` 指到暫存目錄，跑完就丟）。
"$PY" scripts/drill.py > "$CHECK_DIR/drill-$ts.txt" 2>&1
drill_rc=$?

# 2026-08-03 CUTOVER：這裡原本有第二段，去 ../lightrag-v2 那個 worktree 再跑一次
# compat-check 與 canary。worktree 已收掉、acoustics_v155 已退役，現在只有一個
# checkout、一個 workspace，上面那一段就是全部。
#
# 刪掉而不是留著讓 `if [ -d ]` 靜靜跳過 —— 那個 if 會讓「worktree 沒了」與
# 「檢查跑過了」在報表上長得一樣（鐵則 6）。將來真要同時顧兩個庫，正確做法
# 是讓這支腳本吃一份明確的 workspace 清單，而不是猜隔壁目錄存不存在。

# 這份結果是**哪一版的碼**產生的。沒有它，一筆過期的紅燈與一筆剛跑出來的紅燈
# 在審核台上長得一模一樣 —— 而處置完全不同（前者要先問「排程還活著嗎」）。
# 「檢查結果要帶上產生它的版本」是要升上游的通則之一。
commit=$(git -C "$REPO_DIR" rev-parse --short HEAD 2>/dev/null || echo unknown)

# ── status 與離開碼由 check-levels.py 決定 ─────────────────────────────────
# 它印 JSON 到 stdout（`latest.json` 的全文，舊欄位一個都沒少，另加 `levels`／
# `blocking`／`warnings`／`unverified`），三態的清單印到 stderr（systemd 收進
# journal），離開碼 0／1 只看有沒有「擋流程的紅」。
#
# ⚠ **先寫暫存再換上去。** 直接重導向到 latest.json 的話，check-levels.py 自己
# 掛掉會留下一個空檔 —— 而審核台讀到空檔會報 unreadable，看起來像「檢查壞了」
# 而不是「上一次的結果還在」。寫壞不如不寫。
# ── 分母：每一支自己報「這次比對了幾件事」──────────────────────────────
# **約定**：檢查跑完在輸出裡印一行 `#scope <整數>`（`--json` 的那幾支印到
# 自己的 `.err`，因為 stdout 整份是 JSON）。這裡撿起來餵給 check-levels.py，
# 它看到 rc=0 卻沒有分母（或分母 0）會**拒發綠燈**，改判「驗不了」。
#
# **為什麼要有這條約定。** 近 30 天 17 次「燈說假話」裡最大的一族，全部是
# 綠燈在空集合上算出來的：金絲雀守著 0 份（d9c5373）、比對函式在搬家中丟失
# 所以比了 0 次（7d4a878）、基準被清空（4a6e533）、少守 4 個量（0b3319d）。
# 每一次的處置都只修那一盞燈。分母把它變成一條通則。
#
# ⚠ **撿不到就不傳**，不要傳 0 —— 「沒報分母」與「報了 0」在 check-levels.py
# 裡都是驗不了，但訊息不同（「沒報分母」是還沒接上，「比對了 0 件」是真的空）。
scope_of() {   # $1 = 輸出檔；印出分母，沒有就什麼都不印
  [ -f "$1" ] || return 0
  grep -oE '^#scope [0-9]+' "$1" 2>/dev/null | tail -1 | awk '{print $2}'
}
scope_args=()
add_scope() {  # $1 = 檢查名；$2… = 要找的檔（第一個找到的算數）
  local name="$1"; shift
  local f n
  for f in "$@"; do
    n=$(scope_of "$f")
    if [ -n "$n" ]; then scope_args+=(--scope "$name=$n"); return 0; fi
  done
}
add_scope compat   "$CHECK_DIR/compat-$ts.err"
add_scope canary   "$CHECK_DIR/canary-$ts.txt"
add_scope scan     "$CHECK_DIR/scan-$ts.txt"
add_scope units    "$CHECK_DIR/units-$ts.txt"
add_scope deploy   "$CHECK_DIR/deploy-$ts.txt"
add_scope fresh    "$CHECK_DIR/fresh-$ts.txt"
add_scope tests    "$CHECK_DIR/tests-$ts.txt"
add_scope drill    "$CHECK_DIR/drill-$ts.txt"
add_scope parse    "$CHECK_DIR/parse-$ts.txt"
add_scope coverage "$CHECK_DIR/coverage-$ts.err"

tmp_latest="$CHECK_DIR/latest.json.tmp"
"$PY" scripts/check-levels.py \
  --at "$ts" --commit "$commit" --detail "$CHECK_DIR/compat-$ts.json" \
  --rc "compat=$compat_rc"   --report "compat=$CHECK_DIR/compat-$ts.json" \
  --rc "canary=$canary_rc"   --report "canary=$CHECK_DIR/canary-$ts.txt" \
  --rc "scan=$scan_rc"       --report "scan=$CHECK_DIR/scan-$ts.txt" \
  --rc "units=$units_rc"     --report "units=$CHECK_DIR/units-$ts.txt" \
  --rc "deploy=$deploy_rc"   --report "deploy=$CHECK_DIR/deploy-$ts.txt" \
  --rc "fresh=$fresh_rc"     --report "fresh=$CHECK_DIR/fresh-$ts.txt" \
  --rc "tests=$tests_rc"     --report "tests=$CHECK_DIR/tests-$ts.txt" \
  --rc "drill=$drill_rc"     --report "drill=$CHECK_DIR/drill-$ts.txt" \
  --rc "parse=$parse_rc"     --report "parse=$CHECK_DIR/parse-$ts.txt" \
  --rc "coverage=$coverage_rc" --report "coverage=$CHECK_DIR/coverage-$ts.json" \
  "${scope_args[@]}" \
  > "$tmp_latest"
levels_rc=$?
if [ ! -s "$tmp_latest" ]; then
  rm -f "$tmp_latest"
  echo "daily-check: check-levels.py 沒有產出 latest.json（rc=$levels_rc）" >&2
  exit 2
fi
mv "$tmp_latest" "$CHECK_DIR/latest.json"

# 保留最新 120 份。抽成獨立腳本是因為它需要測試 —— 原本寫在這裡的版本按**檔名**
# 排序，而 `canary-` 的字母序排在其餘七種之前，於是每次都先刪掉剛寫好的 canary
# 報告（2026-08-16 實測，理由寫在 prune-checks.sh 的檔頭）。
scripts/prune-checks.sh "$CHECK_DIR" 120

# 2026-08-07：ntfy 已拆，紅燈只寫 stderr —— systemd 會收進 journal。
# ⚠ 沒有人會被打斷。要知道紅燈只能看 journal、$CHECK_DIR，或審核台橫幅。
exit "$levels_rc"
