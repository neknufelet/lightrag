"""封面頁尺寸與內頁不同時的處置。

出版社常在論文前面蓋一張自己產生的封面。2026-08-09 進料 30 份遇到 3 份，形狀一致：
只有第 0 頁不同、內頁彼此一致。**這不是放寬容差** —— 容差 2 點是刻意的，要擋的是
內文頁之間混排（A4 混 Letter），那種會讓 bbox 換算安靜地錯。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from pp.docctx import DocContext, DocContextError  # noqa: E402


def _bundle(tmp_path: Path, sizes: list[tuple[float, float]],
            items: list[dict] | None = None) -> Path:
    raw = tmp_path / "doc.pdf.mineru_raw"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "layout.json").write_text(json.dumps(
        {"pdf_info": [{"page_size": list(s), "page_idx": i} for i, s in enumerate(sizes)]}),
        encoding="utf-8")
    (raw / "content_list.json").write_text(
        json.dumps(items if items is not None else []), encoding="utf-8")
    return raw


A4, LETTERISH = (595.0, 842.0), (612.0, 792.0)


def test_uniform_pages_are_unchanged(tmp_path: Path) -> None:
    ctx = DocContext(_bundle(tmp_path, [A4] * 5))
    assert ctx.page_size == A4


def test_a_differing_cover_page_is_allowed_and_body_size_wins(tmp_path: Path) -> None:
    """封面頁不同、內頁一致 → 放行，而且回傳的是**內頁**尺寸（裁圖要用那個）。"""
    ctx = DocContext(_bundle(tmp_path, [(595.0, 793.0), *[A4] * 4]))
    assert ctx.page_size == A4, "回傳了封面頁的尺寸 —— 內頁的裁圖會全部錯位"


def test_cover_may_differ_in_width_too(tmp_path: Path) -> None:
    """實測的第三份是封面 A4、內頁 Letter，寬高都不同。"""
    ctx = DocContext(_bundle(tmp_path, [A4, *[(612.0, 809.0)] * 18]))
    assert ctx.page_size == (612.0, 809.0)


def test_mixed_body_pages_are_still_rejected(tmp_path: Path) -> None:
    """**這條是例外不能吃掉的東西。** 內文頁之間混排照樣要擋 ——
    那才是 bbox 換算會安靜出錯的情況。"""
    with pytest.raises(DocContextError, match="頁面尺寸不一致"):
        _ = DocContext(_bundle(tmp_path, [A4, A4, LETTERISH, A4])).page_size


def test_a_table_on_the_cover_page_still_blocks(tmp_path: Path) -> None:
    """封面頁上有表格就不能放行：裁圖用內頁尺寸換算封面的 bbox，位置是錯的，
    而裁出來看起來還是像一張表 —— 正是這道檢查存在的理由。"""
    items = [{"type": "table", "page_idx": 0}, {"type": "text", "page_idx": 1}]
    with pytest.raises(DocContextError, match="封面頁"):
        _ = DocContext(_bundle(tmp_path, [(595.0, 793.0), *[A4] * 3], items)).page_size


def test_a_figure_on_the_cover_page_does_not_block(tmp_path: Path) -> None:
    """圖用的是 MinerU 自己抽好的檔案，不經過我們的 bbox 換算，所以不擋。
    實測那三份的第 0 頁都只有一張圖。"""
    items = [{"type": "image", "page_idx": 0}, {"type": "text", "page_idx": 0}]
    ctx = DocContext(_bundle(tmp_path, [(595.0, 793.0), *[A4] * 3], items))
    assert ctx.page_size == A4


def test_the_contract_check_uses_the_same_judgement() -> None:
    """`compat-check` 的 A-14 與解析時要用**同一份**判準。

    2026-08-09 犯過：封面頁例外只加在 `DocContext.page_size` 裡，A-14 還用舊的
    `page_sizes_compatible` —— 於是同一份文件「解析放行、契約檢查說不行」，
    而且是**文件索引完了才被判失敗**（intake 在放行後跑 compat-check）。
    A-14 的註解本來就寫著「判準從 pp/docctx.py import，不在這裡再寫一份」，
    抄本沒有出現 —— 漂掉的是**例外只加了一邊**。

    讀原始碼而不是 import：`compat-check.py` 載入時會讀 `.env`，coder 上沒有。
    """
    src = (ROOT / "scripts" / "compat-check.py").read_text(encoding="utf-8")
    assert "effective_page_sizes" in src, "A-14 沒有用共用判準"
    assert "size_ok = page_sizes_compatible(" not in src, (
        "A-14 還在用不含封面頁例外的舊判準 —— 會跟解析時不一致")
