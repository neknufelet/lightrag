r"""來源登記：五類假報要歸位，而且**查不到的時候要退成 unknown 不是退成通過**。

2026-08-13 逐份核過，原本從檔名推論來源的兩條正規表達式五類全錯 ——
四類是假報方向（把同一本書當成兩篇獨立文獻，於是「兩篇都這樣寫」是假的）。
證據與逐類說明在 `scripts/source-map.py` 的檔頭。

**本檔的重點有兩半**：上半驗提案器把五類收攏（那是一次性的），
下半驗讀取器在**資料不齊**時的行為（那是永久的，而且是七個 bug 的共同形狀 ——
工具報「N 筆」而 N 的母體根本不是真的母體）。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

_spec = importlib.util.spec_from_file_location("source_map", ROOT / "scripts" / "source-map.py")
assert _spec and _spec.loader
sm = importlib.util.module_from_spec(_spec)
sys.modules["source_map"] = sm
_spec.loader.exec_module(sm)

from pp.sources import SourceMap  # noqa: E402

# 檔名全部取自 dker 上 `work/parsed` 的實際目錄名。
TWO_BOOKS_SAME_PREFIX = ["01405_5.5 The influence of unequal path lengths",
                         "01405_8.5 Amplitude Variation Along Rays"]
SPLIT_ACROSS_PREFIXES = ["01700_8 Measuring techniques in room acoustics", "02001_11.1 Loudspeakers"]
SPACE_VARIANT = ["2012 -Combined wave and ray based room acoustic simulations of small rooms_CH3",
                 "2012 - Combined wave and ray based room acoustic simulations of small rooms_CH10"]
HUMAN_ANNOTATION = ["2023 - Perception-of-room-modes_CH7",
                    "2023 - Perception-of-room-modes_Conclusions_CH9",
                    "2023 - Perception-of-room-modes_Control of Room Modes_CH5"]
HANDBOOK = ["C Equivalent Networks", "R Ultrasound Absorption in Solids"]


def _src(docs: list[str]) -> list[str | None]:
    guesses = sm.propose(docs)
    return [guesses[d][0] for d in docs]


# ── 提案器：五類 ────────────────────────────────────────────────────────────


def test_two_books_sharing_a_prefix_are_told_apart() -> None:
    """**唯一的少報方向。** 同一個編號前綴下是兩本不同的書，章號差 9 / 差 6。"""
    a, b = _src(TWO_BOOKS_SAME_PREFIX)
    assert a and b and a != b, (a, b)


def test_one_book_split_across_two_prefixes_is_rejoined() -> None:
    """同一本書被切到 `01xxx` 與 `02xxx` 兩段 —— 那是假報方向，要接回來。"""
    a, b = _src(SPLIT_ACROSS_PREFIXES)
    assert a == b and a is not None, (a, b)


def test_a_single_space_does_not_split_a_thesis() -> None:
    """`2012 -Combined` 與 `2012 - Combined` 差一個空格。"""
    a, b = _src(SPACE_VARIANT)
    assert a == b and a is not None, (a, b)


def test_human_annotations_in_the_filename_do_not_split_a_thesis() -> None:
    """檔名多一段人類註記（`_Conclusions`）不代表換了一本書。"""
    got = _src(HUMAN_ANNOTATION)
    assert len(set(got)) == 1 and got[0] is not None, got


def test_the_handbook_chapters_are_one_source() -> None:
    """單字母章號 A–R 是同一本手冊。**手冊跨章重複公式是常態，這組最會假報。**"""
    a, b = _src(HANDBOOK)
    assert a == b and a is not None, (a, b)


def test_a_supplement_is_left_for_a_human() -> None:
    """附件的正文是哪一篇，檔名對不上 —— **不猜**，留 unknown。"""
    assert _src(["41598_2017_5710_MOESM1_ESM"]) == [None]


def test_an_ordinary_paper_is_its_own_source() -> None:
    assert _src(["2025 - Differentiable Acoustic Radiance Transfer"]) == [
        "doc:2025 - Differentiable Acoustic Radiance Transfer"]


# ── 讀取器：資料不齊的時候 ──────────────────────────────────────────────────

_MAP = {"version": 1,
        "sources": {"book:x": {"label": "書 X", "same_work_as": ["book:y"]},
                    "book:y": {"label": "書 Y", "same_work_as": []}},
        "documents": {
            "clean": {"source": "book:x", "pdf_sha256": "sha256:aaa"},
            "merged": {"source": "book:y", "pdf_sha256": "sha256:bbb"},
            "swapped": {"source": "book:x", "pdf_sha256": "sha256:OLD"}}}
_HASHES = {"clean": "sha256:aaa", "merged": "sha256:bbb", "swapped": "sha256:NEW"}
CORPUS = ["clean", "merged", "swapped", "never-registered"]


def _loaded(tmp_path: Path) -> SourceMap:
    p = tmp_path / "source-map.json"
    p.write_text(json.dumps(_MAP, ensure_ascii=False), encoding="utf-8")
    return SourceMap.load(p)


def test_a_missing_map_means_all_unknown_not_all_fine(tmp_path: Path) -> None:
    """**這條是本檔最重要的一條。** 檔案不在＝全部 unknown，不是全部通過。"""
    smap = SourceMap.load(tmp_path / "does-not-exist.json")
    rec = smap.reconcile(CORPUS, _HASHES)
    assert rec.usable == 0 and rec.registered == 0
    assert all(smap.source_of(d) is None for d in CORPUS)


def test_querying_before_reconciling_returns_unknown(tmp_path: Path) -> None:
    """沒對帳就查，一律 unknown —— 忘了對帳不可以安靜地變成「全部可信」。"""
    smap = _loaded(tmp_path)
    assert smap.source_of("clean") is None
    smap.reconcile(CORPUS, _HASHES)
    assert smap.source_of("clean") == "book:y"      # x 併進 y


def test_a_swapped_pdf_falls_back_to_unknown(tmp_path: Path) -> None:
    """登記在、但檔案被換過 —— **不自動接受**，降 unknown 並列進對帳。"""
    smap = _loaded(tmp_path)
    rec = smap.reconcile(CORPUS, _HASHES)
    assert rec.hash_changed == ["swapped"]
    assert smap.source_of("swapped") is None


def test_an_unregistered_document_is_unknown_and_counted(tmp_path: Path) -> None:
    """沒登記的要被**數出來**，不是安靜跳過。"""
    smap = _loaded(tmp_path)
    rec = smap.reconcile(CORPUS, _HASHES)
    assert rec.unregistered == ["never-registered"]
    assert rec.corpus == 4 and rec.usable == 2
    assert smap.source_of("never-registered") is None


def test_human_declared_merges_are_transitive(tmp_path: Path) -> None:
    """`same_work_as` 做傳遞閉包 —— 這是**人明講的**，不是相似度算的。

    ⚠ `eq-dup` 的 Tier B 刻意不做傳遞閉包，兩者不衝突：相似度串起來會造出
    讀不了的假等價類，人工宣告不會。
    """
    smap = _loaded(tmp_path)
    smap.reconcile(CORPUS, _HASHES)
    assert smap.source_of("clean") == smap.source_of("merged")
