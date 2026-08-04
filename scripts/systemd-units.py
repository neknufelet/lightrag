#!/usr/bin/env python3
"""systemd 單元的單一事實來源：渲染、安裝、比對。

**為什麼需要這支。** 六個單元檔原本只活在 `/etc/systemd/system/`，一行都沒進
版控。那不是決策，是漏的——單元檔寫在那裡就會動，於是沒有人想到它只有一份。
旁邊那個 `lightrag-daily-check.service.bak-20260804` 就是證據：手改過、留個備份、
繼續，改了什麼只剩備份檔知道。

漏掉的後果不只是搬家麻煩：

- `/etc` 掛了 → 每日檢查與冷備份一起消失
- 而它們正是「誰會報錯」的答案 → **消失的時候沒有人會通知你**
- 腳本 `daily-check.sh` / `backup-cold.sh` 都在 repo 裡（安全），
  但**觸發它們的 timer 不在**。腳本還在、排程沒了，看起來一切正常

鐵則 6 說探針要在沒人問的時候會響。在此之前，**探針本身沒有探針**。

**為什麼安裝與比對共用這一支。** 分成兩支的話，兩邊會各自演化出不同的
「正確」，而漂移偵測就變成偵測自己的 bug。渲染只有一個實作，`install` 寫出去、
`verify` 拿同一份渲染結果去對，差異一定是真的差異。

**佔位符**：`@REPO@`（checkout 路徑）、`@USER@`（跑腳本的使用者）、
`@NTFY_URL@`（警報位址，讀 `.env` 的 `NTFY_URL`）。三個都是換機器會變的東西，
寫死就等於這份 repo 只能在一台機器上用。

用法：
    systemd-units.py verify           # 比對 /etc 與 repo，不一致回 2
    systemd-units.py render <目錄>     # 渲染到目錄，不碰 /etc
    systemd-units.py install          # 渲染 → 寫入 /etc → daemon-reload → enable（要 sudo）
"""
from __future__ import annotations

import argparse
import difflib
import getpass
import logging
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UNIT_DIR = REPO / "deploy" / "systemd"
SYSTEM_DIR = Path("/etc/systemd/system")
# 開機時要 enable 的（另外兩個 -crashed 是 OnFailure 觸發的，不進 timers.target）
ENABLE = ("lightrag-daily-check.timer", "lightrag-cold-backup.timer")
DEFAULT_NTFY = "http://127.0.0.1:9800/lightrag"

LOGGER = logging.getLogger("systemd-units")


def ntfy_url(repo: Path) -> str:
    """從 `.env` 讀警報位址。

    與 `notify.sh` 用同一個鍵、同一個預設值 —— 兩邊分頭寫死的話，改了一邊
    另一邊會安靜地繼續打去舊位址。
    """
    env = repo / ".env"
    if env.is_file():
        with env.open(encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("NTFY_URL="):
                    value = line.split("=", 1)[1].strip()
                    if value:
                        return value
    return DEFAULT_NTFY


def render_all(repo: Path, user: str, url: str) -> dict[str, str]:
    """把 deploy/systemd/ 的每個檔套上這台機器的值。"""
    out: dict[str, str] = {}
    for path in sorted(UNIT_DIR.iterdir()):
        if path.suffix not in (".service", ".timer"):
            continue
        body = path.read_text(encoding="utf-8")
        out[path.name] = (body.replace("@REPO@", str(repo))
                              .replace("@USER@", user)
                              .replace("@NTFY_URL@", url))
    return out


def cmd_render(args: argparse.Namespace) -> int:
    target = Path(args.target)
    target.mkdir(parents=True, exist_ok=True)
    rendered = render_all(args.repo, args.user, args.ntfy)
    for name, body in rendered.items():
        (target / name).write_text(body, encoding="utf-8")
        print(f"  {target / name}")
    print(f"\n{len(rendered)} 個單元已渲染。repo={args.repo} user={args.user} ntfy={args.ntfy}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """比對已安裝的與 repo 渲染出來的。

    **缺檔與內容不符都算失敗**，而且分開報：缺檔是「這台機器根本沒裝」，
    內容不符是「有人手改了 /etc 沒回寫 repo」。兩者的處置不同。
    """
    rendered = render_all(args.repo, args.user, args.ntfy)
    if not rendered:
        print("✗ deploy/systemd/ 沒有任何單元檔 —— 母體是空的，這不是通過")
        return 2

    missing: list[str] = []
    differs: list[str] = []
    for name, want in sorted(rendered.items()):
        installed = SYSTEM_DIR / name
        if not installed.is_file():
            missing.append(name)
            continue
        got = installed.read_text(encoding="utf-8")
        if got != want:
            differs.append(name)
            if args.diff:
                print(f"\n── {name}")
                for line in difflib.unified_diff(
                        want.splitlines(), got.splitlines(),
                        fromfile=f"repo/{name}", tofile=f"/etc/{name}", lineterm=""):
                    print(f"   {line}")

    ok = len(rendered) - len(missing) - len(differs)
    print(f"systemd 單元：{ok}/{len(rendered)} 與 repo 一致")
    if missing:
        print(f"  ✗ 沒安裝 {len(missing)} 個：{', '.join(missing)}")
        print("    → 這台機器沒有這些排程。跑 `sudo scripts/systemd-units.py install`")
    if differs:
        print(f"  ✗ 內容不符 {len(differs)} 個：{', '.join(differs)}")
        print("    → 有人手改了 /etc 而沒回寫 repo。用 --diff 看差在哪，"
              "確認哪一邊是對的之後同步過去")
    if missing or differs:
        return 2

    # 裝了但沒 enable 等於沒有排程 —— 檔案存在會讓人以為它在跑。
    inactive = []
    for unit in ENABLE:
        result = subprocess.run(["systemctl", "is-enabled", unit],
                                capture_output=True, text=True, check=False)
        if result.stdout.strip() != "enabled":
            inactive.append(f"{unit}={result.stdout.strip() or result.stderr.strip()}")
    if inactive:
        print(f"  ✗ 單元檔對了但沒 enabled：{', '.join(inactive)}")
        print("    → 檔案在不等於排程在。`systemctl enable --now <unit>`")
        return 2
    print(f"  ✓ {', '.join(ENABLE)} 都是 enabled")
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    if os.geteuid() != 0:
        print("✗ install 要寫 /etc/systemd/system，請用 sudo")
        return 2
    rendered = render_all(args.repo, args.user, args.ntfy)
    for name, body in sorted(rendered.items()):
        target = SYSTEM_DIR / name
        old = target.read_text(encoding="utf-8") if target.is_file() else None
        if old == body:
            print(f"  = {name}（沒變）")
            continue
        target.write_text(body, encoding="utf-8")
        target.chmod(0o644)
        print(f"  {'~' if old is not None else '+'} {name}")
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    for unit in ENABLE:
        subprocess.run(["systemctl", "enable", "--now", unit], check=True)
        print(f"  ✓ enable --now {unit}")
    print(f"\n{len(rendered)} 個單元已安裝。repo={args.repo} user={args.user}")
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--repo", type=Path, default=REPO,
                        help="checkout 路徑，填進 @REPO@（預設：本腳本所在的 repo）")
    parser.add_argument("--user", default=None,
                        help="跑腳本的使用者，填進 @USER@（預設：目前使用者；"
                             "sudo 下讀 SUDO_USER）")
    parser.add_argument("--ntfy", default=None, help="警報位址，填進 @NTFY_URL@（預設讀 .env）")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("verify", help="比對 /etc 與 repo").add_argument(
        "--diff", action="store_true", help="印出逐行差異")
    sub.add_parser("render", help="渲染到目錄，不碰 /etc").add_argument("target")
    sub.add_parser("install", help="寫入 /etc 並 enable（要 sudo）")
    args = parser.parse_args()

    if args.user is None:
        # sudo 下 getuser() 會回 root，但單元要跑的是真正的使用者。
        args.user = os.environ.get("SUDO_USER") or getpass.getuser()
    if args.ntfy is None:
        args.ntfy = ntfy_url(args.repo)

    return {"verify": cmd_verify, "render": cmd_render, "install": cmd_install}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
