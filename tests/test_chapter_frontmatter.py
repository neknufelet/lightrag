"""前言／附錄的英文辨識（2026-08-17 加）。

**為什麼英文不能沿用中文那套比法。** 中文關鍵字是複合詞（`附錄`、`參考`），
夾在正文標題裡的機會低。英文不是 —— `Index` 會命中 `Index of refraction`、
`Notes` 會命中 `Notes on measurement`，兩個都是聲學的真章節。

判準是**寧可漏抓，不要抓錯**：

* 漏抓 → 那一章拿到普通編號，人在勾選清單裡照樣看得到
* 抓錯 → 真章節被編成 900+ 的附錄，排到全書最後面

⚠ 這兩個判定**目前只影響編號**（`split_plan.py:522-527`），不會刪掉任何內容。
之後接進料台時它們會決定「哪幾章預先勾起來」，那時抓錯的代價才會變大。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from chapters.split_plan import is_appendix_title, is_preamble_title  # noqa: E402

# 你庫裡真正的章節標題，2026-08-17 從 `/data/lightrag/library` 撈的樣本。
# 全部是**正文**，一個都不該被判成前言或附錄。
REAL_BODY_TITLES = (
    "10.1 Acoustical scale models",
    "10.2 Linear Acoustic Equations and Energy Dissipation",
    "10.3 Vorticity, Entropy, and Acoustic Modes",
    "10.4 Acoustic Boundary-Layer Theory",
    "10.9 Problems",
    "10 Effects of Viscosity and Other Dissipative Processes",
    "11.10 Ballistic Shocks_ Sonic Booms",
    "11.1 Loudspeakers",
    "11.3 Weak-Shock Theory",
    "5.5 The influence of unequal path lengths",
    "6.5 Sound propagation in porous materials, the rayleigh model",
    "8.7 Source Above an Interface",
    "9.7 Contour-Integral Solution for Diffraction by a Wedge",
    "L Capsules and Cabins",
)


def test_no_real_chapter_title_is_misread() -> None:
    """回歸：實跑 88 個真標題對所有關鍵字**零命中**，這裡守住其中的樣本。"""
    for title in REAL_BODY_TITLES:
        assert not is_preamble_title(title), f"正文被當成前言：{title}"
        assert not is_appendix_title(title), f"正文被當成附錄：{title}"


# ── 該抓到的 ───────────────────────────────────────────────────────────────

def test_english_preamble_is_recognised() -> None:
    for title in ("Preface", "PREFACE", "Foreword", "Acknowledgements",
                  "Acknowledgment", "About the Author", "Dedication",
                  "Copyright", "Table of Contents", "Contents", "Abstract"):
        assert is_preamble_title(title), title


def test_english_appendix_is_recognised() -> None:
    for title in ("Appendix", "Appendix A", "Appendix B: Derivations",
                  "Appendices", "Bibliography", "References",
                  "References and Further Reading", "Glossary", "Index",
                  "Subject Index", "Author Index", "Notation",
                  "List of Symbols", "Epilogue", "Afterword"):
        assert is_appendix_title(title), title


# ── 不該抓到的（每一條都是真的會出現的聲學題目）─────────────────────────

def test_index_inside_a_real_title_is_not_appendix() -> None:
    """⚠ 這條是英文要另立規則的**唯一理由**。子字串比對會在這裡出事。"""
    for title in ("Index of refraction", "Index of Refraction in Moving Media",
                  "Articulation index", "Speech Transmission Index"):
        assert not is_appendix_title(title), title


def test_notes_inside_a_real_title_is_not_appendix() -> None:
    for title in ("Notes on measurement uncertainty",
                  "Notes on the Impedance Tube Method"):
        assert not is_appendix_title(title), title


def test_singular_reference_is_not_appendix() -> None:
    """`References`（複數）是後記；`Reference Sound Source` 是真的量測題目。"""
    assert is_appendix_title("References")
    assert not is_appendix_title("Reference Sound Source Calibration")


def test_introduction_is_deliberately_not_preamble() -> None:
    """⚠ **刻意不收。**

    中文那邊把「緒論／導論／引言」當前言，但英文學術書與論文的 `Introduction`
    幾乎都是第一章正文。收了會把真內容編成前言（小序號，排到全書最前面）。
    """
    assert not is_preamble_title("Introduction")
    assert not is_preamble_title("1 Introduction")
    assert not is_preamble_title("Introduction to Room Acoustics")


def test_contents_only_matches_when_the_title_is_short() -> None:
    """`Contents` 是目錄，但 `Frequency Contents of Impulse Responses` 不是。"""
    assert is_preamble_title("Contents")
    assert is_preamble_title("Table of Contents")
    assert not is_preamble_title("Frequency Contents of Impulse Responses")


def test_chinese_matching_is_unchanged() -> None:
    """英文是**加上去的**，中文那條路一個字都沒動（鐵則 2）。"""
    assert is_preamble_title("目錄")
    assert is_preamble_title("第一章 前言與研究動機")   # 子字串，中文本來就這樣
    assert is_appendix_title("附錄 A")
    assert is_appendix_title("參考文獻")


def test_cover_pages_are_preamble() -> None:
    """封面算前言。**2026-08-17 實測漏掉的那一個。**

    PO 第一本真的透過 Zotero 送進來的教科書（《The science of sound》，63 章），
    規則正確地沒勾「Table of Contents」「Preface to the Third Edition」「Index」，
    **卻把「Cover」勾了起來** —— 封面沒有內容，切出去就是一份垃圾。
    """
    for title in ("Cover", "cover", "Front Cover", "Back Cover"):
        assert is_preamble_title(title), f"{title!r} 應該算前言"


def test_cover_only_matches_the_whole_title() -> None:
    """「cover」走**完全比對**，不得誤傷真章節。

    走開頭比對的話 `Coverage of the audible range` 會被當成封面而預設不勾 ——
    而抓錯比漏抓貴得多：真章節被排到全書最後面，人不一定會發現。
    """
    for title in ("Coverage of the audible range", "Covering materials for absorbers",
                  "Discovery of ultrasound"):
        assert not is_preamble_title(title), f"{title!r} 是真章節，不得當成封面"


def test_titles_without_letters_do_not_crash() -> None:
    for title in ("", "   ", "10.9", "第 3 章"):
        assert isinstance(is_preamble_title(title), bool)
        assert isinstance(is_appendix_title(title), bool)
