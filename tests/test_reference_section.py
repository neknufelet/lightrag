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

from pp.rules import layout_noise  # noqa: E402
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


def test_mineru_sub_type_ref_text_is_also_caught() -> None:
    """MinerU 自己標的 `sub_type: ref_text` 也要抓 —— 即使沒有 References 標題。

    兩個訊號的失效方式不同：標題推斷在標題寫法沒見過時失效，`ref_text` 在
    MinerU 沒分類時失效（實測 C Equivalent Networks 就是 0 項）。
    兩個都失效才會漏，而不是任一個失效就漏。
    """
    items = [
        _head("Body", 2),
        _body("正文"),
        {"type": "list", "sub_type": "ref_text", "page_idx": 3,
         "list_items": ["1. A. Author, A paper, 2020.", "2. B. Author, 2021."]},
    ]
    p = rs.plan(items)
    assert {m.index for m in p.mutes} == {2}
    assert p.mutes[0].kind == "reference"


def test_ratio_counts_list_items_not_just_text() -> None:
    """比例要算 `list_items`，不能只算 `text`。

    **血淚 2026-08-08**：第一版只數 `text`，而參考清單的型別是 `list`、內容在
    `list_items`、`text` 是空的 —— 於是報出「消音 0.05%」，實際是 8–23%。
    統計錯了就沒有人會相信這條規則。
    """
    items = [
        _body("x" * 100),
        {"type": "list", "sub_type": "ref_text", "page_idx": 1,
         "list_items": ["y" * 400]},
    ]
    p = rs.plan(items)
    assert p.body_chars_before == 500, "分母要含 list_items"
    assert p.body_chars_after == 100
    assert abs(p.ratio - 0.8) < 1e-9, p.ratio


def test_apply_clears_list_items_not_only_text() -> None:
    """**核心**：只清 `text` 對參考清單完全沒作用，但計數看起來正常。

    參考清單的型別是 `list`、內容在 `list_items`、`text` 是空的。
    這是靜默失效的教科書案例：報「消了 N 項」而東西還在。
    """
    items = [
        _head("References", 2),
        {"type": "list", "sub_type": "ref_text", "page_idx": 1,
         "list_items": ["1. A. Author, 2020.", "2. B. Author, 2021."]},
    ]
    p = rs.plan(items)
    assert rs.apply_to_items(items, p) == 2
    assert items[0]["text"] == "", "標題要被清掉"
    assert items[1]["list_items"] == [], "清單本體也要被清掉"
    assert items[1]["_pp_original_list_items"] == ["1. A. Author, 2020.",
                                                   "2. B. Author, 2021."]


def test_revert_restores_list_items() -> None:
    """還原不需要備份檔 —— 原文就存在項目裡。"""
    items = [{"type": "list", "sub_type": "ref_text", "page_idx": 1,
              "list_items": ["1. A. Author, 2020."]}]
    p = rs.plan(items)
    rs.apply_to_items(items, p)
    assert rs.revert_items(items) == 1
    assert items[0]["list_items"] == ["1. A. Author, 2020."]
    assert "_pp_original_list_items" not in items[0]


def test_apply_is_idempotent_on_already_muted_items() -> None:
    """跑第二次不得把空值蓋掉原文備份 —— 那會讓還原拿回空的。"""
    items = [{"type": "list", "sub_type": "ref_text", "page_idx": 1,
              "list_items": ["1. A. Author, 2020."]}]
    rs.apply_to_items(items, rs.plan(items))
    rs.apply_to_items(items, rs.plan(items))      # 第二次
    rs.revert_items(items)
    assert items[0]["list_items"] == ["1. A. Author, 2020."], "原文必須完好"


def test_reference_section_does_not_claim_layout_noise_types() -> None:
    """參考區段不得認領 header／footer／aside_text —— 那是 `layout_noise` 的地盤。

    **這條是踩出來的。** 分工原本只寫在 `pp/apply.py` 的註解裡（＝沒有執行者），
    於是漂了：參考文獻在最後幾頁，整段圈下去會連那幾頁的書眉與頁尾 DOI 一起圈走。
    兩條規則同時消音時 `_pp_original_text` 會被寫兩次（第二次存的是空字串），
    還原只還原得回一項 —— apply 因此**整份拒絕**。2026-08-09 進料 22 篇有 8 篇
    卡在這裡（36%），而衝突的項目 100% 是 header/footer。

    排除不會少消東西：那些項目仍由 `layout_noise` 消掉，只是不再被兩條同時認領。
    """
    items = [
        {"type": "text", "text": "正文", "page_idx": 0},
        {"type": "text", "text": "References", "text_level": 2, "page_idx": 8},
        {"type": "text", "text": "[1] Y. Xiao, et al.", "page_idx": 8},
        # 參考清單那幾頁的書眉與頁尾 —— 落在區段範圍內，但不歸這條規則管
        {"type": "header", "text": "New J. Phys. 16 (2014) 033026", "page_idx": 8},
        {"type": "footer", "text": "doi:10.1088/1367-2630", "page_idx": 8},
        {"type": "aside_text", "text": "IOP Publishing", "page_idx": 8},
        {"type": "text", "text": "[2] J Z Song, et al.", "page_idx": 9},
    ]
    plan = rs.plan(items)
    got = {m.index for m in plan.mutes}
    assert got == {1, 2, 6}, f"消到了不該碰的型別：{sorted(got)}"
    for m in plan.mutes:
        assert m.item_type not in layout_noise.OWNED_TYPES, m


def test_the_partition_constant_is_shared_not_copied() -> None:
    """兩邊要讀同一份常數。各寫一份的話，改了一邊而另一邊沒改不會有任何訊號。"""
    src = Path(rs.__file__).read_text(encoding="utf-8")
    assert "layout_noise.OWNED_TYPES" in src, (
        "reference_section 沒有引用共用常數 —— 型別清單被抄了一份，會漂")
    assert '"header", "footer"' not in src, (
        "reference_section 裡出現了抄過來的型別清單，改用 layout_noise.OWNED_TYPES")


def test_an_appendix_stops_the_section_even_without_a_heading_level() -> None:
    """附錄是正文，致謝／參考清單不可以延伸進去 —— **就算解析器沒把它標成標題**。

    2026-08-09 實測（2024 Broadband sound absorbers via quality-factor modulation）：
    `Appendix A. The impedance model…` 這一行 MinerU 沒有給 `text_level`，於是
    「消到下一個同級標題為止」跨過它，`Acknowledgments` 一路吃到參考文獻，把整個
    附錄 A（正文 3 項、公式 4 條、圖 3 張）當成致謝消掉。**沒有錯誤訊息**，
    只有比例守衛（35.1%）攔下來。

    ⚠ 前綴比對不是整行比對：附錄標題後面通常還跟著篇名。
    """
    items = [
        {"type": "text", "text": "正文", "page_idx": 0},
        {"type": "text", "text": "Acknowledgments", "text_level": 2, "page_idx": 8},
        {"type": "text", "text": "This work is supported by NSFC…", "page_idx": 8},
        # ↓ 沒有 text_level，長度也不只 "Appendix A"
        {"type": "text",
         "text": "Appendix A. The impedance model of the two-resonator absorber",
         "page_idx": 8},
        {"type": "text", "text": "The transfer matrix method is used to…", "page_idx": 8},
        {"type": "equation", "text": "$$ T_{pp} = … $$", "page_idx": 9},
        {"type": "text", "text": "References", "text_level": 2, "page_idx": 10},
        {"type": "list", "list_items": ["[1] D.-Y. Maa, Potential of microperforated panel"],
         "sub_type": "ref_text", "page_idx": 10},
    ]
    got = {m.index for m in rs.plan(items).mutes}
    assert 3 not in got and 4 not in got and 5 not in got, (
        f"附錄被消掉了：{sorted(got)} —— 那是正文、公式與圖")
    assert got == {1, 2, 6, 7}, f"該消的沒消或多消：{sorted(got)}"


def test_supplementary_information_is_also_a_hard_boundary() -> None:
    """補充材料同理。2017 那篇靠 `text_level` 擋住過，但不能只靠那個。"""
    items = [
        {"type": "text", "text": "References", "text_level": 2, "page_idx": 5},
        {"type": "list", "list_items": ["[1] …"], "sub_type": "ref_text", "page_idx": 5},
        {"type": "text", "text": "Supplementary Information for this paper", "page_idx": 6},
        {"type": "text", "text": "整份補充材料的真內容", "page_idx": 6},
    ]
    got = {m.index for m in rs.plan(items).mutes}
    assert got == {0, 1}, f"補充材料被吃掉了：{sorted(got)}"
