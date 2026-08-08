"""走向量檢索的 skill 必須照 [ADR-0005](../docs/decisions/0005-translate-query-before-retrieval.md) 送英文查詢。

**為什麼這支測試在這個 repo，而 skill 在另一個 repo**：規則是在這裡決定的
（ADR-0005），但實作在 `AI_TOOLS`。體檢當天的結論是「跨 repo 的規則目前**沒有
執行者**」——決定寫下來了、實作也照做了，但沒有東西守著它繼續照做。
規則在哪裡決定，守它的人就該在哪裡。

**為什麼要同時檢查 frontmatter 的 `description` 與正文**：`description` 是模型在
決定要不要用這個 skill 時唯一會讀到的東西，正文要到載入之後才看得到。規則只寫在
正文，就會出現「載入後才知道要翻譯」——而那時查詢字串往往已經組好了。

**為什麼 `lightrag-fetch` 要明確寫出「不需要翻譯」**：它走檔名查詢、不經過向量
檢索，所以豁免是對的。但「沒有寫規則」與「刻意豁免」必須分得開 —— 否則哪天有人
把它改成走檢索，也不會有人發現它少了一條。
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# AI_TOOLS 與本 repo 是同一個 owner 底下的兄弟目錄。不寫死家目錄——換人 clone
# 到別的地方時，寫死的路徑會讓這支測試永遠 skip，而 skip 看起來像通過。
SKILLS = ROOT.parent / "AI_TOOLS" / "skills" / "common"

# 走向量檢索的 skill：查詢字串會被 embedding，所以必須先轉英文。
RETRIEVAL_SKILLS = ("lightrag-search", "lightrag-images")
# 走檔名查詢的 skill：沒有 embedding 參與，豁免，但要明確寫出來。
LOOKUP_SKILLS = ("lightrag-fetch",)

_needs_skills = pytest.mark.skipif(
    not SKILLS.is_dir(),
    reason=f"找不到 {SKILLS} ⇒ 驗不了（不是通過）")


def _skill(name: str) -> tuple[str, str]:
    """回 (frontmatter 的 description, 正文)。"""
    text = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
    desc = ""
    for line in text.splitlines():
        if line.startswith("description:"):
            desc = line
            break
    return desc, text


@_needs_skills
@pytest.mark.parametrize("name", RETRIEVAL_SKILLS)
def test_description_tells_the_model_to_query_in_english(name: str) -> None:
    """規則要寫在 `description` 裡，因為那是選用 skill 之前唯一讀得到的部分。"""
    desc, _ = _skill(name)
    assert desc, f"{name} 的 SKILL.md 沒有 description"
    low = desc.lower()
    assert "english" in low, f"{name} 的 description 沒有提到用英文查詢：{desc[:120]}"


@_needs_skills
@pytest.mark.parametrize("name", RETRIEVAL_SKILLS)
def test_body_explains_why_and_requires_disclosing_the_query(name: str) -> None:
    """正文要有兩件事：為什麼要翻譯，以及**回答時要講出送出去的英文字串**。

    後者是 ADR-0005 特別寫下來的：使用者問中文、系統查英文，那是一個轉換；
    不講就是安靜地做了別的事，而引用回來的又是英文段落，看的人無從判斷是
    「沒撈到」還是「翻錯了」。
    """
    _, body = _skill(name)
    assert "英文" in body, f"{name} 正文沒有講英文查詢這件事"
    assert "實際送出去的英文" in body, (
        f"{name} 正文沒有要求「講出實際送出去的英文查詢字串」——"
        "那是 ADR-0005 的第二半，少了它使用者無從判斷是沒撈到還是翻錯了")


@_needs_skills
@pytest.mark.parametrize("name", LOOKUP_SKILLS)
def test_lookup_skill_states_its_exemption_explicitly(name: str) -> None:
    """豁免要明說。「沒有寫規則」與「刻意豁免」長得一樣就沒有人守得住。"""
    desc, body = _skill(name)
    assert "no query translation" in desc.lower() or "不需要" in body, (
        f"{name} 走檔名查詢所以豁免翻譯，但沒有明確寫出來 —— "
        "哪天它被改成走檢索，也不會有人發現它少了一條")


@_needs_skills
def test_every_lightrag_skill_is_classified() -> None:
    """`AI_TOOLS` 裡每個 lightrag-* skill 都要被上面兩類之一涵蓋。

    新增一個 skill 卻忘了分類時，這支會紅。否則新 skill 會安靜地不受任何規則管——
    而它很可能正是下一個把中文丟進向量檢索的地方。
    """
    found = sorted(p.name for p in SKILLS.glob("lightrag-*") if p.is_dir())
    classified = set(RETRIEVAL_SKILLS) | set(LOOKUP_SKILLS)
    unclassified = [n for n in found if n not in classified]
    assert not unclassified, (
        f"這些 lightrag skill 沒有被分類成「走檢索」或「走檔名」：{unclassified}")
