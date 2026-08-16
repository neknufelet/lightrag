"""adapters/records.py — 拆章輸出的**結構化記錄**(R10 G3:樹狀勾選)。

舊的 :func:`split_pdf_by_chapter` / :func:`split_epub_by_chapter` 只回傳『檔名清單』
(``list[str]``),GUI 因而只能攤平成單層 CheckboxGroup。一本書動輒數十~數百個節,攤平
後散落難勾。R10 G3 要把章節呈現成**樹狀**(每章一個可收合 Accordion,其下收合該章的節 /
子切 part),故拆章 adapter 需額外吐出**層級 / 編號 / 所屬章群**等中繼資料。

本模組只放這個跨 adapter + service 共用的純資料類別(無 I/O、無第三方依賴),層級 / 章群
的『計算』在各 adapter(沿用 :mod:`core.split_plan` 已算好的 ``level`` / ``number``,不重抄
拆章邏輯)。
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["SplitChapterRecord"]


@dataclass(frozen=True)
class SplitChapterRecord:
    """單一拆章輸出檔的結構化記錄(一個 part = 一筆 = GUI 一個可勾選項)。

    Attributes:
        filename: 寫到 ``split_dir`` 的檔名(basename,不含目錄);由 caller 拼路徑。
        title: 給人看的章節標題(PDF=原始 TOC 標題;EPUB=TOC title / 檔名 fallback;
            純文字=檔名 stem)。可能不唯一(同名節 / 多 part),故**識別**請用 ``filename``
            或 caller 拼出的路徑,不要用 ``title``。
        level: TOC 層級(1=章 / 頂層,2=節,以此類推);EPUB / 純文字恆為 1(扁平)。
        number: :mod:`core.split_plan` 算出的自動編號(章=N*100、節=N*100+s、附錄=900+、
            前言=小序號);未啟用前綴時為 ``None``。
        group_index: 所屬『章群』索引(0 起算);同一章的節 / 子切 part 共用同一值。GUI
            以此把同章項目收進同一 Accordion。
        group_title: 該章群的顯示標題(通常為該群第一個 level==1 項目的標題)。
        part_index: 子切後的 part 序號(1 起算;未子切為 1)。
    """

    filename: str
    title: str
    level: int
    number: int | None
    group_index: int
    group_title: str
    part_index: int = 1
