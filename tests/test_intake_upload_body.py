"""大檔上傳不得因為「一次沒讀完」就被判成中斷。

**2026-08-17 實測踩到的：** PO 拖一本大部頭教科書（Rossing《The science of sound》）
進審核台，畫面沒反應。紀錄（當天稍早才補上的理由）寫著：

    POST /api/upload 擋下（400）：上傳內容不完整（可能中斷）

原因是 `_upload_body` 只呼叫一次 `rfile.read(length)` 就拿長度去比。socket 上的
讀取**本來就可能少於要求的位元組數**，大檔特別容易 —— 而它被當成「連線斷了」。
同一天稍早那份 2.8 MB 的小檔剛好一次讀得完，所以看起來時好時壞。
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import pytest  # noqa: E402
from intake import IntakeError, _upload_body  # noqa: E402


class _ChunkedReader(io.RawIOBase):
    """每次最多只吐 ``chunk`` 個位元組 —— 模擬真實 socket 的短讀。"""

    def __init__(self, data: bytes, chunk: int) -> None:
        self._data = data
        self._chunk = chunk
        self._at = 0

    def read(self, size: int = -1) -> bytes:
        want = len(self._data) - self._at if size < 0 else size
        take = min(want, self._chunk, len(self._data) - self._at)
        out = self._data[self._at:self._at + take]
        self._at += take
        return out


class _FakeHandler:
    def __init__(self, data: bytes, chunk: int, *, declared: int | None = None) -> None:
        self.headers = {"Content-Length": str(len(data) if declared is None else declared)}
        self.rfile = _ChunkedReader(data, chunk)


def test_a_large_body_arriving_in_pieces_is_assembled_whole() -> None:
    """分好幾次才送到的大檔要被拼完整，不得判成中斷。

    這是 PO 那本教科書踩到的那一格。
    """
    body = b"%PDF-1.7" + bytes(5_000_000)

    got = _upload_body(_FakeHandler(body, chunk=64 * 1024))

    assert got == body


def test_a_body_that_really_stops_early_is_still_refused() -> None:
    """真的少送了就照樣擋 —— 修好短讀不等於把這道檢查拆掉。

    沒有這一條，「連線真的斷了」會變成一份被截斷的 PDF 靜靜進收件匣，
    然後在解析階段炸得莫名其妙。
    """
    with pytest.raises(IntakeError) as exc:
        _upload_body(_FakeHandler(b"%PDF-1.7 short", chunk=4, declared=9999))

    assert "不完整" in str(exc.value)


def test_an_empty_body_is_still_refused() -> None:
    """沒有內容照樣擋（拖到資料夾時就是這一格）。"""
    with pytest.raises(IntakeError):
        _upload_body(_FakeHandler(b"", chunk=8))
