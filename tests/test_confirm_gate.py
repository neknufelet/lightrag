"""沒確認的不准往下走（PO 2026-08-17 第二條的下半）。

2026-08-18 實際發生：PO 從 Zotero 丟一篇進來，它**一路走到抽取**，中間沒有
任何地方停下來問他。錢花在一個要被刪掉的舊庫上。

⚠ 這一層只回答「該不該擋、擋的理由是什麼」，不碰檔案、不動狀態機。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from pp.confirm_gate import hold_reason  # noqa: E402


def test_a_document_with_things_to_confirm_waits_for_you() -> None:
    """有東西要人看、又還沒看 → 擋下來，而且**講得出理由**。

    沒有理由的話，畫面上只會是一份文件莫名其妙卡住 —— 這個碼庫記過同型的病
    （被擋掉的請求沒寫下理由，害我連猜兩次都錯）。
    """
    reason = hold_reason(pending=3, confirmed=False)

    assert reason
    assert "3" in reason, "要講出還有幾項"


def test_a_document_you_already_confirmed_goes_through() -> None:
    """確認過就放行 —— 這就是「確認一份、放行一份」。"""
    assert hold_reason(pending=3, confirmed=True) == ""


def test_a_document_with_nothing_to_confirm_is_never_held() -> None:
    """規則全部有把握的文件不該卡住等人。

    **多數乾淨的文件本來就沒有要確認的**，擋它們等於把整條線停掉。
    """
    assert hold_reason(pending=0, confirmed=False) == ""


def test_the_reason_says_what_to_do_not_just_what_happened() -> None:
    """理由要告訴人**怎麼往下走**，不是只說「被擋了」。

    只說被擋的話，人得自己猜要去哪裡按什麼。
    """
    reason = hold_reason(pending=1, confirmed=False)

    assert "確認" in reason
