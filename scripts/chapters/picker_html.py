"""勾選畫面的 HTML —— 純函式，不起服務、不碰檔案。

形狀是 PO 2026-08-17 給的：**先問切到哪一層，再跳勾選框**，規則先幫你勾好，
只改勾錯的。兩步不是一步，因為四百頁的教科書切到「節」可能兩三百列，
先選層次能把清單縮到二十幾列；而且層次選錯的話整批檔名都要重來。

**為什麼不放進 `intake.py`**：那支已經四千多行，而這裡是純函式 —— 放這裡讓它
在 coder 上就測得完（coder 沒有 LightRAG 的 `.env` 也沒有它的 docker，
起不了審核台）。`intake.py` 只留路由。
"""
from __future__ import annotations

import html
import logging
from collections.abc import Sequence

from chapters.selection import LevelOption, SelectionRow

logger = logging.getLogger(__name__)


def _esc(value: object) -> str:
    """跳脫進 HTML 的字串，含單引號。

    ⚠ 屬性值用單引號包（``data-title='…'``），所以 ``quote=True`` 之外還要處理
    ``'`` —— `html.escape` 的 ``quote=True`` 只轉 ``"`` 與 ``&``、``<``、``>``，
    Python 3.8 之後才連 ``'`` 一起轉。這裡明寫出來，不靠版本行為。
    """
    return html.escape(str(value), quote=True).replace("'", "&#x27;")


def _level_choices(options: Sequence[LevelOption], chosen: int) -> str:
    """第一步：切到哪一層。每個選項附「會切出幾個檔」。

    那個數字是先問層次的**理由本身** —— 看不到它，使用者無從判斷該選哪個。
    """
    if not options:
        return "<p class='warn'>這份 PDF 讀不到目錄，沒有層次可選。</p>"
    items = "".join(
        f"<label class='lvl'>"
        f"<input type='radio' name='level' value='{o.level}'"
        f"{' checked' if o.level == chosen else ''}>"
        f"切到第 {o.level} 層 <span class='cnt'>切出 {o.selected_count} 個檔</span>"
        f"</label>"
        for o in options
    )
    return f"<fieldset class='levels'><legend>一、切到哪一層</legend>{items}</fieldset>"


def _row(row: SelectionRow) -> str:
    """勾選框的一列。沒勾的列照樣要畫（藍桶第 2 條：不得無聲消失）。"""
    start, end = row.page_range
    return (
        f"<label class='row{'' if row.selected else ' off'}'>"
        f"<input type='checkbox' data-title='{_esc(row.title)}'"
        f" value='{row.serial}'{' checked' if row.selected else ''}>"
        f"<span class='t'>{_esc(row.title)}</span>"
        f"<span class='f'>{_esc(row.filename)}</span>"
        f"<span class='p'>第 {start}-{end} 頁</span>"
        f"</label>"
    )


def render_picker(*, doc: str, options: Sequence[LevelOption], chosen_level: int,
                  rows: Sequence[SelectionRow]) -> str:
    """畫出「這本書要切哪幾章」的整個畫面。

    Args:
        doc: 這本書的檔名。畫在最上面 —— 同時開兩本時不講清楚就會勾錯。
        options: :func:`chapters.selection.level_options` 的輸出。
        chosen_level: 現在選的層次，用來把對應的 radio 標成選中。
        rows: :func:`chapters.selection.build_selection` 的輸出，含沒勾的列。

    Returns:
        一段 HTML 片段（不是完整頁面）—— 由審核台那頁組進去。
    """
    picked = sum(1 for r in rows if r.selected)
    logger.debug("畫勾選框：%s，%d 列、勾好 %d 列", doc, len(rows), picked)
    return (
        "<section class='picker'>"
        f"<h2>切這本書：{_esc(doc)}</h2>"
        + _level_choices(options, chosen_level)
        + "<fieldset class='rows'><legend>二、要切哪幾章"
        f"（規則先幫你勾了 {picked} 列，只改勾錯的）</legend>"
        + "".join(_row(r) for r in rows)
        + "</fieldset>"
        "<button type='button' class='go'>確認，開始切</button>"
        "</section>"
    )
