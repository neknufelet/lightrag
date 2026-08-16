"""拆章檔名的三個純函式。

**為什麼要重寫這支。** `naming.py` 是 2026-08-17 從 `vibevoice-v2` 搬過來的，
但它原本的測試（`tests/test_naming.py`，643 行）**搬不過來也跑不動** ——
那是「v2 跟 v1 行為一致」的比對測試，比對對象是 `_reference/` 底下的 v1 原始碼，
而那份碼已經從 vibevoice-v2 的 repo 裡刪掉了（2026-08-17 實跑：7 個檔在
collection 階段就 `FileNotFoundError`）。

所以這裡測的不是「跟 v1 一樣」，是**「lightrag 需要它做到什麼」**。

⚠ 兩個判準來自庫裡的實物，不是憑印象：
* 五碼前綴 `01405_` —— `01405_5.5 The influence…`
* 砍 80 字 —— `…imperfect diffusene`，原文 `diffuseness`，82 砍成 80
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from chapters.naming import (  # noqa: E402
    APPENDIX_PREFIX_BASE,
    CHAPTER_NUMBER_MULTIPLIER,
    MAX_FILENAME_LENGTH,
    format_prefix_number,
    pdf_chapter_prefix,
    sanitize_filename,
)

# ── 前綴：字典序必須等於閱讀順序 ───────────────────────────────────────────

def test_prefix_is_zero_padded_to_five() -> None:
    """庫裡的實物長這樣：`01405_5.5 The influence…`（第 14 章第 5 節）。"""
    assert pdf_chapter_prefix(14 * CHAPTER_NUMBER_MULTIPLIER + 5) == "01405_"


def test_sorting_by_filename_gives_reading_order() -> None:
    """這就是零填充存在的唯一理由 —— 少一位，第 10 章會排到第 2 章前面。"""
    nums = [1 * CHAPTER_NUMBER_MULTIPLIER, 2 * CHAPTER_NUMBER_MULTIPLIER,
            10 * CHAPTER_NUMBER_MULTIPLIER, 2 * CHAPTER_NUMBER_MULTIPLIER + 1]
    got = [pdf_chapter_prefix(n) for n in nums]
    assert sorted(got) == ["00100_", "00200_", "00201_", "01000_"]


def test_appendix_sorts_after_all_body_chapters() -> None:
    """附錄從 900 起跳。第 8 章（800）要排在附錄前面，第 9 章會撞 —— 見下。"""
    assert pdf_chapter_prefix(APPENDIX_PREFIX_BASE) > pdf_chapter_prefix(
        8 * CHAPTER_NUMBER_MULTIPLIER)


def test_appendix_base_collides_with_chapter_nine() -> None:
    """⚠ **這不是測試通過，是把一個洞釘住。**

    附錄基底 900 ＝ 第 9 章的編號（9 × 100），而 `split_plan.py:510` 的
    `appendix_idx` **從 0 起算**，所以第一個附錄就是 900。一本有第 9 章又有
    附錄的書，兩者前綴完全相同；第二個附錄（901）會撞第 9 章第 1 節。

    **在碼裡是真的，在現有語料裡還沒咬到**：2026-08-17 實查 `/data/lightrag/library`
    的 88 份拆章檔，`008xx` 與 `009xx` **一份都沒有**（現有那幾本沒切到附錄）。

    釘在這裡是因為它安靜：撞了不會報錯，只會有兩個檔名前綴一樣。真要修就是改
    `APPENDIX_PREFIX_BASE`，而那會改變已經切好的檔名 —— 是決定，不是順手修。
    """
    assert pdf_chapter_prefix(APPENDIX_PREFIX_BASE) == pdf_chapter_prefix(
        9 * CHAPTER_NUMBER_MULTIPLIER)


def test_preamble_zero_sorts_first() -> None:
    """前言用 0，全零前綴刻意排最前面。"""
    assert format_prefix_number(0) == "00000"
    assert "00000_" < "00100_"


# ── 檔名清理 ───────────────────────────────────────────────────────────────

def test_truncates_at_eighty_characters() -> None:
    """庫裡的實物：`diffuseness`（82 字的標題）被砍成 `diffusene`（80）。"""
    title = "Applications of the radiosity integral_ the influence of imperfect diffuseness"
    assert len(title) > MAX_FILENAME_LENGTH - 5
    got = sanitize_filename("x" * 100)
    assert len(got) == MAX_FILENAME_LENGTH


def test_truncation_can_be_disabled() -> None:
    assert len(sanitize_filename("x" * 100, max_length=0)) == 100


def test_windows_illegal_characters_become_underscore() -> None:
    """`5.5 The influence…` 這種標題常帶 `/` 與 `:`，直接當檔名會炸。"""
    assert sanitize_filename('a/b\\c*d?e:f"g<h>i|j') == "a_b_c_d_e_f_g_h_i_j"


def test_control_and_zero_width_characters_are_dropped() -> None:
    """零寬空格是最陰的一種：看不見，但檔名會對不起來。"""
    assert sanitize_filename("Sound\u200babsorption\x00 ") == "Soundabsorption"


def test_tab_becomes_space_not_dropped() -> None:
    """⚠ Tab 的 Unicode 類別是 Cc（控制字元），但這裡刻意轉成空格。

    丟掉的話 `Chapter\\t1` 會變成 `Chapter1`，兩個詞黏在一起。
    """
    assert sanitize_filename("Chapter\t1") == "Chapter 1"


def test_whitespace_is_collapsed_and_stripped() -> None:
    assert sanitize_filename("  Sound   absorption  ") == "Sound absorption"


def test_empty_result_falls_back_instead_of_returning_blank() -> None:
    """全部被清光時要有名字 —— 空字串當檔名會讓整批停在一個看不懂的錯誤上。"""
    assert sanitize_filename(" \u200b\x00") == "untitled"
    assert sanitize_filename("") == "untitled"


def test_cjk_titles_survive_intact() -> None:
    """語料裡有中文文獻。中文是 Lo 類別，不得被當成控制字元清掉。"""
    assert sanitize_filename("微穿孔板吸聲結構") == "微穿孔板吸聲結構"
