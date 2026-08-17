#!/usr/bin/env python3
"""把 dker 資料區的人工裁定拉回 coder 的 repo，好進版控。

**為什麼需要這支。** 服務跑在 dker，人工裁定（拆章勾選、體檢表…）生在那裡；
而 dker 的 repo 唯讀只 `git pull`，只有 coder 有提交權。中間沒有東西搬的話，
裁定就躺在 dker 上永遠上不了 GitHub。

**這個坑踩過。** 體檢表一度 dker 318 份而 git 只有 20 份 —— 備份只做到 6%，
而且沒有任何地方會叫。拆章勾選 2026-08-17 差點重蹈：第一版直接把紀錄寫進 dker
的 repo 目錄，實測 `git status` 只多一個 `??`，那個檔哪都去不了。

**只准變多。** 這支永不刪除 repo 裡的副本：dker 上不見了可能是被歸檔、被誤刪、
或路徑打錯，三種的處置完全不同。刪掉等於用一個猜測毀掉唯一的備份。

用法（在 coder 上跑）：

    scripts/pull-verdicts.py                 # 看會搬什麼，不動手
    scripts/pull-verdicts.py --apply         # 真的搬
    scripts/pull-verdicts.py --host florian-dker --apply

搬完之後**自己看一眼再提交** —— 這支刻意不碰 git。
"""
from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOGGER = logging.getLogger("pull-verdicts")

#: 要搬哪幾種裁定。左邊是 dker 資料區底下的相對路徑，右邊是 repo 底下的。
#: 兩邊名字刻意不同（`records/` vs `verdicts/records/`），照各自現有的慣例。
KINDS: dict[str, tuple[str, str]] = {
    "chapter-splits": ("records/chapter-splits", "verdicts/records/chapter-splits"),
    # 確認清單：人勾好「這段不要進知識庫」的決定。**重跑規則產不出來**，
    # 所以跟其他人工裁定一樣要進版控 —— 少了這一行，live 檔會安靜地只留在
    # dker 上，而 dker 的 repo 推不出去，等於備份沒做。
    "confirm-lists": ("records/confirm-lists", "verdicts/records/confirm-lists"),
    "ledger": ("records/ledger", "verdicts/records/ledger"),
}

DEFAULT_HOST = "florian-dker"
DEFAULT_DATA_ROOT = "/data/lightrag"


@dataclass
class PullResult:
    """一種裁定搬完的結果。

    Attributes:
        added: repo 原本沒有、這次複製過去的。
        updated: 兩邊都有但內容不同、以 dker 為準覆蓋的。
        unchanged: 內容一樣、沒動的份數。
        only_local: **repo 有而 dker 沒有的** —— 留著沒刪，只報出來。
    """

    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: int = 0
    only_local: list[str] = field(default_factory=list)


def sync_records(src: Path, dst: Path, *, apply: bool = True) -> PullResult:
    """把 ``src`` 的 ``*.json`` 同步到 ``dst``。**只加不刪。**

    Args:
        src: 來源目錄（從 dker 抓下來的暫存副本）。
        dst: repo 裡的目的地。
        apply: ``False`` 時只算不寫（dry-run）。

    Returns:
        這次動了什麼。

    Raises:
        FileNotFoundError: ``src`` 不存在 —— **不當成「那邊沒有東西」**。
            當成空的話這支會安靜地報「沒有新的」，而真正的原因是路徑打錯或沒掛上。
    """
    if not src.is_dir():
        raise FileNotFoundError(f"來源目錄不存在：{src}（不是「那邊沒有東西」，是讀不到）")
    dst.mkdir(parents=True, exist_ok=True)

    result = PullResult()
    remote = {p.name: p for p in sorted(src.glob("*.json"))}
    local = {p.name: p for p in sorted(dst.glob("*.json"))}

    for name, path in remote.items():
        body = path.read_bytes()
        target = dst / name
        if name not in local:
            result.added.append(name)
        elif target.read_bytes() != body:
            result.updated.append(name)
        else:
            result.unchanged += 1
            continue
        if apply:
            target.write_bytes(body)

    result.only_local = [name for name in local if name not in remote]
    return result


def is_missing_remote_dir(stderr: str) -> bool:
    """rsync 的失敗是不是「遠端根本還沒有那個目錄」。

    **這跟「連不上」是兩件事。** 第一次還沒有人按過確認時，
    `records/chapter-splits/` 本來就不存在；把它報成錯誤的話每次跑都會紅一次，
    而天天都在的紅會讓人不再看它 —— 這個專案 2026-08-17 才因為同一個形狀，
    讓真的紅燈埋在假紅裡一整天。連不上、沒權限則照樣要紅。
    """
    return "No such file or directory" in stderr and "change_dir" in stderr


def fetch(host: str, remote_dir: str, into: Path) -> None:
    """用 rsync 把 dker 上的目錄抓進本機暫存區。

    遠端沒有那個目錄時 rsync 回非零 —— 這裡讓它往上冒，由呼叫端當成
    「這一種還沒有東西」處理，而不是靜靜跳過。
    """
    into.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["rsync", "-a", "--include=*.json", "--include=*/", "--exclude=*",
         f"{host}:{remote_dir}/", f"{into}/"],
        check=True, capture_output=True, text=True, timeout=300,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default=DEFAULT_HOST, help="部署機的 ssh 名稱")
    ap.add_argument("--data-root", default=DEFAULT_DATA_ROOT, help="部署機上的資料根")
    ap.add_argument("--repo", type=Path, default=REPO, help="本機 repo 根")
    ap.add_argument("--kind", choices=sorted(KINDS), action="append",
                    help="只搬這一種（可重複）；不給就全部")
    ap.add_argument("--apply", action="store_true", help="真的寫入；不給就只看不動手")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    kinds = args.kind or sorted(KINDS)
    exit_code = 0

    with tempfile.TemporaryDirectory(prefix="pull-verdicts-") as tmp:
        for kind in kinds:
            remote_sub, repo_sub = KINDS[kind]
            staged = Path(tmp) / kind
            try:
                fetch(args.host, f"{args.data_root}/{remote_sub}", staged)
            except subprocess.CalledProcessError as exc:
                stderr = (exc.stderr or "").strip()
                if is_missing_remote_dir(stderr):
                    # 還沒有人按過確認，目錄本來就不存在。這是「還沒有東西」，
                    # 不是「出事了」—— 報成紅的話每次跑都紅，紅久了就沒人看。
                    LOGGER.info("%s：dker 上還沒有這個目錄（還沒有人存過）", kind)
                    continue
                # 連不上、沒權限這些照樣紅。**不要當成「沒有新的」** ——
                # 那正是體檢表那次 6% 備份沒有人發現的原因。
                LOGGER.error("%s：抓不到 %s:%s/%s —— %s",
                             kind, args.host, args.data_root, remote_sub, stderr)
                exit_code = 1
                continue

            result = sync_records(staged, args.repo / repo_sub, apply=args.apply)
            LOGGER.info("%s：新增 %d、更新 %d、沒變 %d、repo 才有 %d",
                        kind, len(result.added), len(result.updated),
                        result.unchanged, len(result.only_local))
            for name in result.added:
                LOGGER.info("    ＋ %s", name)
            for name in result.updated:
                LOGGER.info("    ~ %s", name)
            for name in result.only_local:
                LOGGER.info("    ? %s（dker 上沒有，留著沒刪）", name)

    if not args.apply:
        LOGGER.info("\n以上只是預演，沒有寫任何檔。真的要搬請加 --apply。")
    else:
        LOGGER.info("\n搬完了。**自己看一眼再提交** —— 這支刻意不碰 git。")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
