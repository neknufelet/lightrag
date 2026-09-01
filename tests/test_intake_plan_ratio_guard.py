"""計畫階段必須講出 `apply` 會擋的每一條比例守衛。

**為什麼需要這支**：少講一條，文件就會判 clean → 自動放行 → 被 `apply`
拒絕成 failed，而 `--acknowledged-ratio` 只在 `decision != "clean"` 時才帶
—— 於是人在畫面上**重試與放行都回到同一道牆**，沒有任何動作救得了它。

2026-08-09 refs／title 踩過一次（三份綜述論文），當時補了那兩條就停手；
2026-09-01 cover_ad 又踩一次：`CY89WRGB`（物理学报，封面整頁是引用資訊
＋六篇別人的論文廣告，本文只有 8 頁 → 17.0%）。**同一個形狀、兩年內兩次**，
所以這支不是釘住某個數字，而是拿 `apply.py` 當真值來源逐條對帳。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import intake  # noqa: E402

RULES = ("refs", "title", "cover_ad", "margin")


def _payload(doc: str = "x.pdf", **blocks: object) -> dict:
    """`_numeric_issues` 過得去的最小計畫，再蓋上要測的那一段。"""
    empty = {"mute": [], "held": [], "ratio": 0.0, "suspicious": False}
    plan: dict = {
        "doc": doc, "pages": 8, "items": 126, "page_size": [595.0, 842.0],
        "noise": dict(empty), "refs": dict(empty), "title": dict(empty),
        "cover_ad": dict(empty), "margin": dict(empty),
        "tables": {"total": 0, "repair": [], "review": []},
        "charts": {"convert": [], "dangling": []},
    }
    plan.update(blocks)
    return {"plans": [plan], "failed": []}


def _suspicious(ratio: float = 0.1695) -> dict:
    return {"mute": [], "held": [], "ratio": ratio, "suspicious": True}


def test_apply_會擋的每一條計畫階段都要講出來() -> None:
    """清單漏一條就是一條「人救不了」的死路 —— 真值來源是 apply.py 自己。"""
    guard_source = (ROOT / "scripts" / "pp" / "apply.py").read_text("utf-8")
    guarded = set(re.findall(r'_ratio_guard\(\s*"([^"]+)"', guard_source))
    # 這條由 `_numeric_issues` 的 noise.suspicious 負責，不走下面那個迴圈
    guarded.discard("消音比例")
    # 同一條規則，apply 那側的字面多了「區段」兩個字
    guarded.discard("參考文獻區段消音比例")

    surfaced: set[str] = set()
    for key in RULES:
        evaluation = intake.evaluate_plan_payload(
            _payload(**{key: _suspicious()}), "x.pdf")
        assert not evaluation.accepted, (
            f"{key} 超標卻判成 clean —— 它會自動放行然後被 apply 拒絕成 failed，"
            "而畫面上重試與放行都回到同一道牆")
        surfaced.update(r.split("異常（")[0] for r in evaluation.reasons)

    assert not guarded - surfaced, f"apply 會擋、計畫卻不講的：{guarded - surfaced}"


def test_封面廣告頁超標停在等你看而不是失敗() -> None:
    """CY89WRGB（物理学报）的實際數字。"""
    evaluation = intake.evaluate_plan_payload(
        _payload(cover_ad=_suspicious()), "x.pdf")
    assert not evaluation.accepted
    assert evaluation.reasons == ("封面廣告頁消音比例異常（17.0%）",)
    assert "不是正文" in evaluation.details[0]


def test_沒超標的不得被誤擋() -> None:
    """比例都在門檻內的計畫照樣自動放行 —— 這支不是用來把門檻收緊的。"""
    assert intake.evaluate_plan_payload(_payload(), "x.pdf").accepted
