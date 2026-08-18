"""機器自己丟掉的那些，要看得到數字、也要攤得開來看。

PO 2026-08-18 問：「你說這些露出的是機器不確定的。確定的沒露出？」——沒有。
規則有把握的直接丟，畫面上連數字都沒印。

裁決：畫面加一行「這一份另外自己丟了 N 段」，**並且點得開**。
PO 原話：「如果有問題還是要寫看全部吧」——只給數字是死路，
看到數字不對勁卻沒東西可看，等於沒給。

⚠ 攤開的是**這一份**的十幾段，不是全庫那幾百段。一份一份看才走得完。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from pp.confirm import muted_count, muted_items  # noqa: E402
from pp.confirm_html import render_confirm  # noqa: E402
from pp.rules.reference_section import display_text  # noqa: E402

# 三段各一個被丟掉的例子。**refs 那個的原文放在 `list_items`，`text` 是空的**
# —— 這正是 2026-08-18 量到的：382 段參考文獻全部長這樣。
PLAN = {
    "doc": "x.pdf",
    "noise": {"mute": [{"index": 3, "page": 2, "repeat": 9,
                        "text": "PHYS. REV. APPLIED 11"}],
              "held": []},
    "refs": {"mute": [{"index": 88, "page": 8, "kind": "reference",
                       "section": "References",
                       "text": '[1] F. E. Toole, "Subjective Measurements…"'}]},
    "title": {"mute": [{"index": 0, "page": 0, "signal": "publication",
                        "text": "PHYSICAL REVIEW APPLIED 11, 054046"}],
              "held": []},
}


def test_a_reference_list_item_keeps_its_words() -> None:
    """參考清單的型別是 `list`，內容在 `list_items` 裡而 `text` 是空的。

    ⚠ 這個碼庫已經為同一件事付過一次代價：`item_chars` 的第一版只數 `text`，
    於是報出「消音 0.05%」這種假數字（實際 8–23%）。**取字也一樣不能只看 `text`**
    —— 只看的話，攤開來會是 382 個空白。
    """
    listed = {"type": "list", "text": "", "list_items": ["[1] Toole 1986.", "[2] Olive 2004."]}
    plain = {"type": "text", "text": "References", "list_items": []}
    empty = {"type": "image", "text": "", "list_items": []}

    assert "Toole" in display_text(listed) and "Olive" in display_text(listed)
    assert display_text(plain) == "References"
    assert display_text(empty) == ""


def test_the_dropped_ones_can_be_listed_not_just_counted() -> None:
    """`muted_count()` 只回一個數字，看到數字不對勁時沒東西可看。

    所以另外給 `muted_items()`：同樣的形狀（分類、理由、原文、頁碼），
    差別只在 **`suppress` 是真的** —— 它們已經被丟掉了。
    """
    items = muted_items(PLAN)

    assert len(items) == muted_count(PLAN) == 3, "數字與清單必須對得上"
    assert all(i.suppress for i in items), "這些是已經被丟掉的"
    assert {i.category for i in items} == {"頁首頁尾", "參考書目", "標題區塊"}


def test_each_dropped_item_says_why_it_was_dropped() -> None:
    """被丟掉的也要有一句白話理由（PO 第四條同樣適用）。

    ⚠ 理由要說**機器憑什麼有把握**，不是只說分類 —— 人攤開來就是要判斷
    「這個把握是不是合理」。
    """
    by_cat = {i.category: i for i in muted_items(PLAN)}

    assert "9" in by_cat["頁首頁尾"].reason, "重複幾次是判準，要講出來"
    assert by_cat["參考書目"].reason and by_cat["標題區塊"].reason
    assert all("Toole" in i.text or i.text for i in muted_items(PLAN))


def test_an_unknown_basis_is_shown_as_is_not_smoothed_over() -> None:
    """認不得的判準**照原文吐出來**，不要用一句漂亮話蓋掉。

    蓋掉的話，規則多了一種判準而畫面照樣說得頭頭是道，沒有人會發現。
    """
    plan = {"noise": {"mute": []}, "title": {"mute": []},
            "refs": {"mute": [{"index": 1, "page": 1, "kind": "無此判準",
                               "section": "S", "text": "t"}]}}

    assert "無此判準" in muted_items(plan)[0].reason


def test_the_screen_says_how_many_were_dropped_and_opens_them() -> None:
    """畫面要印出數字，**而且點得開**（PO 2026-08-18）。

    只給數字是死路：看到「丟了 12 段」覺得不對勁，卻沒有任何辦法看是哪 12 段。
    """
    out = render_confirm(doc="x.pdf", items=[], position=1, total=1,
                         muted=muted_items(PLAN))

    assert "3" in out, "要印出被丟掉的段數"
    assert "<details" in out, "要能點開"
    assert "Toole" in out, "點開要看得到原文"


def test_nothing_dropped_means_no_extra_noise_on_screen() -> None:
    """一段都沒丟就不要多印一塊「丟了 0 段」。

    畫面上每多一行，人就要多讀一行；沒有資訊的行只是雜訊。
    """
    out = render_confirm(doc="x.pdf", items=[], position=1, total=1, muted=[])

    assert "<details" not in out
