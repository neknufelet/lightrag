#!/usr/bin/env python3
"""實地演習：在部署機上**真的按一次測試鈕**，看燈會不會叫。

**為什麼 pytest 不夠。** 火災警報器的測試鈕是按在裝好的大樓裡，不是工廠裡。
近 30 天 17 次「燈說假話」裡，有兩族 pytest 永遠抓不到：

    7d4a878  金絲雀的比對函式在路徑搬家中丟失 —— 源碼「能」紅，但跑著的那份
             根本沒在比。單元測試餵的是替身，替身不會跟著搬家一起壞。
    4a6e533  基準被清空成 {} —— 那是**資料操作**，當天任何 pytest 都照樣全綠。

⇒ 演習用**真的那一支指令**、**真的那份資料**跑，只是餵它一個故意弄壞的情境，
然後看它會不會紅。不紅就是那盞燈壞了。

## 不准碰真的語料

⚠ 每一場演習都在**暫存資料根**上跑（`PP_DATA_ROOT` 或 `--root`），
需要真資料時只**唯讀複製**一份到暫存區。跑完就丟。
工單「對抗要打在判準上，不是打在資料上」那一節寫死了這條。

## 每一場都要有控制組

只驗「壞的會紅」等於沒驗 —— 一盞天天亮的燈跟不會亮的燈一樣沒用。
所以每場演習都跑兩次：弄壞的要紅、沒弄壞的要綠。

用法：
    ./scripts/drill.py              # 全部演習
    ./scripts/drill.py --list       # 只列出有哪幾場
    ./scripts/drill.py --only canary
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
PY_BIN = str(REPO / ".venv" / "bin" / "python")

#: 演習的離開碼。與其他檢查同一套語意（見 check-levels.py）。
DRILL_OK = 0
DRILL_LAMP_DEAD = 2      # 有燈該紅而沒紅，或不該紅而紅了
DRILL_CANT_RUN = 3       # 這台跑不了（缺真資料），驗不了 ≠ 通過


@dataclass(frozen=True)
class Outcome:
    """一場演習的結果。`ok=None` 是驗不了，不是通過。"""

    lamp_id: str
    ok: bool | None
    detail: str


def _run(argv: list[str], env_extra: dict[str, str] | None = None) -> tuple[int, str]:
    env = {**os.environ, **(env_extra or {})}
    p = subprocess.run(argv, capture_output=True, text=True, check=False, env=env)
    return p.returncode, (p.stdout + p.stderr)[-1500:]


def _one_real_bundle() -> tuple[Path, Path] | None:
    """production 裡最小的一個 bundle 與它的來源 PDF。**只讀。**"""
    from pp.paths import DataPaths, configured_data_root  # noqa: PLC0415

    paths = DataPaths(configured_data_root({}))
    parsed = paths.parsed_dir
    if not parsed.is_dir():
        return None
    bundles = sorted(parsed.glob("*.mineru_raw"),
                     key=lambda b: sum(f.stat().st_size for f in b.rglob("*") if f.is_file()))
    if not bundles:
        return None
    pdf = parsed / bundles[0].name.removesuffix(".mineru_raw")
    return (bundles[0], pdf) if pdf.is_file() else None


def drill_canary(tmp: Path) -> Outcome:
    """金絲雀：把基準裡的一個數字改掉，它必須指名道姓地紅。

    這一場專門守 `7d4a878`（比對函式在搬家中丟失，於是「等於沒在比」）。
    用真的 bundle 跑真的 `plan_one` —— 替身抓不到那種病。
    """
    got = _one_real_bundle()
    if got is None:
        return Outcome("daily:canary", None, "這台沒有 bundle，演習驗不了")
    src_bundle, src_pdf = got

    root = tmp / "data"
    parsed = root / "work" / "parsed"
    parsed.mkdir(parents=True)
    shutil.copytree(src_bundle, parsed / src_bundle.name)
    shutil.copy2(src_pdf, parsed / src_pdf.name)
    baseline = tmp / "baseline.json"
    env = {"PP_DATA_ROOT": str(root)}
    base_cmd = [PY_BIN, str(SCRIPTS / "postprocess.py"), "canary", "--baseline", str(baseline)]

    rc, out = _run([*base_cmd, "--update"], env)
    if rc != 0 or not baseline.is_file():
        return Outcome("daily:canary", False, f"連基準都立不起來（rc={rc}）：{out[-300:]}")

    # ── 控制組：沒動任何東西，必須綠 ──
    rc, out = _run(base_cmd, env)
    if rc != 0:
        return Outcome("daily:canary", False, f"沒動任何東西卻紅了（rc={rc}）：{out[-300:]}")

    # ── 對抗：把基準裡的一個數字改掉，必須紅並指名 ──
    rows = json.loads(baseline.read_text(encoding="utf-8"))
    name = next(iter(rows))
    rows[name]["items"] = int(rows[name].get("items") or 0) + 999
    baseline.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    rc, out = _run(base_cmd, env)
    if rc == 0:
        return Outcome("daily:canary", False,
                       "**基準被動過手腳，金絲雀還是說通過** —— 它沒有在比對")
    if "漂移" not in out or "items" not in out:
        return Outcome("daily:canary", False, f"紅了但沒說是哪一份的哪個數字：{out[-300:]}")
    return Outcome("daily:canary", True, f"改一個數字 → rc={rc}，指名 items")


def _bundle_with(tmp: Path, text: str) -> Path:
    """造一個最小的解析包，正文就是傳進來那一段。"""
    root = tmp / "data"
    raw = root / "work" / "parsed" / "drill.pdf.mineru_raw"
    raw.mkdir(parents=True, exist_ok=True)
    items = [{"type": "text", "text": text, "page_idx": 0,
              "bbox": [0, 0, 100, 100]}]
    (raw / "content_list.json").write_text(
        json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return root


def drill_parse_check(tmp: Path) -> Outcome:
    """碎字元偵測：餵一段真的碎掉的文字，它必須判 ERROR。"""
    mangled = "s d s e   o a sne a        s  t ros se a od   se  se "
    clean = ("The measured absorption coefficient of the porous layer increases "
             "monotonically with frequency across the whole octave band tested.")
    script = str(SCRIPTS / "parse-check.py")

    # ── 對抗：真的碎掉的一段（原文取自 2026-08-21 HMJ6IDEG_10 p23 的實例）──
    root = _bundle_with(tmp / "bad", mangled)
    rc_bad, out_bad = _run([PY_BIN, script, "--root", str(root), "--workspace", "drill"])
    # ── 控制組：通順的英文正文，**不該**被判成壞的 ──
    # 少了這一段就只驗了「壞的會紅」，而一盞天天亮的燈跟不會亮的一樣沒用。
    root = _bundle_with(tmp / "good", clean)
    rc_good, _ = _run([PY_BIN, script, "--root", str(root), "--workspace", "drill"])

    if rc_bad == 0:
        return Outcome("daily:parse", False,
                       f"**餵了碎字元它還是說沒事**（rc=0）：{out_bad[-300:]}")
    if rc_good != 0:
        return Outcome("daily:parse", False, f"乾淨的文字被誤判成壞的（rc={rc_good}）")
    return Outcome("daily:parse", True, f"碎字元 → rc={rc_bad}；乾淨的 → rc=0")


DRILLS: dict[str, Callable[[Path], Outcome]] = {
    "canary": drill_canary,
    "parse": drill_parse_check,
}


def main(argv: Sequence[str] | None = None) -> int:
    """`argv` 收得下的理由：測試要能真的呼叫這一支（而不是驗某個替身）。

    契約寫在 `pyproject.toml` 的 `proves_red` 說明：**證明必須執行發訊號的
    那一支，不是分類器。** 讀死 `sys.argv` 的話那件事在 pytest 裡做不到。
    """
    ap = argparse.ArgumentParser(description="實地演習：真的按一次測試鈕")
    ap.add_argument("--list", action="store_true", help="只列出有哪幾場")
    ap.add_argument("--only", help="只跑這一場")
    a = ap.parse_args(argv)

    if a.list:
        for name, fn in DRILLS.items():
            print(f"  {name:<10} {(fn.__doc__ or '').splitlines()[0]}")
        return DRILL_OK

    chosen = {a.only: DRILLS[a.only]} if a.only else DRILLS
    results: list[Outcome] = []
    for name, fn in chosen.items():
        with tempfile.TemporaryDirectory(prefix=f"drill-{name}-") as d:
            try:
                results.append(fn(Path(d)))
            except Exception as exc:  # noqa: BLE001 —— 演習掛掉本身就是紅燈
                results.append(Outcome(name, False, f"演習自己掛了：{type(exc).__name__}: {exc}"))

    mark = {True: "  ok  ", False: " FAIL ", None: "驗不了"}
    for r in results:
        print(f"{mark[r.ok]}  {r.lamp_id:<16} {r.detail}")

    dead = [r for r in results if r.ok is False]
    unver = [r for r in results if r.ok is None]
    print(f"\n演習 {len(results)} 場：叫得出來 {len(results) - len(dead) - len(unver)}、"
          f"**沒叫 {len(dead)}**、驗不了 {len(unver)}")
    # 分母：真的跑起來的演習場次。驗不了的不算 —— 算進去的話「全部驗不了」
    # 會跟「全部演習過」長得一樣。
    print(f"#scope {len(results) - len(unver)}")
    if dead:
        return DRILL_LAMP_DEAD
    return DRILL_CANT_RUN if unver else DRILL_OK


if __name__ == "__main__":
    sys.path.insert(0, str(SCRIPTS))
    sys.exit(main())
