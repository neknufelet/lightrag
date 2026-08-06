"""已查證紀錄：讓檢查工具在指標超標時自己說出「這個查過了，結論是什麼」。

**為什麼需要這支。** 同一個查證做過兩次了：`K Muffler` 的接地可疑率在舊語料
查過、結論寫進 CLAUDE.md；2026-08-05 跑 18 份體檢時 `L Capsules` 出現同一個
形狀，又逐個看了 22 個實體。沒有這個機制還會有第三次。

**為什麼不是「寫進某個文件」就好。** 寫進 CLAUDE.md 太重（那是每次開工必讀的
鐵則層），寫進 NEXT.md 不對（那是待辦），寫進 LOG 會被時間淹沒。這類結論的
特徵是**只在跑某支檢查、看到某個數字時才需要**——所以正確的送達方式是讓那支
檢查自己印出來，不要求任何人記得去哪裡找。與鐵則 6 同族：探針要在沒人問的
時候會響，而探針知道的事要在該說的時候自己說。

**過期的結論比沒有結論更危險。** 它會讓人跳過本來該做的查證。所以每筆紀錄都
帶 `at_verification`（查證當時的數字），現值偏離超過 `_DRIFT` 時本模組回報
「已查證但數字已變動」而不是原結論——把「這個放心」換成「這個要重查」。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

LOGGER = logging.getLogger(__name__)

RECORD = Path(__file__).resolve().parent.parent.parent / "tests" / "verified-findings.json"

# 現值與查證當時的相對偏離超過這個比例，就不再回報原結論。
# 0.5 不是調出來的：接地可疑率這種比例值在同一份文件上本來就會隨規則微調浮動幾個
# 百分點，抓太緊會讓每次微調都要重查；但**倍數級的變化一定是別的事**，那時候
# 舊結論就不該再被引用。
_DRIFT = 0.5


@dataclass(frozen=True)
class Finding:
    doc: str
    verified_on: str
    verdict: str
    summary: str
    root_cause: str
    sample: tuple[str, ...]
    source: str
    note: str
    at_verification: dict[str, float]
    stale_reason: str = ""

    def lines(self, indent: str = "  ") -> list[str]:
        """給 CLI 印的幾行。第一行永遠說清楚這是「已查證」還是「要重查」。"""
        if self.stale_reason:
            head = f"⚠ 已查證於 {self.verified_on}，但{self.stale_reason} —— **要重查**"
        else:
            head = f"已查證 {self.verified_on}：{self.summary}"
        out = [f"{indent}└ {head}"]
        if not self.stale_reason:
            if self.root_cause:
                out.append(f"{indent}  根因：{self.root_cause}")
            if self.sample:
                out.append(f"{indent}  例：{'、'.join(self.sample[:4])}")
        if self.source:
            out.append(f"{indent}  出處：{self.source}")
        if self.note:
            out.append(f"{indent}  註：{self.note}")
        return out


def _load(path: Path) -> list[dict]:
    if not path.is_file():
        # 缺檔不是錯 —— 這個機制是附加的，沒有它檢查照跑。但要留痕，
        # 否則「沒有紀錄」與「紀錄檔不見了」在畫面上長得一樣。
        LOGGER.warning("找不到已查證紀錄 %s，超標時不會附上前例", path)
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.warning("已查證紀錄讀不了（%s: %s），超標時不會附上前例", type(exc).__name__, exc)
        return []
    rows = data.get("findings")
    return rows if isinstance(rows, list) else []


def lookup(check: str, metric: str, doc: str, current: dict[str, float] | None = None,
           path: Path | None = None) -> Finding | None:
    """查這支檢查、這個指標、這份文件有沒有查證過。

    `doc` 用**關鍵字包含**比對而不是全等：紀錄裡寫 `K Muffler Acoustics`，
    實際 file_path 是 `K Muffler Acoustics.pdf`，而副檔名與路徑前綴都可能變。

    `current` 給了就檢查是否過期。沒給就直接回報原結論 —— 呼叫端沒有現值時
    不該由這裡假裝有。
    """
    for row in _load(path or RECORD):
        if row.get("check") != check or row.get("metric") != metric:
            continue
        key = str(row.get("doc") or "")
        if not key or key not in doc:
            continue

        at = {k: float(v) for k, v in (row.get("at_verification") or {}).items()
              if isinstance(v, (int, float))}
        stale = _drift_reason(at, current) if current else ""
        return Finding(
            doc=key,
            verified_on=str(row.get("verified_on") or "未記日期"),
            verdict=str(row.get("verdict") or ""),
            summary=str(row.get("summary") or ""),
            root_cause=str(row.get("root_cause") or ""),
            sample=tuple(str(s) for s in (row.get("sample") or [])),
            source=str(row.get("source") or ""),
            note=str(row.get("note") or ""),
            at_verification=at,
            stale_reason=stale,
        )
    return None


def _drift_reason(at: dict[str, float], current: dict[str, float]) -> str:
    """現值偏離查證當時太多時，回一句人話說明差在哪。"""
    for name, then in at.items():
        now = current.get(name)
        if now is None or then == 0:
            continue
        if abs(now - then) / abs(then) > _DRIFT:
            return f"{name} 從 {_fmt(then)} 變成 {_fmt(now)}"
    return ""


def _fmt(value: float) -> str:
    return f"{value:.1%}" if 0 < value < 1 else f"{value:g}"
