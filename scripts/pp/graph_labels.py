"""位置標記節點的樣式：哪些確定可刪、哪些只報不刪。

**為什麼量測與清除共用這一份**：2026-08-09 報告第八節提的清除正規式
（`^(equation|eq\\.|figure|fig\\.|table|section) ?[\\d.]+[a-z]?$`）比 `graph-shape.py`
量測用的字首清單窄很多。照那樣各寫一份，清完之後清除端說「39 個都刪了」、量測端
仍回報 27 個殘留，而**沒有任何東西會發現這兩個數字說的不是同一件事**。

審核台 2026-08-08 那六個洞就是這個病的變形：同一件事被算了兩次，計數那半有過濾
狀態、顯示那半沒有，兩段程式碼相距 800 行。修法不是補一行，是改成只有一個真相
來源 —— 這個檔就是位置標記的那個來源。

字首分兩組，差別只在字首，數字尾巴共用：

  CERTAIN   確定可刪。這些字單獨帶一個編號時只可能是「指向文件某處的指標」，
            不會是聲學概念。
  SUSPECT   只報不刪。PO 2026-08-09 裁決：`Region II`、`Zone IV`、`Mode ii`
            在分層介質與管道論文裡可能帶語意（`b_0` 與 `B_0` 未必同一個量，
            同一個道理），先列出來不動。

⚠ **不要加型別過濾。** 報告原本的構想是「正規式 ＋ 型別過濾」，但 2026-08-09
對正式庫實測，28 個 equation 族節點的型別是 concept 15、content 8、other 3、
method 1、data 1 —— **最大一族就是 `concept`**。加型別過濾等於把規則整條廢掉。
名字才是訊號，型別不是。
"""
from __future__ import annotations

import re
from typing import Final, Literal

# ── 確定可刪 ───────────────────────────────────────────────────────────────
#
# 2026-08-09 在正式庫實際命中的：equation、eq.、figure、table、reference。
# 其餘（eqn、formula、fig.、tab.、section、sec.、appendix、chapter、ref.）目前
# **命中 0 個**，是按同一族補上的 —— 它們現在不改變任何數字，之後有新文件進來時
# 才會生效。留著的成本是零，漏掉的代價是下一輪又要重查一次。
CERTAIN_PREFIXES: Final[tuple[str, ...]] = (
    "equation", "eqn", "eq", "formula",
    "figure", "fig",
    "table", "tab",
    "section", "sec",
    "appendix", "chapter",
    "reference", "ref",
)

# ── 只報不刪 ───────────────────────────────────────────────────────────────
#
# 這一組留在量測裡是刻意的：它們仍然是「規則 2a 沒守住」的證據，只是不能自動刪。
SUSPECT_PREFIXES: Final[tuple[str, ...]] = (
    "region", "zone", "mode", "model", "part",
    "case", "sample", "step", "type", "stage", "item", "note", "example",
    "phase", "panel", "scheme", "configuration", "config",
)

# 編號的尾巴。三種寫法都要涵蓋，缺一個就會漏掉一整族：
#
#   阿拉伯數字   `equation 22`、`table 16`
#   小數點分節   `equation 3.3`、`equation 8.36`  ← 教科書章節的編號方式
#   字母／範圍   `equation 8a`、`figure 4f`、`figure 5b-d`
#   羅馬數字     `table i`、`part III`
#
# **這四種是分兩次補齊的，過程記在這裡免得下次又來一輪。** 報告第八節提的
# `[\d.]+[a-z]?` 有小數點但沒有羅馬數字；`graph-shape.py` 原本的
# `[0-9ivxIVX]+[a-z)]?` 有羅馬數字但沒有小數點。2026-08-09 第一版只合併了後者，
# 清完 39 個之後在向量表裡撈到 `equation 3.3`、`figure 5b-d` 還在 —— 少了小數點
# 與字母範圍那兩種。擴充後對正式庫實跑，多抓 14 個、**新增的待裁定 0 個**。
_TAIL: Final[str] = r"[\s._\-#]*([0-9]+(\.[0-9]+)*([a-z](-[a-z])?)?|[ivxIVX]+)[)]?\s*$"

Bucket = Literal["certain", "suspect"]


def pattern(prefixes: tuple[str, ...]) -> str:
    """組出 POSIX ERE 樣式。給 Postgres 的 `~*` 用，也給 Python 的 `re` 用。

    兩邊共用同一個字串是刻意的：SQL 撈出來的集合與 Python 判斷的集合若不同，
    「撈到卻不刪」或「刪了沒撈到」都不會報錯。
    """
    return r"^(" + "|".join(prefixes) + r")" + _TAIL


CERTAIN_RE: Final[str] = pattern(CERTAIN_PREFIXES)
SUSPECT_RE: Final[str] = pattern(SUSPECT_PREFIXES)
ALL_RE: Final[str] = pattern(CERTAIN_PREFIXES + SUSPECT_PREFIXES)

_CERTAIN: Final[re.Pattern[str]] = re.compile(CERTAIN_RE, re.I)
_SUSPECT: Final[re.Pattern[str]] = re.compile(SUSPECT_RE, re.I)


def classify(name: str) -> Bucket | None:
    """這個實體名字屬於哪一組。都不是就回 None。

    `certain` 優先於 `suspect`：兩組字首不重疊，但萬一將來重疊了，
    「確定可刪」這個判斷必須是明示的，不能靠字典順序決定。
    """
    if _CERTAIN.match(name):
        return "certain"
    if _SUSPECT.match(name):
        return "suspect"
    return None
