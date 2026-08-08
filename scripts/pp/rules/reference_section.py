"""參考文獻與致謝區段消音：它們佔掉檢索預算，卻回答不了任何問題。

**為什麼需要這條**（2026-08-08 實測）：把每次查詢的原文從 5 段拉到 20 段之後，
量了四題共 80 段，**6 段（原文 token 的 10%）是參考清單**——`## References` 底下
`[1] Y. Xiao, ...` 那種。分布不均：某一題 18%、某一題 0%。

抽取規則（`prompts/entity_type/acoustics.yml` 第 1 條）管的是「作者名不要變成圖譜
節點」，**管不到這件事**：文字仍然會被切成 chunk、被 embedding、被檢索回來。
兩種浪費要在兩個地方解決。

**為什麼是消音不是刪除**：與 `layout_noise` 同一個理由——`.parsed/` 底下的
sidecar 用 `content_list.json#/6` 這種**陣列索引**當 self_ref，刪掉一項會讓其後
所有引用指向別的東西，而且不報錯。

**消到哪裡為止：下一個同級或更高級的標題，不是文件結尾。**
這一條是被真實資料逼出來的，不是設計出來的。2017 那篇的結構：

    第  80 項  lvl=2  References                    ← 正文的參考清單
    第  81–86 項      list / page_number            ← 清單本體
    第  87 項  lvl=1  Supplementary Information …   ← **真內容，整份補充材料**
    第  89–160 項     推導、公式、圖                 ← 真內容
    第 161 項  lvl=2  References                    ← 補充材料的參考清單

「消到結尾」會把 81–163 全砍，連 72 項真內容一起——**而且不會報錯**。
「消到下一個 lvl ≤ 2 的標題」只消掉 81–86，正確。
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from mineru_common import BODY_TYPES  # noqa: E402

# 參考清單的標題。實測六份文件的寫法：References / REFERENCES / Bibliography。
REFERENCE_HEADING = re.compile(
    r"^\s*#*\s*(references?|bibliography|works\s+cited|literature\s+cited)\s*$", re.I)

# 致謝。**與參考文獻分開計數**，因為它是不同的東西（經費、感謝），
# 只是同樣不回答問題。要保留它時把這個樣式改成永不匹配即可，不必動主邏輯。
# 實測：2020 與 2024、2025 三份都有，各佔 8–14 項。
ACKNOWLEDGEMENT_HEADING = re.compile(
    r"^\s*#*\s*(acknowledge?ments?|funding|author\s+contributions?|"
    r"conflicts?\s+of\s+interest|declaration\s+of\s+competing\s+interest)\s*$", re.I)

# 消音佔比超過此值就標記待查。與 layout_noise 同一個機制：誤消真內容不會報錯，
# 只能靠比例異常察覺。參考文獻在論文裡常佔 10–15%，所以門檻比版面雜訊寬。
SUSPICIOUS_RATIO = 0.30


@dataclass
class RefMute:
    index: int
    item_type: str
    page: object
    text: str
    section: str        # 屬於哪個區段的標題文字
    kind: str           # "reference" | "acknowledgement"


@dataclass
class RefPlan:
    mutes: list[RefMute]
    sections: list[tuple[int, str, str, int]]   # (標題索引, 標題文字, kind, 區段項數)
    body_chars_before: int
    body_chars_after: int

    @property
    def ratio(self) -> float:
        b = self.body_chars_before
        return (b - self.body_chars_after) / b if b else 0.0

    @property
    def suspicious(self) -> bool:
        return self.ratio > SUSPICIOUS_RATIO

    def summary(self) -> str:
        by_kind: dict[str, int] = {}
        for m in self.mutes:
            by_kind[m.kind] = by_kind.get(m.kind, 0) + 1
        detail = "、".join(f"{k} {n} 項" for k, n in sorted(by_kind.items())) or "無"
        return (f"區段消音：{len(self.sections)} 個區段、{len(self.mutes)} 項（{detail}）；"
                f"正文 {self.body_chars_before:,} → {self.body_chars_after:,} "
                f"（{self.ratio * 100:.2f}%）"
                + ("　⚠ 比例異常，請人工確認" if self.suspicious else ""))


def _kind(text: str) -> str | None:
    """這個標題是不是要消音的區段起點。不是就回 None。"""
    if REFERENCE_HEADING.match(text):
        return "reference"
    if ACKNOWLEDGEMENT_HEADING.match(text):
        return "acknowledgement"
    return None


def plan(items: list[dict]) -> RefPlan:
    """算出參考文獻／致謝區段要消音哪些項目。只讀不寫。

    區段的結束條件是「下一個 `text_level` 小於等於本標題的項目」——也就是下一個
    同級或更高級的標題。找不到就消到結尾。
    """
    mutes: list[RefMute] = []
    sections: list[tuple[int, str, str, int]] = []
    muted_idx: set[int] = set()

    for i, it in enumerate(items):
        level = it.get("text_level")
        if not level:
            continue
        text = (it.get("text") or "").strip()
        kind = _kind(text)
        if kind is None:
            continue
        # 已經被前一個區段涵蓋（例如 Acknowledgements 緊接 References）就不重複開段
        if i in muted_idx:
            continue

        end = len(items)
        for j in range(i + 1, len(items)):
            lvl_j = items[j].get("text_level")
            if lvl_j and lvl_j <= level:
                end = j
                break

        span = list(range(i, end))
        for j in span:
            if j in muted_idx:
                continue
            muted_idx.add(j)
            mutes.append(RefMute(index=j, item_type=items[j].get("type", ""),
                                 page=items[j].get("page_idx"),
                                 text=items[j].get("text") or "",
                                 section=text, kind=kind))
        sections.append((i, text, kind, len(span)))

    def body_chars(skip: set[int]) -> int:
        return sum(len(it.get("text") or "")
                   for k, it in enumerate(items)
                   if it.get("type") in BODY_TYPES and k not in skip)

    return RefPlan(mutes, sections, body_chars(set()), body_chars(muted_idx))
