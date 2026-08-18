"""確認清單的畫面 —— 純函式，不起服務、不碰檔案。

形狀是 PO 2026-08-17 裁的（全文在 `docs/confirm-list-design-20260817.md`）：

======================================  ====================================
打勾代表什麼？                          **不要**（要丟的比較多，人少動手）
一份一份還是整批？                      一份一份；**確認一份、放行一份**
不確定的預設怎麼勾？                    **不勾**（＝留著）
每一項要不要講為什麼？                  ⭐ **要，一句白話**
放在哪裡？                              **獨立一頁**，入口掛在審核台
======================================  ====================================

第四條是他看過模擬之後主動指名要保留的：少了那句話，畫面就只剩「一堆勾選框
加一堆文字」，人得自己重新判斷每一項 —— 那就等於規則沒幫上忙。

⚠ **模擬稿有一處跟實際的碼對不上。** 2026-08-17 的模擬畫了兩列「機器有把握，
先幫你勾了」而且是勾好的；實際上**規則有把握的根本不進清單**（8/16 裁決：
規則只做確定的，其餘進清單，見 `pp/confirm.py`）。所以進到這個畫面的每一項
都是「機器不敢決定」的，**一律預設不勾**。要不要另外做一頁覆核那些有把握的，
還沒裁。

**為什麼不放進 `intake.py`**：那支已經四千多行，而這裡是純函式 —— 放這裡讓它
在 coder 上就測得完（coder 沒有 LightRAG 的 `.env` 也沒有它的 docker，
起不了審核台）。`intake.py` 只留路由。形狀比照 `chapters/picker_html.py`。
"""
from __future__ import annotations

import html
import logging
from collections.abc import Sequence

from pp.confirm import ConfirmItem

logger = logging.getLogger(__name__)

#: 原文是空的時候印這句。**不要留一塊白** —— 白的讓人以為自己網路壞了，
#: 這句話讓人知道該回報。2026-08-17 全庫 292 項就是這個狀態（已修）。
NO_TEXT = "（這一項沒有原文，請回報）"


def _esc(value: object) -> str:
    """跳脫進 HTML 的字串，含單引號。

    ⚠ 屬性值用單引號包（``data-key='…'``），所以 ``quote=True`` 之外還要處理
    ``'`` —— 明寫出來，不靠 Python 版本的行為差異。原文片段是從 PDF 抽出來的，
    裡面什麼都有。
    """
    return html.escape(str(value), quote=True).replace("'", "&#x27;")


def _item(item: ConfirmItem) -> str:
    """清單的一列：勾選框、分類、**理由**、原文、頁碼。

    順序刻意是「先講為什麼，再給原文」—— 人是帶著機器的判斷去看原文，
    不是自己從頭讀一遍。
    """
    text = item.text.strip()
    snippet = _esc(text) if text else f"<i class='blank'>{NO_TEXT}</i>"
    return (
        f"<div class='item'>"
        f"<input type='checkbox' name='drop' value='{_esc(item.key)}'"
        f" data-cat='{_esc(item.category)}'>"
        f"<div>"
        f"<p class='why'><b>{_esc(item.category)}</b>　{_esc(item.reason)}</p>"
        f"<p class='snip'>{snippet}</p>"
        f"<p class='meta'>第 {item.page} 頁</p>"
        f"</div></div>"
    )


def _bulk(items: Sequence[ConfirmItem]) -> str:
    """整份快速處理。**只給這一份真的有的分類**。

    ⚠ 按了不會有反應的按鈕比沒有按鈕更糟 —— 人會以為是自己做錯了
    （拆章那個畫面 2026-08-17 被 PO 實際踩到）。
    """
    cats: list[str] = []
    for item in items:
        if item.category not in cats:
            cats.append(item.category)
    buttons = "".join(
        f"<button type='button' class='bulk' data-cat='{_esc(c)}'>{_esc(c)}全打勾</button>"
        for c in cats
    )
    return (
        "<div class='quick'><span>整份快速處理：</span>"
        + buttons
        + "<button type='button' class='bulk' data-cat='*'>全部打勾</button>"
        "<button type='button' class='bulk' data-cat=''>全部取消</button>"
        "</div>"
    )


def _dropped(muted: Sequence[ConfirmItem]) -> str:
    """「機器另外自己丟了 N 段」+ 點得開。

    PO 2026-08-18 問「確定的沒露出？」—— 在此之前完全沒有，連數字都沒印。
    ⚠ **只給數字是死路**：看到數字不對勁，卻沒有任何辦法看是哪幾段。
    PO 原話：「如果有問題還是要寫看全部吧」。

    ⚠ 攤開的是**這一份**的十幾段，不是全庫那幾百段 —— 一份一份看才走得完。
    ⚠ 一段都沒丟就整塊不畫：畫面上每多一行，人就要多讀一行。
    """
    if not muted:
        return ""
    rows = "".join(
        f"<div class='item muted'><div>"
        f"<p class='why'><b>{_esc(m.category)}</b>　{_esc(m.reason)}</p>"
        f"<p class='snip'>{_esc(m.text.strip()) if m.text.strip() else NO_TEXT}</p>"
        f"<p class='meta'>第 {m.page} 頁</p>"
        f"</div></div>"
        for m in muted
    )
    return (
        "<details class='dropped'>"
        f"<summary>這一份機器另外自己丟了 <b>{len(muted)}</b> 段（規則有把握的）"
        "—— 點開看是哪些</summary>"
        # ⚠ 這裡是 HTML 不是 Markdown，強調要用 <b> —— 寫 `**…**` 會原樣印出星號。
        "<p class='note'>這些<b>已經丟掉了</b>，這裡只是給你看。覺得不對就回報，"
        "改的是規則、不是這一頁。</p>"
        + rows +
        "</details>"
    )


def render_confirm(*, doc: str, items: Sequence[ConfirmItem],
                   position: int, total: int, evidence: str = "",
                   muted: Sequence[ConfirmItem] = ()) -> str:
    """畫出「這一份有哪幾段要你確認」的整個畫面。

    Args:
        doc: 這份文件的檔名。畫在最上面 —— 同時開兩份時不講清楚就會勾錯。
        items: :func:`pp.confirm.items_from_plan` 的輸出。**含人決定留著的**。
        position: 這是第幾份（1 起算）。
        total: 一共幾份。**進度看不到的話，人不知道自己能不能停。**
        evidence: 這一份的佐證數字（例如「參考書目佔 32.4%，平常 15–20%」）。
            ⚠ 選填，**目前還沒有接上任何來源**。有量到的就給，讓人自己判斷
            嚴重度；不要用形容詞替人下結論（`ledger.py` 曾把嚴重程度寫死成
            形容詞，實測差六百倍）。
        muted: :func:`pp.confirm.muted_items` 的輸出 —— **規則已經丟掉**的那些。
            選填；給了就多畫一塊可以點開的「機器另外丟了 N 段」。

    Returns:
        一段 HTML 片段（不是完整頁面）—— 由審核台那頁組進去。
    """
    logger.debug("畫確認清單：%s，第 %d/%d 份、%d 項", doc, position, total, len(items))

    back = "<p class='back'><a class='btn' href='/'>← 回收件匣</a></p>"
    head = (
        f"<header><h1>確認清單</h1>"
        "<p class='sub'><b>打勾 ＝ 這段不要進知識庫。</b>"
        "機器不敢決定的才列在這裡，你只勾要丟的。</p></header>"
        f"<p class='prog'>現在第 <b>{position}</b> / <b>{total}</b> 份"
        f"，做到哪算到哪，隨時可以關掉。</p>"
        f"<h2 class='doc'>{_esc(doc)}</h2>"
    )

    if not items:
        # **沒有要確認的就直說。** 畫一個空清單配一顆存檔鍵，按下去什麼也不會
        # 發生 —— 那比沒有按鈕更糟。多數乾淨的文件本來就沒有要確認的。
        logger.info("%s 沒有要確認的項目", doc)
        return (
            f"<section class='confirm' data-doc='{_esc(doc)}'>" + back + head
            + "<p class='ok'>這一份<b>沒有</b>要你確認的段落，規則全部都有把握。"
            "直接放行就好。</p>"
            # ⚠ 沒有要確認的，**不代表沒有東西被丟掉** —— 這條路更需要那塊，
            # 因為整頁除此之外什麼都沒有，人無從判斷「規則全部有把握」對不對。
            + _dropped(muted)
            + "<div class='foot'>"
            "<button type='button' class='pri go-next'>下一份 →</button>"
            "</div>" + back + "</section>"
        )

    ev = f"<p class='ev'>{_esc(evidence)}</p>" if evidence else ""
    return (
        f"<section class='confirm' data-doc='{_esc(doc)}'>" + back + head + ev
        + f"<p class='count'>這一份有 <b>{len(items)}</b> 項要你看。</p>"
        + _bulk(items)
        + "".join(_item(i) for i in items)
        + "<div class='foot'>"
        "<button type='button' class='pri save-next'>存起來，下一份 →</button>"
        "<button type='button' class='skip'>跳過這份</button>"
        "<button type='button' class='stop'>存起來，今天到這</button>"
        "</div>"
        + _dropped(muted)
        + "<p class='after'>確認完的會排進下一批<b>抽取</b>；"
        "沒確認的等著，<b>不會被抽取</b> —— 先抽再改要重抽一次，那是最貴的一步。</p>"
        + back + "</section>"
    )
