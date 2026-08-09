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
from dataclasses import dataclass

from pp.rules import layout_noise

# 參考清單的標題。實測六份文件的寫法：References / REFERENCES / Bibliography。
REFERENCE_HEADING = re.compile(
    r"^\s*#*\s*(references?|bibliography|works\s+cited|literature\s+cited)\s*$", re.I)

# 致謝。**與參考文獻分開計數**，因為它是不同的東西（經費、感謝），
# 只是同樣不回答問題。要保留它時把這個樣式改成永不匹配即可，不必動主邏輯。
# 實測：2020 與 2024、2025 三份都有，各佔 8–14 項。
ACKNOWLEDGEMENT_HEADING = re.compile(
    r"^\s*#*\s*(acknowledge?ments?|funding|author\s+contributions?|"
    r"conflicts?\s+of\s+interest|declaration\s+of\s+competing\s+interest)\s*$", re.I)

# **正文重新開始的硬邊界，與標題層級無關。**
#
# 2026-08-09 實測（2024 Broadband sound absorbers via quality-factor modulation）：
# `Appendix A. The impedance model of the two-resonator absorber…` 這一行 MinerU
# **沒有標成標題**（沒有 `text_level`），於是「消到下一個同級或更高級的標題為止」
# 直接跨過它 —— `Acknowledgments` 區段一路吃到參考文獻，把整個附錄 A
# （正文 3 項、公式 4 條、圖 3 張）當成致謝消掉，**而且不會有錯誤訊息**。
# 只有比例守衛（35.1%）攔下了它。
#
# 附錄**依定義就是正文**，致謝與參考清單不可能延伸進去。所以判準不能只靠
# 「MinerU 有沒有把它標成標題」—— 那是解析器的判斷，會漏。
#
# ⚠ 前綴比對，不是整行比對：附錄標題後面通常還跟著篇名
#（上面那行就是），用 `$` 收尾會配不到。
BODY_RESUMES = re.compile(
    r"^\s*#*\s*(appendix|supplementary\s+(information|material))\b", re.I)

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


def item_chars(item: dict) -> int:
    """一個項目的實際字數。

    ⚠ **不能只看 `text`。** 參考清單的型別是 `list`，內容在 `list_items` 陣列裡，
    `text` 是空的——2026-08-08 第一版就是只數 `text`，於是報出「消音 0.05%」
    這種假數字（實際是 8–23%）。而且 `list` 不在 `BODY_TYPES` 裡，用型別過濾
    會把整個參考清單排除在分母之外。**統計錯了，就沒有人會相信這條規則。**
    """
    return (len(item.get("text") or "")
            + sum(len(x) for x in (item.get("list_items") or [])))


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
            # 附錄／補充材料是正文，區段到此為止 —— 就算解析器沒把它標成標題。
            # 見 `BODY_RESUMES` 的說明（附錄被當致謝消掉的實例）。
            if BODY_RESUMES.match((items[j].get("text") or "").strip()):
                end = j
                break

        span = list(range(i, end))
        for j in span:
            if j in muted_idx:
                continue
            # **不碰 header／footer／aside_text —— 那是 `layout_noise` 的地盤。**
            # 參考文獻在最後幾頁，整段圈下去會連那幾頁的書眉與頁尾 DOI 一起圈走，
            # 而它們每頁重現、本來就會被書眉規則消掉。兩條同時消音時
            # `_pp_original_text` 會被寫兩次（第二次存的是空字串），還原只還原得回
            # 一項 —— `pp/apply.py` 因此整份拒絕。2026-08-09 這批 22 篇有 8 篇
            # 卡在這裡（36%），而衝突的項目**全部**是 header/footer。
            #
            # 排除不會少消東西：這些項目仍然由 `layout_noise` 消掉，只是不再被
            # 兩條規則同時認領。
            if items[j].get("type") in layout_noise.OWNED_TYPES:
                continue
            muted_idx.add(j)
            mutes.append(RefMute(index=j, item_type=items[j].get("type", ""),
                                 page=items[j].get("page_idx"),
                                 text=items[j].get("text") or "",
                                 section=text, kind=kind))
        sections.append((i, text, kind, len(span)))

    # 補強：MinerU 自己把參考清單標成 `sub_type: "ref_text"`。
    #
    # 2026-08-08 六份文件實測：標題推斷是 ref_text 的**超集**（每一項 ref_text
    # 都已被涵蓋），所以這一段目前不會多抓到東西。留著是因為兩者的失效方式不同：
    #   標題推斷  在標題寫法沒見過、或整份沒有 References 標題時失效
    #   ref_text  在 MinerU 沒分類時失效（實測 C Equivalent Networks 就是 0 項）
    # 兩個都失效才會漏，而不是任一個失效就漏。
    for i, it in enumerate(items):
        if it.get("sub_type") != "ref_text" or i in muted_idx:
            continue
        muted_idx.add(i)
        mutes.append(RefMute(index=i, item_type=it.get("type", ""),
                             page=it.get("page_idx"), text=it.get("text") or "",
                             section="<MinerU sub_type=ref_text>", kind="reference"))

    total = sum(item_chars(it) for it in items)
    return RefPlan(mutes, sections, total, total - sum(item_chars(items[i]) for i in muted_idx))


def apply_to_items(items: list[dict], plan_: RefPlan) -> int:
    """就地消音。原文存進 `_pp_original_*` —— 還原時讀它，查帳時比對它。

    ⚠ **必須同時清 `text` 與 `list_items`。** 參考清單的型別是 `list`，內容全在
    `list_items` 陣列裡而 `text` 是空的 —— 只清 `text`（`layout_noise` 的作法）
    對它**完全沒有作用**，但函式仍會回報「消了 N 項」。那是靜默失效：
    數字看起來對，參考文獻照樣進索引。

    `text` 沿用 `_pp_original_text` 這個鍵，所以 `layout_noise.revert_items`
    還原得了它；`list_items` 是本規則獨有的，由下面的 `revert_items` 負責。
    """
    n = 0
    for m in plan_.mutes:
        it = items[m.index]
        touched = False
        if it.get("text"):
            it["_pp_original_text"] = it["text"]
            it["text"] = ""
            touched = True
        if it.get("list_items"):
            it["_pp_original_list_items"] = it["list_items"]
            it["list_items"] = []
            touched = True
        n += 1 if touched else 0
    return n


def revert_items(items: list[dict]) -> int:
    """還原 `list_items`。`text` 那半由 `layout_noise.revert_items` 負責（同一個鍵）。

    分開寫而不是自己也還原 `text`：兩支都還原同一個鍵的話，先跑的那支還原、
    後跑的那支看到鍵已不在就當成沒事，計數會少算一半——而計數是查帳的依據。
    """
    n = 0
    for it in items:
        if "_pp_original_list_items" in it:
            it["list_items"] = it.pop("_pp_original_list_items")
            n += 1
    return n
