"""第 0 頁上被解析器標成頁眉／頁尾／側邊的，一律是版面家具。

PO 2026-08-18 裁。動機是他自己在真資料上按出來的：連續 17 份、50 項，他丟了
**48 項**（96%），而剩下最大的一堆就是期刊名印在封面上緣——`ELSEVIER` 17 次、
`applied acoustics` 6、`Applied Acoustics` 5、`JOURNAL OF SOUND AND VIBRATION`、
`mssp` 3、`inter.noise NANTES FRANCE`、`ISRA 2013`。

**為什麼重複次數與位置都救不了它們**：期刊名只印在封面那一頁，所以整份只出現
一次，過不了重複門檻；而封面上的標題與作者本來就排得很高，`body_band` 的正文
上緣被它們拉到 y≈97，於是 y=110 的頁眉落在「正文範圍內」。兩條既有的判準同時
失效，**但型別本身就是答案**：正文永遠不會是 header/footer/aside_text。

## 量到的（dker 全母體 319 份，2026-08-18）

    清單裡的頁首頁尾 110 項 → 第 0 頁 74 項、其他頁 36 項
    全庫第 0 頁上這三種型別共 566 項（大多數已被既有規則消掉）

那 74 項**逐項看完**：期刊名、出版商標章、機構典藏封面、DOI＋收稿日期、
版權與授權聲明、會議名。另外把 566 項裡**最長的 20 項**也翻過（最長 385 字，
是牛津大學出版社的版權宣告）。**沒有一項是聲學內容。**

⚠ **只認第 0 頁，其他頁一項都不能動。** 其他頁那 36 項裡有被標錯的真東西：
某份論文的 `from jax import random`（程式碼）被標成 footer、`Boundary layer
flow:`／`Transition:` 被標成 aside_text。同一個型別在封面是版面、在內頁可能
是內容 —— 差別就是位置。

⚠ **試過並否決的做法**：把正文範圍改成「不算第 0 頁」。實測只多抓到 2 項，
卻會讓 174 段真正文落在範圍外（最長 1605 字）。量出來就丟掉了。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from pp.rules import layout_noise as ln  # noqa: E402


def _body(i: int, page: int = 0) -> dict:
    return {"type": "text", "page_idx": page, "bbox": [79, 97 + i * 40, 917, 127 + i * 40],
            "text": "正文一段夠長的內容，用來把正文帶量出來"}


#: 封面的標題與作者排得很高 → 正文上緣被拉到 y=97，頁眉因此落在「範圍內」。
CORPUS = [_body(i) for i in range(6)] + [_body(i, page=1) for i in range(6)]


def _furniture(text: str, page: int, kind: str = "header") -> dict:
    return {"type": kind, "text": text, "page_idx": page, "bbox": [79, 110, 300, 133]}


def test_a_journal_name_on_the_cover_is_furniture_even_appearing_once() -> None:
    """`Journal of Sound and Vibration` 只印在封面，永遠過不了重複門檻。"""
    items = [*CORPUS, _furniture("Journal of Sound and Vibration", 0)]

    p = ln.plan(items, n_pages=2)

    assert [m.text for m in p.mutes] == ["Journal of Sound and Vibration"]
    assert p.held == []


def test_the_same_string_on_an_inner_page_is_still_held_for_a_human() -> None:
    """**只認第 0 頁。** 內頁被標成頁眉的可能是被標錯的真內容。

    實測其他頁那 36 項裡有 `from jax import random` 與 `Boundary layer flow:`。
    """
    items = [*CORPUS, _furniture("from jax import random", 1, kind="footer")]

    p = ln.plan(items, n_pages=2)

    assert p.mutes == []
    assert [m.text for m in p.held] == ["from jax import random"]


def test_all_three_owned_types_count_on_the_cover() -> None:
    """三種型別共用同一份清單（`OWNED_TYPES`），不要在這裡再抄一次。"""
    items = [*CORPUS,
             _furniture("ELSEVIER", 0),
             _furniture("cc BY", 0, kind="footer"),
             _furniture("Aps hds prs", 0, kind="aside_text")]

    p = ln.plan(items, n_pages=2)

    assert sorted(m.text for m in p.mutes) == ["Aps hds prs", "ELSEVIER", "cc BY"]


def test_body_text_on_the_cover_is_never_touched() -> None:
    """正文永遠不是這三種型別 —— 這條規則碰不到正文，是型別給的保證。

    ⚠ 這裡**不能**用 `body_chars_before == body_chars_after` 當斷言：
    `mineru_common.BODY_TYPES` 把 header/footer/aside_text 也算進去了，
    所以那兩個數字本來就會差一個頁眉的長度。要斷言的是型別。
    """
    items = [*CORPUS, _furniture("ELSEVIER", 0)]

    p = ln.plan(items, n_pages=2)

    assert all(m.item_type in ln.OWNED_TYPES for m in p.mutes)
    assert not [m for m in p.mutes if m.item_type == "text"]
