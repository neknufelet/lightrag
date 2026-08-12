"""題本的形狀：每一題都要說清楚「**送去檢索的是哪一串**」。

2026-08-12 之前題本只有 `text`，而 `retrieval-score.py` 直接把中文原句送去檢索
—— 那繞過了 ADR-0005 的翻譯步驟，**量的是沒有人在走的那條路**。

量出來的「中文比英文差 63–86%」因此是假警報：三個對照實驗顯示落差主要來自
打分模型對語言的偏心，不是知識庫撈不到（文件一個字沒變、只把問題改成中文，
分數掉 82%）。詳見 `docs/worklist-20260811.md`。

⇒ 題本改成兩欄：`text` 是使用者會打的字，`retrieval_text` 是**實際送進向量檢索
與 reranker 的字**（照 ADR-0005，一律英文）。這幾條守著那個結構。
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOOK = json.loads((ROOT / "tests" / "retrieval-questions.json").read_text(encoding="utf-8"))
QUESTIONS = BOOK["questions"]


def test_every_question_says_what_gets_retrieved() -> None:
    """沒有 `retrieval_text` 的話，評分腳本只能拿 `text` 去猜 —— 那正是舊的洞。"""
    missing = [q["id"] for q in QUESTIONS if not q.get("retrieval_text", "").strip()]
    assert not missing, f"這些題沒說要送什麼去檢索：{missing}"


def test_what_gets_retrieved_is_always_english() -> None:
    """ADR-0005：走向量檢索的查詢一律用英文送出，即使使用者是用中文問的。

    判準粗但夠用：**送出去的那串不得含中日韓字元**。
    """
    for q in QUESTIONS:
        han = [ch for ch in q["retrieval_text"] if "一" <= ch <= "鿿"]
        assert not han, f"{q['id']} 送去檢索的字串含中文：{''.join(han)}"


def test_an_english_question_retrieves_itself() -> None:
    """英文題不該有兩種寫法 —— 那會讓「翻譯有沒有損失」變成在比兩個英文句子。"""
    for q in QUESTIONS:
        if q["lang"] == "en":
            assert q["retrieval_text"] == q["text"], q["id"]


def test_the_pairs_are_still_pairs() -> None:
    """配對是刻意的：不配對只能給一個總平均，看不出是哪類問題掉最兇。

    ⚠ 補了 `retrieval_text` 之後，配對量的東西**變了**：
    從「中文問 vs 英文問」變成「中文題翻成英文 vs 原生英文題」——
    也就是**翻譯有沒有損失**。這才是 ADR-0005 之後真正該問的問題。
    """
    pairs: dict[str, set[str]] = {}
    for q in QUESTIONS:
        pairs.setdefault(q["pair"], set()).add(q["lang"])
    for pair, langs in pairs.items():
        assert langs == {"zh", "en"}, f"{pair} 不是一中一英：{langs}"
