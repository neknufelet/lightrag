"""印在頁面左右邊緣的字，位置就是答案。

PO 2026-08-18 指著 Annual Reviews 那頁的左緣說：

    「第二章左邊也是屬於外面的，可以全部裁掉吧，感覺邊界上的都沒甚麼用」

那條字是直排的下載聲明（`Annu. Rev. Mater. Res. 2017.47:83-114. Downloaded
from www.annualreviews.org…`）。跟頁眉同一族 —— **不用管重複幾次，它就在正文
框外面**。這條是 `layout_noise` 那條「位置就是答案」的橫向版本。

全庫實測 2026-08-18：要人看的 248 項裡 **46 項**完全落在正文左右緣之外。
誤傷試算：全庫 28,934 段正文型別的段落，落在框外的 **80 段**，逐段看過 ——
版權宣告、投稿日期、作者單位、期刊標籤（`acoustics`／`Article`／`OPEN`）、
掃壞的字（`Chdpte 1`／`wwwwoorg`）。**沒有一段是聲學內容。**
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from _plan_skeleton import skeleton  # noqa: E402
from pp.rules import margin_text as mt  # noqa: E402


def _body(i: int, text: str = "正文一段夠長的內容，用來量出正文框在哪裡") -> dict:
    return {"type": "text", "text": text, "page_idx": 0,
            "bbox": [79, 100 + i * 40, 917, 130 + i * 40]}


BODY = [_body(i) for i in range(12)]


def _edge(x0: int, x1: int, text: str, kind: str = "aside_text") -> dict:
    return {"type": kind, "text": text, "page_idx": 0, "bbox": [x0, 200, x1, 800]}


def test_text_left_of_the_body_frame_is_dropped() -> None:
    """PO 截圖上那條 —— 直排、貼在左緣、整份只出現一次。"""
    items = [*BODY, _edge(0, 35, "Annu. Rev. Mater. Res. 2017.47:83-114. Downloaded")]

    p = mt.plan(items)

    assert p.fired is True
    assert [m.text for m in p.mutes] == ["Annu. Rev. Mater. Res. 2017.47:83-114. Downloaded"]
    assert p.mutes[0].signal == "left_margin"


def test_text_right_of_the_body_frame_is_dropped() -> None:
    """右緣同理 —— 書眉印在右側的那種（`Chdpte 1` 在 x=946..970）。"""
    items = [*BODY, _edge(946, 970, "Chdpte 1", kind="header")]

    p = mt.plan(items)

    assert [m.text for m in p.mutes] == ["Chdpte 1"]
    assert p.mutes[0].signal == "right_margin"


def test_text_that_merely_overlaps_the_frame_is_kept() -> None:
    """**要完全在框外才算。** 只是探出去一點的是正文，不是版面家具。

    判準用「整個盒子都在外面」而不是「起點在外面」—— 後者會把首行縮排、
    公式編號那種正常凸出的東西一起吃掉，而那不會有任何錯誤訊息。
    """
    items = [*BODY, _edge(40, 200, "跨過左緣的一段", kind="text")]

    p = mt.plan(items)

    assert p.mutes == []


def test_no_body_frame_means_the_rule_stays_out_of_it() -> None:
    """量不出正文框就不要猜 —— 猜錯一條邊界會把正文消掉而且不報錯。"""
    p = mt.plan([_body(0), _edge(0, 20, "邊緣的字")])

    assert p.fired is False
    assert p.reason
    assert p.mutes == []


def test_items_without_a_box_are_left_alone() -> None:
    """沒有 bbox 就沒有位置可以判 —— 不判，留給人看。"""
    items = [*BODY, {"type": "text", "text": "沒有座標的一段", "page_idx": 0}]

    p = mt.plan(items)

    assert p.mutes == []


def test_items_claimed_by_another_rule_are_left_alone() -> None:
    """三條以上的消音規則消到同一項，`apply` 會整份拒絕（`pp/apply.py`）。"""
    items = [*BODY, _edge(0, 35, "Downloaded from www.annualreviews.org")]

    p = mt.plan(items, claimed={12})

    assert p.mutes == []


def test_apply_stores_the_original_text_so_it_can_be_reverted() -> None:
    """沿用 `_pp_original_text`，`layout_noise.revert_items` 才還原得了。"""
    items = [*BODY, _edge(0, 35, "Downloaded from www.annualreviews.org")]
    p = mt.plan(items)

    n = mt.apply_to_items(items, p)

    assert n == 1
    assert items[12]["text"] == ""
    assert items[12]["_pp_original_text"] == "Downloaded from www.annualreviews.org"
    assert items[0]["text"].startswith("正文")


def test_summary_reports_the_count_even_when_it_did_not_fire() -> None:
    """數字不見的話，「這份沒有邊緣字」與「規則沒跑」在畫面上長得一樣。"""
    assert "0 項" in mt.plan(BODY).summary()


# ── 接進管線 ────────────────────────────────────────────────────────────


def _fired_plan() -> mt.MarginPlan:
    return mt.MarginPlan(
        mutes=[mt.MarginMute(index=12, item_type="aside_text", page=0,
                             text="Downloaded from www.annualreviews.org",
                             signal="left_margin")],
        fired=True, reason="", body_chars_before=100, body_chars_after=90)


def test_as_json_carries_the_margin_text_with_its_reason() -> None:
    """被丟掉的也要看得見原文與判準 —— 藍桶第 2 條。"""
    import postprocess

    out = postprocess.as_json(skeleton(margin=_fired_plan()))["margin"]

    assert out["mute"][0]["text"] == "Downloaded from www.annualreviews.org"
    assert out["mute"][0]["signal"] == "left_margin"


def test_canary_watches_the_margin_rule() -> None:
    """規則不進金絲雀＝改了多少項都不會有人發現。這個病這個碼庫犯過三次。"""
    import postprocess

    row = postprocess.canary_row(skeleton(margin=_fired_plan()))

    assert row["margin_mute"] == 1
    assert row["margin_fired"] is True


def test_muted_items_shows_the_margin_text_in_plain_words() -> None:
    """只給數字是死路 —— 覺得不對勁要打得開看是哪幾段。"""
    from pp.confirm import muted_count, muted_items

    plan_ = {"doc": "x.pdf", "noise": {"mute": [], "held": []}, "refs": {"mute": []},
             "title": {"mute": [], "held": []},
             "margin": {"mute": [{"index": 12, "page": 0, "signal": "left_margin",
                                  "text": "Downloaded from www.annualreviews.org"}]}}

    got = muted_items(plan_)

    assert [i.text for i in got] == ["Downloaded from www.annualreviews.org"]
    assert got[0].category == "頁面邊緣"
    assert got[0].suppress is True
    assert got[0].reason
    assert muted_count(plan_) == 1


def test_items_already_dropped_by_the_margin_rule_leave_the_confirm_list() -> None:
    """丟掉之後，清單不能還在問同樣那幾項。

    ⚠ 過濾寫在清單這一層，不寫進規則層 —— `noise.held` 是那條規則自己的安全網。
    """
    from pp.confirm import items_from_plan

    plan_ = {"doc": "x.pdf",
             "noise": {"mute": [], "held": [{"index": 12, "page": 0, "repeat": 1,
                                             "text": "Chdpte 1"}]},
             "title": {"mute": [], "held": []},
             "margin": {"mute": [{"index": 12, "page": 0, "signal": "right_margin",
                                  "text": "Chdpte 1"}]}}

    assert items_from_plan(plan_) == []


def test_apply_runs_the_margin_rule_and_guards_the_overlap() -> None:
    """`apply` 自己重算計畫 —— 少接這一條的話，唯讀階段說要丟、動手時不丟。"""
    src = Path(ROOT / "scripts" / "pp" / "apply.py").read_text(encoding="utf-8")

    assert "margin_text.plan" in src, "apply 沒有算頁面邊緣，計畫與實作會漂"
    assert "margin_text.apply_to_items" in src, "算了卻沒有真的消音"
    assert "頁面邊緣" in src, "重疊守衛的名單裡沒有這一條"
