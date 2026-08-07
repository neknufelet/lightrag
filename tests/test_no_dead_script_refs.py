"""指向 `scripts/` 或 `tests/` 的引用，被指的檔案必須存在。

**為什麼需要這支**：2026-08-07 清理時差點刪掉 `archive-ledger.py`。它沒有被任何
程式 import，看起來是孤兒——但 `ledger.py` 在體檢表與現役文件脫節時會**拒絕輸出
總表**，而它印給人看的處置就是「去跑 `scripts/archive-ledger.py`」。刪掉它等於
把那個狀態的唯一出口拆掉，而**沒有任何東西會發現**：不是 import，靜態分析看不到；
不是測試，跑起來也是綠的。發現它純粹靠手動 grep。

**這支是驗證器，不是黑名單。** 上游 `standards/scripts/self-check.py` 的 `dead_refs`
只認三個寫死的樣式（Windows 路徑、WSL 掛載、MYTOOLS），所以它對「新出現的死引用」
結構上無能為力——實測它在 `README.md` 指名三支不存在的腳本時仍回報「乾淨」。
只認已知樣式的檢查，綠燈是誤導的。

**判準**：檔案裡出現 `scripts/x.py` 這種字串，那個檔就必須在。說明「它已經不存在」
的句子不算（同上游的作法，關鍵字比對）。`cairn/LOG.md` 整份豁免——流水帳的工作
就是記載「某天刪了什麼」，那裡的死引用是刻意的。
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

SCAN_SUFFIXES = frozenset({".py", ".sh", ".md", ".yaml", ".yml"})

# 凍結的歷史紀錄：它們的職責就是記載「當時是什麼樣子」，裡面的死引用是刻意的，
# 改掉反而是竄改紀錄。`cairn/LOG.md` 是逆時序流水帳、`docs/decisions/` 是 ADR
# 快照（專案規則：ADR 凍結不改）、`verdicts/records/review/` 是工單與終審判定全文。
EXEMPT_FILES = frozenset({"cairn/LOG.md"})
EXEMPT_PREFIXES = ("docs/decisions/", "verdicts/")

# 同一行講明「這東西沒了」時不算死引用。與上游 self-check 的作法一致。
GONE_WORDS = ("刪除", "刪掉", "不存在", "已廢", "退役", "原本", "曾經", "移除")

# 前面不得緊接路徑字元 —— 否則 `standards/scripts/self-check.py`（**別的 repo**
# 的腳本）會被當成本 repo 底下的同名檔。這支檢查第一次跑就在自己的說明裡踩到
# 這個誤報，而且緊接著又踩了第二次：把修正的理由寫成裸路徑，那本身就是一個
# 死引用。兩次都是它自己抓到的。
_REF = re.compile(r"(?<![\w/.-])(?:scripts|tests)/[A-Za-z0-9_./-]+?\.(?:py|sh)\b")


def _tracked_files() -> list[Path]:
    out = subprocess.run(("git", "-C", str(ROOT), "ls-files"),
                         capture_output=True, text=True, timeout=20, check=False)
    if out.returncode != 0:
        return []
    return [ROOT / line for line in out.stdout.splitlines() if line.strip()]


def _dangling() -> list[str]:
    hits: list[str] = []
    for path in _tracked_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel in EXEMPT_FILES or rel.startswith(EXEMPT_PREFIXES):
            continue
        if path.suffix not in SCAN_SUFFIXES:
            continue
        if not path.is_file():
            continue
        for lineno, line in enumerate(
                path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if any(word in line for word in GONE_WORDS):
                continue
            for ref in _REF.findall(line):
                if not (ROOT / ref).exists():
                    hits.append(f"{rel}:{lineno} → {ref}")
    return hits


def test_git_is_readable() -> None:
    """讀不到 git 就驗不了 —— 那不是通過，是量不到（鐵則第 7 條）。"""
    assert _tracked_files(), "git ls-files 讀不到任何檔案，這支檢查驗不了"


def test_no_dangling_script_references() -> None:
    """被指名的腳本必須存在。"""
    hits = _dangling()
    if not hits:
        return
    shown = "\n  ".join(hits[:10])
    more = f"\n  …另外 {len(hits) - 10} 處" if len(hits) > 10 else ""
    pytest.fail(
        f"{len(hits)} 處指向不存在的腳本：\n  {shown}{more}\n"
        "要嘛把檔案救回來（git show <commit>:<path>），要嘛把指過去的那句改掉。\n"
        "「A 的錯誤訊息叫你去跑 B」這種耦合不是 import，靜態分析看不到。")
