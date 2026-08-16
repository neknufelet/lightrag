"""拆章檔名：清字元、算前綴編號。純函式，不碰檔案系統。

**這份碼是 2026-08-17 從 `vibevoice-v2` 搬過來的**，只保留 `split_plan.py` 真正
用得到的部分。原檔 429 行裡有一大半是那個專案的音檔命名（`run_id`、
`script_stem`、`podcast_stem`、`slugify_for_path`、檔案雜湊）與 EPUB 前綴 ——
全部刪掉，刪的清單寫在搬進來的那個 commit 訊息裡。

**為什麼前綴長那樣。** 檔名前面五碼是「章 × 100 ＋ 節」，零填充到五位，
所以字典序就是閱讀順序（`01405_` ＝ 第 14 章第 5 節）。附錄從 900 起跳，
排在所有正文之後。

⚠ **這個編號不是全域身分。** 它是「這本書裡的第幾章」——庫裡實查過
`01405_` 在兩本不同的書上都出現。身分要靠檔名前面那 8 碼 Zotero key
（外掛 0.3.5 已經在送），拆章之後的流水號由進料台加。

⚠ **檔名砍在 80 字**，庫裡看得到後果：`…imperfect diffusene` 的原文是
`diffuseness`，82 字砍成 80。這是刻意的（Windows 路徑長度），不是 bug。
"""

from __future__ import annotations

import logging
import re
import unicodedata

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# 常數
# --------------------------------------------------------------------------- #

#: 檔名元件最大長度（不含副檔名與前綴）。
#: 80 字元對 Windows MAX_PATH(260) 即使深層巢狀仍安全。
MAX_FILENAME_LENGTH: int = 80

#: 清乾淨之後變成空字串時用它。
EMPTY_FILENAME_FALLBACK: str = "untitled"

#: 章節前綴零填充寬度，決定字典序正確性。
PREFIX_WIDTH: int = 5

#: 附錄前綴的基底偏移，排在所有正文之後。
APPENDIX_PREFIX_BASE: int = 900

#: 章（Level 1）編號的倍數，留出節（Level 2）的子號空間。
CHAPTER_NUMBER_MULTIPLIER: int = 100

#: Windows 非法檔名字元。
_WINDOWS_ILLEGAL_RE = re.compile(r'[\\/*?:"<>|]')

#: 連續空白收斂。
_WHITESPACE_RE = re.compile(r"\s+")


def sanitize_filename(name: str, *, max_length: int = MAX_FILENAME_LENGTH) -> str:
    """清理字串為安全的檔名元件。

    移除不可見 / 控制 Unicode 字元（null byte、控制字元、zero-width space、
    BOM 等）與 Windows 非法字元。

    * Unicode 類別過濾：只保留類別首字為 ``L``(Letter)、``N``(Number)、
      ``P``(Punctuation)、``S``(Symbol) 者，以及 ``Zs``(Space-separator)；
      其餘控制(Cc/Cf)、未指派(Cn)、行 / 段分隔(Zl/Zp)、surrogate(Cs)
      一律丟棄。**特例**：``\\t``（其類別為 Cc）被轉成空格而非丟棄。
    * Windows 非法字元 ``\\ / * ? : " < > |`` 全替換為 ``_``。
    * 連續空白 ``\\s+`` 收斂為單一空格並 strip。
    * 結果為空時回傳 :data:`EMPTY_FILENAME_FALLBACK`（``"untitled"``）。
    * 僅 ``max_length > 0`` 時截斷（預設 80）；``max_length == 0`` 停用截斷。

    Args:
        name: 原始標題或標籤。
        max_length: 截斷至此字元數；設為 0 停用截斷。

    Returns:
        清理後、檔案系統安全的字串。結果為空時回傳 ``"untitled"``。
    """
    # 去除不可見 / 控制字元 — 只留可印類別。
    cleaned: list[str] = []
    for ch in name:
        cat = unicodedata.category(ch)
        # 保留：Letter(L)、Number(N)、Punctuation(P)、Symbol(S)、Space-separator(Zs)
        # 過濾：Control(Cc/Cf)、Unassigned(Cn)、Line/Para-sep(Zl/Zp)、Surrogate(Cs)
        if cat[0] in ("L", "N", "P", "S") or cat == "Zs":
            cleaned.append(ch)
        elif ch in (" ", "\t"):
            # \t 特例：類別為 Cc 但仍轉成空格。
            cleaned.append(" ")
    name = "".join(cleaned)

    # 替換 Windows 非法檔名字元。
    name = _WINDOWS_ILLEGAL_RE.sub("_", name)
    # 收斂空白。
    name = _WHITESPACE_RE.sub(" ", name).strip()

    if not name:
        return EMPTY_FILENAME_FALLBACK

    if max_length > 0:
        name = name[:max_length]

    return name


def format_prefix_number(value: int, *, width: int = PREFIX_WIDTH) -> str:
    """固定寬度零填充章節前綴數字，用於檔名字典序排序。

    Args:
        value: 章節編號（可為 0，preamble idx 0 產生全零前綴刻意排最前）。
        width: 零填充寬度，預設 :data:`PREFIX_WIDTH`（5）。

    Returns:
        零填充字串，如 ``"00100"``、``"00900"``、``"00000"``。
    """
    return f"{value:0{width}d}"


def pdf_chapter_prefix(value: int, *, width: int = PREFIX_WIDTH) -> str:
    """PDF 章節前綴（含尾端底線），如 ``"00100_"``。

    編號**值**的計算（preamble / appendix / level 邏輯）屬切分器職責，
    不在這裡；本函式只負責格式化。

    Args:
        value: 已算好的章節編號值。
        width: 零填充寬度，預設 :data:`PREFIX_WIDTH`（5）。

    Returns:
        前綴字串，含尾端 ``_``，如 ``"00100_"``。
    """
    return f"{format_prefix_number(value, width=width)}_"
