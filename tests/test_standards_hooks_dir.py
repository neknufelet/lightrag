"""standards-check 的 hook 路徑在 worktree 裡也要找對（2026-10-14 誤報過）。"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load_hooks_dir() -> Callable[[Path], Path]:
    spec = importlib.util.spec_from_file_location("standards_check", REPO / "scripts" / "standards-check.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclass 要在 sys.modules 裡找得到自己
    spec.loader.exec_module(mod)
    return mod.hooks_dir


def test_hooks_dir_matches_git(tmp_path: Path) -> None:
    hooks_dir = _load_hooks_dir()
    main = tmp_path / "main"
    subprocess.run(["git", "init", "-q", str(main)], check=True)
    subprocess.run(["git", "-C", str(main), "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "-q", "--allow-empty", "-m", "init"], check=True)
    wt = tmp_path / "wt"
    subprocess.run(["git", "-C", str(main), "worktree", "add", "-q", str(wt)], check=True)
    assert (wt / ".git").is_file()                      # worktree 的 .git 是檔案
    assert hooks_dir(wt) == (main / ".git" / "hooks").resolve()
    assert hooks_dir(main) == (main / ".git" / "hooks").resolve()
