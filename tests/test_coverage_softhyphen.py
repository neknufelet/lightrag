r"""軟連字號造成的假漏字 —— **解析是對的，量測工具錯了**。

2026-08-13 實測：`2025 - Incorporating extended neck …` 量出漏詞 5.6%，
漏最多的是 `tion(10)`、`quency(7)`、`absorp(6)`、`sorption(6)`、`asurface(4)`。
看起來像 MinerU 把整段內容弄丟，實際上 `pdftotext` 吐的是**軟連字號**
（U+00AD，隱形字元）：

```
參考文字層   absorp<U+00AD>\ntion     → 被 [a-z]{4,} 切成 absorp ＋ tion
MinerU       absorption               → 正確接好的一個詞
```

⚠ 這是檔頭記的 `ﬂ` 連字（U+FB02）**同一個形狀的第二次**。NFKC 修得掉連字，
修不掉軟連字號 —— 前者是相容字元，後者是格式字元。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

_spec = importlib.util.spec_from_file_location("coverage_check", ROOT / "scripts" / "coverage-check.py")
assert _spec and _spec.loader
cc = importlib.util.module_from_spec(_spec)
sys.modules["coverage_check"] = cc
_spec.loader.exec_module(cc)

SOFT = "­"
# 取自 dker 上那份 PDF 的文字層原文（2026-08-13）。
REAL = f"signs have limitations as their absorp{SOFT}\ntion response bounces"


def test_a_soft_hyphenated_word_counts_as_one_word() -> None:
    """**本檔的理由。** 排版斷字接回去，不是兩個詞。"""
    got = cc.words(REAL)
    assert got["absorption"] == 1, sorted(got)
    assert got["absorp"] == 0 and got["tion"] == 0


def test_the_parser_side_and_reference_side_now_agree() -> None:
    """兩邊本來就是同一個字 —— 修完要對得上，不然這個修法沒有意義。"""
    assert cc.words(REAL)["absorption"] == cc.words("their absorption response")["absorption"]


def test_nfkc_alone_does_not_fix_it() -> None:
    """控制組：**NFKC 修不掉軟連字號**（它是格式字元不是相容字元）。

    這條在的理由是防止有人日後把 `desoft` 當成多餘的一步拿掉 ——
    看起來 NFKC 好像該處理，實際上不會。
    """
    import unicodedata
    assert SOFT in unicodedata.normalize("NFKC", REAL)


def test_a_real_hyphen_is_not_joined() -> None:
    """真的連字號不能接 —— `low-frequency` 不是 `lowfrequency`。

    ⚠ 只認 U+00AD。ASCII 連字號在論文裡是真的複合詞，接起來會造出
    不存在的字，把一種假漏字換成另一種。
    """
    got = cc.words("a low-frequency absorber")
    assert got["frequency"] == 1 and got["lowfrequency"] == 0
