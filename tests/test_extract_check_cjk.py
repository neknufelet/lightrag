r"""接地檢查對中文語料是壞的（2026-08-12 抓到）。

正規化用 `[^a-z0-9]` 把「不是英數字」的全換成空白，**中文整串被抹成空字串**：

    norm("微穿孔板") = ''

於是庫裡唯一那份中文文獻（`2025 - Recent advancements in sound-absorbing
materials`）233 個實體裡 **95 個被判成「模型編出來的」**，而 `微穿孔板`
用 SQL 查得到就在原文裡。**表上那面紅燈在說謊。**

⚠ 這是同一個形狀今天第三次出現：中文文獻「搜不到」、中文題「檢索差 63–86%」、
中文實體「幻覺」—— 全部是量測方法造成的。這個庫的檢查工具都是為英文語料寫的。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

_spec = importlib.util.spec_from_file_location(
    "extract_check", ROOT / "scripts" / "extract-check.py")
assert _spec and _spec.loader
ec = importlib.util.module_from_spec(_spec)
sys.modules["extract_check"] = ec
_spec.loader.exec_module(ec)

# 取自 dker 上那份文件真正的 chunk 原文（2026-08-12 用 SQL 撈的）。
REAL_CHUNK = (
    "用于吸声的常见共振器构型包括法布里佩罗共振器、亥姆霍兹共振器和薄膜型共振器，"
    "如图 2(a) 所示．微穿孔板共振结构通过热传导-黏滞效应耗散声能．"
)


def test_a_chinese_entity_that_is_in_the_source_is_grounded() -> None:
    """`微穿孔板` 就在原文裡 —— 不能判成幻覺。"""
    assert ec.grounded("微穿孔板", REAL_CHUNK)


def test_a_chinese_entity_that_is_not_in_the_source_is_not_grounded() -> None:
    """**控制組，而且是最重要的一條。**

    修法不能是「中文一律放行」—— 那樣接地檢查對中文語料就等於沒有，
    而它存在的理由正是抓憑空捏造的實體。
    """
    assert not ec.grounded("聲子晶體能隙", REAL_CHUNK)


def test_normalisation_no_longer_wipes_chinese() -> None:
    assert ec.norm("微穿孔板") != ""


def test_a_two_character_chinese_entity_still_works() -> None:
    """短詞不能因為「詞太短就跳過」而變成永遠通過。

    `grounded` 的逐詞退路只看長度 > 2 的詞；中文兩個字就是一個完整的詞，
    落在那個門檻之下 —— 要走整串比對那條路。
    """
    assert ec.grounded("声能", REAL_CHUNK)
    assert not ec.grounded("雷射", REAL_CHUNK)


def test_english_behaviour_is_unchanged() -> None:
    """**控制組：不能為了修中文而動到英文那半。**

    這兩條是 `norm` 與 `grounded` 的說明裡寫死的血淚 ——
    變音符號要折疊（`Michał Raczyński` → `Michal Raczynski`），
    合併命名要走逐詞退路（`Orifice Partition Impedance Z_Mi`）。
    """
    assert ec.grounded("Michal Raczynski", "co-authored with Michał Raczyński in 2019")
    assert ec.grounded("Orifice Partition Impedance Z_Mi",
                       "the orifice impedance Z_Mi across the partition")
    assert not ec.grounded("Fabry Perot resonator", "the Helmholtz resonator neck")


def test_a_mixed_chinese_and_english_entity_needs_both_halves() -> None:
    """中英混寫的實體，兩半都要在原文裡才算接得回去。"""
    assert not ec.grounded("微穿孔板 metasurface", REAL_CHUNK)
