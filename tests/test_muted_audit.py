"""後處理拿掉了什麼 —— 兩條備份路徑都要算。

**這支存在的理由是一次真實的量錯。** 2026-08-21 判讀 `XVK63KEV` 的
「參考文獻消音比例 32.4%」時，第一版腳本只數 `_pp_original_text`，量出
「拿掉 10.8%」，跟體檢表記的 32.4% 對不上。差額是 43 條參考文獻 ——
MinerU 把它們放在 `list_items`，備份欄位是 `_pp_original_list_items`。

**帳對不上時，錯的通常是量法不是母體。** 少算的那條路不會報錯，只會給出一個
看起來合理的小數字，而小數字會讓人下「沒事」的結論 —— 比大數字危險。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "muted-audit.py"

_spec = importlib.util.spec_from_file_location("muted_audit", SCRIPT)
assert _spec and _spec.loader
ma = importlib.util.module_from_spec(_spec)
sys.modules["muted_audit"] = ma
_spec.loader.exec_module(ma)


def _bundle(tmp_path: Path, items: list[dict]) -> Path:
    raw = tmp_path / "x.pdf.mineru_raw"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "content_list.json").write_text(
        json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return raw


def test_reference_lists_are_counted_not_skipped(tmp_path: Path) -> None:
    """**本檔最重要的一條。** 參考文獻在 `list_items`，不在 `text`。

    只數 `_pp_original_text` 的話，這份會量出「拿掉 5 字」而不是「拿掉 65 字」。
    """
    raw = _bundle(tmp_path, [
        {"type": "text", "page_idx": 0, "text": "正文" * 10},          # 留著的
        {"type": "header", "page_idx": 0, "text": "",
         "_pp_original_text": "頁首abc"},                              # 5 字
        {"type": "list", "sub_type": "ref_text", "page_idx": 1, "list_items": [],
         "_pp_original_list_items": ["參考文獻" * 5, "參考文獻" * 5,
                                     "參考文獻" * 5]},                  # 60 字、3 條
    ])
    got = ma.audit_doc(raw)
    assert got["gone_chars"] == 65, f"少算了：{got['gone_chars']}"
    assert got["list_entries"] == 3, "參考文獻條數要數得出來"
    assert got["total_chars"] == 65 + 20
    assert 0.76 < got["ratio"] < 0.77   # 65/85


def test_rewritten_items_are_not_counted_as_removed(tmp_path: Path) -> None:
    """有備份但現值還在 ＝ 改寫（LaTeX 正規化／人工文字修補），不是拿掉。

    算進去的話，每份數學密集的文件都會看起來像被刪掉一大半。
    """
    raw = _bundle(tmp_path, [
        {"type": "equation", "page_idx": 0, "text": "$$ x = 1 $$",
         "_pp_original_text": "$$\\nx = 1$$"},
        {"type": "text", "page_idx": 0, "text": "留著的正文"},
    ])
    got = ma.audit_doc(raw)
    assert got["gone_chars"] == 0, "改寫被誤算成拿掉"
    assert got["removed"] == []


def test_kinds_break_down_what_was_removed(tmp_path: Path) -> None:
    """只給百分比不夠 —— 判斷「消對了沒有」要看拿掉的是哪一種東西。"""
    raw = _bundle(tmp_path, [
        {"type": "header", "page_idx": 0, "text": "", "_pp_original_text": "書眉"},
        {"type": "header", "page_idx": 1, "text": "", "_pp_original_text": "書眉"},
        {"type": "footer", "page_idx": 0, "text": "", "_pp_original_text": "頁尾"},
        {"type": "text", "page_idx": 0, "text": "正文"},
    ])
    got = ma.audit_doc(raw)
    assert got["kinds"] == {"header/-": 2, "footer/-": 1}


def test_missing_content_list_is_an_error_not_a_clean_bill(tmp_path: Path) -> None:
    """解析沒完成的 bundle 不得回「拿掉 0%」—— 那跟「乾淨」長得一樣。"""
    raw = tmp_path / "y.pdf.mineru_raw"
    raw.mkdir()
    assert "error" in ma.audit_doc(raw)
