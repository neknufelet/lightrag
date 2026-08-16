#!/usr/bin/env bash
# 保留最新 N 份檢查報告，其餘刪掉。從 daily-check.sh 抽出來，因為它需要測試。
#
# ⚠ **按修改時間排，不要按檔名排。**
#
# 2026-08-16 實測到的事故：原本寫在 daily-check.sh 裡的是
#
#     find "$CHECK_DIR" \( -name 'compat-2*' -o -name 'canary-2*' -o … \) |
#       sort | head -n -120 | xargs -r rm --
#
# `sort` 排的是**完整路徑**，所以前綴的字母序決定了一切：
#
#     canary- < compat- < coverage- < deploy- < fresh- < parse- < scan- < units-
#
# `canary-` 排在其餘七種**全部之前**。於是總數一碰到上限，第一個被刪的永遠是
# canary —— 包括同一輪才剛寫好的那一份。當天實測：清理前 121 個、清理後正好
# 120 個，被刪的就是那一份；`checks/` 底下**一個 canary 檔都沒有**，
# 而 daily-check 的紅燈訊息一直指著它。
#
# ⇒ **紅燈是真的，證據被自己刪了。** 這是「檢查自己壞掉」那一族裡形狀最惡劣的
# 一種：不是漏報，是報了之後把證據銷毀。
#
# 按 mtime 排還有一個好處：它不依賴檔名的形狀。將來多一種前綴、或前綴改名，
# 這支都不必跟著改 —— 而按檔名排的版本會再犯一次同樣的錯，而且一樣安靜。
#
# 用法：
#   prune-checks.sh <目錄> [保留份數]     真的刪
#   PRUNE_DRY_RUN=1 prune-checks.sh …     只印要刪誰，不刪
set -u

dir=${1:?用法: prune-checks.sh <目錄> [保留份數]}

# ⚠ 這裡是 `${2-120}` 不是 `${2:-120}`。差別在「給了但是空字串」：
# `:-` 會把空字串也當成沒給、靜靜落回 120，於是呼叫端寫成
# `prune-checks.sh "$DIR" "$RETENTIN"`（變數名打錯）時**不會有任何訊號**，
# 只是安靜地用了別的數字。`-` 只在**真的沒給**時才用預設，空字串會落到
# 下面的檢查被擋下來。
keep=${2-120}

case "$keep" in
  ''|*[!0-9]*) echo "prune-checks: 保留份數要是非負整數，收到 '$keep'" >&2; exit 2 ;;
esac

[ -d "$dir" ] || { echo "prune-checks: 目錄不存在 $dir" >&2; exit 2; }

# 樣式維持與原版相同。`v2-*` 那組是 CUTOVER 之前雙 checkout 時代的歷史紀錄
# （已不再產生），仍列著是為了讓它們也會隨時間被清掉 —— 漏掉的話就是一堆
# 只增不減、永遠不會過期的檔案。
victims=$(
  find "$dir" -maxdepth 1 -type f \
    \( -name 'compat-2*'    -o -name 'canary-2*' \
       -o -name 'v2-compat-2*' -o -name 'v2-canary-2*' \
       -o -name 'scan-2*'   -o -name 'units-2*' \
       -o -name 'deploy-2*' -o -name 'fresh-2*' \
       -o -name 'parse-2*'  -o -name 'coverage-2*' \) \
    -printf '%T@\t%p\n' |
  sort -rn |                 # 新的在前
  tail -n +$((keep + 1)) |   # 跳過要保留的那 N 份，剩下的就是要刪的
  cut -f2-
)

[ -z "$victims" ] && exit 0

if [ -n "${PRUNE_DRY_RUN:-}" ]; then
  printf '%s\n' "$victims"
  exit 0
fi

printf '%s\n' "$victims" | xargs -d '\n' -r rm --
