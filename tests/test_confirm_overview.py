"""確認清單的總覽：一次看完還剩哪些東西。

PO 2026-08-18：「我現在能看一下 357 項還有哪些東西嗎」→「不是在原本的頁面看嗎」。
他是對的 —— 我先丟了一個外部檔案給他，但那應該長在產品裡。

**為什麼需要總覽**：確認清單一次只給一份文件（357 項散在 124 份）。要看出
「還有沒有規律」，得把整批攤在一起，照一模一樣的文字分組 ——
出現越多次，越可能是規則抓得到的東西。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from pp.confirm import ConfirmItem  # noqa: E402
from pp.confirm_html import group_items, render_overview  # noqa: E402


def _item(cat: str, text: str, doc: str = "a.pdf", page: int = 1) -> tuple[str, ConfirmItem]:
    return doc, ConfirmItem(section="noise", index=0, category=cat, reason="r",
                            text=text, page=page, suppress=False)


PAIRS = [
    _item("頁首頁尾", "ELSEVIER", "a.pdf"),
    _item("頁首頁尾", "ELSEVIER", "b.pdf"),
    _item("頁首頁尾", "ELSEVIER", "c.pdf"),
    _item("標題區塊", "Check for updates", "a.pdf"),
    _item("頁首頁尾", "只出現一次的東西", "d.pdf"),
]


def test_identical_text_collapses_into_one_row() -> None:
    """一模一樣的文字併成一組，**而且要數得出來幾次**。

    次數就是「這值不值得變成規則」的證據 —— 17 份文件都有 'ELSEVIER'，
    那不是內容。
    """
    groups = group_items(PAIRS)

    assert groups[0].count == 3
    assert groups[0].text == "ELSEVIER"


def test_the_common_ones_come_first() -> None:
    """次數多的排前面。**規律藏在前面**，只出現一次的往後放。"""
    groups = group_items(PAIRS)

    assert [g.count for g in groups] == [3, 1, 1]


def test_the_same_words_in_different_sections_do_not_merge() -> None:
    """同樣的字出現在不同分類要**分開算**。

    'Check for updates' 同時出現在頁首頁尾與標題區塊 —— 併在一起的話，
    「這一類有幾項」就再也算不準。
    """
    groups = group_items([*PAIRS, _item("標題區塊", "ELSEVIER", "e.pdf")])

    same = [g for g in groups if g.text == "ELSEVIER"]
    assert len(same) == 2
    assert {g.category for g in same} == {"頁首頁尾", "標題區塊"}


def test_it_says_which_documents_so_you_can_go_look() -> None:
    """要說得出在哪些文件裡，否則看到可疑的也追不下去。"""
    groups = group_items(PAIRS)

    assert groups[0].docs[:2] == ["a.pdf", "b.pdf"]


def test_the_page_shows_the_totals_and_a_way_back() -> None:
    """畫面要講清楚「共幾項、幾組」，並且回得去。

    只有列表沒有總數的話，人不知道自己在看的是全部還是一部分。
    """
    out = render_overview(group_items(PAIRS), total=5, docs=4)

    assert "5" in out and "4" in out
    assert "href='/confirm'" in out, "要回得去一份一份確認那頁"


def test_an_empty_overview_says_so() -> None:
    """全部確認完就直說，不要畫一張空表。"""
    out = render_overview([], total=0, docs=0)

    assert "沒有" in out


def test_text_from_a_pdf_cannot_break_the_page() -> None:
    """原文照樣要跳脫 —— 總覽跟清單同一批資料。"""
    out = render_overview(group_items([_item("頁首頁尾", "<script>x</script>")]),
                          total=1, docs=1)

    assert "<script>x" not in out
    assert "&lt;script&gt;" in out


# ── 全庫視角（PO 2026-08-19：「能重新把 117 讓我看一下嗎」）──────────────


def test_the_corpus_view_says_it_ignores_what_you_already_confirmed() -> None:
    """**全庫視角要講清楚它算的是什麼**，否則兩個不同的總數會互相打架。

    PO 全部按完之後畫面是空的（有紀錄的不再問人），但「規則還是不確定的」
    仍然有 117 項 —— 新庫從零灌進來時那些會再問一次。兩個數字都對，
    差別只在母體，所以**母體要寫在畫面上**。
    """
    html = render_overview(group_items(PAIRS), total=5, docs=4, scope="corpus")

    assert "已經確認過" in html
    assert "全庫" in html


def test_each_view_links_to_the_other() -> None:
    """兩個視角要互相到得了 —— 只能從網址切換的功能等於不存在。"""
    pending = render_overview(group_items(PAIRS), total=5, docs=4)
    corpus = render_overview(group_items(PAIRS), total=5, docs=4, scope="corpus")

    assert "scope=corpus" in pending, "還沒確認的那頁要有去全庫的路"
    assert "scope=corpus" not in corpus, "全庫那頁不該再連到自己"
    assert "view=all" in corpus, "全庫那頁要連得回還沒確認的那頁"


def test_an_empty_corpus_view_still_offers_the_way_back() -> None:
    """空的時候也要留著回去的路（深色模式那次的教訓：看得見才算存在）。"""
    html = render_overview([], total=0, docs=0, scope="corpus")

    assert "一份一份確認" in html


def test_the_app_can_show_the_whole_corpus_not_just_the_queue() -> None:
    """全庫視角要真的**繞過**「已確認就不再問」那道過濾，不是只換一句文案。

    PO 2026-08-19 全部按完之後畫面是空的，他問「能重新把 117 讓我看一下嗎」。
    如果只改文案而母體照舊，那一頁會永遠是空的 —— 而且看起來完全正常。
    """
    src = (ROOT / "scripts" / "intake.py").read_text(encoding="utf-8")

    assert "def confirm_overview(self, scope" in src, "總覽沒有母體參數"
    assert "SCOPE_CORPUS" in src, "app 沒有用共用常數，兩邊字串會漂"
    assert "scope=corpus" in src or 'get("scope")' in src, "路由沒有讀 scope"
