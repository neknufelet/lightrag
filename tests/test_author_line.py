"""封面上單獨一行的人名要自己丟。

PO 2026-08-18 在 19 份真資料裡丟過的作者名就是這種：

    'FLOYD E. TOOLE'   'Michael R. Stinson'   'A. CRAGGS'

期刊把作者排成一行一個名字，所以每個都自成一段、只出現一次。

⚠ PO 自己問到重點：「單獨人名不會錯嗎？在文章裡面的好像不容易單獨拆開來」——
**他是對的，而且量得出來**：把這個樣式套到 1827 段正文上，命中 0 段。
正文裡的人名總是夾在句子裡，不會自成一段。

⚠ 而且規則**只在封面那一區抓**。實測 62 個命中裡 56 個在第 0 頁；
不在封面的那 6 個是期刊標章與掃壞的字（'AUDIO A ES'、'AC IPT'），
不是內容 —— 但既然位置給得起保險，就收緊到封面，一個都不多碰。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from pp.rules.title_block import is_standalone_name  # noqa: E402


def test_the_shapes_journals_actually_use() -> None:
    """實測庫裡真的出現過的幾種寫法。"""
    for text in ["FLOYD E. TOOLE", "Michael R. Stinson", "A. CRAGGS",
                 "Thiago S. Camilo", "Julio Cesar B. Torres", "Samir N. Y. Gerges"]:
        assert is_standalone_name(text), text


def test_a_trailing_comma_still_counts() -> None:
    """作者一行一個時常常帶著逗號或分號。"""
    assert is_standalone_name("Michael R. Stinson,")
    assert is_standalone_name("A. CRAGGS;")


def test_a_sentence_mentioning_a_person_is_not_a_name_line() -> None:
    """⚠ **正文提到人名不算。** 這是這條規則唯一會出事的方向。

    判準是「整段就只有那個名字」—— 正文段落一定更長、而且有小寫的連接詞。
    """
    for text in [
        "Toole reported a similar trend in his listening tests.",
        "The method of Stinson and Champoux is used throughout this paper.",
        "As Rayleigh showed, the scattered field can be expanded in spherical harmonics.",
    ]:
        assert not is_standalone_name(text), text


def test_a_section_heading_is_not_a_name() -> None:
    """章節標題不是人名 —— 教科書裡真的有以人命名的章節。"""
    for text in ["Sound Absorption", "The Rayleigh Integral In Detail",
                 "8.7 Source Above an Interface"]:
        assert not is_standalone_name(text), text


def test_a_name_without_an_initial_is_left_alone() -> None:
    """沒有縮寫點的名字**故意不抓**。

    ⚠ 這是被 `test_a_section_heading_is_not_a_name` 逼出來的：兩個大寫字的
    判準讓 'Sound Absorption' 通過了。實測庫裡 62 個真人名每一個都有縮寫點。
    代價是漏掉 "Michael Stinson" 這種寫法 —— **那是安全的方向**：
    漏抓只是多問人一次，誤抓是丟掉真內容而且不報錯。
    """
    assert not is_standalone_name("Michael Stinson")


def test_one_single_word_is_not_enough() -> None:
    """單一個字不算人名。

    'Frequency'、'Problems' 這種章節標題會被誤抓 —— 至少要兩個詞。
    """
    assert not is_standalone_name("Rayleigh")
    assert not is_standalone_name("Frequency")


def test_something_far_too_long_is_not_a_name_line() -> None:
    """長度也要把關 —— 一整串大寫的標題不是人名。"""
    assert not is_standalone_name(
        "PREDICTING WAVE PROPAGATION BEHAVIOR WITHIN AN ARBITRARY ENCLOSURE")


def test_empty_input_is_safe() -> None:
    assert not is_standalone_name("")
    assert not is_standalone_name("   ")
