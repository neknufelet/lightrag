"""版面雜訊過濾：把 header / footer 消音，不刪除。

為什麼是消音而不是刪除：.parsed/ 底下的 tables.json 用 `content_list.json#/6`
這種**陣列索引**當 self_ref。刪掉一個項目，其後所有 sidecar 引用就指向別的東西，
而且不會報錯 —— 正是本專案一路在防的那種靜默損壞。

為什麼按型別而不是按字串：實測「刪掉含 'Equivalent Networks' 的項目」會一併殺掉
文件標題（idx 0，text_level:1）與章節標題 'C.1 Fundamentals of Equivalent Networks'。
型別是 MinerU 已經做好的判斷，字串比對是我們自己重做一次，而且做得更差。
"""
from __future__ import annotations

import collections
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from mineru_common import BODY_TYPES  # noqa: E402

# 真正的字：至少三個字母且含母音。用來判斷一段文字是不是語言。
_WORD = re.compile(r"[A-Za-z]{3,}")
_VOWEL = re.compile(r"[aeiouAEIOU]")

# 書眉/頁尾要數的是**樣板**，不是字面字串。實測一篇 ASEE 論文的頁尾是
# 'Page 24.417.1' … 'Page 24.417.15' —— 每頁一個、15 個全都不重複，
# 字面計數永遠是 1，重複規則完全失效。把數字抹掉後 'Page ##.###.##' 出現
# 15 次 = 100% 的頁，才看得出它是頁尾。
# 只有「除了數字以外完全相同」才會併成同一個樣板，所以 '3.1 Reflection' 與
# '3.2 Scattering' 不會被誤併（文字不同）。
_DIGITS = re.compile(r"\d+")


def template_key(text: str) -> str:
    return _DIGITS.sub("#", text.strip())

# **這條規則的地盤。** 三條消音規則靠型別分工，撞在一起時 `_pp_original_text`
# 會被寫兩次而還原只還原得回一次（`pp/apply.py` 有執行者，撞到就整份拒絕）。
#
# 分工原本只寫在 `apply.py` 的註解裡 —— 也就是**沒有執行者**，於是漂了：
# `reference_section` 圈整個參考區段時把那幾頁的頁首頁尾一起圈走，
# 2026-08-09 這批 22 篇有 8 篇因此被擋（36%）。現在它 import 這個常數來排除，
# 兩邊讀同一份，不各寫一份。
OWNED_TYPES: tuple[str, ...] = ("header", "footer", "aside_text")

# 重複幾次以上才算書眉。書眉會在每頁重現，真正的章節標題只出現一次。
# 實測 C Equivalent Networks 的 111 個 header 只有 4 種文字：
# 'Equivalent Networks'×67、'C'×34、'd'×9、''×1 —— 全部遠高於門檻。
RUNNING_HEAD_MIN_REPEAT = 3

# 但絕對門檻對短文件失效：A Conventions 只有 3 頁，書眉 'Conventions' 只能
# 出現 2 次，永遠達不到 3。書眉的本質是「大部分頁都出現」而不是「出現超過幾次」，
# 所以門檻不能超過該文件的頁數所能產生的次數。
RUNNING_HEAD_PAGE_FRACTION = 0.5


def head_threshold(n_pages: int) -> int:
    """實際門檻。短文件放寬，長文件維持 3 —— 68 頁時 min(3, 34) 仍是 3，
    既有行為不變；3 頁時 min(3, 2) = 2，書眉抓得到。"""
    if n_pages <= 0:
        return RUNNING_HEAD_MIN_REPEAT
    import math
    return max(2, min(RUNNING_HEAD_MIN_REPEAT,
                      math.ceil(n_pages * RUNNING_HEAD_PAGE_FRACTION)))

# 消音佔比超過此值就標記待查。誤刪真內容不會有錯誤訊息，只能靠比例異常察覺。
# 實測：論文 2.2%、J Duct 1.3%、C Equivalent Networks 5.58%。
SUSPICIOUS_RATIO = 0.10


@dataclass
class Mute:
    index: int          # content_list 的陣列索引
    item_type: str
    page: object
    text: str           # 原文，寫進 _pp_original_text 以便還原與查帳
    repeat: int         # 該文字在文件內出現次數


@dataclass
class NoisePlan:
    mutes: list[Mute]
    held: list[Mute]            # 重複次數不足，疑似真標題，留給人看
    body_chars_before: int
    body_chars_after: int
    distinct: dict[str, int]    # 文字 → 出現次數

    @property
    def ratio(self) -> float:
        b = self.body_chars_before
        return (b - self.body_chars_after) / b if b else 0.0

    @property
    def suspicious(self) -> bool:
        return self.ratio > SUSPICIOUS_RATIO

    def summary(self) -> str:
        return (f"消音 {len(self.mutes)} 項、保留待查 {len(self.held)} 項；"
                f"正文 {self.body_chars_before:,} → {self.body_chars_after:,} "
                f"（{self.ratio*100:.2f}%）"
                + ("　⚠ 比例異常，請人工確認" if self.suspicious else ""))


def is_gibberish(text: str) -> bool:
    """一個真正的字都沒有 —— 不是語言，是 OCR 殘骸。

    判準刻意保守（**零**個真字才算），因為這條規則用在只出現一次的項目上，
    沒有「重複次數」可以當保險。實測論文頁邊直排那條抓到的是
    '9r 0 1 -.s] :0006'：token 是 9r / 0 / 1 / s / 0006，零個真字。
    真正的側欄註解一定有字，不會被誤傷。
    """
    return not any(_VOWEL.search(w) for w in _WORD.findall(text))


def plan(items: list[dict], n_pages: int = 0) -> NoisePlan:
    """算出要消音哪些項目。只讀不寫。

    兩種雜訊用兩條不同的規則，因為訊號不同：
      header/footer —— 每頁重現，用重複次數判斷（真章節標題只出現一次）
      aside_text    —— 頁邊直排的期刊資訊，**只出現一次**，重複次數對它無效；
                       改用「這串文字是不是語言」判斷
    """
    thr = head_threshold(n_pages)
    targets = [(i, it) for i, it in enumerate(items)
               if it.get("type") in OWNED_TYPES]
    counts = collections.Counter((it.get("text") or "").strip() for _, it in targets)
    # 樣板計數：抹掉數字後再數一次。頁碼型頁尾只有這樣才數得到。
    tcounts = collections.Counter(template_key(it.get("text") or "") for _, it in targets)

    mutes: list[Mute] = []
    held: list[Mute] = []
    for i, it in targets:
        text = it.get("text") or ""
        key = text.strip()
        # 取字面與樣板兩者的較大值 —— 樣板一定 >= 字面，這樣既有行為不變，
        # 又補上頁碼型頁尾。
        n = max(counts[key], tcounts[template_key(key)])
        m = Mute(index=i, item_type=it["type"], page=it.get("page_idx"), text=text, repeat=n)
        # 空字串消音沒有意義也沒有風險，直接跳過不列入計畫
        if not key:
            continue
        # 重複／樣板規則對三種型別都先跑。is_gibberish 只是後備，處理
        # 「只出現一次而且不是語言」的殘骸。
        #
        # 先前把 aside_text 整個導向 is_gibberish 是錯的 —— 那是從一份文件
        # （2016 論文的單次 OCR 殘骸）推論出「aside_text 只出現一次」。
        # 另一份 ASEE 論文用 aside_text 放每頁的 'Page 24.417.N' 頁邊頁尾，
        # 15 頁全都是，重複規則明明有效。同一個型別在不同期刊是不同東西。
        if n >= thr or (it["type"] == "aside_text" and is_gibberish(key)):
            mutes.append(m)
        else:
            held.append(m)

    def body_chars(skip: set[int]) -> int:
        return sum(len(it.get("text") or "")
                   for i, it in enumerate(items)
                   if it.get("type") in BODY_TYPES and i not in skip)

    before = body_chars(set())
    after = body_chars({m.index for m in mutes})
    return NoisePlan(mutes, held, before, after, dict(counts))


def apply_to_items(items: list[dict], plan_: NoisePlan) -> int:
    """就地消音。原文存進 _pp_original_text —— 還原時讀它，查帳時比對它。

    只清 "text"。ir_builder._coerce_text 依序讀 text / content / body / code_body，
    但 header 項目只有 text；若未來出現帶其他欄位的 header，compat-check 的 A-06
    會先擋下（欄位順序改變即失敗）。
    """
    n = 0
    for m in plan_.mutes:
        it = items[m.index]
        if it.get("text"):
            it["_pp_original_text"] = it["text"]
            it["text"] = ""
            n += 1
    return n


def revert_items(items: list[dict]) -> int:
    """從 _pp_original_text 還原。不需要備份檔就能回到原狀。"""
    n = 0
    for it in items:
        if "_pp_original_text" in it:
            it["text"] = it.pop("_pp_original_text")
            n += 1
    return n
