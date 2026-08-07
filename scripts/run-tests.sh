#!/usr/bin/env bash
# lightrag 的完整測試入口：pytest 不會收集 tests/test_gates.py，兩邊都要跑。
set -u

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR" || exit 2

# pytest 裝了沒，要先分開問。
#
# 2026-08-07 實測：dker 上沒有 pytest，於是 `python3 -m pytest` 回非零，這支就報
# 「測試失敗：pytest rc=1」—— 而那**不是**測試失敗，是根本沒跑。兩件完全不同的
# 事長成同一句話，紅燈落地在 /data/lightrag/checks/ 裡沒有人看得懂。
#
# 「驗不了」不是「失敗」也不是「通過」（鐵則 7 那一族）。
if ! python3 -c "import pytest" 2>/dev/null; then
  echo "驗不了：這台沒有裝 pytest（python3 -c 'import pytest' 失敗）。" >&2
  echo "  這不是測試失敗，是測試根本沒跑。裝法：apt install python3-pytest" >&2
  echo "  test_gates.py 不需要 pytest，下面仍會跑。" >&2
  pytest_rc=0
  pytest_unavailable=1
else
  echo "== python3 -m pytest tests/ -q =="
  pytest_rc=0
  pytest_unavailable=0
  python3 -m pytest tests/ -q || pytest_rc=$?
fi

echo "== python3 tests/test_gates.py =="
gates_rc=0
python3 tests/test_gates.py || gates_rc=$?

if [ "$pytest_rc" -ne 0 ] || [ "$gates_rc" -ne 0 ]; then
  echo "測試失敗：pytest rc=$pytest_rc，test_gates.py rc=$gates_rc" >&2
  exit 1
fi

if [ "$pytest_unavailable" -eq 1 ]; then
  # 回 3 而不是 0：這台只驗了一半。回 0 會讓「一半沒跑」看起來像「全部通過」，
  # 而那正是本專案反覆踩到的形狀。
  echo "test_gates.py 通過，但 pytest 那半驗不了（本機沒裝）。" >&2
  exit 3
fi

echo "兩個測試入口全部通過。"
