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


def test_a_body_page_that_differs_blocks_only_when_it_carries_a_table(
    tmp_path: Path,
) -> None:
    """**判準從「整份一致」改成「要裁的那幾頁一致」（2026-08-10）。**

    頁面尺寸只影響一件事：`bbox_to_points()` 把正規化座標換成 PDF 點，
    而那只發生在**要裁的表格**上（`empty_table.plan`）。「這張表要不要修補」
    的判定完全不看頁面尺寸。所以離群的那一頁上沒有表格時，換算根本不會發生。

    舊判準要求整份（或內頁）一致，而老掃描件的頁面尺寸**本來就不可能一致** ——
    那是一個達不到的條件，把無害的文件擋在門外。2026-08-10 實測四份：
    只有一份（表格就在橫向頁上）是真的有問題。

    ⚠ **不是放寬容差。** 2 點的容差沒有動，動的是「哪些頁要算進來」。
    """
    sizes = [A4, A4, LETTERISH, A4]
    # 表格在第 1 頁（尺寸與基準相同）—— 離群的第 2 頁上沒有東西要裁
    ok = DocContext(_bundle(tmp_path, sizes, [{"type": "table", "page_idx": 1}]))
    assert ok.page_size == A4

    # 表格就落在離群的那一頁 —— 這才是會安靜裁錯的情況
    with pytest.raises(DocContextError, match="頁面尺寸"):
        _ = DocContext(_bundle(tmp_path, sizes,
                               [{"type": "table", "page_idx": 2}])).page_size


def test_an_old_scan_with_no_tables_gets_through(tmp_path: Path) -> None:
    """1986 那份的形狀：26 頁幾乎每頁尺寸都不同，但**一張表都沒有**。

    掃描件每頁歪一點是常態。沒有表格就沒有 bbox 換算，整份文件與這條規則
    沒有任何接觸點 —— 擋它等於用一個達不到的條件把文件關在門外。
    """
    sizes = [(607.0 + i, 859.0 + i // 3) for i in range(26)]
    items = [{"type": "chart", "page_idx": 3}, {"type": "text", "page_idx": 5}]
    ctx = DocContext(_bundle(tmp_path, sizes, items))
    assert ctx.page_size in sizes


def test_a_good_table_on_a_rotated_page_does_not_block(tmp_path: Path) -> None:
    """**判準再收一格（2026-08-10）：問的是「那張表需要裁圖嗎」，不是「那頁有表格嗎」。**

    2017 那份的實況：第 6 頁是橫向頁、上面就是 Table 1，但 MinerU 已經把整張表
    抽出來了（五種 liner 一列不少、公式都在），`classify()` 判定 **OK**。
    OK 的表不會進修補名單、不會被裁圖 —— **這份文件從頭到尾不會發生一次 bbox 換算**。

    擋它等於把一篇論文永遠關在庫外，而危害是零。

    ⚠ 代價：判準會**隨解析結果變動**。同一份文件重抽之後可能從「過」變成「擋」
    （鐵則第 8 條：MinerU 對表格的辨識不可重現）。那不是規則不穩 —— 它忠實反映
    「現在這份 bundle 需不需要裁圖」，而 preflight 與 A-14 每次都拿當下的
    content_list 重算，所以不會過期。
    """
    portrait, landscape = (544.0, 742.0), (742.0, 544.0)
    sizes = [*[portrait] * 6, landscape, *[portrait] * 10]
    good = {"type": "table", "page_idx": 6,
            "table_body": "<table><tr><td>Liner</td><td>Sketch</td></tr>"
                          "<tr><td>Single degree of freedom (SDOF)</td>"
                          "<td>impedance model with real content</td></tr></table>"}
    ctx = DocContext(_bundle(tmp_path, sizes, [good]))
    assert ctx.page_size == portrait


def test_a_rotated_page_carrying_a_table_is_still_blocked(tmp_path: Path) -> None:
    """2017 那份的形狀：整份直式，其中一頁是**橫向**（同尺寸轉 90 度），
    而那一頁上就有一張表。

    **這是控制組。** 沒有它的話，上面兩條可以靠「一律放行」通過 —— 而那正是
    這道檢查存在的理由：裁出來的框完全不對，圖看起來還是像一張表。
    """
    portrait, landscape = (544.0, 742.0), (742.0, 544.0)
    sizes = [*[portrait] * 6, landscape, *[portrait] * 10]
    with pytest.raises(DocContextError, match="頁面尺寸"):
        _ = DocContext(_bundle(tmp_path, sizes,
                               [{"type": "table", "page_idx": 6}])).page_size


def test_a_table_on_the_cover_page_still_blocks(tmp_path: Path) -> None:
    """封面頁上有表格就不能放行：裁圖用內頁尺寸換算封面的 bbox，位置是錯的，
    而裁出來看起來還是像一張表 —— 正是這道檢查存在的理由。

    ⚠ 2026-08-10：**行為沒變，訊息變了。** 「封面頁例外」原本是一條獨立的特例，
    改成「要裁的那幾頁要相容」之後它被通則吸收掉了 —— 封面頁不過就是「離群的
    那一頁」的一種。所以這裡不再比對「封面頁」三個字，改成比對它真正該說的事：
    **第 0 頁上有表格而那一頁尺寸不相容**。
    """
    items = [{"type": "table", "page_idx": 0}, {"type": "text", "page_idx": 1}]
    with pytest.raises(DocContextError, match="第 0 頁"):
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

    2026-08-10 判準又動了一次（改成「要裁的那幾頁與基準相容」），**兩邊照樣一起改**
    —— 這條測試的意圖沒變，只是要比對的名字換了。

    讀原始碼而不是 import：`compat-check.py` 載入時會讀 `.env`，coder 上沒有。
    """
    src = (ROOT / "scripts" / "compat-check.py").read_text(encoding="utf-8")
    assert "cropping_pages_mismatch(" in src, "A-14 沒有用共用判準"
    assert "reference_page_size(" in src, "A-14 沒有用共用的基準尺寸"
    assert "size_ok = page_sizes_compatible(" not in src, (
        "A-14 還在用「整份一致」的舊判準 —— 會跟解析時不一致")
