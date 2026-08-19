"""出版商夾在最前面那一頁，整頁丟掉。

PO 2026-08-18 看著兩張截圖說「出現好多份這種期刊一開始的廣告頁面上的廣告字典被
抽出來」。量完發現他講的不是幾個字，是**一整頁**：AIP／JASA 下載下來的 PDF 前面
會多一頁，上面只有三種東西 ——

    這篇自己的標題（後面的頁上還會再出現一次）
    「Articles you may be interested in」＋**別人論文的標題與卷期**
    廣告（LakeShore、Zurich Instruments、Get the whitepaper、Lock-in Amplifiers）

⚠ 中間那項才是真正的害處：**別人的論文標題正在被當成這篇的內容吃進去。**

全庫實測 2026-08-18：26 份有這一頁、合計 475 個區塊。整頁丟掉安全嗎 ——
26 份**每一份自己的標題在後面的頁上都還在**（其中 1 份是連字號斷字才比對不到，
逐份打開看過）。

⚠ **只認第 0 頁。** 有一份（`2021 - A low-frequency sound absorber`）的廣告字
出現在第 1 頁，而那一頁有 807 字的真正文 —— 不加這道關就會刪掉整段內容。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from _plan_skeleton import skeleton  # noqa: E402
from pp.rules import cover_ad_page as cap  # noqa: E402


def _row(text: str, page: int = 0, **kw: object) -> dict:
    row: dict = {"type": "text", "text": text, "page_idx": page}
    row.update(kw)
    return row


def _wrapper_page(page: int = 0) -> list[dict]:
    """真實形狀：標題、招牌、別人的論文、廣告。取自 2017 - Single-channel labyrinthine。"""
    return [
        _row("Single-channel labyrinthine metasurfaces as perfect sound absorbers", page),
        _row("Articles you may be interested in", page),
        _row("Cherenkov terahertz radiation from graphene surface plasmon polaritons", page),
        _row("Applied Physics Letters 110, 231102 (2017); 10.1063/1.4984961", page),
        _row("LEARN MORE", page),
    ]


def _real_body(page: int = 1) -> list[dict]:
    return [_row("Sound absorption, as a vital recipe for noise remediation in numerous "
                 "applications, has captured considerable attention. " * 4, page)]


def test_publisher_wrapper_page_is_dropped_whole() -> None:
    """整頁丟掉 —— 不是挑幾個廣告字，因為害處在「別人論文的標題」那幾行。"""
    items = _wrapper_page() + _real_body()

    p = cap.plan(items)

    assert p.fired is True
    assert sorted(m.index for m in p.mutes) == [0, 1, 2, 3, 4]


def test_real_body_on_later_pages_is_untouched() -> None:
    """後面的頁一個字都不能碰。"""
    items = _wrapper_page() + _real_body()

    p = cap.plan(items)

    assert 5 not in {m.index for m in p.mutes}


def test_marker_on_a_later_page_does_not_fire() -> None:
    """`2021 - A low-frequency sound absorber` 的廣告字在第 1 頁，而那頁有 807 字正文。"""
    items = [_row("A low-frequency sound absorber based on coiled channels", 0),
             *_wrapper_page(page=1)]

    p = cap.plan(items)

    assert p.fired is False
    assert p.mutes == []


def test_one_marker_plus_a_long_paragraph_is_not_an_ad_page() -> None:
    """保險：**只有一個招牌時**，頁上有長段落就不當廣告頁。

    ⚠ 這支原本用 `_wrapper_page()`（招牌兩個），2026-08-19 加上「兩個招牌豁免
    字數關」之後那個樣本就不再測得到這道關 —— 改成單一招牌。
    **測試樣本會被後來的規則掏空，行為斷言不會。**
    """
    items = [_row("LEARN MORE", 0), _row("x" * (cap.BODY_PARAGRAPH_MIN_CHARS + 1), 0)]

    p = cap.plan(items)

    assert p.fired is False
    assert p.mutes == []


def test_document_without_the_markers_does_not_fire() -> None:
    """一般論文的第 0 頁不能被當成廣告頁。"""
    items = [_row("A theoretical framework for room acoustics", 0),
             _row("Institut Jean Le Rond d'Alembert, Sorbonne Universite", 0),
             *_real_body()]

    p = cap.plan(items)

    assert p.fired is False
    assert p.reason


def test_items_claimed_by_another_rule_are_left_alone() -> None:
    """三條消音規則不得消到同一項 —— `apply` 撞到會整份拒絕（`pp/apply.py`）。"""
    items = _wrapper_page() + _real_body()

    p = cap.plan(items, claimed={0, 4})

    assert sorted(m.index for m in p.mutes) == [1, 2, 3]


def test_apply_stores_the_original_text_so_it_can_be_reverted() -> None:
    """沿用 `_pp_original_text`，`layout_noise.revert_items` 才還原得了。"""
    items = _wrapper_page() + _real_body()
    p = cap.plan(items)

    n = cap.apply_to_items(items, p)

    assert n == 5
    assert items[1]["text"] == ""
    assert items[1]["_pp_original_text"] == "Articles you may be interested in"
    assert items[5]["text"].startswith("Sound absorption")


def test_summary_reports_the_count_even_when_it_did_not_fire() -> None:
    """數字不見的話，人分不出「這份沒有廣告頁」與「規則沒跑」（藍桶第 2 條）。"""
    p = cap.plan(_real_body(page=0))

    assert "0 項" in p.summary()


# ── 接進管線：算出來的東西要走到計畫、數字與畫面上 ──────────────────────


def test_as_json_carries_the_cover_ad_page_with_its_text() -> None:
    """被丟掉的也要看得見原文 —— 藍桶第 2 條，不得無聲消失。"""
    import postprocess

    cover = cap.CoverAdPlan(
        mutes=[cap.CoverAdMute(index=1, item_type="text", page=0,
                               text="Articles you may be interested in",
                               signal="wrapper_page")],
        fired=True, reason="", body_chars_before=100, body_chars_after=90)

    out = postprocess.as_json(skeleton(cover_ad=cover))["cover_ad"]

    assert out["mute"][0]["text"] == "Articles you may be interested in"
    assert out["mute"][0]["signal"] == "wrapper_page"


def test_muted_count_includes_the_cover_ad_page() -> None:
    """少算的話，「這一份另外自己丟了 N 段」會少報，人分不出規則做了什麼。"""
    from pp.confirm import muted_count

    plan_ = {"doc": "x.pdf", "noise": {"mute": [], "held": []}, "refs": {"mute": []},
             "title": {"mute": [], "held": []},
             "cover_ad": {"mute": [{"index": 1, "page": 0, "signal": "wrapper_page",
                                    "text": "LEARN MORE"}]}}

    assert muted_count(plan_) == 1


def test_muted_items_shows_the_cover_ad_page_in_plain_words() -> None:
    """只給數字是死路 —— 覺得不對勁要打得開看是哪幾段。"""
    from pp.confirm import muted_items

    plan_ = {"doc": "x.pdf", "noise": {"mute": [], "held": []}, "refs": {"mute": []},
             "title": {"mute": [], "held": []},
             "cover_ad": {"mute": [{"index": 1, "page": 0, "signal": "wrapper_page",
                                    "text": "LEARN MORE"}]}}

    got = muted_items(plan_)

    assert [i.text for i in got] == ["LEARN MORE"]
    assert got[0].category == "封面廣告頁"
    assert got[0].suppress is True
    assert got[0].reason, "每一項都要有一句白話理由"


def test_no_index_is_claimed_by_two_rules_on_the_same_cover_page() -> None:
    """三條消音規則消到同一項，`apply` 會**整份拒絕**（`pp/apply.py` 的 mute_sets）。

    廣告頁跟標題頁在同一頁，重疊是必然的 —— 所以 `claimed` 不是選配。
    """
    from pp.rules import layout_noise, reference_section, title_block

    items = [
        _row("Single-channel labyrinthine metasurfaces as perfect sound absorbers",
             0, text_level=1),
        _row("Institute of Acoustics, Tongji University, Shanghai 200092, China", 0),
        _row("Articles you may be interested in", 0),
        _row("Cherenkov terahertz radiation from graphene surface plasmon polaritons", 0),
        {"type": "footer", "text": "LakeShore", "page_idx": 0},
        *_real_body(),
    ]
    noise = layout_noise.plan(items, 2)
    refs = reference_section.plan(items)
    title = title_block.plan(items)
    claimed = ({m.index for m in noise.mutes} | {m.index for m in refs.mutes}
               | {m.index for m in title.mutes})

    cover = cap.plan(items, claimed=claimed)

    assert cover.fired is True
    assert not (claimed & {m.index for m in cover.mutes}), "兩條規則搶同一項"


def test_apply_runs_the_cover_ad_rule_and_guards_the_overlap() -> None:
    """`apply` 自己重算計畫 —— 少接這一條的話，唯讀階段說要丟、動手時不丟。"""
    src = Path(ROOT / "scripts" / "pp" / "apply.py").read_text(encoding="utf-8")

    assert "cover_ad_page.plan" in src, "apply 沒有算封面廣告頁，計畫與實作會漂"
    assert "claimed=" in src, "apply 沒有把已認領的項目讓開，26 份會整份被拒"
    assert "cover_ad_page.apply_to_items" in src, "算了卻沒有真的消音"
    assert "封面廣告頁" in src, "重疊守衛的名單裡沒有這一條"


def test_canary_watches_the_cover_ad_rule() -> None:
    """規則不進金絲雀＝改了多少項都不會有人發現。

    `postprocess.canary_row` 的註解自己記著這個病犯過兩次（參考文獻／標題頁一次、
    LaTeX 三格一次）：規則落地了，基準沒跟上，於是行為漂移完全沒有訊號。
    `fired` 要單獨記一格 —— 開火消了 0 項與根本沒開火是兩件事。
    """
    import postprocess

    row = postprocess.canary_row(skeleton(cover_ad=cap.CoverAdPlan(
        mutes=[cap.CoverAdMute(index=1, item_type="text", page=0,
                               text="LEARN MORE", signal="wrapper_page")],
        fired=True, reason="", body_chars_before=100, body_chars_after=90)))

    assert row["cover_ad_mute"] == 1
    assert row["cover_ad_fired"] is True


def test_items_already_dropped_by_the_cover_rule_leave_the_confirm_list() -> None:
    """整頁丟掉之後，清單不能還在問同樣那幾項。

    ⚠ **過濾寫在清單這一層，不寫進規則層**（PO 2026-08-18 裁，上一輪踩過兩次）：
    `noise.held`／`title.held` 是那兩條規則自己的安全網，`plan --details` 要印
    得出來。這裡只是不再拿已經丟掉的東西去佔用人的時間。
    """
    from pp.confirm import items_from_plan

    plan_ = {"doc": "x.pdf",
             "noise": {"mute": [], "held": [{"index": 4, "page": 0, "repeat": 1,
                                             "text": "LakeShore"}]},
             "title": {"mute": [], "held": [{"index": 2, "page": 0, "why": "沒有訊號",
                                             "text": "Articles you may be interested in"}]},
             "cover_ad": {"mute": [{"index": 2, "page": 0, "signal": "wrapper_page",
                                    "text": "Articles you may be interested in"},
                                   {"index": 4, "page": 0, "signal": "wrapper_page",
                                    "text": "LakeShore"}]}}

    assert items_from_plan(plan_) == []


# ── 出版商換一家，招牌就換一批（PO 2026-08-19 指出 Taylor & Francis 那份）──


def _tf_wrapper() -> list[dict]:
    """Taylor & Francis 的包裝頁。取自 `2025 - 3D Printed multilayer overlapping`。

    ⚠ 上面那段「引用格式」有 369 字 —— 比 `BODY_PARAGRAPH_MIN_CHARS` 還長，
    所以單靠字數那道關會把整頁放掉。
    """
    return [
        _row("3D Printed multilayer overlapping resonators for lowfrequency broadband"),
        _row("Yiming Zhao, Zichao Guo, Jie Ye, Junjie Deng, Xinying Lu, Kexin Zeng"),
        _row("To cite this article: " + "Yiming Zhao, Zichao Guo, Jie Ye. " * 11),
        _row("To link to this article:https://doi.org/10.1080/17452759.2025.2455540"),
        _row("Submit your article to this journal"),
        _row("View related articles"),
        _row("Citing articles: 1 View citing articles"),
    ]


def test_two_markers_waive_the_long_paragraph_guard() -> None:
    """兩個以上招牌就夠強了，不必再靠字數。

    PO 2026-08-19：「這個一樣有第 0 頁耶」。它有 10 處招牌，卻因為引用格式那段
    369 字而整頁被放掉。**兩個獨立招牌是比字數更強的證據。**
    """
    items = [*_tf_wrapper(), *_real_body()]

    p = cap.plan(items)

    assert p.fired is True
    assert len(p.mutes) == 7


def test_one_marker_plus_a_long_paragraph_still_does_not_fire() -> None:
    """只有一個招牌時，字數那道關**要留著**。

    全庫實測 2026-08-19：有招牌但不開火的 38 份，全部是「一個招牌 ＋ 頁上有
    1,200～2,500 字的真正文」—— 那是正常論文的第一頁，碰了就是刪內容。
    """
    items = [_row("To cite this article: J Z Song et al 2014 New J. Phys."),
             _row("正文第一段。" * 60),
             *_real_body()]

    p = cap.plan(items)

    assert p.fired is False
    assert "長段落" in p.reason


def test_the_iop_wording_counts_as_a_marker() -> None:
    """IOP 用的是「You may also like」——`title_block` 的檔頭早就點名過這一種。"""
    items = [_row("Acoustic coherent perfect absorbers"),
             _row("You may also like"),
             _row("- Ultra-broadband underwater metaabsorber with gradient impedance"),
             *_real_body()]

    p = cap.plan(items)

    assert p.fired is True


# ── Elsevier 的「Journal Pre-proof」預印頁（PO 2026-08-19 在新庫第一批抓到）──


def _preproof() -> list[dict]:
    """取自 `K7SS62X5 2026 - Ultra-broadband diffuse-field…` 的第 0 頁。

    13 個區塊，**一個字都不是內容**，而舊規則一條都沒開火。
    """
    return [
        _row("Journal Pre-proof"),
        _row("Ultra-broadband diffuse-field sound insulation enabled by a bilayer"),
        _row("Yong-Hua Yu , Yuan-Yuan Li , Long-Xiang Xie , Weichun Huang"),
        _row("PII: S0022-460X(26)00348-2"),
        _row("DOI: https://doi.org/10.1016/j.jsv.2026.119986"),
        _row("To appear in: Journal of Sound and Vibration"),
        _row("Received date: 24 February 2026"),
        _row("Please cite this article as: Yong-Hua Yu, Yuan-Yuan Li. " * 7),
        _row("This is a PDF of an article that has undergone enhancements after "
             "acceptance, such as the addition of a cover page. " * 9),
        _row("©2026 Published by Elsevier Ltd."),
    ]


def test_the_elsevier_preproof_front_page_is_dropped() -> None:
    """PO 2026-08-19 送進新庫的第一批就有一份，**整頁 13 個區塊全進了知識庫**。

    三個原因疊在一起才漏掉的：招牌字寫的是 `To cite this article` 而它寫
    `Please cite this article as`；那頁有 835 字的聲明撞到字數關；封面頁眉那條
    只認 header／footer 型別而這頁全是 text。
    """
    items = [*_preproof(), *_real_body()]

    p = cap.plan(items)

    assert p.fired is True
    assert len(p.mutes) == len(_preproof())


def test_the_preproof_markers_are_enough_to_waive_the_length_guard() -> None:
    """那一頁有 835 字的段落 —— 靠的是「兩個以上不同招牌」才過得了字數關。"""
    blob = "\n".join(x["text"] for x in _preproof())

    assert cap.distinct_markers(blob) >= cap.MARKERS_WAIVING_LENGTH


def test_a_normal_article_first_page_is_still_untouched() -> None:
    """同一批的另外兩篇第 0 頁**就是正文第一頁**，一個字都不能碰。

    取自 `42AK2LLR` 與 `PXUXLG4Y`：標題 → ARTICLE INFO → Keywords → ABSTRACT
    → 1. Introduction → 大段正文。
    """
    items = [
        _row("A new inverse design method for sound-absorbing metamaterial"),
        _row("ARTICLE INFO"),
        _row("Keywords: Acoustic metamaterial Inverse design Deep learning"),
        _row("ABSTRACT"),
        _row("Recent advances in deep learning demonstrate significant potential. " * 25),
        _row("1. Introduction"),
        *_real_body(),
    ]

    p = cap.plan(items)

    assert p.fired is False, [m.text for m in p.mutes]
