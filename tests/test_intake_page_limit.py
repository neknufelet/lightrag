r"""太厚的 PDF 要在**送出去之前**擋下來。

2026-08-14 撞到：`n.d. - Perception of room modes…`（225 頁）送進 MinerU 官方
API，等到遠端解析才拿回一句英文：

```
number of pages exceeds limit (200 pages), please split the file and try again
```

⚠ 檔案就在本機，頁數 `pdfinfo` 一秒就數得出來 ——
**能在本機判的不要拿去問外面的服務。**

⚠ 而那本書其實早就切成九章進庫了（九章 212 頁／整本 225 頁），
這一份是重複丟進來的 —— 所以錯誤訊息要順帶提醒這件事。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import intake  # noqa: E402


class _Info:
    """假的 `pdfinfo` 輸出。"""

    def __init__(self, stdout: str) -> None:
        self.stdout = stdout


def _fake(stdout: str):                                           # noqa: ANN202
    return lambda *a, **k: _Info(stdout)


def test_a_pdf_over_the_limit_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """**本檔的理由。** 225 頁要在本機就擋下。"""
    monkeypatch.setattr(subprocess, "run", _fake("Title: x\nPages:          225\n"))
    msg = intake._too_many_pages(Path("x.pdf"), 200)
    assert msg and "225" in msg and "200" in msg


def test_the_message_says_what_to_do(monkeypatch: pytest.MonkeyPatch) -> None:
    """錯誤訊息要能直接動作 —— 切章節，或先確認是不是重複丟的。"""
    monkeypatch.setattr(subprocess, "run", _fake("Pages: 225\n"))
    msg = intake._too_many_pages(Path("x.pdf"), 200) or ""
    assert "切成章節" in msg and "已經切好進過" in msg


def test_the_message_hands_over_a_working_link(monkeypatch: pytest.MonkeyPatch) -> None:
    """訊息要給**點得下去的路**，不是只叫人「去切一切」。

    2026-08-17 之前這句話寫著「把它切成章節再進」，而那時候根本沒有切章的畫面 ——
    等於叫人去做一件做不到的事。現在有了，就要把路給出來。

    ⚠ 檔名要 URL 編碼：書名有空格與 `&`，不編碼的話連結會斷在第一個特殊字元。
    """
    monkeypatch.setattr(subprocess, "run", _fake("Pages: 500\n"))

    msg = intake._too_many_pages(Path("A&B 2015 - Big Book.pdf"), 200) or ""

    assert "/chapters?doc=" in msg
    assert "A%26B%202015" in msg, "檔名要編碼，不然連結會斷"


def test_being_too_thick_and_being_worth_splitting_stay_separate(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """**「太厚」與「該不該切」是兩件事**（設計文件的提醒），不得合成同一個判斷。

    一本 150 頁的學位論文照樣該按章切，而它不會經過這道擋 —— 所以這道擋只負責
    「送不出去」，切不切由使用者在收件匣那一列自己決定（那裡每一本都有切章入口）。
    這條釘住的是：**沒超過上限就一個字都不說**，不要在這裡順便勸人去切。
    """
    monkeypatch.setattr(subprocess, "run", _fake("Pages: 150\n"))

    assert intake._too_many_pages(Path("thesis.pdf"), 200) is None


def test_a_pdf_at_the_limit_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """**邊界。** 剛好 200 頁是可以的，上限是「超過」不是「達到」。"""
    monkeypatch.setattr(subprocess, "run", _fake("Pages: 200\n"))
    assert intake._too_many_pages(Path("x.pdf"), 200) is None


def test_an_unreadable_page_count_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """**控制組，而且是最重要的一條。** 數不出來就放行。

    `pdfinfo` 讀不到頁數的 PDF 仍然可能解析得動；在這裡擋下等於用一個猜測
    否定一份可能沒問題的文件。
    """
    monkeypatch.setattr(subprocess, "run", _fake("Title: 沒有 Pages 這一行\n"))
    assert intake._too_many_pages(Path("x.pdf"), 200) is None


def test_pdfinfo_missing_does_not_block(monkeypatch: pytest.MonkeyPatch) -> None:
    """連 `pdfinfo` 都沒有的機器上，這道檢查要讓路而不是擋路。"""
    def boom(*a: object, **k: object) -> None:
        raise FileNotFoundError("pdfinfo")
    monkeypatch.setattr(subprocess, "run", boom)
    assert intake._too_many_pages(Path("x.pdf"), 200) is None


def test_the_limit_is_overridable() -> None:
    """上限是**別人家的規則**，會變 —— 要能用環境變數改，不必改程式。"""
    runner = intake.SubprocessRunner(ROOT, {"MINERU_PAGE_LIMIT": "500"})
    assert runner.mineru_page_limit == 500
    assert intake.SubprocessRunner(ROOT, {}).mineru_page_limit == intake.MINERU_PAGE_LIMIT
