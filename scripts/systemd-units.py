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

**佔位符**：`@REPO@`（checkout 路徑）、`@USER@`（跑腳本的使用者）、`@WORKSPACE@`、
`@DATA_ROOT@`、`@STACK_DIR@`（Dockge 的 stack 目錄）、`@BIND_ADDR@`（開機時要等它
出現的位址）。都讀 `.env`。全部是換機器會變的東西，寫死就等於這份 repo 只能在
一台機器上用。

用法：
    systemd-units.py verify           # 比對 /etc 與 repo，不一致回 2
    systemd-units.py render <目錄>     # 渲染到目錄，不碰 /etc
    systemd-units.py install          # 渲染 → 寫入 /etc → daemon-reload → enable（要 sudo）
    systemd-units.py install --only lightrag-stack.service
                                      # 檔案全寫，但只 enable 指定的那個

⚠ 不帶 `--only` 會 enable **整個 ENABLE 清單**，包含 daily-check 與 cold-backup
的 timer。2026-08-07 的裁決是「重建後先決定警報走哪裡，再把排程重新 enable」
（`docs/NEXT.md`），所以在那之前要用 `--only`。
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
# 開機時要 enable 的。2026-08-07：兩個 -crashed 備援單元隨 ntfy 一起移除，
# 所以現在沒有 OnFailure 觸發的單元 —— 腳本掛掉只留在 journal，沒有人會被打斷。
ENABLE = ("lightrag-daily-check.timer", "lightrag-cold-backup.timer",
          "lightrag-intake.service",
          # 2026-08-07 加：沒有它，重開機之後 lightrag 與 kbapi 不會回來
          # （docker 比 tailscale 早起，綁 Tailscale 位址失敗）。實測過。
          "lightrag-stack.service",
          # 2026-08-19 加：資料根那顆碟掉了要停容器，否則 LightRAG 會在空目錄上
          # 建一個新的空知識庫**而且不報錯**。這個檔在此之前**不在版控裡** ——
          # 重建時跟著 /etc 一起被刪掉，只能照設計文件重寫。
          "lightrag-mount-guard.service")

# **刻意暫停**的單元：鍵是單元名，值是理由。
#
# 為什麼要跟「沒 enable」分開：警報管道 2026-08-08 才上線（紅燈顯示在審核台
# :9710）。一個預期中、沒人打算修的紅燈，會訓練人開始無視所有紅燈 ——
# `docs/judgement-flow.md` 記過「假警報會讓人開始忽略警報」。
#
# 但也不能靜靜跳過：那樣「刻意暫停」與「有人手滑關掉」又變成同一件事。
# 所以照樣報出來，只是說清楚是誰、為什麼，並且不算失敗。
# 2026-08-13 清空：`lightrag-cold-backup.timer` 的暫停條件已經滿足並移除。
# 當初暫停的理由是「backup-cold.sh 改過 DBS 陣列但一次都沒跑過，而它會停容器」。
# 2026-08-11 04:00 實跑完整一輪（停容器 → 抄 22,774 檔 4.18 GiB → restic
# 快照 bcc02bb0 → 開回來 → 清暫存 → 完成，rc=0），之後兩次因指紋未變而跳過。
# ⇒ 條件滿足，留在這裡只會讓「刻意暫停」與「有人手滑關掉」再度混在一起。
PAUSED: dict[str, str] = {}

LOGGER = logging.getLogger("systemd-units")


def env_value(repo: Path, key: str, default: str) -> str:
    """從 `.env` 讀一個鍵。

    多個地方要讀同一個鍵時走這裡，不要各自寫死 —— 分頭寫死的話，
    改了一邊另一邊會安靜地繼續用舊值。
    """
    env = repo / ".env"
    if env.is_file():
        with env.open(encoding="utf-8") as fh:
            for line in fh:
                if line.startswith(f"{key}="):
                    value = line.split("=", 1)[1].strip()
                    if value:
                        return value
    return default


def render_all(repo: Path, user: str,
               workspace: str = "acoustics_v2",
               data_root: str = "/data/lightrag",
               stack_dir: str = "/opt/stacks/lightrag",
               bind_addr: str = "100.87.88.7") -> dict[str, str]:
    """把 deploy/systemd/ 的每個檔套上這台機器的值。

    `@STACK_DIR@` 與 `@BIND_ADDR@` 是 2026-08-07 為 lightrag-stack.service 加的：
    前者是 Dockge 的 stack 目錄（compose 在那裡），後者是要等它出現的那個位址。
    兩個都是換機器會變的東西，寫死等於這份 repo 只能在一台機器上用。
    """
    out: dict[str, str] = {}
    for path in sorted(UNIT_DIR.iterdir()):
        if path.suffix not in (".service", ".timer"):
            continue
        body = path.read_text(encoding="utf-8")
        out[path.name] = (body.replace("@REPO@", str(repo))
                              .replace("@USER@", user)
                              .replace("@WORKSPACE@", workspace)
                              .replace("@DATA_ROOT@", data_root)
                              .replace("@STACK_DIR@", stack_dir)
                              .replace("@BIND_ADDR@", bind_addr))
    return out


def cmd_render(args: argparse.Namespace) -> int:
    target = Path(args.target)
    target.mkdir(parents=True, exist_ok=True)
    rendered = render_all(args.repo, args.user, args.workspace, args.data_root,
                          args.stack_dir, args.bind_addr)
    for name, body in rendered.items():
        (target / name).write_text(body, encoding="utf-8")
        print(f"  {target / name}")
    print(f"\n{len(rendered)} 個單元已渲染。repo={args.repo} user={args.user}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """比對已安裝的與 repo 渲染出來的。

    **缺檔與內容不符都算失敗**，而且分開報：缺檔是「這台機器根本沒裝」，
    內容不符是「有人手改了 /etc 沒回寫 repo」。兩者的處置不同。
    """
    rendered = render_all(args.repo, args.user, args.workspace, args.data_root,
                          args.stack_dir, args.bind_addr)
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
    inactive: list[str] = []
    paused_off: list[str] = []
    paused_but_on: list[str] = []
    for unit in ENABLE:
        result = subprocess.run(["systemctl", "is-enabled", unit],
                                capture_output=True, text=True, check=False)
        state = result.stdout.strip() or result.stderr.strip()
        if unit in PAUSED:
            # 暫停中卻是 enabled ⇒ 有人開回來了但沒清掉 PAUSED，也要講。
            (paused_but_on if state == "enabled" else paused_off).append(unit)
            continue
        if state != "enabled":
            inactive.append(f"{unit}={state}")

    for unit in paused_off:
        print(f"  ⏸ {unit} 刻意暫停：{PAUSED[unit]}")
    for unit in paused_but_on:
        print(f"  ✗ {unit} 列在 PAUSED 卻是 enabled —— 恢復之後要從 PAUSED 移除，"
              "否則下次真的暫停時沒有人會發現")
    if inactive:
        print(f"  ✗ 單元檔對了但沒 enabled：{', '.join(inactive)}")
        print("    → 檔案在不等於排程在。`systemctl enable --now <unit>`")
    if inactive or paused_but_on:
        return 2
    expected = [u for u in ENABLE if u not in PAUSED]
    print(f"  ✓ {', '.join(expected)} 都是 enabled"
          + (f"（另有 {len(paused_off)} 個刻意暫停）" if paused_off else ""))
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    if os.geteuid() != 0:
        print("✗ install 要寫 /etc/systemd/system，請用 sudo")
        return 2
    rendered = render_all(args.repo, args.user, args.workspace, args.data_root,
                          args.stack_dir, args.bind_addr)
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

    # `--only` 存在的理由：ENABLE 裡有 daily-check 與 cold-backup 的 timer，而
    # 2026-08-07 的裁決是「重建後先決定警報走哪裡，再把排程重新 enable」
    # （docs/NEXT.md）。不分開的話，裝一個新單元會順手把三個沒講好的東西也開起來
    # ——那是「順手做了沒講」，本專案抱怨最多的一種。
    wanted = tuple(args.only) if args.only else ENABLE
    unknown = [u for u in wanted if u not in rendered]
    if unknown:
        print(f"✗ 不認得這些單元：{', '.join(unknown)}", file=sys.stderr)
        return 2

    for unit in wanted:
        subprocess.run(["systemctl", "enable", "--now", unit], check=True)
        print(f"  ✓ enable --now {unit}")
    skipped = [u for u in ENABLE if u not in wanted]
    if skipped:
        # 收合輸出時必須報出「幾項沒做」——否則「沒印出來」跟「沒跳過」長得一樣。
        #
        # **但要分清楚「這次沒動」與「現在是停用的」**：2026-08-08 實測，原本寫
        # 「檔案已寫入但沒有 enable」，而清單裡的 lightrag-stack.service 其實上一輪
        # 就 enable 了 —— 那句話讀起來像它是停用的。查一次真實狀態再講。
        for unit in skipped:
            state = subprocess.run(["systemctl", "is-enabled", unit],
                                   capture_output=True, text=True, check=False)
            now = state.stdout.strip() or "unknown"
            print(f"  · 這次沒動 {unit}（目前 {now}）")
    print(f"\n{len(rendered)} 個單元的檔案已安裝，{len(wanted)} 個已啟用。"
          f"repo={args.repo} user={args.user}")
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--repo", type=Path, default=REPO,
                        help="checkout 路徑，填進 @REPO@（預設：本腳本所在的 repo）")
    parser.add_argument("--user", default=None,
                        help="跑腳本的使用者，填進 @USER@（預設：目前使用者；"
                             "sudo 下讀 SUDO_USER）")
    parser.add_argument("--workspace", default=None, help="填進 @WORKSPACE@（預設讀 .env）")
    parser.add_argument("--data-root", default=None, help="填進 @DATA_ROOT@（預設讀 .env）")
    parser.add_argument("--stack-dir", default=None,
                        help="填進 @STACK_DIR@，Dockge 的 stack 目錄（預設讀 .env）")
    parser.add_argument("--bind-addr", default=None,
                        help="填進 @BIND_ADDR@，開機時要等它出現的位址（預設讀 .env）")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("verify", help="比對 /etc 與 repo").add_argument(
        "--diff", action="store_true", help="印出逐行差異")
    sub.add_parser("render", help="渲染到目錄，不碰 /etc").add_argument("target")
    inst = sub.add_parser("install", help="寫入 /etc 並 enable（要 sudo）")
    inst.add_argument("--only", action="append", metavar="UNIT",
                      help="只 enable 指定的單元（可重複）。檔案仍會全部寫入。"
                           "不給就照 ENABLE 清單全開")
    args = parser.parse_args()

    if args.user is None:
        # sudo 下 getuser() 會回 root，但單元要跑的是真正的使用者。
        args.user = os.environ.get("SUDO_USER") or getpass.getuser()
    if args.workspace is None:
        args.workspace = env_value(args.repo, "WORKSPACE", "acoustics_v2")
    if args.data_root is None:
        args.data_root = env_value(args.repo, "DATA_ROOT", "/data/lightrag")
    if args.stack_dir is None:
        args.stack_dir = env_value(args.repo, "STACK_DIR", "/opt/stacks/lightrag")
    if args.bind_addr is None:
        args.bind_addr = env_value(args.repo, "BIND_ADDR", "100.87.88.7")

    return {"verify": cmd_verify, "render": cmd_render, "install": cmd_install}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
