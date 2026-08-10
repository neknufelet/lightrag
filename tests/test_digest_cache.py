"""選片掃描的雜湊快取：算過的不重算，動過的一定重算。

**為什麼需要**：畫面每 3 秒問一次 `/api/state`，而 `state()` 每一次都把
`library/`、`work/parsed/`、`inputs/`、收件匣底下**每一個 PDF 重新雜湊一遍**
（`CandidateScanner._known_hashes`）。2026-08-10 實測 257 份文件、400 多個 PDF：
`/health` 0.001 秒、`/api/state` **5.1–5.5 秒**，而且跟檔案總數成正比。

**內容定址本身是對的**——同一份文件改了檔名還認得出來，那是這個判準存在的理由。
錯的只是每次都重算。

⚠ **快取只給選片掃描用。** `_sha256()` 本身不加快取：另外十一個呼叫點是拿它來
驗證「剛複製進去的檔案內容對不對」「即將刪掉的檔案是不是我以為的那個」——
那些地方吃快取等於把**驗證**變成**假設**，而這個專案一路在防的就是那個。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from intake import DigestCache, _sha256  # noqa: E402


def test_a_file_is_hashed_once_and_then_remembered(tmp_path: Path) -> None:
    """算過就記住 —— 這條是整個改動的目的。"""
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.7 content")
    cache = DigestCache()

    first = cache.digest(pdf)
    second = cache.digest(pdf)

    assert first == second == _sha256(pdf)
    assert cache.computed == 1, f"同一個沒動過的檔案算了 {cache.computed} 次"


def test_a_changed_file_is_hashed_again(tmp_path: Path) -> None:
    """**控制組。** 沒有這條的話，「永遠回第一次的值」也會通過上面那支 ——
    而那會讓改過的檔案被當成原來那份，是比慢更糟的失敗。
    """
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.7 first")
    cache = DigestCache()
    before = cache.digest(pdf)

    pdf.write_bytes(b"%PDF-1.7 second and longer")
    after = cache.digest(pdf)

    assert after != before, "檔案改了卻回舊的雜湊"
    assert after == _sha256(pdf)
    assert cache.computed == 2


def test_verification_never_goes_through_the_cache(tmp_path: Path) -> None:
    """`_sha256()` 必須是**真的讀檔**，不吃快取。

    快取的鍵是「大小＋修改時間」，所以內容變了但那兩項都沒變時它會回舊值。
    這裡刻意製造那個情境：**快取回舊的（這是它的已知限制，要看得見），
    而 `_sha256()` 回新的**。

    十一個驗證呼叫點（複製進暫存區後比對、刪除前比對、放行前比對來源 PDF）
    全部依賴後者。它們吃快取的話，「驗證過了」就變成「假設沒變」。
    """
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"AAAA")
    stat = pdf.stat()
    cache = DigestCache()
    cached_before = cache.digest(pdf)

    pdf.write_bytes(b"BBBB")                       # 同樣長度
    os.utime(pdf, ns=(stat.st_atime_ns, stat.st_mtime_ns))   # 時間戳也復原

    assert cache.digest(pdf) == cached_before, (
        "快取的已知限制變了 —— 這條測試在描述現況，不是在要求它變舊")
    assert _sha256(pdf) != cached_before, (
        "`_sha256` 被加上快取了 —— 驗證路徑會因此變成假設")
