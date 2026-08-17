"""確認清單的純算層：從處理計畫挑出「要人看的段落」。

設計與四條裁決在 `docs/confirm-list-design-20260817.md`。這一層**不開畫面、
不寫檔**，只回答「這份文件有哪幾項要你確認、規則預設怎麼勾、為什麼」。

**規則有把握的不進清單**（裁決：規則只做確定的，其餘進清單）——
但也**不能不提**（藍桶第 2 條：不得無聲消失），所以另外給一個數字。

2026-08-17 在 dker 全母體實測：要確認的 1,232 項散在 218 份（平均 5.7 項），
規則有把握直接丟的 7,586 項。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from pp.confirm import items_from_plan, muted_count  # noqa: E402

# 一份計畫的形狀，照 `postprocess.py as_json()` 的真實輸出裁下來。
PLAN = {
    "doc": "2019 - Compact Acoustic Rainbow Trapping.pdf",
    "noise": {
        "mute": [{"index": 3, "page": 2, "repeat": 9, "text": "PHYS. REV. APPLIED 11"}],
        "held": [{"index": 41, "page": 3, "repeat": 5,
                  "text": "GRADED LOCALLY RESONANT METAMATERIALS"}],
    },
    "refs": {"mute": [{"index": 88, "page": 8, "kind": "reference", "section": "ref_text"}]},
    "title": {
        "mute": [{"index": 0, "page": 1, "text": "PHYSICAL REVIEW APPLIED 11, 054046"}],
        "held": [{"index": 1, "page": 1, "text": "Received 14 January 2019"}],
    },
}


def test_only_the_uncertain_items_become_rows() -> None:
    """進清單的是**規則沒把握**的那些，有把握的不進來。

    有把握的也塞進來的話，實測會從 1,232 列變成 8,818 列 —— 人看不完，
    而「規則先幫你勾好」這個設計就失去意義。
    """
    items = items_from_plan(PLAN)

    assert [i.index for i in items] == [41, 1]
    assert all(not i.suppress for i in items), "沒把握的預設不勾（＝留著）"


def test_the_confident_ones_are_counted_not_hidden() -> None:
    """規則直接丟掉的要**報個數**，不能安靜消失（藍桶第 2 條）。

    數字不見的話，人分不出「這份很乾淨」與「規則把半份文件丟了」。
    """
    assert muted_count(PLAN) == 3          # noise 1 + refs 1 + title 1


def test_every_row_carries_a_plain_reason() -> None:
    """每一列都要有一句白話理由（PO 2026-08-17 第四條）。

    ⚠ 理由要說**為什麼**，不是只說**是什麼**：「頁首頁尾」是分類，
    「重複 5 次像頁首，但不敢確定」才是理由。人要判斷的是「機器憑什麼這樣勾」。
    """
    items = items_from_plan(PLAN)

    by_index = {i.index: i for i in items}
    assert by_index[41].category == "頁首頁尾"
    assert "5" in by_index[41].reason, "重複次數是判準，要講出來"
    assert by_index[1].category == "標題區塊"
    assert by_index[1].reason, "標題區塊那條也要有理由"


def test_each_row_says_where_it_came_from() -> None:
    """要記得原文與頁碼 —— 不給原文，人沒辦法判斷；不給頁碼，人回不去查。"""
    items = items_from_plan(PLAN)

    first = items[0]
    assert first.text == "GRADED LOCALLY RESONANT METAMATERIALS"
    assert first.page == 3


def test_a_plan_with_nothing_held_gives_an_empty_list() -> None:
    """沒有不確定的項目就回空清單 —— 不丟例外，那是正常且值得高興的狀態。"""
    clean = {"doc": "x.pdf", "noise": {"mute": [], "held": []},
             "refs": {"mute": []}, "title": {"mute": [], "held": []}}

    assert items_from_plan(clean) == []
    assert muted_count(clean) == 0


def test_a_half_built_plan_does_not_pretend_to_be_clean() -> None:
    """計畫半路失敗（缺整段）時**不得回空清單假裝乾淨**。

    這個碼庫記過同型事故：`pp.tables` 因為缺鍵而回 `{}`，一路走到「共 None 張，
    沒有待修的」，在 dker 上產生 4 個假通過。缺段就要講不知道。
    """
    broken = {"doc": "x.pdf", "refs": {"mute": []}}          # noise 與 title 都不見了

    try:
        items_from_plan(broken)
    except KeyError as exc:
        assert "noise" in str(exc) or "title" in str(exc)
        # ⚠ **不得寫死原因。** 第一版寫「多半是計畫半路失敗」，2026-08-17 實測
        # dker 上 50 份缺段的**一份都不是失敗**，全是舊版程式跑的舊文件。
        # 寫死的因果跟寫死的數字一樣會過期。
        assert "舊版" in str(exc) and "半路失敗" in str(exc), "兩種可能都要講"
        assert "重跑" in str(exc), "要給處置"
    else:
        raise AssertionError("計畫缺段時必須丟例外，不得回空清單")
