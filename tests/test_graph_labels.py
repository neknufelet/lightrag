"""位置標記樣式：確定可刪的抓得到，真概念不誤傷，而且只有一份清單。

**測資全部是 2026-08-09 從正式庫 `acoustics_v2` 實際撈出來的節點名**，不是想像的。
當天圖譜裡有 66 個這種節點，逐一看過之後分成兩組：39 個確定可刪、27 個待裁定。

這支測試守三件事：

  1. 報告第八節提的正規式漏掉的兩種（羅馬數字、`reference` 字首）現在抓得到
  2. 真的聲學概念不會被誤傷 —— 誤刪是不可逆的
  3. 量測、清除、警報三處**共用同一份清單**（SSOT）
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from pp.graph_labels import (  # noqa: E402
    ALL_RE,
    CERTAIN_PREFIXES,
    SUSPECT_PREFIXES,
    classify,
)

# ── 2026-08-09 正式庫實測：確定可刪那 39 個的代表 ──────────────────────────
CERTAIN_NAMES = [
    "equation 22", "equation 8a", "equation 3", "Equation 10",
    "eq. 7",
    "figure 3", "figure 4f", "figure 5a", "Figure 5",
    "table 1", "table 16",
    # ↓ 報告提的 `[\d.]+` 抓不到這一個（羅馬數字），是本輪補上的
    "table i",
    # ↓ 報告的字首清單沒有 `reference`，也是本輪補上的
    "reference 1",
    # ↓ 小數點分節（教科書章節的編號方式）。第一版漏掉，清完 39 個之後才在
    #   向量表裡撈到 —— 12 個 `equation X.Y` 還活著。
    "equation 3.3", "equation 8.36", "equation 1.19",
    # ↓ 字母範圍。同一批漏網。
    "figure 5b-d", "figure 5e-g",
]

# ── 待裁定那 27 個的代表：PO 2026-08-09 裁決先不刪 ─────────────────────────
SUSPECT_NAMES = [
    "region i", "region II", "Region I", "region III",
    "zone iv", "Zone IV", "zone iii",
    "mode i", "mode ii",
    "model 1", "model 3",
    "part I", "part III",
]

# ── 不可誤傷：這些是真的聲學概念或一般名詞 ────────────────────────────────
#
# 判準是「字首後面沒有編號」。位置標記的本質是**指標**（指向文件某處），
# 而指標一定帶編號 —— 沒有編號的同一個字是概念。
INNOCENT_NAMES = [
    "Equation of State",
    "Helmholtz Resonator",
    "Acoustic Pressure",
    "Reflection Coefficient",
    "Section Modulus",
    "Modal Density",
    "Reference Impedance",
    "Table of Contents",
    "Figure of Merit",
    "Transfer Matrix Method",
    "Sound Absorption Coefficient",
    # ↓ 這三個是圖譜裡真實存在的節點，而且是**最危險的一組**：字首 `reference`
    #   在確定可刪清單裡，後面接的字又以 `i` 開頭 —— 而 `i` 是羅馬數字。
    #   樣式一旦寫鬆（例如尾巴允許後面還有東西），它們會被當成位置標記刪掉，
    #   而 `reference impedance` 是聲學的真概念。
    "reference impedance z0",
    "reference impedance z 0",
    "reference impedance Z_i",
]


@pytest.mark.parametrize("name", CERTAIN_NAMES)
def test_certain_names_are_deletable(name: str) -> None:
    assert classify(name) == "certain", f"{name!r} 應該是確定可刪"


@pytest.mark.parametrize("name", SUSPECT_NAMES)
def test_suspect_names_are_reported_not_deleted(name: str) -> None:
    """這一組**不可以**落進 certain —— 落進去就會被自動刪掉，而且不可逆。"""
    assert classify(name) == "suspect", f"{name!r} 應該只報不刪"


@pytest.mark.parametrize("name", INNOCENT_NAMES)
def test_real_concepts_are_never_matched(name: str) -> None:
    assert classify(name) is None, f"{name!r} 是真概念，不該被當成位置標記"


def test_roman_numerals_are_covered() -> None:
    """報告第八節的正規式是 `[\\d.]+[a-z]?`，抓不到羅馬數字。

    正式庫裡 `table i` 就是這樣漏掉的。這一條在的話，下次有人把樣式改回
    只認阿拉伯數字，測試會紅。
    """
    assert classify("table i") == "certain"
    assert classify("table iv") == "certain"
    assert classify("section III") == "certain"


def test_decimal_and_range_numbering_are_covered() -> None:
    """編號的四種寫法要全部涵蓋，缺一種就漏掉一整族。

    2026-08-09 實測：第一版只合併了「羅馬數字」那一半，清掉 39 個之後圖譜裡
    還活著 12 個 `equation X.Y`（教科書章節的編號）與 2 個 `figure 5b-d`。
    **少的那一種不會有錯誤訊息，只會安靜地留在圖譜裡。**
    """
    assert classify("equation 3.3") == "certain"      # 小數點分節
    assert classify("equation 8.36") == "certain"
    assert classify("figure 5b-d") == "certain"       # 字母範圍
    assert classify("equation 8a") == "certain"       # 單一字母
    assert classify("table i") == "certain"           # 羅馬數字
    assert classify("table 16") == "certain"          # 純數字


def test_buckets_do_not_overlap() -> None:
    """一個字首只能屬於一組。同時在兩組的話，`classify` 的結果取決於判斷順序，
    而那個順序是實作細節不是決定。"""
    both = set(CERTAIN_PREFIXES) & set(SUSPECT_PREFIXES)
    assert not both, f"這些字首同時在兩組：{sorted(both)}"


def test_graph_shape_uses_the_shared_pattern() -> None:
    """SSOT：量測端不得自己再寫一份字首清單。

    **為什麼要測這個**：量測與清除各留一份的話，清除端說「39 個都刪了」、
    量測端仍回報殘留，兩個數字說的不是同一件事而沒有任何東西會發現。
    2026-08-08 審核台六個洞就是這個形狀。
    """
    script = ROOT / "scripts" / "graph-shape.py"
    spec = importlib.util.spec_from_file_location("graph_shape", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.LABEL_RE == ALL_RE, "graph-shape.py 的樣式與 pp/graph_labels.py 不同"


def test_compat_check_alarm_uses_the_shared_pattern() -> None:
    """警報端也是同一份。斷言 A-33 直接 import `CERTAIN_RE`，不自己抄一份。"""
    source = (ROOT / "scripts" / "compat-check.py").read_text(encoding="utf-8")
    assert "from pp.graph_labels import CERTAIN_RE" in source
    assert "A-33" in source
