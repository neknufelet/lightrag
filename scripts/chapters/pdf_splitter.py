"""PDF 拆章 adapter — 用 fitz 開 PDF,委派 :mod:`core.split_plan` 算計畫,寫出子 PDF。

v1 的 :func:`split_pdf_by_chapter`(_reference chapter_splitter.py:152-285)把
『決定切哪些章 / 編號 / 頁範圍 / 子切點』與『開 fitz、寫檔』綁在同一支。v2 把前者
抽進純函式 :func:`chapters.split_plan.plan_pdf_split`(已有 golden test),
本 adapter 只保留**真正的 I/O**:

1. 用 fitz 開 PDF、取 TOC、(需子切時)解析逐頁字型特徵成
   :class:`~chapters.split_plan.PageFeatures`;
2. 把 TOC / 頁特徵餵給 :func:`plan_pdf_split` 取得拆章計畫;
3. 依計畫的每個 part 開新 fitz doc、``insert_pdf`` 指定頁範圍、``tobytes()`` 寫出。

行為來源(characterization,逐項標注 file:line):

* 檔不存在 raise :class:`FileNotFoundError`:chapter_splitter.py:176-177。
* 無 TOC raise :class:`ValueError`(中文訊息):chapter_splitter.py:187-188。
* 子切點偵測需逐頁字型 → 只在 ``max_pages > 0`` 時解析(對應 _reference 只在
  子切分支讀 ``get_text("dict")``,chapter_splitter.py:248-251)。
* 磁碟去重(``while os.path.exists`` 加 ``_N`` 後綴):chapter_splitter.py:271-275。
* 每個 part 開新 doc、``insert_pdf(from_page, to_page)``、``tobytes()`` 寫 bytes
  (非 ``save()``)、``close()``:chapter_splitter.py:266-281。
* 回傳『檔名清單』由 caller 拼路徑:chapter_splitter.py:282-285。

設計鐵則(藍桶):pathlib、``with`` 管理寫檔、:mod:`logging` 不用 ``print``、
fitz 延遲 import(無 PyMuPDF 仍能 import 本模組),完整 type hints。
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

from chapters.records import SplitChapterRecord
from chapters.split_plan import (
    PageFeatures,
    PageLine,
    PageSpan,
    PdfChapterPart,
    PdfChapterPlan,
    is_degenerate_pdf_toc,
    plan_pdf_no_toc,
    plan_pdf_split,
)

if TYPE_CHECKING:  # pragma: no cover - 型別用,避免 runtime 依賴 fitz
    import fitz

logger = logging.getLogger(__name__)

#: 無 TOC 時的中文錯誤訊息(_reference chapter_splitter.py:188);caller(GUI / CLI)
#: 依此訊息 / 例外型別做 UI 提示,故凍結為具名常數。
NO_TOC_MESSAGE: str = "PDF 沒有目錄（TOC），無法拆分"

#: 無 TOC 策略(R10 L1):``"error"`` 維持舊行為 raise;``"whole"`` 整本當一章;
#: ``"pages"`` 用 ``max_pages`` 固定每段頁數**確定性**分段(不靠標題偵測,避免亂跳)。
NO_TOC_ERROR: str = "error"
NO_TOC_WHOLE: str = "whole"
NO_TOC_PAGES: str = "pages"

#: fitz text block 的『文字 block』type 值(``block["type"] == 0``);其餘(圖片
#: 等)與標題偵測無關,解析時跳過(_reference chapter_splitter.py:69,87)。
_TEXT_BLOCK_TYPE: int = 0


def _require_fitz() -> fitz:
    """延遲 import PyMuPDF(``fitz``),缺套件時給友善錯誤。

    對應 _reference chapter_splitter.py:20-28。

    Returns:
        匯入的 ``fitz`` 模組。

    Raises:
        RuntimeError: 環境未安裝 PyMuPDF。
    """
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:  # pragma: no cover - 取決於環境
        raise RuntimeError(
            "PyMuPDF (`fitz`) is required for PDF chapter splitting. "
            "Install `pymupdf` in the active environment."
        ) from exc
    return fitz


def pdf_has_toc(pdf_path: Path) -> bool:
    """偵測 PDF 是否帶**可用**目錄——假目錄視同無 TOC。

    『有 TOC / 無 TOC』是文件的**客觀事實**(非使用者選項):有 TOC 走 :func:`plan_pdf_split`
    的章節層次拆分,無 TOC 才談整檔 / 固定頁數策略(:func:`_compute_pdf_plans`)。GUI 上傳後以本
    函式探測,只顯示**生效**的那組旋鈕,不再把兩組互斥選項並排。

    某些 PDF 的 ``get_toc()`` 雖非空，內容卻是每頁一筆、全部 level 1、標題只是頁碼。
    這種退化 TOC 會造成數百個一頁碎片，故以 :func:`is_degenerate_pdf_toc` 排除。

    Args:
        pdf_path: PDF 路徑。

    Returns:
        有非空且非退化的 TOC 才回 ``True``。

    Raises:
        FileNotFoundError: 檔案不存在。
    """
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF 檔案不存在: {pdf_path}")
    fitz = _require_fitz()
    try:
        doc = fitz.open(pdf_path)
    except (RuntimeError, ValueError) as exc:
        # fitz 對損壞 / 加密 / 空檔 / 非 PDF 丟 FileDataError / EmptyFileError(皆 RuntimeError
        # 子類)。轉成 ValueError,讓服務層(api)統一映 422(對齊 /splits 既有 ValueError→422),
        # 不外溢成裸 500 —— probe 是上傳後**第一個**打的端點,壞檔須乾淨回報(R1 對抗審查)。
        raise ValueError(f"無法讀取 PDF（檔案損壞、加密或非 PDF）：{exc}") from exc
    try:
        toc = [(level, title, page) for level, title, page in doc.get_toc()]
        return bool(toc) and not is_degenerate_pdf_toc(toc, doc.page_count)
    finally:
        doc.close()


def read_toc(pdf_path: Path) -> tuple[list[tuple[int, str, int]], int]:
    """讀出 PDF 的目錄與總頁數。勾選畫面的入口。

    **兩個一起回**：少了總頁數就算不出最後一章的結束頁。分兩次開檔既慢，
    又可能讀到不同的檔（中途被換掉），那正是「照舊的切、檔名不變」要防的。

    這支是 fitz adapter 的職責 —— 開檔在這裡發生，讓
    :mod:`chapters.selection` 與 :mod:`chapters.picker_html` 維持純函式、不碰磁碟，
    因此在沒有資料的機器上（coder）也驗得完。

    Args:
        pdf_path: PDF 路徑。

    Returns:
        ``(toc, total_pages)``。``toc`` 是 ``[(level, title, page), ...]``，
        ``page`` 為 1-indexed，同 fitz ``get_toc()`` 的形狀。
        **沒有目錄時回空清單**，不是丟例外、也不是硬編一個第 1 層 ——
        硬編等於宣稱知道書的結構，而我們不知道。

    Raises:
        FileNotFoundError: 檔案不存在。
        ValueError: 檔案損壞、加密或不是 PDF（與 :func:`pdf_has_toc` 同一套處置）。
    """
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF 檔案不存在: {pdf_path}")
    fitz = _require_fitz()
    try:
        doc = fitz.open(pdf_path)
    except (RuntimeError, ValueError) as exc:
        raise ValueError(f"無法讀取 PDF（檔案損壞、加密或非 PDF）：{exc}") from exc
    try:
        toc = [(level, title, page) for level, title, page in doc.get_toc()]
        return toc, doc.page_count
    finally:
        doc.close()


def read_page_count(pdf_path: Path) -> int:
    """只讀 PDF 的總頁數。收件匣清單那一格。

    **為什麼不用 `read_toc`**：那支會順便把整份目錄解出來，而清單只要一個數字。
    收件匣每 3 秒被重畫一次，白工會跟著檔案數一起長。

    這支是 fitz adapter 的職責 —— 開檔在這裡發生，跟 :func:`read_toc` 同一條界線。

    Args:
        pdf_path: PDF 路徑。

    Returns:
        總頁數。**讀不出來不回 0** —— 呼叫端要能分辨「這份是 0 頁」與
        「這份讀不出來」，而 0 兩種都像。

    Raises:
        FileNotFoundError: 檔案不存在。
        ValueError: 檔案損壞、加密或不是 PDF（與 :func:`read_toc` 同一套處置）。
    """
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF 檔案不存在: {pdf_path}")
    fitz = _require_fitz()
    try:
        doc = fitz.open(pdf_path)
    except (RuntimeError, ValueError) as exc:
        raise ValueError(f"無法讀取 PDF（檔案損壞、加密或非 PDF）：{exc}") from exc
    try:
        return doc.page_count
    finally:
        doc.close()


def extract_pages(pdf_path: Path, out_dir: Path,
                  cuts: list[tuple[str, int, int]]) -> list[Path]:
    """把指定頁範圍各自存成一個 PDF。**真的動刀的那一層。**

    這裡只做「按頁切」，**不決定切哪裡** —— 切哪裡是勾選紀錄說了算
    （`docs/chapter-selection-record-20260817.md`：照舊的切、檔名不變）。

    Args:
        pdf_path: 來源 PDF。
        out_dir: 輸出目錄，不存在就建。
        cuts: ``[(檔名, 起頁, 迄頁), ...]``，頁碼 1-indexed **含頭含尾**。

    Returns:
        實際寫出的檔案路徑，順序同 ``cuts``。

    Raises:
        FileNotFoundError: 來源不存在。
        ValueError: 有任何一段的頁碼超出範圍或頭尾顛倒。
        FileExistsError: 目的地已經有同名檔。

    ⚠ **先全部檢查，再開始寫。** 寫到一半才發現有問題的話，收件匣裡會多出幾個章、
    少了幾個章，而**沒有任何地方會說少了** —— 人看到檔案出現就以為切完了。
    """
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF 檔案不存在: {pdf_path}")
    if not cuts:
        return []

    fitz = _require_fitz()
    doc = fitz.open(pdf_path)
    try:
        total = doc.page_count
        # ── 先驗完全部，一個不合格就整批不寫 ──────────────────────────────
        for name, start, end in cuts:
            if not 1 <= start <= end <= total:
                raise ValueError(
                    f"{name} 的頁碼超出範圍：{start}-{end}，這份 PDF 只有 {total} 頁")
            if (out_dir / name).exists():
                raise FileExistsError(
                    f"{out_dir / name} 已經存在。同名多半代表這本書已經切過 —— "
                    "那是要人決定的事，不在這裡猜。")

        out_dir.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        for name, start, end in cuts:
            part = fitz.open()
            try:
                part.insert_pdf(doc, from_page=start - 1, to_page=end - 1)
                target = out_dir / name
                target.write_bytes(part.tobytes())
                written.append(target)
            finally:
                part.close()
    finally:
        doc.close()

    logger.info("從 %s 切出 %d 個檔到 %s", pdf_path.name, len(written), out_dir)
    return written


def _build_page_features(
    doc: fitz.Document, needed_pages: set[int]
) -> list[PageFeatures]:
    """把 fitz doc 解析成 :class:`PageFeatures`(只保留文字 block 的行 / span）。

    對應 _reference :func:`_find_section_heading_pages` 內讀
    ``doc[pg].get_text("dict")["blocks"]`` 並過濾 ``block["type"] != 0`` 的部分
    (chapter_splitter.py:67-76,86-106)。把 fitz 的 block→line→span 階層攤平成
    『每頁的行序列』,順序與 _reference 逐 block→line→span 迭代一致,只保留
    :class:`PageSpan` 用到的 ``text`` / ``size`` 兩鍵。

    **只對 ``needed_pages`` 真的呼叫 ``get_text("dict")``**;其餘頁回傳空
    :class:`PageFeatures`(``lines=()``)佔位。這使本函式讀取的頁面恰好等於
    _reference 會讀的頁(只有觸發子切的章節範圍),不擴大解析失敗面 —— 非子切
    章節的某頁若損壞,_reference 不會讀到,本函式也不讀(Codex R3 驗收 minor)。
    由於非子切章節不會被 :func:`find_section_heading_pages` 掃描,其空佔位不影響
    任何輸出。

    Args:
        doc: 已開啟的 fitz 文件。
        needed_pages: 需要真正解析的 0-indexed 頁碼集合(子切章節涵蓋的頁)。

    Returns:
        以 0-indexed 頁碼索引的 :class:`PageFeatures` 清單(``[pg]`` 對應
        ``doc[pg]``),長度等於總頁數;不在 ``needed_pages`` 者為空佔位。
    """
    pages: list[PageFeatures] = []
    for pg in range(doc.page_count):
        if pg not in needed_pages:
            # 不索引 doc[pg]:fitz 的 __getitem__ 會 load_page,故非 needed 頁完全
            # 不觸碰(讀取頁集合恰等於 _reference 只在子切章節讀 doc[pg])。
            pages.append(PageFeatures(lines=()))
            continue
        page = doc[pg]
        lines: list[PageLine] = []
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != _TEXT_BLOCK_TYPE:
                continue
            for line in block.get("lines", []):
                spans = tuple(
                    PageSpan(
                        text=span.get("text", ""),
                        size=span.get("size", 0),
                    )
                    for span in line.get("spans", [])
                )
                lines.append(PageLine(spans=spans))
        pages.append(PageFeatures(lines=tuple(lines)))
    return pages


def _pages_needing_features(
    toc: list[tuple[int, str, int]],
    total_pages: int,
    *,
    max_level: int,
    max_pages: int,
) -> set[int]:
    """算出哪些 0-indexed 頁屬於『會觸發子切』的章節(需解析字型特徵)。

    以 ``max_pages=0`` 再跑一次純函式 :func:`plan_pdf_split`(不子切)取得各章
    頁範圍,挑出頁數 ``> max_pages`` 的章節所涵蓋的頁。**重用核心算範圍,不在
    adapter 重抄 level 過濾 / 頁範圍邏輯**(避免 v1 app.py 那種重複漂移)。

    Args:
        toc: ``[(level, title, page), ...]``,1-indexed page。
        total_pages: PDF 總頁數。
        max_level: 最大拆分深度。
        max_pages: 每塊最大頁數(子切觸發門檻)。

    Returns:
        需要解析的 0-indexed 頁碼集合。
    """
    needed: set[int] = set()
    for plan in plan_pdf_split(toc, total_pages, max_level=max_level, max_pages=0):
        start, end = plan.page_range
        if end - start + 1 > max_pages:
            needed.update(range(start - 1, end))  # 1-indexed 含頭含尾 -> 0-indexed
    return needed


def _unique_output_name(output_dir: Path, base_name: str) -> str:
    """產生 ``output_dir`` 內不撞名的 ``.pdf`` 檔名(磁碟去重)。

    對應 _reference chapter_splitter.py:271-275:先試 ``base_name.pdf``,撞名則
    依序加 ``_1`` / ``_2`` … 後綴。**以磁碟存在與否判定**(非記憶體 set),故重跑到
    非空 ``output_dir`` 時會避讓既有檔(沿用 v1 PDF 行為,與 EPUB 的記憶體去重
    刻意不同,見 inventory risks[2])。

    Args:
        output_dir: 輸出目錄。
        base_name: 不含副檔名的檔名主幹(已含 prefix / part 後綴)。

    Returns:
        在 ``output_dir`` 內唯一的 ``.pdf`` 檔名(basename)。
    """
    filename = f"{base_name}.pdf"
    counter = 1
    while (output_dir / filename).exists():
        filename = f"{base_name}_{counter}.pdf"
        counter += 1
    return filename


def _compute_pdf_plans(
    doc: fitz.Document,
    *,
    max_level: int,
    chapter_prefix: bool,
    max_pages: int,
    no_toc_strategy: str,
) -> list[PdfChapterPlan]:
    """算 PDF 拆章計畫:有 TOC 走 :func:`plan_pdf_split`;無 TOC 依 ``no_toc_strategy``。

    無 TOC 時:``"error"`` raise(舊行為);``"whole"`` 整本一章;``"pages"`` 用
    ``max_pages`` 確定性固定分段(:func:`plan_pdf_no_toc`,不靠標題偵測 → 不亂跳)。
    """
    toc: list[tuple[int, str, int]] = [
        (lvl, title, page) for lvl, title, page in doc.get_toc()
    ]
    total_pages = doc.page_count

    if not toc or is_degenerate_pdf_toc(toc, total_pages):
        if toc:
            logger.warning(
                "PDF TOC 判定為退化逐頁索引，改用無 TOC 策略(entries=%d, pages=%d)",
                len(toc),
                total_pages,
            )
        if no_toc_strategy == NO_TOC_WHOLE:
            return plan_pdf_no_toc(total_pages, pages_per_chunk=0)
        if no_toc_strategy == NO_TOC_PAGES:
            return plan_pdf_no_toc(total_pages, pages_per_chunk=max_pages)
        raise ValueError(NO_TOC_MESSAGE)  # "error"(預設,維持舊行為)

    # 只解析『會觸發子切』章節涵蓋的頁字型特徵 —— 讀取頁面與 _reference 完全一致
    # (只在子切分支讀 get_text("dict")),不擴大解析失敗面。
    pages = (
        _build_page_features(
            doc, _pages_needing_features(toc, total_pages, max_level=max_level, max_pages=max_pages)
        )
        if max_pages > 0
        else None
    )
    return plan_pdf_split(
        toc,
        total_pages,
        max_level=max_level,
        chapter_prefix=chapter_prefix,
        max_pages=max_pages,
        pages=pages,
    )


def _iter_plan_group_parts(
    plans: list[PdfChapterPlan],
) -> Iterator[tuple[PdfChapterPlan, PdfChapterPart, int, str]]:
    """逐 part yield ``(plan, part, group_index, group_title)``,**就地**算章群。

    章群規則(preview / commit 共用,避免漂移):每遇到 ``level <= 1`` 的計畫即開新章群,
    其後 ``level >= 2`` 的節 / 各 part 共用該章群;首項若為節(無前置章)則自成一群。
    """
    group_index = -1
    group_title = ""
    for plan in plans:
        if plan.level <= 1 or group_index < 0:
            group_index += 1
            group_title = plan.title or plan.safe_title
        for part in plan.parts:
            yield plan, part, group_index, group_title


def preview_pdf_split(
    pdf_path: Path,
    *,
    max_level: int = 2,
    chapter_prefix: bool = True,
    max_pages: int = 0,
    no_toc_strategy: str = NO_TOC_WHOLE,
) -> list[SplitChapterRecord]:
    """**只算結構不寫檔**的 PDF 拆章預覽(R10 L1 預覽-b)。

    與 :func:`split_pdf_by_chapter_records` 用**同一套**計畫 + 章群邏輯,但**不開新 doc、
    不寫任何檔**;``filename`` 為**預測檔名**(無磁碟去重,僅供顯示),caller(API)預覽
    回應不依賴它指向真實檔。確認後才呼叫 commit 版真的寫檔。

    Raises:
        FileNotFoundError / ValueError(無 TOC 且 ``no_toc_strategy="error"``)。
    """
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF 檔案不存在: {pdf_path}")
    fitz = _require_fitz()
    doc = fitz.open(pdf_path)
    try:
        plans = _compute_pdf_plans(
            doc, max_level=max_level, chapter_prefix=chapter_prefix,
            max_pages=max_pages, no_toc_strategy=no_toc_strategy,
        )
    finally:
        doc.close()

    records: list[SplitChapterRecord] = []
    for plan, part, gi, gt in _iter_plan_group_parts(plans):
        base = f"{plan.prefix}{plan.safe_title}{part.part_suffix}"  # 預測檔名(不去重)
        records.append(
            SplitChapterRecord(
                filename=f"{base}.pdf", title=plan.title or plan.safe_title,
                level=plan.level, number=plan.number,
                group_index=gi, group_title=gt, part_index=part.part_index,
            )
        )
    return records


def split_pdf_by_chapter_records(
    pdf_path: Path,
    output_dir: Path,
    max_level: int = 2,
    chapter_prefix: bool = False,
    max_pages: int = 0,
    *,
    no_toc_strategy: str = NO_TOC_ERROR,
) -> list[SplitChapterRecord]:
    """同 :func:`split_pdf_by_chapter`,但回傳**結構化記錄**(含層級 / 章群,R10 G3)。

    決策邏輯(編號 / 頁範圍 / 子切 / 無 TOC 策略)委派 :func:`_compute_pdf_plans`;章群委派
    :func:`_iter_plan_group_parts`(與 preview 共用,不漂移);本函式只做 fitz **寫檔** I/O。

    Args:
        pdf_path: 原始 PDF 路徑。
        output_dir: 拆分後子 PDF 的輸出目錄(不存在則建立)。
        max_level: 最大拆分深度(1=章, 2=節);超過此 level 的 TOC 項目丟棄。
        chapter_prefix: 是否在檔名前加自動章節編號前綴(如 ``00100_``)。
        max_pages: 每塊最大頁數,超過時自動偵測內文標題子切(``0``=停用)。
        no_toc_strategy: 無 TOC 時的策略(``"error"`` 預設 raise / ``"whole"`` 整檔 /
            ``"pages"`` 用 ``max_pages`` 確定性分段)。

    Returns:
        :class:`SplitChapterRecord` 清單,順序同拆章計畫(一個 part 一筆)。

    Raises:
        FileNotFoundError: 輸入 PDF 不存在(chapter_splitter.py:176-177)。
        ValueError: PDF 沒有目錄(TOC)且 ``no_toc_strategy="error"``(維持舊行為)。
    """
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF 檔案不存在: {pdf_path}")

    fitz = _require_fitz()
    output_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(pdf_path)
    try:
        plans = _compute_pdf_plans(
            doc, max_level=max_level, chapter_prefix=chapter_prefix,
            max_pages=max_pages, no_toc_strategy=no_toc_strategy,
        )

        records: list[SplitChapterRecord] = []
        for plan, part, group_index, group_title in _iter_plan_group_parts(plans):
            start_idx = part.page_range[0] - 1  # 1-indexed -> 0-indexed
            end_idx = part.page_range[1] - 1

            # new_doc 與寫檔在同一 try 內(filename 決策與落檔同一保護域);
            # finally 確保 new_doc 必關。tobytes() 先完成才開輸出檔(對齊
            # _reference 順序),避免 tobytes 失敗時留下空檔污染下次磁碟去重。
            new_doc = fitz.open()
            try:
                new_doc.insert_pdf(doc, from_page=start_idx, to_page=end_idx)
                base_name = f"{plan.prefix}{plan.safe_title}{part.part_suffix}"
                filename = _unique_output_name(output_dir, base_name)
                pdf_bytes = new_doc.tobytes()
                with (output_dir / filename).open("wb") as fh:
                    fh.write(pdf_bytes)
            finally:
                new_doc.close()

            records.append(
                SplitChapterRecord(
                    filename=filename,
                    title=plan.title or plan.safe_title,
                    level=plan.level,
                    number=plan.number,
                    group_index=group_index,
                    group_title=group_title,
                    part_index=part.part_index,
                )
            )
            logger.info(
                "PDF chapter written: %s (pages %d-%d)",
                filename,
                part.page_range[0],
                part.page_range[1],
            )
    finally:
        doc.close()

    logger.info(
        "split_pdf_by_chapter: %d files written from %s",
        len(records),
        pdf_path.name,
    )
    return records


def split_pdf_by_chapter(
    pdf_path: Path,
    output_dir: Path,
    max_level: int = 2,
    chapter_prefix: bool = False,
    max_pages: int = 0,
) -> list[str]:
    """依 TOC(預設到節 Level 2)把 PDF 拆成多個子 PDF,寫到 ``output_dir``。

    薄包裝:委派 :func:`split_pdf_by_chapter_records`(SSOT,含實際 fitz I/O)後只取
    檔名,維持舊 ``list[str]`` 介面(既有 caller / CLI 不變)。

    Args:
        pdf_path: 原始 PDF 路徑。
        output_dir: 拆分後子 PDF 的輸出目錄(不存在則建立)。
        max_level: 最大拆分深度(1=章, 2=節);超過此 level 的 TOC 項目丟棄。
        chapter_prefix: 是否在檔名前加自動章節編號前綴(如 ``00100_``)。
        max_pages: 每塊最大頁數,超過時自動偵測內文標題子切(``0``=停用)。

    Returns:
        產生的檔名清單(basename,不含目錄),順序同拆章計畫;由 caller 拼路徑。

    Raises:
        FileNotFoundError: 輸入 PDF 不存在(chapter_splitter.py:176-177)。
        ValueError: PDF 沒有目錄(TOC)(chapter_splitter.py:187-188,中文訊息)。
    """
    return [
        r.filename
        for r in split_pdf_by_chapter_records(
            pdf_path, output_dir, max_level, chapter_prefix, max_pages
        )
    ]
