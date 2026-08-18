"""確認清單的畫面。

形狀是 PO 2026-08-17 裁的四條（`docs/confirm-list-design-20260817.md`）：
打勾＝不要／一份一份、確認一份放行一份／不確定的預設不勾／**每一項都要有一句
白話理由**。第四條是他看過模擬之後主動指名要保留的，因為少了它，畫面就只剩
「一堆勾選框加一堆文字」，人得自己重新判斷每一項 —— 規則就白幫了。

⚠ **模擬稿與實際的碼對不上一處**（2026-08-17 的模擬 vs 8/18 的 `pp/confirm.py`）：
模擬畫了兩列「機器有把握，先幫你勾了」且勾好的。實際上**規則有把握的根本不進
清單**（那是 8/16 的裁決：規則只做確定的，其餘進清單），所以進到畫面的每一項
都是「機器不敢決定」的，**一律預設不勾**。要覆核那些有把握的是另一件事。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from pp.confirm import ConfirmItem  # noqa: E402
from pp.confirm_html import render_confirm  # noqa: E402

DOC = "2019 - Compact Acoustic Rainbow Trapping.pdf"

ITEMS = [
    ConfirmItem(section="noise", index=41, category="頁首頁尾",
                reason="重複 5 次，像頁首頁尾，但次數不夠多、不敢確定",
                text="GRADED LOCALLY RESONANT METAMATERIALS", page=3, suppress=False),
    ConfirmItem(section="title", index=1, category="標題區塊",
                reason="沒看到單位、通訊作者、期刊那些封面訊號，不敢確定",
                text="Received 14 January 2019", page=0, suppress=False),
    ConfirmItem(section="title", index=2, category="標題區塊",
                reason="讀起來像正文，不像封面資訊，所以不敢消",
                text="We measured the absorption coefficient…", page=0, suppress=False),
]


def _render(**kw: object) -> str:
    args = {"doc": DOC, "items": ITEMS, "position": 12, "total": 165}
    args.update(kw)
    return render_confirm(**args)          # type: ignore[arg-type]


def test_every_item_shows_its_reason_and_the_original_text() -> None:
    """⭐ PO 第四條：每一項都要有一句白話理由，而且看得到原文。

    沒有理由，人得自己重新判斷每一項；沒有原文，人根本無從判斷。
    這兩樣是「規則先幫你勾好」能不能省下人力的關鍵，不是裝飾。
    """
    out = _render()

    for item in ITEMS:
        assert item.reason in out, f"少了理由：{item.category}"
        assert item.text in out, f"少了原文：{item.category}"


def test_nothing_is_ticked_to_begin_with() -> None:
    """不確定的預設不勾＝留著（PO 第三條）。寧可多留垃圾，不要誤刪正文。

    ⚠ **進到這個畫面的每一項都是「機器不敢決定」的** —— 規則有把握的走
    `muted_count()`，根本不進清單。所以這裡不該有任何一個預先勾好的框。
    """
    assert "checked" not in _render()


def test_the_screen_says_what_ticking_means() -> None:
    """打勾＝不要（PO 第一條）。**這件事講錯，人會把整份正文勾掉。**

    勾選框的意思沒有自然的預設 —— 不寫出來，一半的人會以為打勾是「要留」。
    """
    out = _render()

    assert "打勾" in out and "不要" in out


def test_it_says_which_document_and_how_far_along() -> None:
    """一份一份做，要看得到「現在第幾份、還有幾份」（PO 第二條）。

    做到一半關掉是常態，不是例外 —— 看不到進度的話，人不知道自己能不能停。
    """
    out = _render()

    assert DOC in out
    assert "12" in out and "165" in out


def test_bulk_buttons_cover_the_categories_that_are_actually_here() -> None:
    """整份快速處理：畫面上有哪幾類，就給哪幾顆按鈕。

    ⚠ **不要給不存在的分類按鈕** —— 按了不會有反應的按鈕比沒有按鈕更糟，
    人會以為是自己做錯了（拆章那個畫面 2026-08-17 被 PO 實際踩到）。
    """
    out = _render()

    assert "頁首頁尾" in out and "標題區塊" in out
    assert "參考書目" not in out, "這份沒有這一類，就不該出現那顆按鈕"


def test_a_document_with_nothing_to_confirm_does_not_pretend_to_need_you() -> None:
    """沒有要確認的項目就直說，**不要畫一個空的清單配一顆存檔鍵**。

    這是拆章那頁學到的：一頁幾乎空白、卻附著一顆亮著的按鈕，按下去什麼也不會
    發生。多數乾淨的文件本來就沒有要確認的，這是常態不是例外。
    """
    out = _render(items=[])

    assert "沒有" in out
    assert "checkbox" not in out


def test_there_is_always_a_way_back() -> None:
    """一定要有回去的路。

    這一頁自成一頁（PO 第五條：獨立一頁），沒有連結就只剩瀏覽器的上一頁 ——
    使用者不該被迫用瀏覽器的按鈕來走我們自己做的流程（2026-08-17 PO 實際踩到，
    而且當時是**正常那條路漏了、例外那條反而有**）。
    """
    assert _render().count("href='/'") >= 1
    assert "href='/'" in _render(items=[]), "沒東西可確認時更要給路"


def test_original_text_cannot_break_the_page() -> None:
    """原文片段是從 PDF 抽出來的，裡面什麼都有 —— 一律跳脫。

    ⚠ 屬性值用單引號包，所以 `'` 也要轉；`html.escape(quote=True)` 的行為
    在不同版本不一樣，這裡明著測，不靠版本。
    """
    nasty = ConfirmItem(section="noise", index=0, category="頁首頁尾",
                        reason="測試", text="<script>alert('x')</script> & \"quoted\"",
                        page=1, suppress=False)

    out = _render(items=[nasty])

    assert "<script>" not in out
    assert "&lt;script&gt;" in out
    assert "&#x27;" in out


def test_an_item_with_no_text_says_so_instead_of_showing_a_blank() -> None:
    """原文是空的時候要**明講**，不要留一塊白。

    2026-08-17 全庫 292 項就是這樣：有勾選框、沒有原文。修掉之後現在應該
    不會再有，但畫面不能假設上游永遠正確 —— 一塊白讓人以為自己網路壞了，
    一句「這一項沒有原文」讓人知道要回報。
    """
    blank = ConfirmItem(section="title", index=9, category="標題區塊",
                        reason="沒看到封面訊號", text="   ", page=0, suppress=False)

    out = _render(items=[blank])

    assert "沒有原文" in out


def test_the_footer_offers_save_skip_and_stop() -> None:
    """底部三條路：存起來下一份／跳過這份／存起來今天到這。

    「跳過」與「今天到這」不是裝飾 —— 少了它們，人遇到看不懂的一份就只能亂勾
    或整個關掉，而關掉之後不知道自己有沒有存到。
    """
    out = _render()

    assert "下一份" in out
    assert "跳過" in out
    assert "今天到這" in out


def test_it_says_what_happens_after_you_confirm() -> None:
    """要講清楚「確認完的會被抽取、沒確認的不會」（PO 第二條的下半）。

    看不到這句的話，人不知道自己按下去會花錢，也不知道沒做完會不會擋住別的事。
    """
    out = _render()

    assert "抽取" in out


def test_the_page_carries_the_document_name_in_a_readable_place() -> None:
    """畫面本身要帶著「我現在在看哪一份」，**不能只靠網址**。

    2026-08-18 PO 實際踩到：從首頁點進 `/confirm`（網址上沒有 `?doc=`）之後
    按「跳過這份」完全沒反應 —— 按鈕去問網址「現在是哪一份」，網址說不知道，
    於是跳給自己看，畫面重載成同一份。

    ⚠ **這一份是誰，是伺服器決定的**（隊伍最前面那份），所以答案要由伺服器
    寫進畫面，不能讓瀏覽器去猜。
    """
    out = _render()

    assert f"data-doc='{DOC}'" in out


def test_even_the_nothing_to_do_page_says_which_document() -> None:
    """沒有要確認的那條路也要帶檔名 —— 那一頁上的「下一份」按鈕同樣要用它。"""
    out = render_confirm(doc=DOC, items=[], position=1, total=1)

    assert f"data-doc='{DOC}'" in out


def test_each_item_shows_what_comes_before_and_after() -> None:
    """要人判斷「這是頁眉還是標題」，就得讓他看到前後文（PO 2026-08-18 裁）。

    PO 原話：「只出現一行字就要我確認這是什麼，我有點搞不太清楚」。
    一段孤立的文字沒有辦法判斷 —— 全庫 82% 的問題都是這一種。
    """
    ctx = {"noise:41": (["前面那段"], ["後面那段"])}

    out = _render(context=ctx)

    assert "前面那段" in out
    assert "後面那段" in out


def test_an_item_without_context_still_renders() -> None:
    """拿不到上下文（編號超出範圍、內容換過）也要畫得出來，不要整頁掛掉。"""
    out = _render(context={})

    assert "GRADED LOCALLY RESONANT METAMATERIALS" in out


def test_the_context_is_visibly_not_the_thing_being_asked() -> None:
    """上下文要看得出來「不是在問這幾段」，否則人會勾錯。

    ⚠ 前後文沒有自己的勾選框，但**排版上必須分得開** —— 三段長得一樣的話，
    人會以為要一起決定。
    """
    ctx = {"noise:41": (["前面那段"], ["後面那段"])}

    out = _render(context=ctx)

    assert "class='ctx up'" in out and "class='ctx down'" in out, \
        "上下文要有自己的樣式、而且分得出前後，跟被問的那段不一樣"
