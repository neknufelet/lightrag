"""標題頁消音：位置只圈範圍，每一項要自己通過測試才消。

**為什麼需要這支**：2026-08-09 逐份看過 27 份解析結果，「從標題消到第一個小標題
為止」這個直覺做法被真實資料證偽了三次 —— 有三份文件的第一項是 `lvl=1` 標題，
但標題後面接的是**正文或摘要**。照位置消會把真內容整段吃掉，而且不報錯。

下面的測資全部是那 27 份裡的真實文字，不是想像的。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from pp.rules import title_block as tb  # noqa: E402


def _title(text: str) -> dict:
    return {"type": "text", "text": text, "text_level": 1, "page_idx": 0}


def _head(text: str, level: int = 2) -> dict:
    return {"type": "text", "text": text, "text_level": level, "page_idx": 0}


def _body(text: str, itype: str = "text", page: int = 0) -> dict:
    return {"type": itype, "text": text, "page_idx": page}


# ── 真實的作者列（12 份文件抄下來的）────────────────────────────────────────
AUTHOR_LINES = [
    r"Min Yang1, Shuyu Chen³, Caixing Fu13, Ping Sheng1,2,\*",
    "Houyou Long, Shuxiang Gao, Ying Cheng, and Xiaojun Liu",
    "Thydal, Tobias; Pind, Finnur; Jeong, Cheol-Ho; Engsig-Karup, Allan Peter",
    "James Hipperson1,2, Jonathan A. Hargreaves1, Trevor J. Cox1",
    "Sibo Huang, Xinsheng Fang, Xu Wang, Badreddine Assouar, Qian Cheng, and Yong Li",
    "Fei Wu, Yong Xiao, Dianlong Yu, Honggang Zhao, Yang Wang, and Jihong Wen",
    "Józef KOTUS(1), (2), Andrzej CZYŻEWSKI(1), Bożena KOSTEK(2)",
    r"Noé Jiménez1\*, Trevor J. Cox², Vicent Romero-García1, and Jean-Philippe Groby1",
    "Xiaotian Bai a,b, Zhaoyang Xiao a,c, Huaitao Shia,b, Ke Zhang b, Zhong Luo d, Yuhou Wub",
    "Haiqin Duan, Xinmin Shen, Enshuai Wang, Fei Yang, Xiaonan Zhang, and Qin Yin",
]

# ── 真實的單位列 ──────────────────────────────────────────────────────────
AFFILIATION_LINES = [
    "1Department of Physics, HKUST, Clear Water Bay, Kowloon, Hong Kong, China",
    "2Institute for Advanced Study, HKUST, Clear Water Bay, Kowloon, Hong Kong, China",
    "3Acoustic Metamaterials Co. Ltd, No.2 Science Park West Avenue",
    "a School of Aerospace Engineering and Applied Mechanics, Tongji University, Shanghai",
    "d Department of Engineering Mechanics, North University of China, Taiyuan 030051, China",
    "Faculty of Electronics, Telecommunications and Informatics",
    "Gdańsk University of Technology",
    "AFFILIATIONS",
    "1Acoustics Research Centre, University of Salford, UK 2Funktion-One Research Ltd. Dorking, UK",
]

# ── 真實的出版資訊（機構節點的來源）────────────────────────────────────────
PUBLICATION_LINES = [
    "Citation: Appl. Phys. Lett. 112, 033507 (2018);",
    "Cite as: Appl. Phys. Lett. 118, 241904 (2021); doi: 10.1063/5.0054562",
    "View online: https://doi.org/10.1063/1.5013225",
    "View Table of Contents: http://aip.scitation.org/toc/apl/112/3",
    "Published by the American Institute of Physics",
    "Published in: Applied Acoustics",
    "Publication date: 2021",
    "Link back to DTU Orbit",
    "Document Version Peer reviewed version",
]

# ── 真實的正文／摘要：一項都不可以消 ──────────────────────────────────────
#
# 這一組是本規則的核心風險。它們全部出現在「標題之後、第一個小標題之前」，
# 位置上與作者列一模一樣。
REAL_CONTENT_LINES = [
    # 01701_8.1 General remarks on instrumentation：教科書章節，標題後就是正文
    "The starting point of modern room acoustics is marked by attempts to define physical "
    "sound field parameters which are related to the subjective impressions of listeners",
    "Room acoustic measurements are necessary for research and design purposes and are also "
    "used as a tool for the acoustical diagnosis of existing halls and rooms",
    # C Equivalent Networks：同上
    "The application of equivalent networks is a useful method for the solution of many tasks "
    "in acoustics, and it is used in this book for many purposes and derivations",
    # 2016 - 3D Acoustic Field：span 第 11 項是摘要
    "The aim of this paper is two-fold. First, some basic notions on acoustic field intensity "
    "and its measurement are recalled, then the design of a probe is presented in detail",
]


def test_author_lines_are_muted() -> None:
    for line in AUTHOR_LINES:
        assert tb._signal(line) is not None, f"作者列沒被認出來：{line!r}"


def test_affiliation_lines_are_muted() -> None:
    for line in AFFILIATION_LINES:
        assert tb._signal(line) == "affiliation", f"單位列沒被認出來：{line!r}"


def test_publication_lines_are_muted() -> None:
    for line in PUBLICATION_LINES:
        assert tb._signal(line) == "publication", f"出版資訊沒被認出來：{line!r}"


def test_real_content_is_never_muted() -> None:
    """**這是本規則最重要的一條。** 消掉真內容不會報錯，只會安靜地少掉知識。"""
    for line in REAL_CONTENT_LINES:
        assert tb._signal(line) is None, f"真內容被當成標題頁區塊：{line[:60]!r}"


def test_prose_mentioning_a_university_is_not_muted() -> None:
    """散文裡提到 University 不算單位列。

    不擋這一條的話，正文一句「…… measured at Tongji University ……」就會把
    整段真內容消掉 —— 而消掉的是一整項，不是那個詞。
    """
    line = ("The measurements reported in this section were carried out in the anechoic "
            "chamber at Tongji University during the spring of 2024, using the same "
            "impedance tube described above")
    assert tb.looks_like_prose(line)
    assert tb._signal(line) is None


def test_textbook_chapter_does_not_fire_at_all() -> None:
    """教科書章節第 0 頁是從半句話開始的正文，第一項沒有 text_level。

    實測 `01204_3.4 Non-rigid walls`：照位置消會吃掉 8 項推導與公式。
    """
    items = [_body("octants. Hence, only half of them have been accounted for so far."),
             _body("The number of all lattice points corresponding to tangential modes"),
             {"type": "equation", "text": "$$N_{tan}=...$$", "page_idx": 0}]
    p = tb.plan(items)
    assert not p.fired
    assert p.mutes == []
    assert "lvl=1" in p.reason


def test_title_page_with_body_text_holds_instead_of_muting() -> None:
    """有 lvl=1 標題但後面是正文（01701、C Equivalent Networks 的形狀）。

    規則會開火（結構符合），但每一項都通不過測試，所以**一項都不消**，
    全部進 held 讓人看得到。
    """
    items = [_title("8.1 General remarks on instrumentation"),
             _body(REAL_CONTENT_LINES[0]),
             _body(REAL_CONTENT_LINES[1]),
             _head("8.2 Sound pressure measurement")]
    p = tb.plan(items)
    assert p.fired
    assert p.mutes == []
    assert len(p.held) == 2
    assert all(h.why == "散文" for h in p.held)


def test_abstract_inside_the_span_survives() -> None:
    """2016 那份的形狀：作者、單位、地址、摘要、關鍵詞全在同一個區塊裡。

    前面的要消，摘要不能消 —— 這正是「位置不能單獨當判準」的理由。
    """
    items = [_title("3D Acoustic Field Intensity Probe Design and Measurements"),
             _body(AUTHOR_LINES[6]),
             _body("(1) Multimedia Systems Department"),
             _body("Gdańsk University of Technology"),
             _body("Narutowicza 11/12, 80-233 Gdańsk, Poland; e-mail: bokostek@audioakustyka.org"),
             _body(REAL_CONTENT_LINES[3]),
             _body("Keywords: sound intensity; acoustic vector sensor; calibration.")]
    p = tb.plan(items)
    muted = {m.index for m in p.mutes}
    assert 1 in muted and 2 in muted and 3 in muted and 4 in muted
    assert 5 not in muted, "摘要被消掉了"
    assert 6 not in muted, "關鍵詞被消掉了"


def test_span_stops_at_the_first_heading() -> None:
    items = [_title("Optimal Sound-Absorbing Structures"),
             _body(AUTHOR_LINES[0]),
             _body(AFFILIATION_LINES[0]),
             _head("Abstract"),
             _body("Causal nature of the acoustic response dictates an inequality")]
    p = tb.plan(items)
    assert {m.index for m in p.mutes} == {1, 2}


def test_span_stops_at_the_page_break() -> None:
    """翻頁就結束。第 1 頁的內容不是標題頁區塊。"""
    items = [_title("Some Paper"),
             _body(AUTHOR_LINES[1]),
             _body("Later body text on the next page", page=1)]
    p = tb.plan(items)
    assert {m.index for m in p.mutes} == {1}


def test_page_zero_footnote_with_email_is_muted() -> None:
    """通訊作者的 email 掛在頁腳，而頁腳在 Abstract 之後 —— 不在區塊裡。

    實測 2017 Optimal：`\\*Corresponding author. Email: sheng @ust.hk`
    """
    items = [_title("Optimal Sound-Absorbing Structures"),
             _body(AUTHOR_LINES[0]),
             _head("Abstract"),
             _body("Causal nature of the acoustic response dictates an inequality"),
             _body(r"\*Corresponding author. Email: sheng @ust.hk", itype="page_footnote")]
    p = tb.plan(items)
    muted = {m.index for m in p.mutes}
    assert 4 in muted
    assert 3 not in muted


def test_headers_are_left_to_layout_noise() -> None:
    """header／footer 不歸這條規則管。兩條規則消到同一項的話，
    `_pp_original_text` 會被寫兩次而還原只還原得了一次。"""
    items = [_title("Some Paper"),
             _body(AUTHOR_LINES[1]),
             _body("121st ASEE Annual Conference & Exposition", itype="header"),
             _body("©American Society for Engineering Education, 2014", itype="footer")]
    p = tb.plan(items)
    assert {m.index for m in p.mutes} == {1}


def test_apply_is_revertible() -> None:
    """消音要能還原 —— `layout_noise.revert_items` 認同一個鍵。"""
    from pp.rules import layout_noise

    items = [_title("Some Paper"), _body(AUTHOR_LINES[1]), _body(AFFILIATION_LINES[0])]
    p = tb.plan(items)
    assert tb.apply_to_items(items, p) == 2
    assert items[1]["text"] == "" and items[2]["text"] == ""
    assert layout_noise.revert_items(items) == 2
    assert items[1]["text"] == AUTHOR_LINES[1]
    assert items[2]["text"] == AFFILIATION_LINES[0]
