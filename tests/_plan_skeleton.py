"""`postprocess.as_json()` 要吃的計畫骨架 —— **只有一份**。

兩個測試檔（`test_confirm_items.py`、`test_cover_ad_page.py`）都要對真的
`as_json` 下斷言，而 `as_json` 會讀計畫裡的每一段。骨架各寫一份的話，管線多接
一條規則時只會有一邊紅，另一邊安靜地繼續測一個不存在的形狀 —— 同
`tests/_scripts.py` 檔頭記的「同一件事兩個地方」。

⚠ **預設值是空殼，不是零值物件**：要測哪一段就傳哪一段進來，其餘留空。
"""
from __future__ import annotations

from types import SimpleNamespace


def _empty(**extra: object) -> SimpleNamespace:
    """五條消音規則共用的空殼。`extra` 補那一段自己才有的欄位。"""
    return SimpleNamespace(mutes=[], held=[], fired=False, reason="",
                           body_chars_before=0, body_chars_after=0,
                           ratio=0.0, suspicious=False, **extra)


def skeleton(**sections: object) -> dict:
    """`as_json` 需要的最小骨架。傳進來的那幾段蓋掉空殼。

    Args:
        sections: 要放真貨的段名 → 規則算出來的 Plan 物件（`title`、`cover_ad`…）。
    """
    # ⚠ 這份骨架要跟得上 `postprocess.CANARY_WATCHED` —— 那裡新增一個量而這裡
    # 沒補，`canary_row` 會在測試裡 AttributeError。**那是好事**：骨架落後會當場
    # 紅，不會安靜地測一個不存在的形狀（同本檔檔頭記的「同一件事兩個地方」）。
    base: dict = {
        "ctx": SimpleNamespace(doc_name="x.pdf", n_pages=1, items=[], page_size=(595, 842)),
        # boilerplate_chars 只有 noise 有 —— 出版社樣板不計入消音比例（2026-08-31）。
        "noise": _empty(distinct={}, boilerplate_chars=0),
        "refs": _empty(sections=[]),
        "title": _empty(),
        "cover_ad": _empty(),
        "margin": _empty(),
        "tables": SimpleNamespace(total=0, targets=[], repairable=[], review=[]),
        "charts": SimpleNamespace(convert=[], dangling=[], with_caption=0),
        # `canary_row` 讀的是另外五格 —— 兩支都要餵，否則骨架只夠用一半。
        "latex": SimpleNamespace(fixes=[], summary=lambda: "", edits={}, items=0,
                                 times=0, partials=0, glued=0, vetoed=[]),
    }
    base.update(sections)
    return base
