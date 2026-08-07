#!/usr/bin/env python3
"""Dockge stack 的部署與比對：repo 是 SSOT，`/opt/stacks/lightrag/` 是副本。

**為什麼需要這支。** 2026-08-07 決定用 Dockge 管理之後，`compose.yaml` 在兩個地方
各一份：repo（進版控）與 stack 目錄（Dockge 讀的那份）。當天那份副本是**手動 `cp`
過去的**，沒有任何東西守它們一致——而 Dockge 的 UI 可以直接編輯 compose，改完不會
有人知道 repo 那份已經不是真的了。

這是本專案踩過三次的形狀：同一類東西兩個地方，而漂移不報錯。

**為什麼是複製不是 symlink。** Dockge UI 能編輯 compose，寫下去就是改到 dker 的
git checkout ⇒ 下次 `git pull --ff-only` 直接失敗（dker 的 repo 是唯讀、只 pull）。

**為什麼 stack 目錄必須是真目錄。** 2026-08-07 之前 dockge 的 compose 有一條
`- <repo>:/opt/stacks/lightrag`，把 repo 掛進 Dockge 容器。宿主上那是空目錄，
但容器裡看到的是 repo 本身 ⇒ **UI 的「刪除」按鈕會刪掉 repo**，連 `.env` 一起。
那條掛載已移除，本支在 `install` 時會拒絕寫進一個 symlink 或掛載點。

**比對與安裝共用同一個讀取實作**（`_read`），理由與 `systemd-units.py` 相同：
分成兩份的話兩邊會各自演化出不同的「正確」，漂移偵測就變成偵測自己的 bug。

⚠ **執行者目前是弱的。** `verify` 只有在有人跑它、或 dker 上跑 `run-tests.sh` 時才
會執行——而 dker 的排程 2026-08-07 起全部停用。真正的解法是重建警報管道之後把
`daily-check` 接回來（見 `docs/NEXT.md`）。在那之前，這支至少讓「想查的時候查得到」，
而不是「只能靠記得」。

用法：
    deploy-stack.py verify            # 比對，不一致回 2
    deploy-stack.py diff              # 印出差在哪
    deploy-stack.py install           # repo → stack（會先印 diff 並要 --commit）
    deploy-stack.py install --commit  # 真的寫
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO / "compose.yaml"

# 換機器會變，所以可覆寫；預設是 dker 上的實際位置。
DEFAULT_STACK_DIR = Path("/opt/stacks/lightrag")


class StackError(RuntimeError):
    """部署前提不成立。**一律停下來，不猜。**"""


def _read(path: Path) -> str:
    """讀一份 compose。比對與安裝共用這裡，避免兩邊各自演化。"""
    if not path.is_file():
        raise StackError(f"{path} 不存在或不是普通檔案")
    return path.read_text(encoding="utf-8")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _guard_stack_dir(stack_dir: Path) -> None:
    """stack 目錄必須是真目錄。

    是 symlink 的話，Dockge UI 的刪除會沿著它刪到目標；而目標最可能是 repo
    ——那正是 2026-08-07 拆掉的那條掛載造成的事故形狀。
    """
    if stack_dir.is_symlink():
        raise StackError(
            f"{stack_dir} 是 symlink（指向 {stack_dir.resolve()}）。"
            "stack 目錄必須是真目錄——Dockge UI 的刪除會沿著它刪到目標。")
    if stack_dir.exists() and not stack_dir.is_dir():
        raise StackError(f"{stack_dir} 存在但不是目錄")


def _target(stack_dir: Path) -> Path:
    return stack_dir / "compose.yaml"


def cmd_verify(args: argparse.Namespace) -> int:
    stack_dir = Path(args.stack_dir)
    _guard_stack_dir(stack_dir)
    target = _target(stack_dir)
    if not target.exists():
        print(f"stack 還沒部署：{target} 不存在")
        print("  修法：deploy-stack.py install --commit")
        return 2

    src, dst = _read(SOURCE), _read(target)
    if src == dst:
        print(f"一致　sha256:{_sha(src)}　（{SOURCE.name} ↔ {target}）")
        return 0

    n = sum(1 for line in difflib.unified_diff(
        dst.splitlines(), src.splitlines(), lineterm="") if line[:1] in "+-")
    print(f"**不一致**　repo sha256:{_sha(src)}　stack sha256:{_sha(dst)}　差 {n} 行")
    print("  repo 是 SSOT。stack 那份若是在 Dockge UI 改的，先把改動搬回 repo，")
    print("  不要直接覆蓋——那會靜靜丟掉別人的修改。看差異：deploy-stack.py diff")
    return 2


def cmd_diff(args: argparse.Namespace) -> int:
    stack_dir = Path(args.stack_dir)
    _guard_stack_dir(stack_dir)
    target = _target(stack_dir)
    dst = _read(target) if target.exists() else ""
    lines = list(difflib.unified_diff(
        dst.splitlines(), _read(SOURCE).splitlines(),
        fromfile=str(target), tofile=str(SOURCE), lineterm=""))
    if not lines:
        print("沒有差異")
        return 0
    print("\n".join(lines))
    return 2


def cmd_install(args: argparse.Namespace) -> int:
    stack_dir = Path(args.stack_dir)
    _guard_stack_dir(stack_dir)
    target = _target(stack_dir)
    src = _read(SOURCE)

    if target.exists() and _read(target) == src:
        print(f"已經一致，沒有動作　sha256:{_sha(src)}")
        return 0

    cmd_diff(args)
    if not args.commit:
        print("\ndry-run，沒有寫任何檔案。確認無誤後加 --commit")
        return 0

    stack_dir.mkdir(parents=True, exist_ok=True)
    if target.exists():
        backup = stack_dir / "compose.yaml.bak"
        shutil.copy2(target, backup)
        print(f"舊版備份到 {backup}")
    shutil.copy2(SOURCE, target)
    print(f"已寫入 {target}　sha256:{_sha(src)}")
    print("  ⚠ 這只是把檔案放好。要讓它生效還要在 stack 目錄跑 docker compose up -d")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--stack-dir", default=str(DEFAULT_STACK_DIR),
                    help=f"Dockge 的 stack 目錄（預設 {DEFAULT_STACK_DIR}）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("verify", help="比對 repo 與 stack，不一致回 2")
    sub.add_parser("diff", help="印出差在哪")
    inst = sub.add_parser("install", help="repo → stack")
    inst.add_argument("--commit", action="store_true", help="真的寫檔（預設只印 diff）")
    a = ap.parse_args()

    try:
        return {"verify": cmd_verify, "diff": cmd_diff, "install": cmd_install}[a.cmd](a)
    except StackError as e:
        print(f"停下來：{e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
