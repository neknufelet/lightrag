"""消音比例不該把出版社樣板算進去。

2026-08-31：ASA 期刊那行 161 字的重製宣告
（`Redistribution subject to ASA license or copyright; see http://…`）貼在每一頁上，
**單靠它**就佔 TDYNP8ZY 正文的 6.22%、XG57NPIY 的 6.22%、CK37MDB2 的 7.85%。
三份因此各自剛好踩過 10% 的切點被擋下來要人看，而它們的消音清單裡**一項正文都沒有**。

比例守衛防的是「規則圈太大、吃到正文」。版權宣告按定義不是正文，把它算進來，
量到的就變成「這家期刊的頁尾有多長」。

⚠ **這份檔案裡有三支控制組**，因為改動守衛最容易犯的錯是把守衛關掉
（2026-08-21 血淚：漏字檢查的切點改壞，coder 上 6 條測試全綠，真實資料一跑
關掉了九成的檢查）。三支分別釘住：沒有樣板時行為不變、真的吃到正文時仍然會叫、
以及全部都是樣板時不會炸。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from pp.rules import layout_noise as ln  # noqa: E402

# 這行是真的，從 TDYNP8ZY 的 content_list.json 抄來的（161 字元）。
ASA = ("Redistribution subject to ASA license or copyright; "
       "see http://acousticalsociety.org/content/terms. Download to IP: 129.105.215.14")
PROSE = ("The transfer-matrix approach yields the characteristic impedance and the "
         "wave number of a limp porous layer from two surface impedance measurements. ")

#: 給每段正文一個**不含數字**的尾巴，讓它們在 `template_key` 之後仍然互不相同。
SECTIONS = ("introduction", "theory", "method", "apparatus", "results", "discussion",
            "validation", "uncertainty", "comparison", "conclusion", "appendix", "summary")


def _doc(n_pages: int = 12, *, footer: str | None = None,
         prose_as_footer: int = 0, n_footers: int = 1) -> list[dict]:
    """一份合成文件：每頁一段正文，可選擇加逐頁重複的頁尾。

    `prose_as_footer`：把前幾頁的**正文**誤標成 footer 並挪到正文帶上方 ——
    那就是「版面分析把正文當頁眉」的形狀，也是這道守衛存在的理由。

    ⚠ **頁數要夠。** `body_band` 需要至少 `BODY_MIN_PARAGRAPHS`（5）段真正的
    `text` 才量得出正文帶，量不出來就退回重複次數判斷、誤吃的那幾段根本不會被
    消音 —— 於是測試會在「守衛沒被觸發」的情況下綠掉，而那是假的綠。
    12 頁扣掉最多 4 段誤吃仍有 8 段，安全。
    """
    items: list[dict] = []
    for page in range(n_pages):
        eaten = page < prose_as_footer
        items.append({
            # ⚠ 每段正文的文字都**不同，而且差在字不是數字**。全都一樣的話，
            # 誤吃的那幾段會被「逐頁重複」規則消掉，測試就因為錯的理由而綠 ——
            # 我們要釘的是「正文帶判斷把正文當頁眉」那條路。
            # ⚠ 用編號區分沒有用：`template_key` 會把數字抹成 `#`，
            #   'paragraph 0/1/2' 併成同一個樣板，重複次數照樣達標。
            "type": "footer" if eaten else "text",
            "text": f"{PROSE * 3} The {SECTIONS[page % len(SECTIONS)]} section follows.",
            "page_idx": page,
            # 誤吃的那幾段挪到正文帶上方，其餘留在帶內。
            "bbox": [50.0, 10.0, 550.0, 40.0] if eaten else [50.0, 100.0, 550.0, 700.0],
        })
        for k in range(n_footers if footer is not None else 0):
            items.append({"type": "footer", "text": footer, "page_idx": page,
                          "bbox": [50.0, 780.0 + k, 550.0, 800.0 + k]})
    return items


def _pages(items: list[dict]) -> int:
    return len({it["page_idx"] for it in items})


# ── 主張 ───────────────────────────────────────────────────────────────────

def test_publisher_boilerplate_is_left_out_of_the_ratio() -> None:
    """版權宣告被消音**是對的**，但它不該把比例推上去。"""
    items = _doc(footer=ASA)
    plan = ln.plan(items, _pages(items))

    assert all(m.text == ASA for m in plan.mutes), "只該消掉那行宣告"
    assert plan.boilerplate_chars == len(ASA) * 12
    assert plan.ratio == 0.0, f"樣板不該算進比例，卻算出 {plan.ratio:.2%}"
    assert not plan.suspicious


def test_the_summary_shows_the_excluded_characters() -> None:
    """數字要對得起來。只印 before → after 與百分比，讀的人會以為算錯。"""
    items = _doc(footer=ASA)
    plan = ln.plan(items, _pages(items))

    assert "出版社樣板" in plan.summary()
    assert f"{len(ASA) * 12:,}" in plan.summary()


# ── 控制組一：沒有樣板時，行為必須與舊版完全一樣 ───────────────────────────

def test_a_document_without_boilerplate_is_measured_exactly_as_before() -> None:
    """**控制組。** 改動只准影響帶樣板的文件。

    實測三份沒有樣板的真文件，新舊逐位相同：26C22T9I 12.86%／2GAAEJGE 8.51%／
    38CF8F6F 14.18%。這裡用合成文件釘住同一件事：樣板字元為 0 時，比例就是
    「消掉的正文 ÷ 全部正文」，跟舊公式一字不差。
    """
    items = _doc(footer="Journal of Nothing, Vol. 3", prose_as_footer=0)
    plan = ln.plan(items, _pages(items))

    assert plan.boilerplate_chars == 0, "這行頁尾不含網址／DOI／©，不該被當成樣板"
    before, after = plan.body_chars_before, plan.body_chars_after
    assert plan.ratio == (before - after) / before


# ── 控制組二：真的吃到正文時，還是要叫 ─────────────────────────────────────

def test_eating_real_prose_still_trips_the_guard() -> None:
    """**控制組，這一支最重要。**

    少了它，「比例永遠回 0」也會讓上面每一支通過 —— 而那就是把守衛關掉，
    正是 2026-08-21 那次的形狀。這裡把兩段真正的正文誤標成 footer，
    守衛必須照樣叫。
    """
    items = _doc(footer=ASA, prose_as_footer=2)
    plan = ln.plan(items, _pages(items))

    assert plan.ratio > ln.SUSPICIOUS_RATIO, (
        f"吃掉兩段正文卻只算出 {plan.ratio:.2%}，守衛被關掉了")
    assert plan.suspicious


def test_the_boilerplate_never_masks_the_prose_it_is_mixed_with() -> None:
    """**控制組。** 樣板越多，也不准把同一份文件裡吃掉的正文洗掉。

    分子分母同時扣掉樣板，所以剩下的比例仍然是「吃掉的正文 ÷ 可能是正文的字」。
    如果只扣分子不扣分母，樣板一多比例就會被稀釋 —— 那正是漏掉的那一種錯。
    """
    # **同樣的文件、同樣吃掉 3 段正文**，只有樣板的量不同（每頁 1 行 vs 3 行）。
    few = ln.plan(_doc(footer=ASA, prose_as_footer=3, n_footers=1), 12)
    many = ln.plan(_doc(footer=ASA, prose_as_footer=3, n_footers=3), 12)

    assert many.boilerplate_chars == 3 * few.boilerplate_chars
    assert few.suspicious and many.suspicious
    assert few.ratio == many.ratio, (
        f"樣板量改變了正文的判定：{few.ratio:.2%} vs {many.ratio:.2%}")


# ── 控制組三：極端輸入不准炸 ───────────────────────────────────────────────

def test_a_document_that_is_nothing_but_boilerplate_does_not_divide_by_zero() -> None:
    """**控制組。** 分母扣完剩 0 時要回 0，不是拋例外、也不是負數。"""
    items = [{"type": "footer", "text": ASA, "page_idx": p,
              "bbox": [50.0, 780.0, 550.0, 800.0]} for p in range(4)]
    plan = ln.plan(items, 4)

    assert plan.ratio == 0.0
    assert not plan.suspicious
