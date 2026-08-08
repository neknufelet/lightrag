"""參考文獻區段消音：消到「下一個同級標題」為止，不是消到文件結尾。

**為什麼需要這支**：2026-08-08 實測 2017 那篇的結構把「消到結尾」這個直覺做法
證偽了——它的正文參考清單後面還接著整份補充材料（真內容），消到結尾會砍掉 72 項
推導與公式，**而且不會報錯**。

    第  80 項  lvl=2  References                    ← 正文的參考清單
    第  81–86 項      list / page_number            ← 清單本體，該消
    第  87 項  lvl=1  Supplementary Information …   ← 真內容，不能碰
    第 161 項  lvl=2  References                    ← 補充材料的參考清單，該消

下面的測資就是這個形狀。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from pp.rules import reference_section as rs  # noqa: E402


def _head(text: str, level: int) -> dict:
    return {"type": "text", "text": text, "text_level": level, "page_idx": 0}


def _body(text: str) -> dict:
    return {"type": "text", "text": text, "page_idx": 0}


def test_stops_at_the_next_same_level_heading() -> None:
    """這是本規則的核心。消到下一個同級標題，不是消到結尾。"""
    items = [
        _head("Introduction", 2),
        _body("正文一"),
        _head("References", 2),
        _body("[1] Someone, A paper, 2020."),
        _head("Conclusion", 2),          # ← 同級，區段在此結束
        _body("正文二"),
    ]
    p = rs.plan(items)
    assert {m.index for m in p.mutes} == {2, 3}, "只該消掉標題與清單本體"
    assert "正文二" not in {m.text for m in p.mutes}


def test_stops_at_a_higher_level_heading_the_2017_shape() -> None:
    """2017 那篇：參考清單之後接著整份補充材料（更高階的標題）。

    這一條是被真實資料逼出來的。「消到結尾」在這份文件上會砍掉真內容而且不報錯。
    """
    items = [
        _head("Optimal Sound-Absorbing Structures", 1),
        _body("正文"),
        _head("References", 2),
        _body("[1] …"),
        _body("[2] …"),
        _head("Supplementary Information", 1),   # ← 更高階，區段在此結束
        _body("推導與公式"),
        _head("References", 2),                  # ← 補充材料自己的參考清單
        _body("[S1] …"),
    ]
    p = rs.plan(items)
    muted = {m.index for m in p.mutes}
    assert muted == {2, 3, 4, 7, 8}, f"兩段參考清單都要消，中間的真內容不能碰：{muted}"
    assert 5 not in muted and 6 not in muted, "補充材料是真內容"
    assert len(p.sections) == 2, "兩個區段各自成段"


def test_runs_to_the_end_when_no_heading_follows() -> None:
    """參考清單在最後一節時，消到結尾是對的。"""
    items = [_head("Body", 2), _body("正文"), _head("References", 2),
             _body("[1] …"), _body("[2] …")]
    assert {m.index for m in rs.plan(items).mutes} == {2, 3, 4}


def test_acknowledgements_counted_separately_from_references() -> None:
    """致謝與參考文獻分開計數 —— 它們是不同的東西，只是同樣不回答問題。

    分開才有辦法在「只想消參考文獻」時一眼看出影響範圍。
    """
    items = [_head("Acknowledgements", 2), _body("感謝經費"),
             _head("References", 2), _body("[1] …")]
    p = rs.plan(items)
    kinds = {m.kind for m in p.mutes}
    assert kinds == {"acknowledgement", "reference"}
    assert [k for _, _, k, _ in p.sections] == ["acknowledgement", "reference"]


def test_a_section_is_not_opened_twice() -> None:
    """Acknowledgements 緊接 References 時，第二個標題已被前一段涵蓋。

    重複開段會讓同一項被消兩次、統計數字灌水，而數字錯了就沒人會信這份報告。
    """
    items = [_head("Acknowledgements", 1), _body("感謝"),
             _head("References", 2), _body("[1] …")]
    p = rs.plan(items)
    assert len({m.index for m in p.mutes}) == len(p.mutes), "同一項不得重複列入"
    assert len(p.sections) == 1, "References 已被 Acknowledgements 那段涵蓋"


def test_a_body_mention_of_references_is_not_a_heading() -> None:
    """內文提到 references 不算 —— 只有帶 text_level 的標題項才是區段起點。"""
    items = [_head("Body", 2),
             _body("See the references for details."),
             _body("references"),
             _body("正文")]
    assert rs.plan(items).mutes == []


def test_ratio_flags_an_implausible_amount() -> None:
    """消掉太多要標記待查。誤消真內容不會報錯，只能靠比例異常察覺。"""
    items = [_head("References", 2)] + [_body("x" * 500) for _ in range(9)]
    p = rs.plan(items)
    assert p.suspicious, f"消掉 {p.ratio:.0%} 應該要標記"
