"""拆章「計畫」純函式 —— 不做任何 I/O、不寫檔，只回傳結構化拆章計畫。

**這份碼是 2026-08-17 從 `vibevoice-v2` 搬過來的。** 原檔 931 行，EPUB 的
八個類別／函式（265 行）已刪 —— 這裡只進 PDF。刪的清單寫在搬進來那個 commit。

**它已經在生產跑過**：庫裡 `/data/lightrag/library` 那 88 份五碼前綴的檔案就是
它切的（2026-08-17 實查）。所以搬的是「跑過的東西」，不是紙上設計。

⚠ **它原本的測試沒有跟過來，因為那些測試本身就跑不動了。** 那是
「v2 跟 v1 行為一致」的比對測試，比對對象是 vibevoice 的 v1 原始碼
（`_reference/`），而那份碼已從 vibevoice-v2 的 repo 刪除 —— 2026-08-17 實跑
它的測試：7 個檔在 collection 階段就 `FileNotFoundError`。⇒ 這裡的測試是
重寫的，測「lightrag 需要它做到什麼」，不是「跟 v1 一樣」。

**為什麼計畫與 I/O 要分開**（原設計的理由，保留）：切法算一次、兩邊共用。
預覽（給人勾選）與實際輸出如果各算一份編號，兩邊必須永遠一致，否則檔名對不上。
分開之後也才能在不開 PDF 的情況下測編號與子切邏輯。

輸入是已抽好的 TOC／頁數／偵測到的內文標題頁（由 `pdf_splitter.py` 用 fitz
取得後注入），輸出是一份計畫：每章的標題、編號值、前綴、頁範圍與子切後的
part 清單。

編號規則：章 × 100、節 ＝ 章 × 100 ＋ 序、附錄 900 起跳、前言用小序號。
⚠ 附錄基底 900 會撞第 9 章（900），見 `tests/test_chapter_naming.py`。

⚠ 內文裡那些 `_reference chapter_splitter.py:NNN` 是**來歷註記**，指的是
vibevoice v1 的原始碼。那份檔案已經不存在了（連 vibevoice-v2 的 repo 裡都沒有），
所以**它們是歷史說明，不是可以去查的位址** —— 留著是因為「這個門檻哪來的」比
「這行指到哪」有用，但不要照著去找檔案。

設計鐵則：純函式、單一職責、完整 type hints（禁裸 ``Any``）、用 :mod:`logging`
不用 ``print``、import 時無副作用。檔名前綴格式化在 :mod:`chapters.naming`，
本模組只負責『編號值的計算』與『拆章結構的組裝』。
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field

from chapters.naming import (
    APPENDIX_PREFIX_BASE,
    CHAPTER_NUMBER_MULTIPLIER,
    PREFIX_WIDTH,
    pdf_chapter_prefix,
    sanitize_filename,
)

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# 具名常數(_reference 散落的 magic number / 關鍵字集中於此)
# --------------------------------------------------------------------------- #

#: 子切合併下限:尾塊 / 首塊小於此頁數時併入相鄰塊。
#: 來源:_reference chapter_splitter.py:111(``_MIN_CHUNK_PAGES = 10``)。
MIN_CHUNK_PAGES: int = 10

#: 內文標題字體判定門檻:大於 body_size 此倍數視為標題。
#: 來源:_reference chapter_splitter.py:82(``body_size * 1.15``)。
HEADING_SIZE_RATIO: float = 1.15

#: 內文標題最短文字長度(span 文字 strip 後須 > 此值才採信字體信號)。
#: 來源:_reference chapter_splitter.py:104(``len(...strip()) > 3``)。
HEADING_MIN_TEXT_LEN: int = 3

#: 段落節號 pattern,如 ``"3.1 Title"``。
#: 來源:_reference chapter_splitter.py:63(``r"^\d+\.\d+\s+\w"``)。
SECTION_HEADING_PATTERN: re.Pattern[str] = re.compile(r"^\d+\.\d+\s+\w")

# 有些 PDF 會把「每頁頁碼」寫成 TOC，例如 448 頁文件帶 430 筆、全部 level 1、
# 標題依序為 "1" / "2" / "3"。這不是可用的章節目錄；若只判斷 get_toc() 非空，
# GUI 會把它當成真目錄並切出數百個一頁碎片。
_PAGE_NUMBER_TOC_TITLE: re.Pattern[str] = re.compile(
    r"^\s*(?:第\s*)?(?:\d+|[ivxlcdm]+)\s*(?:頁)?\s*$",
    re.IGNORECASE,
)

# 假目錄判定採保守門檻：至少 20 筆，避免短文件被少量特殊標題誤判。
DEGENERATE_TOC_MIN_ENTRIES: int = 20
DEGENERATE_TOC_DENSE_RATIO: float = 0.75
DEGENERATE_TOC_NUMERIC_RATIO: float = 0.75
DEGENERATE_TOC_LEVEL_ONE_RATIO: float = 0.90

#: preamble(前言 / 序)關鍵字集合(15 個),以子字串比對。
#: 來源:_reference chapter_splitter.py:34-40(inventory 誤記 16,實際清單為 15)。
PREAMBLE_KEYWORDS: tuple[str, ...] = (
    "目錄", "序言", "前言", "導讀", "導論", "緒論",
    "引言", "推薦序", "自序", "譯者序", "作者序",
    "致謝", "謝辭", "版權", "出版",
)

# ── 英文（2026-08-17 加）──────────────────────────────────────────────────
#
# **為什麼不能沿用中文那套「子字串比對」。** 中文關鍵字是複合詞，夾在正文標題
# 裡的機會低。英文不是：`Index` 會命中 `Index of refraction`、`Notes` 會命中
# `Notes on measurement` —— 兩個都是聲學的真章節。所以英文分兩種比法。
#
# 判準是**寧可漏抓，不要抓錯**。漏抓 → 那一章拿到普通編號，人在勾選清單裡照樣
# 看得到；抓錯 → 真章節被編成 900+ 的附錄，排到全書最後面。
#
# ⚠ 拿現有語料驗過：`/data/lightrag/library` 的 88 個章節標題，
# 對 index／note／content／preface／appendix／reference／biblio／glossar／
# foreword／acknowledg／introduc 全部**零命中**（2026-08-17 實跑）。
#
# ⚠ **刻意不收 `Introduction`。** 中文那邊把「緒論／導論／引言」當前言，但英文
# 學術書與論文的 `Introduction` 幾乎都是**第一章正文**。收了會把真內容編成前言。

#: 開頭比對：標題**以這個字開頭**（整字、不分大小寫）就算。
#: 只放「幾乎不可能當正文章節開頭」的字。
#: ⚠ `references` 用複數：`Reference Sound Source`（單數）是真的聲學題目。
_EN_PREAMBLE_HEAD: tuple[str, ...] = (
    "preface", "foreword", "dedication", "acknowledgment", "acknowledgement",
    "acknowledgments", "acknowledgements", "copyright", "frontispiece",
    "about the author", "about the authors", "title page", "half title",
)
_EN_APPENDIX_HEAD: tuple[str, ...] = (
    "appendix", "appendices", "bibliography", "glossary", "colophon",
    "afterword", "epilogue", "references",
)

#: 完全比對：整個標題（只看英文單字、不分大小寫）**剛好等於**其中一條才算。
#:
#: 這條專門處理危險字。**第一版寫成「≤3 個字且以該字結尾」，當場被自己的測試
#: 打臉**：`Articulation index`（清晰度指數，真的聲學名詞）符合那個形狀。
#: 改成明列完整片語 —— 沒有啟發式，看得懂、加得動、不會誤傷。
_EN_PREAMBLE_EXACT: tuple[str, ...] = (
    "contents", "table of contents", "abstract",
    "list of figures", "list of tables", "list of illustrations",
    # 2026-08-17 實測補：第一本真的透過 Zotero 進來的教科書（63 章）裡，規則正確地
    # 放過了目錄／序／索引，卻把「Cover」勾了起來 —— 封面沒有內容，切出去是垃圾。
    # ⚠ **只能走完全比對。** 放進 HEAD 的話 `Coverage of the audible range` 會被
    # 當成封面，而抓錯比漏抓貴得多（真章節被排到全書最後面，人不一定會發現）。
    "cover", "front cover", "back cover",
)
_EN_APPENDIX_EXACT: tuple[str, ...] = (
    "index", "subject index", "author index", "name index", "general index",
    "notes", "notation", "nomenclature", "symbols", "list of symbols",
)

#: 抓英文單字用。撇號留著（`Author's Note`）。
_EN_WORD_RE: re.Pattern[str] = re.compile(r"[A-Za-z][A-Za-z']*")

#: appendix(附錄)關鍵字集合(7 個),以子字串比對。
#: 來源:_reference chapter_splitter.py:44-46。
APPENDIX_KEYWORDS: tuple[str, ...] = (
    "附錄", "附記", "後記", "索引", "參考", "注釋", "結語",
)

# --------------------------------------------------------------------------- #
# 結構:拆章計畫資料類別
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PdfChapterPart:
    """PDF 一章子切後的單一輸出單位。

    Attributes:
        page_range: 1-indexed 含頭含尾頁範圍 ``(start, end)``。
        part_index: 1 起算的 part 序號(未子切時為 1)。
        part_suffix: 檔名 part 後綴,如 ``"_part2"``;單塊時為空字串。
    """

    page_range: tuple[int, int]
    part_index: int
    part_suffix: str


@dataclass(frozen=True)
class PdfChapterPlan:
    """PDF 單一章節(TOC 項目)的拆章計畫。

    Attributes:
        title: 原始 TOC 標題(未清理)。
        safe_title: 經 :func:`sanitize_filename` 清理後的標題。
        level: TOC 層級(1=章, 2=節)。
        number: 自動編號值(preamble idx / 900+appendix / 章*100 / 章*100+節);
            ``chapter_prefix`` 關閉時為 ``None``。
        prefix: 含尾端底線的前綴字串(如 ``"00100_"``);關閉時為空字串。
        page_range: 整章 1-indexed 含頭含尾頁範圍。
        parts: 子切後的 part 清單(至少 1 個);多 part 時共用同一 ``prefix``。
    """

    title: str
    safe_title: str
    level: int
    number: int | None
    prefix: str
    page_range: tuple[int, int]
    parts: tuple[PdfChapterPart, ...] = field(default_factory=tuple)


# --------------------------------------------------------------------------- #
# PDF:preamble / appendix 偵測(_reference chapter_splitter.py:30-46)
# --------------------------------------------------------------------------- #


def _english_words(title: str) -> list[str]:
    """標題裡的英文單字，全部轉小寫。編號、標點、中文都不算字。

    ``"Appendix A: Derivations"`` → ``["appendix", "a", "derivations"]``
    ``"10.9 Problems"``           → ``["problems"]``
    """
    return [w.lower() for w in _EN_WORD_RE.findall(title)]


def _matches_english(
    title: str,
    head_keywords: tuple[str, ...],
    exact_keywords: tuple[str, ...],
) -> bool:
    """英文比對：以某個字開頭，或整個標題剛好等於某個片語。

    ⚠ **不是子字串比對**，理由見 :data:`_EN_PREAMBLE_HEAD` 上方那段。

    Args:
        title: 原始 TOC 標題。
        head_keywords: 以此開頭就算（可含空格的片語，如 ``"about the author"``）。
        exact_keywords: 整個標題剛好等於此片語才算（危險字走這條）。

    Returns:
        命中則 ``True``。
    """
    words = _english_words(title)
    if not words:
        return False
    if " ".join(words) in exact_keywords:
        return True
    return any(words[: len(needle := phrase.split())] == needle
               for phrase in head_keywords)


def is_preamble_title(title: str) -> bool:
    """標題是否屬於 preamble(前言 / 序 / 目錄類)。

    中文：以 :data:`PREAMBLE_KEYWORDS` 任一關鍵字『子字串』比對(非完全相等)。
    英文(2026-08-17 加)：見 :func:`_matches_english` —— **比法不同**，
    因為英文的關鍵字會夾在真章節標題裡。

    Args:
        title: 原始 TOC 標題。

    Returns:
        命中任一 preamble 關鍵字則 ``True``。
    """
    stripped = title.strip()
    if any(kw in stripped for kw in PREAMBLE_KEYWORDS):
        return True
    return _matches_english(stripped, _EN_PREAMBLE_HEAD, _EN_PREAMBLE_EXACT)


def is_appendix_title(title: str) -> bool:
    """標題是否屬於 appendix(附錄 / 後記 / 索引類)。

    中文：以 :data:`APPENDIX_KEYWORDS` 任一關鍵字『子字串』比對。
    英文(2026-08-17 加)：見 :func:`_matches_english`。

    Args:
        title: 原始 TOC 標題。

    Returns:
        命中任一 appendix 關鍵字則 ``True``。
    """
    stripped = title.strip()
    if any(kw in stripped for kw in APPENDIX_KEYWORDS):
        return True
    return _matches_english(stripped, _EN_APPENDIX_HEAD, _EN_APPENDIX_EXACT)


def is_degenerate_pdf_toc(
    toc: list[tuple[int, str, int]],
    total_pages: int,
) -> bool:
    """判斷 PDF TOC 是否其實只是逐頁索引，而非可用章節目錄。

    目前辨識兩種高可信度退化形狀：

    * TOC 筆數接近總頁數，且幾乎全部只有 level 1；
    * TOC 至少覆蓋半數頁面、幾乎全為 level 1，且多數標題只是頁碼。

    門檻刻意保守：正常技術書即使目錄很多，只要有章節階層或實際文字標題，
    就不會被誤判。``total_pages <= 0`` 或少於 20 筆一律視為非退化。
    """
    entry_count = len(toc)
    if total_pages <= 0 or entry_count < DEGENERATE_TOC_MIN_ENTRIES:
        return False

    level_one_count = sum(1 for level, _title, _page in toc if level <= 1)
    numeric_title_count = sum(
        1 for _level, title, _page in toc if _PAGE_NUMBER_TOC_TITLE.fullmatch(title)
    )
    level_one_ratio = level_one_count / entry_count
    numeric_title_ratio = numeric_title_count / entry_count
    density_ratio = entry_count / total_pages

    dense_flat_index = (
        density_ratio >= DEGENERATE_TOC_DENSE_RATIO
        and level_one_ratio >= DEGENERATE_TOC_LEVEL_ONE_RATIO
    )
    mostly_page_numbers = (
        density_ratio >= 0.50
        and level_one_ratio >= DEGENERATE_TOC_LEVEL_ONE_RATIO
        and numeric_title_ratio >= DEGENERATE_TOC_NUMERIC_RATIO
    )
    return dense_flat_index or mostly_page_numbers


# --------------------------------------------------------------------------- #
# PDF:子切 greedy 分塊 + 合併(_reference chapter_splitter.py:114-149)
# --------------------------------------------------------------------------- #


def subsplit_pages(
    start: int,
    end: int,
    max_pages: int,
    split_candidates: list[int],
) -> list[tuple[int, int]]:
    """將 ``[start, end]`` greedy 切成每塊至多 ``max_pages`` 頁,再合併過小塊。

    行為逐項對應 _reference chapter_splitter.py:114-149:

    * ``max_pages`` 下限拉到 :data:`MIN_CHUNK_PAGES`,絕不產生小於合併下限的塊
      (ref line 123,``max(max_pages, _MIN_CHUNK_PAGES)``)。
    * greedy:每個 window ``(cur, cur+max_pages-1]`` 內取『最大』候選切點;
      無候選則硬切 ``cur+max_pages``(ref line 127-134)。
    * 合併:尾塊 / 中間塊 < :data:`MIN_CHUNK_PAGES` 併入『前一塊』
      (ref line 137-143);若首塊仍 < 下限則 forward 併入『後一塊』
      (ref line 145-147)。

    Args:
        start: 1-indexed 起頁。
        end: 1-indexed 終頁(含)。
        max_pages: 每塊最大頁數(會被拉到 :data:`MIN_CHUNK_PAGES` 下限)。
        split_candidates: 1-indexed 合法切點起頁清單(通常為偵測到的標題頁)。

    Returns:
        1-indexed ``(start, end)`` 塊清單(至少 1 個)。
    """
    capped_max = max(max_pages, MIN_CHUNK_PAGES)
    chunks: list[tuple[int, int]] = []
    cur = start

    while end - cur + 1 > capped_max:
        window_end = cur + capped_max - 1
        in_window = [p for p in split_candidates if cur < p <= window_end]
        split_at = max(in_window) if in_window else cur + capped_max
        chunks.append((cur, split_at - 1))
        cur = split_at

    chunks.append((cur, end))

    # 合併過小塊:尾 / 中間塊併入前一塊。
    merged: list[tuple[int, int]] = []
    for cs, ce in chunks:
        if merged and (ce - cs + 1) < MIN_CHUNK_PAGES:
            prev_s, _ = merged[-1]
            merged[-1] = (prev_s, ce)
        else:
            merged.append((cs, ce))

    # forward pass:首塊仍過小則併入後一塊。
    if len(merged) > 1 and (merged[0][1] - merged[0][0] + 1) < MIN_CHUNK_PAGES:
        merged = [(merged[0][0], merged[1][1]), *merged[2:]]

    return merged


# --------------------------------------------------------------------------- #
# PDF:內文標題頁偵測(雙訊號)— 抽象化 fitz page dict 的純函式
# (_reference chapter_splitter.py:54-108,_find_section_heading_pages)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PageSpan:
    """一個文字 span 的字型 / 文字特徵(對應 fitz line dict 的 ``spans[i]``)。

    _reference 只讀 span 的 ``text`` / ``size`` 兩個鍵
    (chapter_splitter.py:73-74,90-91,102-104),故抽象化只保留此二者;
    其餘 fitz 欄位(font / flags / bbox / color …)與標題判定無關,刻意不模型化。

    Attributes:
        text: span 文字(對應 ``span.get("text", "")``)。
        size: span 字型大小,單位 pt(對應 ``span.get("size", 0)``)。
    """

    text: str
    size: float


@dataclass(frozen=True)
class PageLine:
    """一行文字,由若干 span 組成(對應 fitz block dict 的 ``lines[i]``)。

    _reference 以 ``" ".join(span.text)`` 組出 ``line_text`` 後判定 section regex
    與長度(chapter_splitter.py:90-93),再逐 span 判字體訊號
    (chapter_splitter.py:102-104),故抽象化只保留 span 序列。

    Attributes:
        spans: 該行的 span 序列(順序即 fitz 原順序,join 時影響空白位置)。
    """

    spans: tuple[PageSpan, ...]


@dataclass(frozen=True)
class PageFeatures:
    """單頁的文字 span 特徵(僅含 type==0 文字 block 的行)。

    對應 _reference ``doc[pg].get_text("dict")["blocks"]`` 攤平後『文字 block』
    (``block.get("type") == 0``,chapter_splitter.py:69,87)的所有行。
    非文字 block(圖片 type==1 等)被 _reference 跳過,故由 R3 adapter 在建構
    此結構時就過濾掉,本核心不再模型化 block 階層 / type。

    Attributes:
        lines: 本頁所有(文字 block 內的)行,順序同 fitz。
    """

    lines: tuple[PageLine, ...]


def find_section_heading_pages(
    pages: list[PageFeatures],
    start_idx: int,
    end_idx: int,
) -> list[int]:
    """掃描章內各頁,以雙訊號偵測可作為子切點的內文段落標題頁。

    本函式『在函式內真的執行』_reference :func:`_find_section_heading_pages`
    (chapter_splitter.py:54-108)的偵測邏輯,**不**要求 caller 注入結果:

    1. **內文字體基準(body_size)**:統計章內 ``[start_idx, end_idx]`` 全部 span
       (跳過 strip 後為空或 ``size <= 0`` 者),以『字元數』加權累計各 size
       (``round(size, 1)``),取出現最多者為 body_size
       (chapter_splitter.py:66-81)。章內完全無文字 -> 回傳空清單
       (chapter_splitter.py:78-79)。
    2. **門檻** = ``body_size *`` :data:`HEADING_SIZE_RATIO`(1.15)
       (chapter_splitter.py:82)。
    3. **逐頁掃描(排除章首頁)**:只看 ``[start_idx + 1, end_idx]``,章首頁切無意義
       (chapter_splitter.py:85)。對每一行:
       * ``line_text`` = 以空格 join 該行各 span 文字後 ``strip()``;長度 < 3 跳過
         (chapter_splitter.py:90-94)。
       * **訊號 1(section regex)**:``line_text`` 命中
         :data:`SECTION_HEADING_PATTERN`(``^\\d+\\.\\d+\\s+\\w``)即記為標題頁
         並跳出該行(chapter_splitter.py:97-99)。
       * **訊號 2(字體大小)**:該行任一 span ``size >= 門檻`` 且其 strip 後文字長度
         ``>`` :data:`HEADING_MIN_TEXT_LEN`(3),記為標題頁
         (chapter_splitter.py:102-106)。

    回傳 0-indexed 頁碼,落在 ``(start_idx, end_idx]`` 內(章首頁 ``start_idx``
    必不入列),已排序。caller(R3 adapter)再 ``+1`` 轉 1-indexed 切點丟給
    :func:`subsplit_pages`(對應 chapter_splitter.py:252-253)。

    Args:
        pages: 整本(或至少涵蓋本章範圍)的逐頁特徵,以 0-indexed 頁碼索引
            (``pages[pg]``,對應 _reference 的 ``doc[pg]``)。由 R3 adapter 用
            fitz 解析後建構,故本核心不相依 PyMuPDF。
        start_idx: 章首頁的 0-indexed 頁碼(含;但其本身不會被列為切點)。
        end_idx: 章末頁的 0-indexed 頁碼(含)。

    Returns:
        排序後的 0-indexed 標題頁清單;無內文或無命中時為空 ``[]``。
    """
    # --- body_size:章內各 size(round 到 1 位)以字元數加權的眾數 ---
    size_counts: Counter[float] = Counter()
    for pg in range(start_idx, end_idx + 1):
        for line in pages[pg].lines:
            for span in line.spans:
                txt = span.text.strip()
                sz = span.size
                if txt and sz > 0:
                    size_counts[round(sz, 1)] += len(txt)

    if not size_counts:
        return []

    body_size = size_counts.most_common(1)[0][0]
    heading_threshold = body_size * HEADING_SIZE_RATIO

    heading_pages: set[int] = set()
    for pg in range(start_idx + 1, end_idx + 1):  # 排除章首頁
        for line in pages[pg].lines:
            line_text = " ".join(span.text for span in line.spans).strip()
            if len(line_text) < HEADING_MIN_TEXT_LEN:
                continue

            # 訊號 1:section 節號 pattern。
            if SECTION_HEADING_PATTERN.match(line_text):
                heading_pages.add(pg)
                break

            # 訊號 2:字體大於內文門檻且文字夠長。
            for span in line.spans:
                if (
                    span.size >= heading_threshold
                    and len(span.text.strip()) > HEADING_MIN_TEXT_LEN
                ):
                    heading_pages.add(pg)
                    break

    return sorted(heading_pages)


# --------------------------------------------------------------------------- #
# PDF:整本拆章計畫(_reference chapter_splitter.py:185-285 的純邏輯部分)
# --------------------------------------------------------------------------- #


def plan_pdf_split(
    toc: list[tuple[int, str, int]],
    total_pages: int,
    *,
    max_level: int = 2,
    chapter_prefix: bool = False,
    max_pages: int = 0,
    pages: list[PageFeatures] | None = None,
    heading_pages_by_chapter: dict[int, list[int]] | None = None,
) -> list[PdfChapterPlan]:
    """從 PDF TOC 計算完整拆章計畫(不開 PDF、不寫檔)。

    這對應 _reference :func:`split_pdf_by_chapter`(chapter_splitter.py:152-285)
    中『決定要切哪些章 / 編號 / 頁範圍 / 子切』的純邏輯。子切所需的『內文標題頁
    偵測』(_reference 內嵌的 :func:`_find_section_heading_pages`)由本函式以
    :func:`find_section_heading_pages` **在函式內真的執行**(只要 caller 提供
    抽象化的逐頁 ``pages`` 特徵,而非把偵測結果委派出去);實際開 PDF / 寫檔仍屬
    R3 adapter 職責。

    各行為的 _reference 對應:

    * level 過濾 ``lvl > max_level`` 直接丟棄:chapter_splitter.py:191-194。
    * 頁範圍:起頁=TOC page(1-indexed);終頁=下一個『已過濾』TOC 項目
      ``page - 1``,最後一項=``total_pages``;且 ``end = max(next-1, start)``
      防負區間:chapter_splitter.py:206-212。
    * ``start > end`` 整章跳過(不產出):chapter_splitter.py:214-215。
    * 自動編號(僅 ``chapter_prefix`` 時計算):chapter_splitter.py:222-244。
      preamble(且 ``not first_chapter_seen``)用 ``preamble_idx`` 從 0 遞增;
      appendix 無條件用 ``900 + appendix_idx``;``lvl==1`` 先 ``chapter_num+1``
      再 ``*100`` 並重置 ``section_idx`` 且標記 ``first_chapter_seen``;
      ``lvl==2`` 用 ``chapter_num*100 + section_idx``(``section_idx`` 先 +1);
      其他 lvl 在未見第一章前當 preamble,否則當新章。
    * 子切:僅 ``max_pages > 0 且 total > max_pages`` 才觸發;切點由
      :func:`find_section_heading_pages` 對該章頁範圍偵測後 ``+1`` 轉 1-indexed
      (對應 chapter_splitter.py:249-256);``_partN`` 後綴僅在 > 1 塊時加:
      chapter_splitter.py:247-260,269。
    * prefix 與子切無關,每章只算一次,所有 part 共用:chapter_splitter.py:217。

    Args:
        toc: ``[(level, title, page), ...]``,``page`` 為 1-indexed(同 fitz
            ``doc.get_toc()`` 的形狀)。
        total_pages: PDF 總頁數(用於最後一章終頁)。
        max_level: 最大拆分深度(1=章, 2=節);超過此 level 的項目丟棄。
        chapter_prefix: 是否計算自動章節編號 / 前綴。
        max_pages: 每塊最大頁數;``0`` 停用子切。
        pages: 整本 PDF 的逐頁文字 span 特徵(0-indexed,``pages[pg]``),由 R3
            adapter 以 fitz 解析後建構。提供時,本函式於每章觸發子切的場合『真的
            執行』:func:`find_section_heading_pages` 偵測切點(章頁範圍轉 0-indexed
            傳入,結果 ``+1`` 轉回 1-indexed),**不**要求 caller 自行注入偵測結果。
        heading_pages_by_chapter: 進階覆寫:``{chapter_index: [1-indexed 切點起頁]}``
            (``chapter_index`` 為『已過濾後』章節清單索引)。給定某章時直接採用,
            略過 ``pages`` 偵測(供測試或已預算好切點的 caller);``None`` / 缺鍵時
            回退到 ``pages`` 偵測,兩者皆無則視為無候選。

    Returns:
        :class:`PdfChapterPlan` 清單(已跳過 ``start > end`` 的章節),順序同 TOC。
    """
    # level 過濾(SPLIT-01):chapter_splitter.py:191-194。
    chapters: list[tuple[int, str, int]] = [
        (lvl, title, page) for lvl, title, page in toc if lvl <= max_level
    ]

    headings = heading_pages_by_chapter or {}

    # 自動編號狀態(SPLIT-04):chapter_splitter.py:197-201。
    current_chapter_num = 0
    current_section_idx = 0
    preamble_idx = 0
    appendix_idx = 0
    first_chapter_seen = False

    plans: list[PdfChapterPlan] = []

    for i, (lvl, title, page) in enumerate(chapters):
        start_page = page

        # 頁範圍(SPLIT-02):chapter_splitter.py:206-212。
        if i < len(chapters) - 1:
            next_page = chapters[i + 1][2]
            end_page = max(next_page - 1, start_page)
        else:
            end_page = total_pages

        # start > end 跳過(SPLIT-03):chapter_splitter.py:214-215。
        if start_page > end_page:
            logger.debug(
                "Skipping chapter with empty range: %r (start=%d > end=%d)",
                title,
                start_page,
                end_page,
            )
            continue

        safe_title = sanitize_filename(title)

        # 自動編號(SPLIT-04/05/06/07/26):chapter_splitter.py:222-244。
        number: int | None = None
        prefix = ""
        if chapter_prefix:
            if is_preamble_title(title) and not first_chapter_seen:
                number = preamble_idx
                preamble_idx += 1
            elif is_appendix_title(title):
                number = APPENDIX_PREFIX_BASE + appendix_idx
                appendix_idx += 1
            elif lvl == 1:
                current_chapter_num += 1
                current_section_idx = 0
                first_chapter_seen = True
                number = current_chapter_num * CHAPTER_NUMBER_MULTIPLIER
            elif lvl == 2:
                current_section_idx += 1
                number = (
                    current_chapter_num * CHAPTER_NUMBER_MULTIPLIER
                    + current_section_idx
                )
            else:
                if not first_chapter_seen:
                    number = preamble_idx
                    preamble_idx += 1
                else:
                    current_chapter_num += 1
                    current_section_idx = 0
                    number = current_chapter_num * CHAPTER_NUMBER_MULTIPLIER
            prefix = pdf_chapter_prefix(number, width=PREFIX_WIDTH)

        # 子切(SPLIT-08/11/26):chapter_splitter.py:247-260。
        total_chapter_pages = end_page - start_page + 1
        if max_pages > 0 and total_chapter_pages > max_pages:
            if i in headings:
                # 進階覆寫:caller 已預算好 1-indexed 切點。
                candidates = headings[i]
            elif pages is not None:
                # 真的執行雙訊號偵測:章頁範圍轉 0-indexed,結果 +1 轉 1-indexed
                # (對應 chapter_splitter.py:249-256)。
                heading_pages_0idx = find_section_heading_pages(
                    pages, start_page - 1, end_page - 1
                )
                candidates = [p + 1 for p in heading_pages_0idx]
            else:
                candidates = []
            sub_chunks = subsplit_pages(start_page, end_page, max_pages, candidates)
        else:
            sub_chunks = [(start_page, end_page)]

        needs_part_suffix = len(sub_chunks) > 1
        parts = tuple(
            PdfChapterPart(
                page_range=(chunk_start, chunk_end),
                part_index=part_idx,
                part_suffix=f"_part{part_idx}" if needs_part_suffix else "",
            )
            for part_idx, (chunk_start, chunk_end) in enumerate(sub_chunks, 1)
        )

        plans.append(
            PdfChapterPlan(
                title=title,
                safe_title=safe_title,
                level=lvl,
                number=number,
                prefix=prefix,
                page_range=(start_page, end_page),
                parts=parts,
            )
        )

    return plans


def plan_pdf_no_toc(
    total_pages: int,
    *,
    pages_per_chunk: int = 0,
) -> list[PdfChapterPlan]:
    """無 TOC 的 PDF **確定性**分段(R10 L1)—— 不靠標題偵測,避免舊版「亂跳」。

    舊版無 TOC 時用字型/節號雙訊號偵測標題當切點,但沒有 TOC 結構撐著,偵測極易誤判
    (大字標題 / 頁眉 / 圖說 / 頁碼都會中),切點忽前忽後 → 段落長短亂跳、位置不穩。
    本函式**完全不偵測**,改成兩種可預測模式:

    * ``pages_per_chunk <= 0`` → **整檔處理**:整本當一章(1 個 level-1 plan)。
    * ``pages_per_chunk > 0`` → **固定每段頁數**:以 :func:`subsplit_pages`(空候選 →
      純等距 greedy + 小尾段合併)切成每段至多 N 頁。**同一本書 + 同一個 N 永遠切出
      一模一樣的結果**(deterministic),不會亂跳。注意 :func:`subsplit_pages` 會把每段
      下限拉到 :data:`MIN_CHUNK_PAGES`(避免 1~2 頁的碎段),故實際每段 ≥ 該下限。

    每段一個 ``level=1`` 的 :class:`PdfChapterPlan`、單一 part、依序編號(供檔名排序)。

    Args:
        total_pages: PDF 總頁數。
        pages_per_chunk: 每段最大頁數;``<=0`` → 整本一章。

    Returns:
        :class:`PdfChapterPlan` 清單(順序即頁序);``total_pages<=0`` 回空清單。
    """
    if total_pages <= 0:
        return []

    if pages_per_chunk > 0:
        chunks = subsplit_pages(1, total_pages, pages_per_chunk, [])
    else:
        chunks = [(1, total_pages)]

    multi = len(chunks) > 1
    plans: list[PdfChapterPlan] = []
    for idx, (start, end) in enumerate(chunks, 1):
        title = f"第 {idx} 段（頁 {start}-{end}）" if multi else "全書"
        plans.append(
            PdfChapterPlan(
                title=title,
                safe_title=sanitize_filename(title),
                level=1,
                number=idx,
                prefix=pdf_chapter_prefix(idx, width=PREFIX_WIDTH),
                page_range=(start, end),
                parts=(
                    PdfChapterPart(page_range=(start, end), part_index=1, part_suffix=""),
                ),
            )
        )
    return plans
