"""拆章勾選清單的純算層：吃拆章計畫，回一份給人勾的清單。

**這一層不開畫面、不切檔、不寫檔。** 它只回答兩件事：這本書有哪幾列可以勾、
規則先幫你勾成什麼樣。畫面與寫檔是後面的事。

命名照 `docs/design-one-name-20260814.md`：``<KEY>_<NN> <尾巴>``，
``NN`` 是兩位流水號、**只保證唯一與穩定，不承載章節號**。
舊的五碼書碼（``01405_``）不能當身分 —— 2026-08-17 實測庫裡 89 個切好的章
有 30 個前綴撞號、0 個帶 Zotero key。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from chapters.naming import MAX_FILENAME_LENGTH  # noqa: E402
from chapters.selection import build_selection  # noqa: E402
from chapters.split_plan import PdfChapterPlan, plan_pdf_split  # noqa: E402

# 一本假書：前言、兩章（各一節）、參考文獻。level 與頁碼照 fitz get_toc 的形狀。
BOOK_TOC = [
    (1, "Preface", 1),
    (1, "Chapter 1 Sound", 5),
    (2, "1.1 Waves", 6),
    (1, "Chapter 2 Rooms", 20),
    (2, "2.1 Modes", 22),
    (1, "References", 40),
]
BOOK_PAGES = 50


def _plans(max_level: int = 2) -> list[PdfChapterPlan]:
    return plan_pdf_split(BOOK_TOC, BOOK_PAGES, max_level=max_level, chapter_prefix=True)


def test_rules_pre_check_body_and_skip_frontmatter() -> None:
    """規則先幫你勾好：正文勾、前言與參考文獻不勾。

    這是「你只改勾錯的」的前提。全部預設勾或全部預設不勾，人就得逐列看完
    兩三百列 —— 那正是這個設計要避免的。
    """
    rows = build_selection(_plans(), key="W7M3NDKV", tail="2015 - Some Book")

    picked = {r.title: r.selected for r in rows}
    assert picked == {
        "Preface": False,
        "Chapter 1 Sound": True,
        "1.1 Waves": True,
        "Chapter 2 Rooms": True,
        "2.1 Modes": True,
        "References": False,
    }


def test_unchecked_rows_stay_in_the_list() -> None:
    """沒勾的列照樣要在清單裡（藍桶第 2 條：不得無聲消失）。

    整列不見的話，讀的人分不出「看過決定不要」與「根本沒偵測到」。
    """
    rows = build_selection(_plans(), key="W7M3NDKV", tail="2015 - Some Book")

    assert len(rows) == len(BOOK_TOC)
    assert [r.title for r in rows] == [t for _, t, _ in BOOK_TOC], "順序要照書的順序"


def test_every_row_says_who_decided_it() -> None:
    """每一列都要講「這格是誰決定的」。剛算完時全部是規則決定的。"""
    rows = build_selection(_plans(), key="W7M3NDKV", tail="2015 - Some Book")

    assert {r.decided_by for r in rows} == {"rule"}


def test_serial_is_assigned_over_the_whole_plan_not_the_selected_rows() -> None:
    """``NN`` 配在**完整計畫**上，包含沒勾的列。

    這是 PO 2026-08-17 那條裁決（「照舊的切、檔名不變」）的直接後果：
    如果配號跳過沒勾的列，把第 3 列取消勾選會讓第 4 列從 ``_04`` 遞補成 ``_03``
    —— **檔名跟著勾選浮動**，同一本書切兩次就會長出兩套檔名，而下游的
    MinerU 解析與 DeepSeek 抽取都要重跑一次（燒 token、燒錢）。

    所以沒勾的列照樣佔一個號，取消勾選在號碼上留下**空隙**。
    空隙不違反規格 —— `NN` 只保證唯一與穩定，本來就不承載章節號。
    """
    rows = build_selection(_plans(), key="W7M3NDKV", tail="2015 - Some Book")

    # Preface 與 References 沒勾，但它們各自佔掉 _01 與 _06。
    assert [r.serial for r in rows] == [1, 2, 3, 4, 5, 6]

    selected = [r.serial for r in rows if r.selected]
    assert selected == [2, 3, 4, 5], "取消勾選要留下空隙，不是把後面往前遞補"


def test_filename_carries_the_zotero_key() -> None:
    """檔名前面是 ``<KEY>_<NN>``，不是舊的五碼書碼。

    舊的 ``01405_`` 是「這本書的第 14 章第 5 節」，換一本書就從頭數 —— 它不是身分。
    2026-08-17 實測：庫裡 89 個切好的章，30 個前綴撞號、0 個帶 Zotero key。
    """
    rows = build_selection(_plans(), key="W7M3NDKV", tail="2015 - Some Book")

    assert rows[0].filename.startswith("W7M3NDKV_01 ")
    assert rows[3].filename.startswith("W7M3NDKV_04 ")
    assert "Chapter 2 Rooms" in rows[3].filename
    assert rows[3].filename.endswith(".pdf")


def test_long_titles_are_cut_at_the_tail_never_at_the_identity() -> None:
    """長標題砍尾巴，頭部的身分完整留著。

    ⚠ 那個 80 是砍**標題**，不含前綴與 ``.pdf`` —— 2026-08-17 在 dker 量到真實
    檔名最長 90 字（`01407_` 六碼 ＋ 80 ＋ `.pdf`）。以前我把它讀成「整個檔名 80」，
    以實測為準改回來。

    砍尾巴不砍頭是 `design-one-name-20260814.md` 的結論（Zotero 自己也這樣做，
    翻譯本先砍到 110 再接 `_zh-TW_dual`，頭部從沒被動過）。
    """
    long_toc = [(1, "Chapter 1 " + "Very Long Title " * 12, 1)]
    rows = build_selection(
        plan_pdf_split(long_toc, 30, max_level=2, chapter_prefix=True),
        key="W7M3NDKV", tail="2015 - Some Book",
    )

    name = rows[0].filename
    assert name.startswith("W7M3NDKV_01 "), "砍尾巴不得砍掉身分"
    body = name.removeprefix("W7M3NDKV_01 ").removesuffix(".pdf")
    assert len(body) == MAX_FILENAME_LENGTH, "超長標題要剛好被砍到上限"
