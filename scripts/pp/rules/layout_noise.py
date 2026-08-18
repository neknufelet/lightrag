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
from typing import Final

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


#: 量正文上下緣時，取第幾百分位。取極值會被少數壓在很上面的段落帶歪，
#: 取中位又會把正常正文算成邊緣。10% 是折衷。
BODY_EDGE_PERCENTILE = 10

#: 要有幾段正文才敢量邊界。太少的話量出來的邊界是噪音，
#: **而猜錯一條邊界的後果是把正文當頁眉消掉，不會有任何錯誤訊息。**
BODY_MIN_PARAGRAPHS = 5


def body_band(items: list[dict]) -> tuple[float | None, float | None]:
    """這份文件的正文從哪裡到哪裡（y 座標）。量不出來就回 ``(None, None)``。

    ⚠ **每份自己量，不要用固定門檻。** 這個庫的版面尺寸本來就不一致
    （體檢表天天在講「頁面尺寸不一致」），拿固定像素去比一定錯。

    ⚠ **量不出來就不要猜。** 回 None 讓規則退回原本的重複次數判斷 ——
    猜一條邊界的後果是把正文當頁眉消掉，而那不會有任何錯誤訊息。
    """
    tops, bottoms = [], []
    for it in items:
        if it.get("type") != "text" or not (it.get("text") or "").strip():
            continue
        box = it.get("bbox") or []
        if len(box) >= 4:
            tops.append(box[1])
            bottoms.append(box[3])
    if len(tops) < BODY_MIN_PARAGRAPHS:
        return None, None
    tops.sort()
    bottoms.sort()
    k = max(0, len(tops) * BODY_EDGE_PERCENTILE // 100)
    return tops[k], bottoms[len(bottoms) - 1 - k]


def _outside_body(it: dict, top: float | None, bottom: float | None) -> bool:
    """這一項在不在正文範圍之外（＝頁眉區或頁尾區）。

    **為什麼位置比重複次數可靠**：論文與報告的頁眉常常印「現在是第幾章」，
    每換一章就換一個字串，所以每個只出現一兩次，永遠過不了重複門檻 ——
    但它就在頁面最上緣。2026-08-18 全庫實測，要人看的 1053 項裡有 819 項
    （78%）落在邊緣，剩下 234 項才是真的夾在正文裡、需要人判斷的。
    """
    if top is None or bottom is None:
        return False
    box = it.get("bbox") or []
    if len(box) < 4:
        return False
    return box[3] <= top or box[1] >= bottom


#: 出版商印在版面上的東西：期刊首頁、DOI、版權、ISSN。**不是內容。**
#:
#: ⚠ 判準是「整段幾乎就是那個東西」，不是「裡面出現過那個字」。聲學論文本來
#: 就會提到 ISO、doi、www —— 誤判的代價是消掉真內容，而那不會有錯誤訊息。
#: 長度那道關就是為此：實測出版商樣板都很短，正文提到網址時整段都很長。
PUBLISHER_PATTERNS: Final[re.Pattern[str]] = re.compile(
    r"(journal\s+homepage|https?://|doi\.org|\bdoi:\s*10\."
    r"|©|\(c\)\s*\d{4}|all\s+rights\s+reserved|\bISSN\b"
    r"|this\s+article\s+is\s+copyrighted)", re.I)

#: 超過這麼長就不當樣板。實測 2026-08-18：命中樣式的 57 項最長 210 字
#: （那是整段版權宣告），而正文提到網址的段落動輒好幾百字。
PUBLISHER_MAX_CHARS: Final[int] = 240


def is_publisher_boilerplate(text: str) -> bool:
    """這一段是不是出版商的版面家具（期刊首頁、DOI、版權、ISSN）。

    **為什麼值得一條規則**：2026-08-18 量剩下要人看的 243 項，其中 86 項是
    「同一個字串出現在好幾份不同文件」—— 那是出版商印上去的，不是內容。
    但計畫是一份一份算的、看不到別份文件，所以只做**不依賴語料**的這半：
    看樣式，不看跨文件次數。

    ⚠ 另外那 62 項（'ELSEVIER'、'AIP Publishing'…）要靠一份出版商名單才抓得到。
    **刻意不做**：名單是從舊語料長出來的，而舊語料要被刪掉，新庫的出版商組合
    不一樣。等新庫有東西再量。
    """
    t = (text or "").strip()
    if not t or len(t) > PUBLISHER_MAX_CHARS:
        return False
    return bool(PUBLISHER_PATTERNS.search(t))


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

    band_top, band_bottom = body_band(items)
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
        # **位置優先於次數。** 在正文範圍之外就是版面，不必管它出現幾次
        # （見 `_outside_body` 的說明：頁眉會隨章節換字串）。
        if (n >= thr
                or _outside_body(it, band_top, band_bottom)
                or is_publisher_boilerplate(key)
                or (it["type"] == "aside_text" and is_gibberish(key))):
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
