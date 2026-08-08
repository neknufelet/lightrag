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

**`freshness` 守的是另一半：檔案放對了，不代表跑著的是它。**
2026-08-08 實測 dker 落後 origin 3 個 commit（含一個 `fix(intake)`），而容器
healthy、端點會回應、測試也過——**跑舊碼完全沒有外顯症狀**。根因是「部署」不是
一個動作而是一串要靠人記得的動作：pull、restart、確認新碼真的在跑。漏掉任何一步
都不會有人吭聲。只做 pull + restart 而不驗證，是同一個坑換位置再踩。

用法：
    deploy-stack.py verify            # 比對 compose，不一致回 2
    deploy-stack.py freshness         # 跑著的是不是最新的碼，不是回 2
    deploy-stack.py diff              # 印出差在哪
    deploy-stack.py install           # repo → stack（會先印 diff 並要 --commit）
    deploy-stack.py install --commit  # 真的寫
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO / "compose.yaml"

# 換機器會變，所以可覆寫；預設是 dker 上的實際位置。
DEFAULT_STACK_DIR = Path("/opt/stacks/lightrag")

# 部署機唯一該有的分支。落後它就是「跑舊碼」。
UPSTREAM_REF = "origin/master"

# compose 給自己容器打的專案標籤。用它列容器**而不是寫死名字**——名字含
# workspace（`kbapi-acoustics_v2`），寫死就會在改 workspace 時安靜地少檢查一台。
COMPOSE_PROJECT = "lightrag"

# 改動哪些路徑之後，容器要重啟才會生效。
#
# 依據是 compose.yaml 的掛載，不是猜的：**只有 kbapi 掛了
# `${REPO_DIR}/scripts:/app/scripts:ro`**，其餘三個跑 baked image ＋ 資料目錄。
# 所以 `scripts/` 改了跟 lightrag／postgres／infinity 無關。
#
# 為什麼要分開：拿 HEAD 當基準的話，一個純文件 commit 就會讓四個容器全部轉紅。
# 「一個預期中、沒人打算修的紅燈，會訓練人開始無視所有紅燈」——這條寫在
# systemd-units.py:63，這裡是同一個道理。
DEPLOY_PATHS_DEFAULT: tuple[str, ...] = ("compose.yaml",)
DEPLOY_PATHS_BY_PREFIX: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("kbapi-", ("compose.yaml", "scripts")),
)


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


def _run(argv: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    """跑一個外部指令。不丟例外——呼叫端要能分辨「指令失敗」與「答案是壞的」。"""
    return subprocess.run(argv, capture_output=True, text=True,
                          timeout=timeout, check=False)


def _git(*args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return _run(["git", "-C", str(REPO), *args], timeout=timeout)


def _rfc3339_to_epoch(value: str) -> float:
    """docker 的 `StartedAt` 是奈秒精度的 RFC3339，`fromisoformat` 只吃到微秒。

    直接丟進去會 ValueError，而那個例外看起來像「docker 壞了」而不是「多了三位
    小數」——所以在這裡把它截掉，不要讓呼叫端去猜。
    """
    text = re.sub(r"(\.\d{6})\d+", r"\1", value.strip().replace("Z", "+00:00"))
    return datetime.fromisoformat(text).timestamp()


def _deploy_paths_for(container: str) -> tuple[str, ...]:
    for prefix, paths in DEPLOY_PATHS_BY_PREFIX:
        if container.startswith(prefix):
            return paths
    return DEPLOY_PATHS_DEFAULT


def _last_commit_epoch(paths: tuple[str, ...]) -> float | None:
    """最後一個動到這些路徑的 commit 時間。沒有任何 commit 動過就回 None。"""
    p = _git("log", "-1", "--format=%ct", "--", *paths)
    value = p.stdout.strip()
    return float(value) if p.returncode == 0 and value else None


def _project_containers() -> list[tuple[str, float]]:
    """本專案跑著的容器與各自的啟動時間。"""
    p = _run(["docker", "ps", "--filter",
              f"label=com.docker.compose.project={COMPOSE_PROJECT}",
              "--format", "{{.Names}}"])
    if p.returncode != 0:
        raise StackError(f"docker ps 失敗：{p.stderr.strip()[:200]}")
    names = [n for n in p.stdout.split() if n]
    out: list[tuple[str, float]] = []
    for name in names:
        q = _run(["docker", "inspect", "-f", "{{json .State.StartedAt}}", name])
        if q.returncode != 0:
            raise StackError(f"docker inspect {name} 失敗：{q.stderr.strip()[:200]}")
        out.append((name, _rfc3339_to_epoch(json.loads(q.stdout))))
    return out


def cmd_freshness(args: argparse.Namespace) -> int:
    """跑著的東西是不是最新的碼。三條各自獨立，全綠才回 0。"""
    problems: list[str] = []

    # ── 1. 落後版控 ──────────────────────────────────────────────
    fetched = _git("fetch", "--quiet", "origin", timeout=120)
    if fetched.returncode != 0:
        # 抓不到就是「不知道」，不是「沒落後」。三態的正確用法。
        problems.append(f"git fetch 失敗，落後與否無法判斷：{fetched.stderr.strip()[:200]}")
    else:
        p = _git("rev-list", "--count", f"HEAD..{UPSTREAM_REF}")
        behind = int(p.stdout.strip() or 0) if p.returncode == 0 else -1
        if behind != 0:
            problems.append(f"落後 {UPSTREAM_REF} {behind} 個 commit —— 跑的是舊碼")
        else:
            print(f"版控　與 {UPSTREAM_REF} 同步")

    # ── 2. 工作區乾淨 ────────────────────────────────────────────
    # 部署機的 repo 是唯讀、只 pull。有未提交的改動就代表有人手改了檔案，
    # 那份改動不在版控裡、沒有人審過，而且下次 `pull --ff-only` 會直接失敗。
    p = _git("status", "--porcelain")
    dirty = [ln for ln in p.stdout.splitlines() if ln.strip()]
    if dirty:
        problems.append(f"工作區有 {len(dirty)} 項未提交改動（部署機應唯讀）："
                        f"{[ln[3:] for ln in dirty[:5]]}")
    else:
        print("工作區　乾淨")

    # ── 3. 容器比它該跑的碼新 ────────────────────────────────────
    for name, started in sorted(_project_containers()):
        paths = _deploy_paths_for(name)
        commit_at = _last_commit_epoch(paths)
        if commit_at is None:
            problems.append(f"{name}：查不到 {list(paths)} 的最後 commit")
            continue
        lag_h = (commit_at - started) / 3600
        if started < commit_at:
            problems.append(
                f"{name} 啟動於 {datetime.fromtimestamp(started):%m-%d %H:%M}，"
                f"但 {list(paths)} 的最後 commit 是 "
                f"{datetime.fromtimestamp(commit_at):%m-%d %H:%M}（晚 {lag_h:.1f} 小時）"
                " —— 檔案更新了，跑著的還是舊的，要重啟")
        else:
            print(f"{name}　啟動晚於 {list(paths)} 的最後 commit")

    if problems:
        print()
        for line in problems:
            print(f"**{line}**")
        return 2
    return 0


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
    sub.add_parser("freshness", help="跑著的是不是最新的碼，不是回 2")
    sub.add_parser("diff", help="印出差在哪")
    inst = sub.add_parser("install", help="repo → stack")
    inst.add_argument("--commit", action="store_true", help="真的寫檔（預設只印 diff）")
    a = ap.parse_args()

    try:
        return {"verify": cmd_verify, "freshness": cmd_freshness,
                "diff": cmd_diff, "install": cmd_install}[a.cmd](a)
    except StackError as e:
        print(f"停下來：{e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
