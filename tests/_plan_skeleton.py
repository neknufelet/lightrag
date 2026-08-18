"""`postprocess.as_json()` 要吃的計畫骨架 —— **只有一份**。

兩個測試檔（`test_confirm_items.py`、`test_cover_ad_page.py`）都要對真的
`as_json` 下斷言，而 `as_json` 會讀計畫裡的每一段。骨架各寫一份的話，管線多接
一條規則時只會有一邊紅，另一邊安靜地繼續測一個不存在的形狀 —— 同
`tests/_scripts.py` 檔頭記的「同一件事兩個地方」。

⚠ **預設值是空殼，不是零值物件**：要測哪一段就傳哪一段進來，其餘留空。
"""
from __future__ import annotations

from types import SimpleNamespace


def _empty() -> SimpleNamespace:
    return SimpleNamespace(mutes=[], held=[], fired=False, reason="",
                           body_chars_before=0, body_chars_after=0,
                           ratio=0.0, suspicious=False)


def skeleton(**sections: object) -> dict:
    """`as_json` 需要的最小骨架。傳進來的那幾段蓋掉空殼。

    Args:
        sections: 要放真貨的段名 → 規則算出來的 Plan 物件（`title`、`cover_ad`…）。
    """
    base: dict = {
        "ctx": SimpleNamespace(doc_name="x.pdf", n_pages=1, items=[], page_size=(595, 842)),
        "noise": _empty(),
        "refs": _empty(),
        "title": _empty(),
        "cover_ad": _empty(),
        "margin": _empty(),
        "tables": SimpleNamespace(total=0, repairable=[], review=[]),
        "charts": SimpleNamespace(convert=[], dangling=[]),
        # `canary_row` 讀的是另外五格 —— 兩支都要餵，否則骨架只夠用一半。
        "latex": SimpleNamespace(fixes=[], summary=lambda: "", items=0, times=0,
                                 partials=0, glued=0, vetoed=[]),
    }
    base.update(sections)
    return base
