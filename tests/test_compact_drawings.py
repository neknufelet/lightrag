"""回給 agent 的原文裡，圖片標記只留圖說。

`search` 的字元額度是固定的（預設 12,000），而 chunk 裡的 `<drawing …>` 帶著
`id`／`format`／`src`／`path`（一長串 sha256 檔名）—— 那些對回答問題沒有幫助，
只是把額度吃掉。2026-08-09 實測三個查詢，扣掉 caption 之後的雜訊佔 4.3%／8.5%／
**26.0%**，而且圖多的論文正好是最需要原文的那種。

**這支測試存在的理由**：判準本來寫在 `kbapi.py` 裡，而那個檔一被載入就要讀
`.env`（coder 上刻意沒有），所以測不到 —— 等於只有註解在守。搬到
`mineru_common` 之後才守得住。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from mineru_common import compact_drawings  # noqa: E402

REAL = (
    '<drawing id="im-624ee07835d0c1d1e4eac6176a751347-0006" format="jpg" '
    'caption="FIG. 2. (a) Absorption of two hybrid absorbers predicted by a '
    'theoretical method (solid line) and by FEM (circles)." '
    'path="2019 - Low-frequency sound absorption of hybrid absorber.blocks.assets/'
    '41723107804dc21d639809adc8da6f092fa3b7276dd0404888305d06bec6ffab.jpg" src="" />'
)


def test_caption_survives_and_the_rest_goes() -> None:
    out = compact_drawings(REAL)
    assert "FIG. 2." in out and "Absorption of two hybrid absorbers" in out
    for noise in ("im-624ee", "blocks.assets", "41723107804dc21d", "format=", "src="):
        assert noise not in out, f"{noise} 還在 —— 那是純雜訊"
    # 這個真實標記 350 字元，壓完 119 —— 省 66%。門檻訂 50% 是為了留餘裕給
    # 圖說比較長的那些，同時仍然會在「壓縮失效」時咬到（失效就是 0%）。
    assert len(out) <= len(REAL) / 2, f"沒省下多少：{len(REAL)} → {len(out)}"


def test_a_drawing_without_caption_disappears_entirely() -> None:
    """沒有圖說的標記留下來也沒有資訊，整個丟掉。"""
    tag = ('<drawing id="im-1" format="jpg" '
           'path="doc.blocks.assets/abc123.jpg" src="" />')
    assert compact_drawings(f"前{tag}後") == "前後"


def test_surrounding_prose_is_untouched() -> None:
    """**只動圖標記。** 動到散文就是在改答案本身。"""
    prose = ("At the resonance frequency, a much larger velocity at the interface "
             "of the MPP is observed. $Z_s = Z_M + \\xi \\cdot Z_{C1}^{L}$")
    assert compact_drawings(prose) == prose


def test_many_drawings_in_one_chunk() -> None:
    """實測最糟的那一段有 12 個標記。逐個處理，不是只換第一個。"""
    text = "a" + REAL * 5 + "b"
    out = compact_drawings(text)
    assert out.startswith("a") and out.endswith("b")
    assert out.count("[圖：") == 5
    assert "blocks.assets" not in out


def test_no_drawings_is_a_no_op() -> None:
    assert compact_drawings("") == ""
    assert compact_drawings("純文字") == "純文字"


def test_kbapi_uses_the_shared_helper_not_its_own_copy() -> None:
    """**不能各寫一份。** 抄一份到 kbapi 的話，改了這裡而那裡沒改不會有任何訊號
    —— 今天已經因為同一個形狀踩過兩次（量測與清除各算一次、規則分工只寫在註解裡）。

    不 import kbapi 來驗（那個檔載入時就要 `.env`），改成讀原始碼。
    """
    src = (ROOT / "scripts" / "kbapi.py").read_text(encoding="utf-8")
    assert "compact_drawings" in src, "kbapi 沒有用這個函式"
    assert "from mineru_common import" in src and "compact_drawings" in src.split(
        "from mineru_common import")[1][:120], "不是從 mineru_common 匯入的"
    assert "def compact_drawings" not in src, "kbapi 裡有自己的抄本，會漂"
