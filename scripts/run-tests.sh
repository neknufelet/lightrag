#!/usr/bin/env bash
# lightrag 的完整測試入口：pytest 不會收集 tests/test_gates.py，兩邊都要跑。
set -u

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR" || exit 2

echo "== python3 -m pytest tests/ -q =="
pytest_rc=0
python3 -m pytest tests/ -q || pytest_rc=$?

echo "== python3 tests/test_gates.py =="
gates_rc=0
python3 tests/test_gates.py || gates_rc=$?

if [ "$pytest_rc" -ne 0 ] || [ "$gates_rc" -ne 0 ]; then
  echo "測試失敗：pytest rc=$pytest_rc，test_gates.py rc=$gates_rc" >&2
  exit 1
fi

echo "兩個測試入口全部通過。"
