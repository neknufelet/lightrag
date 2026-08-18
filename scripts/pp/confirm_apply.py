"""把人在確認清單勾的「這段不要」，變成真的消音。

⚠ **沒有這一層，確認清單是假的**：人勾完、畫面說存好了、抽取照樣把那幾段送
進去。那比沒有確認清單更糟 —— 人以為自己做了決定。

做法刻意是「把人勾的那幾項從 ``held`` 搬進 ``mutes``」，而不是另外寫一條消音
路徑。搬過去之後就走既有的 ``apply_to_items``：還原（``_pp_original_text``）、
計數、守衛全部跟規則消音一致。**同一件事不要有兩條路。**

⚠ **比例守衛看不到人加的這幾項**（`ratio` 是 `plan()` 當下算的）。那是刻意的：
守衛防的是「規則圈太大、吃到正文」，而人勾的東西按定義已經被人看過了。
`pp/apply.py` 另有 `--acknowledged-ratio` 給「人看過消音清單」的情況。
"""
from __future__ import annotations

import logging
from collections.abc import Container
from typing import Protocol


class _Row(Protocol):
    """消音清單的一列。三條規則各有自己的 dataclass，共通的只有 `index`。"""

    index: int


class _Sectioned(Protocol):
    """一段的計畫：規則已經決定要消的、以及不敢決定留給人的。

    ⚠ 用 Protocol 而不是 `Any` —— `layout_noise.NoisePlan` 與
    `title_block.TitlePlan` 是兩個不同的類別，共通的只有這兩個欄位。
    宣告成 `Any` 的話，欄位名打錯到執行期才會知道。
    """

    mutes: list
    held: list

logger = logging.getLogger(__name__)


def _move(plan: _Sectioned, section: str, suppressed: Container[str]) -> tuple[int, set[str]]:
    """一段裡面，把人勾的從 ``held`` 搬到 ``mutes``。回 ``(搬了幾項, 用到的 key)``。"""
    moved, used = 0, set()
    keep = []
    for row in plan.held:
        key = f"{section}:{row.index}"
        if key in suppressed:
            plan.mutes.append(row)
            used.add(key)
            moved += 1
        else:
            keep.append(row)
    plan.held[:] = keep
    return moved, used


def honour(noise: _Sectioned, title: _Sectioned, suppressed: Container[str],
           *, report_missing: bool = False) -> int | tuple[int, list[str]]:
    """把人勾要丟的那幾項搬進消音清單。

    Args:
        noise: :func:`pp.rules.layout_noise.plan` 的結果。
        title: :func:`pp.rules.title_block.plan` 的結果。
        suppressed: 人勾起來（＝要丟）的 ``section:index``。
        report_missing: 順便回報「勾了但找不到對應項目」的那些。

    Returns:
        搬了幾項；``report_missing`` 為真時回 ``(搬了幾項, 找不到的 key 清單)``。

    ⚠ **靠 ``section:index`` 分辨，不能只看 index** —— 兩段的 index 各自從 0
    起算，只看 index 的話 ``noise:1`` 與 ``title:1`` 會撞在一起，勾一個消掉兩個。

    ⚠ **重跑安全**：搬走的已經不在 ``held`` 裡，所以第二次跑回 0。`pp/apply.py`
    本來就可以重跑（協調者會重試），而 ``_pp_original_text`` 只記第一次 ——
    重複搬會讓計數說謊。
    """
    total, used = 0, set()
    for plan, section in ((noise, "noise"), (title, "title")):
        moved, hit = _move(plan, section, suppressed)
        total += moved
        used |= hit

    missing = sorted(k for k in suppressed if k not in used) if report_missing else []
    if missing:
        # ⚠ **找不到要講出來，不要安靜忽略。** 這會發生在重新解析之後：紀錄是
        # 舊的、項目換了。安靜忽略等於人的決定無聲消失（藍桶第 2 條）。
        logger.warning("確認紀錄裡有 %d 項找不到對應的段落（可能是重新解析過）：%s",
                       len(missing), "、".join(missing[:5]))
    if total:
        logger.info("依人工確認額外消音 %d 項", total)
    return (total, missing) if report_missing else total
