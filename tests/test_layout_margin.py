"""在頁面邊緣的頁眉頁尾，不用管重複幾次 —— 位置就是答案。

PO 2026-08-18 看著確認清單問「像這個都是段落 這要怎麼辦」，螢幕上是
`1. Introduction`、`2. Impedance tube theory…`。我第一個反應是「解析器標錯了」，
**量完發現是我錯**：

    '1. Introduction'            y頂 = 58    ← 頁高 1000，正文從 99 才開始
    '2. Impedance tube theory…'  y頂 = 57

它們真的在頁眉區。論文與報告的慣例是頁眉印「現在是第幾章」，所以**每換一章就
換一個字串**，每個只出現一兩次，永遠過不了「重複夠多次」那道門檻。

全庫實測（1053 項要人看的頁首頁尾類）：

    553 項（53%）在正文上緣之上
    266 項（25%）在正文下緣之下
    234 項（22%）真的夾在正文裡    ← 只有這些需要人判斷

⇒ 78% 只要看位置就能決定。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from pp.rules.layout_noise import body_band, plan  # noqa: E402


def _page(y0: int, y1: int, text: str, kind: str = "header") -> dict:
    return {"type": kind, "text": text, "page_idx": 0, "bbox": [70, y0, 900, y1]}


def _body(y0: int, y1: int, text: str = "正文一段夠長的內容") -> dict:
    return {"type": "text", "text": text, "page_idx": 0, "bbox": [70, y0, 900, y1]}


BODY = [_body(100 + i * 40, 130 + i * 40) for i in range(12)]


def test_the_body_band_is_measured_per_document() -> None:
    """正文的上下緣**每份自己量**。

    ⚠ 這個庫的版面尺寸本來就不一致（體檢表天天在講），拿固定像素門檻去比一定錯。
    """
    top, bottom = body_band(BODY)

    assert top is not None and bottom is not None
    assert top <= 140, "正文上緣要落在最上面那幾段附近"
    assert bottom >= 500


def test_too_few_body_paragraphs_means_no_band_at_all() -> None:
    """正文太少就**量不出邊界**，這時候不要猜 —— 回 None，讓規則退回舊行為。

    猜一條邊界的後果是把正文當頁眉消掉，而那不會有任何錯誤訊息。
    """
    assert body_band([_body(100, 130)]) == (None, None)
    assert body_band([]) == (None, None)


def test_a_running_head_above_the_body_is_muted_however_rare() -> None:
    """在正文上緣之上 → 就是頁眉，**不管整份只出現一次**。

    這就是 PO 卡住的那一類：頁眉每換一章就換字串，次數永遠不夠。
    """
    items = [_page(51, 67, "8.7 Source Above an Interface"), *BODY]

    p = plan(items, n_pages=10)

    assert [m.text for m in p.mutes] == ["8.7 Source Above an Interface"]
    assert p.held == [], "位置已經講清楚了，不該再問人"


def test_something_sitting_inside_the_body_still_asks() -> None:
    """夾在正文裡的**照舊問人**（全庫 22%）。位置給不了答案的才輪到人。

    ⚠ 這條測試原本拿 `Check for updates` 當例子，2026-08-18 PO 裁掉了那一類
    （他的原話：「我以為那是你寫的字」），它現在走出版商樣板那條規則。
    **例子會過期，測試守的行為不會** —— 換一個位置在正文裡、規則真的說不準的。
    """
    items = [*BODY[:6], _page(300, 340, "Frequency"), *BODY[6:]]

    p = plan(items, n_pages=10)

    assert [h.text for h in p.held] == ["Frequency"]
    assert p.mutes == []


def test_a_footer_below_the_body_is_muted_too() -> None:
    """頁尾同理 —— 在正文下緣之下就是頁尾。"""
    items = [*BODY, _page(900, 920, "DOI:10.1201/9781003389873-6", kind="footer")]

    p = plan(items, n_pages=10)

    assert [m.text for m in p.mutes] == ["DOI:10.1201/9781003389873-6"]


def test_without_a_band_the_old_repeat_rule_still_decides() -> None:
    """量不出邊界時**完全照舊**：重複夠多次才消，不夠就問人。

    新規則只能**多**判得出來，不能讓舊的判斷變差。
    """
    items = [_page(51, 67, "只出現一次的東西"), _body(100, 130)]

    p = plan(items, n_pages=10)

    assert [h.text for h in p.held] == ["只出現一次的東西"]


# ── 左右邊緣：PO 2026-08-18 指著 Annual Reviews 印在頁緣的下載聲明 ──────────


def test_the_horizontal_body_band_is_measured_the_same_way() -> None:
    """左右緣跟上下緣同一套量法 —— **百分位與門檻只有一份**，各寫一份就會漂。"""
    from pp.rules.layout_noise import body_hband

    left, right = body_hband(BODY)

    assert (left, right) == (70, 900)


def test_too_few_body_paragraphs_means_no_horizontal_band_either() -> None:
    """量不出來就回 None。猜一條邊界的後果是把正文當版面消掉，而且不報錯。"""
    from pp.rules.layout_noise import body_hband

    assert body_hband([_body(100, 130)]) == (None, None)
    assert body_hband([]) == (None, None)
