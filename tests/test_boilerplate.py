"""出版商樣板與「規則自己就知道是正文」的，不要拿來問人。

2026-08-18 量剩下的 536 項，找到兩條規律：

    出版商樣板   跨 17 份文件都有 'ELSEVIER'、'journal homepage: www.elsevier…'
    判成散文的   標題區塊 138 項判準是「散文」，中位 602 字，明顯是正文

⚠ **跨文件重複這條沒有做。** 計畫是一份一份算的，看不到別份文件；要靠一份
出版商名單，而名單是從舊語料長出來的、舊語料要被刪掉。只做**不依賴語料**的
那半：網址、DOI、版權、ISSN 這些樣式。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from pp.rules.layout_noise import is_publisher_boilerplate  # noqa: E402


def test_publisher_furniture_is_recognised() -> None:
    """網址、期刊首頁、DOI、版權、ISSN —— 這些是出版商印上去的，不是內容。"""
    for text in [
        "journal homepage: www.elsevier.com/locate/apacoust",
        "https://doi.org/10.1016/j.apacoust.2020.107311",
        "© 2012 American Institute of Physics",
        "ISSN 0003-682X",
        "This article is copyrighted as indicated in the article. Reuse of AIP content",
        "All rights reserved.",
    ]:
        assert is_publisher_boilerplate(text), text


def test_real_content_is_not_mistaken_for_furniture() -> None:
    """⚠ **正文不能被誤判。** 誤判的代價是消掉真內容，而那不會有錯誤訊息。

    聲學論文裡本來就會出現 doi、www 這種字 —— 判準要看「整段就是那個東西」，
    不是「裡面出現過那個字」。
    """
    for text in [
        "The absorption coefficient was measured according to ISO 10534-2.",
        "We compare our results with those of Toole, who reported a similar trend.",
        "Reverberation and steady-state energy density",
        "8.7 Source Above an Interface",
    ]:
        assert not is_publisher_boilerplate(text), text


def test_an_empty_or_tiny_string_is_not_boilerplate() -> None:
    """空的、一兩個字的不要亂認 —— 那由別的規則處理。"""
    assert not is_publisher_boilerplate("")
    assert not is_publisher_boilerplate("   ")


def test_a_long_paragraph_that_merely_mentions_a_url_stays() -> None:
    """一整段正文裡提到網址 → **留著**。

    判準是「這一段幾乎只有那個東西」，用長度把關：出版商樣板都很短。
    """
    long_text = ("The measurement procedure follows the standard described at "
                 "www.iso.org, and the resulting absorption coefficients are "
                 "compared with the analytical model derived in Section 3, "
                 "which accounts for the viscous and thermal losses in the pores.")

    assert not is_publisher_boilerplate(long_text)
