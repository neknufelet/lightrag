#!/usr/bin/env python3
"""每日體檢的紅燈語意：一盞燈是「擋流程的紅」、「提醒的紅」，還是「驗不了」。

**為什麼要有這個檔。** `daily-check.sh` 原本把「任何非零」都當成失敗，於是
`latest.json` 的 `status` 天天是 `fail` —— 而其中一盞**永遠不會綠**：
`run-tests.sh` 在 dker 上回 3 的意思是「這台沒有 node，那支 JS 測試根本沒跑」，
它自己的訊息就寫著「驗不了 ≠ 失敗」。2026-08-16 實測，至少從 08-13 起每天都是 3。

**一個永遠會叫的判準等於沒有判準**，而它把真的紅燈一起淹掉了：同一天
`fresh_rc=2`（「跑著的是舊碼，晚 58.3 小時」）就埋在那一片紅裡面，沒有人看出來。

三態不是二態：「驗不了」既不是通過也不是失敗（鐵則 7 那一族）。當成通過，
「沒跑」會長得跟「跑過了」一樣；當成失敗，紅燈就永遠亮著。

**判準只有這一份。** `daily-check.sh`（決定 status 與離開碼）與審核台橫幅
（決定畫面上喊什麼）共用它 —— 兩個地方各寫一份的話，哪天有人只改一邊，
兩邊會打架而且沒有人會發現。這個專案已經被「兩條路」咬過（十二道閘門）。

用法：
    check-levels.py --at 20260817T000000 --commit c34dc41 \\
        --rc compat=5 --rc tests=3 ... \\
        --report compat=/data/lightrag/checks/compat-….json ...

    stdout  完整的 latest.json（呼叫端自己決定寫去哪）
    stderr  擋流程的紅、提醒的紅、驗不了，各自列出來
    離開碼  0 沒有擋流程的紅／1 有
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from typing import Final

BLOCK: Final[str] = "block"
WARN: Final[str] = "warn"
UNVERIFIED: Final[str] = "unverified"
OK: Final[str] = "ok"

#: 檢查名 → 一句話，寫進 stderr 讓讀 journal 的人不必回查腳本。
WHAT: Final[dict[str, str]] = {
    "compat": "契約斷言",
    "canary": "規則漂移",
    "scan": "∂ 誤讀探針",
    "parse": "解析碎字元",
    "coverage": "漏詞比對",
    "units": "systemd 單元與 repo 一致",
    "deploy": "stack 的 compose 與 repo 一致",
    "fresh": "跑著的是不是最新的碼",
    "tests": "測試入口",
}


def level_of(check: str, rc: int) -> str:
    """一個離開碼落在哪一態。不認得的檢查名一律當成擋流程的紅。

    **拒絕，不猜**（鐵則 1 那一族）：打錯字的檢查名如果落成「提醒」，它會安靜地
    從紅燈名單裡消失。不認得就當最嚴重的那一態，錯了會吵，不會沉默。
    """
    if rc == 0:
        return OK
    if check == "compat":
        # compat-check.py:1182 自己的離開碼：2 = 有 hard 斷言不過、5 = 只有 soft。
        # soft 是它設計上就標成「參考不擋」的那一類，所以 5 → 提醒。
        # 其餘非零是腳本自己掛了，那要當場處理。
        return WARN if rc == 5 else BLOCK
    if check == "tests":
        # run-tests.sh 回 3 的定義（它自己的檔頭）：「跑得動的都通過了，但這台
        # 驗不了全部」。那是**執行環境的限制**，不是缺陷 —— dker 上沒有 node，
        # 明天也不會有。回 1 才是真的有測試掛掉。
        return UNVERIFIED if rc == 3 else BLOCK
    if check in ("parse", "coverage"):
        # 兩把尺量的是**語料內容**，不是系統壞掉，而且都有大量已查證的假訊號：
        # `parse-check` 317 份裡 WARN 283（89%）、`coverage-check` 15 份超標裡
        # 逐份查證的 5 份全部是量錯。設計文件第一層的裁決是「尺不改，但紅燈只印
        # 警告不擋」（誤判太貴）。判斷交給 `kb-health-check` skill。
        return WARN
    # canary／scan／units／deploy／fresh：非零就是「跑著的東西跟它該是的樣子不一樣」。
    # ⚠ `scan` 回 3（沒有基準檔）**刻意留在擋流程那一態**，跟 tests 的 3 不同 ——
    # 那不是「這台驗不了」，是「有人要去建一份基準」，是做得完的事。
    return BLOCK


def classify(rcs: Mapping[str, int]) -> dict[str, str]:
    """全部檢查的三態。"""
    return {name: level_of(name, rc) for name, rc in rcs.items()}


def _names(levels: Mapping[str, str], want: str) -> list[str]:
    return sorted(name for name, lv in levels.items() if lv == want)


def summarise(rcs: Mapping[str, int]) -> dict[str, object]:
    """三態 ＋ 三份名單 ＋ status。status 只看擋流程的那一態。

    ⚠ 對外一律用 `xxx_rc` 這個名字 —— `latest.json` 的欄位、`levels` 的鍵、
    三份名單、審核台橫幅回的清單全部同一種寫法。輸入用裸名（`compat`）是因為
    `daily-check.sh` 那邊就是那樣傳的，轉換只在這一個地方做。
    """
    levels = {f"{name}_rc": lv for name, lv in classify(rcs).items()}
    blocking = _names(levels, BLOCK)
    return {
        "status": "fail" if blocking else "pass",
        "levels": levels,
        "blocking": blocking,
        "warnings": _names(levels, WARN),
        "unverified": _names(levels, UNVERIFIED),
    }


def messages(rcs: Mapping[str, int], reports: Mapping[str, str]) -> list[str]:
    """給人看的行。**三態都印** —— 「驗不了」不印出來就等於當成通過了。"""
    levels = classify(rcs)
    label = {BLOCK: "擋", WARN: "提醒", UNVERIFIED: "驗不了"}
    out: list[str] = []
    for tag in (BLOCK, WARN, UNVERIFIED):
        for name in _names(levels, tag):
            where = reports.get(name)
            tail = f" → {where}" if where else ""
            out.append(f"[{label[tag]}] {WHAT.get(name, name)} (rc={rcs[name]}){tail}")
    return out


def _pairs(raw: Sequence[str], what: str) -> dict[str, str]:
    got: dict[str, str] = {}
    for item in raw:
        name, sep, value = item.partition("=")
        if not sep or not name:
            raise SystemExit(f"--{what} 要寫成 名稱=值，收到 {item!r}")
        got[name] = value
    return got


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="每日體檢的紅燈語意（擋／提醒／驗不了）")
    ap.add_argument("--at", required=True, help="時間戳，直接寫進 latest.json")
    ap.add_argument("--commit", required=True, help="產生這筆結果的 commit")
    ap.add_argument("--detail", default="", help="compat 的完整報告路徑")
    ap.add_argument("--rc", action="append", default=[], metavar="名稱=離開碼")
    ap.add_argument("--report", action="append", default=[], metavar="名稱=路徑")
    a = ap.parse_args(argv)

    raw = _pairs(a.rc, "rc")
    try:
        rcs = {name: int(value) for name, value in raw.items()}
    except ValueError as exc:
        raise SystemExit(f"--rc 的值要是整數：{exc}") from exc
    reports = _pairs(a.report, "report")

    summary = summarise(rcs)
    # 舊欄位一個都不動 —— 讀 latest.json 的人（審核台橫幅、人）還在用它們，
    # 而升級當下那份檔案還是舊的（鐵則 2：不得無聲消失）。
    out: dict[str, object] = {"at": a.at, "status": summary["status"], "commit": a.commit}
    out.update({f"{name}_rc": rc for name, rc in rcs.items()})
    out["detail"] = a.detail
    out["levels"] = summary["levels"]
    out["blocking"] = summary["blocking"]
    out["warnings"] = summary["warnings"]
    out["unverified"] = summary["unverified"]

    print(json.dumps(out, ensure_ascii=False))
    for line in messages(rcs, reports):
        print(line, file=sys.stderr)
    return 1 if summary["blocking"] else 0


if __name__ == "__main__":
    sys.exit(main())
