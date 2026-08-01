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
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from mineru_common import BODY_TYPES  # noqa: E402

# 重複幾次以上才算書眉。書眉會在每頁重現，真正的章節標題只出現一次。
# 實測 C Equivalent Networks 的 111 個 header 只有 4 種文字：
# 'Equivalent Networks'×67、'C'×34、'd'×9、''×1 —— 全部遠高於門檻。
RUNNING_HEAD_MIN_REPEAT = 3

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


def plan(items: list[dict]) -> NoisePlan:
    """算出要消音哪些項目。只讀不寫。"""
    targets = [(i, it) for i, it in enumerate(items)
               if it.get("type") in ("header", "footer")]
    counts = collections.Counter((it.get("text") or "").strip() for _, it in targets)

    mutes: list[Mute] = []
    held: list[Mute] = []
    for i, it in targets:
        text = it.get("text") or ""
        key = text.strip()
        n = counts[key]
        m = Mute(index=i, item_type=it["type"], page=it.get("page_idx"), text=text, repeat=n)
        # 空字串消音沒有意義也沒有風險，直接跳過不列入計畫
        if not key:
            continue
        (mutes if n >= RUNNING_HEAD_MIN_REPEAT else held).append(m)

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
