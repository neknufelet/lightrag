"""DocContext：一份文件的所有相關檔案，以及它們之間該有的一致性。

來源 PDF 在掃描前位於 `inputs/<workspace>/`，LightRAG 歸檔後與 bundle 一起位於
`work/parsed/`。唯一可靠的識別是 manifest 記錄的 source_content_hash；用內容定址
找檔案，找不到就停，不猜。
"""
from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mineru_common import KNOWN_TYPES, read_json  # noqa: E402

from pp.rules import empty_table  # noqa: E402


class DocContextError(RuntimeError):
    pass


# 頁面尺寸容差，單位是 PDF 點。**判準只有這一份**，`compat-check` 的 A-14 從這裡
# import ——兩處各寫一份同義判準，只要有人改一邊就會靜靜地不一致（同 oracle.py
# 的 `force_reparse_is_on`）。
#
# 為什麼是 2 點：原本的判準是「所有頁尺寸必須完全相同」，而 2017 那篇 22 頁裡
# 前 14 頁是 594×842、後 8 頁是 595×842 —— **差 1 點**，是同一張 A4 的捨入差，
# bbox 換算的誤差 0.2%，實務上無害。但它讓那篇文件從 2026-08-08 起天天紅燈。
#
# 容差不能再放大：真正要擋的是「A4 混 A3」那種（595×842 vs 842×1191，差好幾百點）
# 與「A4 混 Letter」（差 17×50 點）。2 點乾淨地把「同一張紙的捨入」與「真的不同
# 尺寸」分開，而且**不是為了讓某一篇過關而挑的數字**——挑 1 點也能過，挑 2 點是
# 為了容納下一份可能差 2 點的文件而不必再改一次。
PAGE_SIZE_TOLERANCE_PT = 2.0


def page_size_spread(sizes: list[tuple[float, float]]) -> tuple[float, float]:
    """一份文件裡各頁尺寸的最大差距 `(寬的差, 高的差)`。空清單回 (0, 0)。"""
    if not sizes:
        return (0.0, 0.0)
    widths = [float(w) for w, _ in sizes]
    heights = [float(h) for _, h in sizes]
    return (max(widths) - min(widths), max(heights) - min(heights))


def page_sizes_compatible(sizes: list[tuple[float, float]]) -> bool:
    """各頁尺寸是否落在容差內 —— 也就是 bbox 換算可不可以只用一組尺寸。"""
    dw, dh = page_size_spread(sizes)
    return dw <= PAGE_SIZE_TOLERANCE_PT and dh <= PAGE_SIZE_TOLERANCE_PT


def _will_be_cropped(item: dict) -> bool:
    """這個項目會不會真的被裁圖 —— 也就是它的 bbox 會不會被換算成 PDF 點。

    **只有「需要修補的表格」會。** `empty_table.plan()` 是唯一會叫
    `bbox_to_points()` 的地方（`pp/apply.py`），而它只對 `classify() != OK`
    的表格算座標；判定 OK 的表連進都不會進修補名單。

    圖用的是 MinerU 自己抽好的檔案、chart 依裁決只登記不處理、方程式那條路
    （`eq-check.py`）是診斷工具不在主流程上 —— 後者是既有的已知限制，沒有改變。

    ⚠ **判準因此會隨解析結果變動。** 鐵則第 8 條：重解析同一份 PDF，MinerU 對
    表格的辨識不可重現，今天判 OK 的表明天可能變成空殼。那不是規則不穩 ——
    它忠實回答「**現在這份 bundle** 需不需要裁圖」，而 preflight 與 A-14 每次都
    拿當下的 `content_list.json` 重算，所以不會過期。
    """
    if item.get("type") != "table":
        return False
    return empty_table.classify(item) is not empty_table.TableClass.OK


def reference_page_size(sizes: list[tuple[float, float]]) -> tuple[float, float]:
    """換算 bbox 的基準尺寸 ＝ **出現最多次的那一組**，不是第一頁的。

    一份 22 頁的文件若 14 頁是 594×842、8 頁是 595×842，用多數那組誤差最小。
    """
    counts: dict[tuple[float, float], int] = {}
    for size in sizes:
        counts[size] = counts.get(size, 0) + 1
    return max(counts.items(), key=lambda kv: (kv[1], -sizes.index(kv[0])))[0]


def cropping_pages_mismatch(
    sizes: list[tuple[float, float]],
    items: list[dict],
    reference: tuple[float, float],
) -> list[int]:
    """要裁的東西落在哪幾頁、而那幾頁與基準尺寸不相容。回頁碼清單，空的代表沒問題。

    **判準的重點在這裡：頁面尺寸只影響「裁下來的框畫在哪」。**
    「這張表要不要修補」由 `empty_table.classify()` 決定，它完全不看頁面尺寸。
    所以離群的那一頁上沒有表格時，換算根本不會發生在它身上。

    ⚠ **每次都對著當下的 bundle 重算，所以不會過期。** 鐵則第 8 條：重解析同一份
    PDF，MinerU 對表格的辨識不可重現 —— 今天沒有表的頁，重抽後可能長出一張。
    但 preflight 與 A-14 都是拿現在的 `content_list.json` 判的，那一刻就會擋下來。
    """
    bad: list[int] = []
    for item in items:
        if not _will_be_cropped(item):
            continue
        page = item.get("page_idx")
        if not isinstance(page, int) or not 0 <= page < len(sizes):
            continue
        if not page_sizes_compatible([sizes[page], reference]) and page not in bad:
            bad.append(page)
    return sorted(bad)


# ⚠ **`effective_page_sizes()` 已於 2026-08-10 刪除**（藍桶第 2 條：刪除必須明確說明）。
#
# 它回答的是「整份（或扣掉封面的內頁）尺寸一致嗎」，判準換成
# `reference_page_size()` + `cropping_pages_mismatch()` 之後就沒有呼叫端了。
#
# **留著它會是第二份判準。** 「同一件事兩個地方」是本專案踩過五次的形狀，
# 而這條規則本身就是因為「例外只加了一邊」出過事（2026-08-09）才被抽成共用函式的。
#
# 它做的兩件事都沒有消失，只是換了形狀：
#   「多數尺寸當基準」  → `reference_page_size()`
#   「封面頁例外」      → 被通則吸收：封面不過就是「離群的那一頁」，
#                        上面沒有表格就不影響換算，有表格照樣擋


@dataclass
class DocContext:
    raw_dir: Path
    source_dir: Path | None = None

    # ---- 基本 ----

    @property
    def doc_name(self) -> str:
        return self.raw_dir.name.removesuffix(".mineru_raw")

    @property
    def content_list_path(self) -> Path:
        return self.raw_dir / "content_list.json"

    @property
    def manifest_path(self) -> Path:
        return self.raw_dir / "_manifest.json"

    @cached_property
    def manifest(self) -> dict:
        return read_json(self.manifest_path)

    @cached_property
    def items(self) -> list[dict]:
        return read_json(self.content_list_path)

    @cached_property
    def layout(self) -> dict:
        return read_json(self.raw_dir / "layout.json")

    # ---- 頁面幾何 ----

    @cached_property
    def page_size(self) -> tuple[float, float]:
        """PDF 點座標的頁面尺寸。

        基準是**出現最多次的那一組**，不是第一頁的：一份 22 頁的文件若 14 頁是
        594×842、8 頁是 595×842，用多數那組會讓換算誤差最小。

        **擋的判準是「要裁的那幾頁與基準相容嗎」，不是「整份一致嗎」**
        （2026-08-10 改）。尺寸只影響 `bbox_to_points()` 把正規化座標換成 PDF 點，
        而那只發生在表格上；離群的頁上沒有表格時，換算根本不會發生在它身上。

        舊判準要求整份（或內頁）一致 —— 而老掃描件的頁面尺寸**本來就不可能一致**，
        那是達不到的條件。2026-08-10 實測四份被它擋下的：只有一份（表格就落在
        橫向頁上）是真的有問題，其餘三份連一個接觸點都沒有。

        ⚠ **容差沒有動**，2 點還是 2 點；動的是「哪些頁要算進來」。
        ⚠ **封面頁例外因此被吸收掉了** —— 它本來就是「離群那頁沒東西要裁」的特例。
           封面上有表格照樣擋，那條測試仍然綠。
        """
        raw = [tuple(p.get("page_size") or ()) for p in self.layout["pdf_info"]]
        sizes = [(float(w), float(h)) for w, h in raw if len((w, h)) == 2]
        if not sizes:
            raise DocContextError(f"{self.doc_name}：layout.json 沒有 page_size")
        # 判準在模組層 —— `compat-check` 的 A-14 用同一組函式，**不各寫一份**。
        # 2026-08-09 犯過：例外只加在這裡，A-14 還用舊判準，同一份文件
        # 「解析放行、檢查說不行」，而且是索引完了才被判失敗。
        reference = reference_page_size(sizes)
        bad_pages = cropping_pages_mismatch(sizes, self.items, reference)
        if bad_pages:
            details = "、".join(f"第 {p} 頁 {sizes[p]}" for p in bad_pages[:5])
            dw, dh = page_size_spread([reference, *(sizes[p] for p in bad_pages)])
            raise DocContextError(
                f"{self.doc_name}：頁面尺寸不一致 —— 有表格落在與基準尺寸"
                f"{reference} 不相容的頁上（{details}；寬差 {dw:g}、高差 {dh:g} 點，"
                f"容差 {PAGE_SIZE_TOLERANCE_PT:g}）。裁圖會用基準尺寸換算那幾頁的 "
                "bbox，裁出來的位置是錯的，而圖看起來還是像一張表")
        return reference

    @cached_property
    def n_pages(self) -> int:
        return len(self.layout["pdf_info"])

    def assert_layout_aligned(self) -> None:
        """layout 的 page_idx 必須等於陣列位置。整體位移時 bbox 仍會命中「一張表」，
        只是命中隔壁頁的 —— 書眉每頁幾何相同，錯頁比對照樣通過。"""
        bad = [k for k, p in enumerate(self.layout["pdf_info"]) if p.get("page_idx") != k]
        if bad:
            raise DocContextError(f"{self.doc_name}：layout 頁序錯位於 {bad[:5]}")

    # ---- 來源 PDF：內容定址 ----

    @cached_property
    def source_pdf(self) -> Path:
        want = self.manifest["source_content_hash"]
        cands = []
        if self.source_dir is not None:
            cands.append(self.source_dir / self.doc_name)
        cands.extend([
            self.raw_dir.parent / self.doc_name,        # LightRAG 歸檔的來源 PDF
            *sorted(self.raw_dir.glob("*_origin.pdf")),  # MinerU 回傳的副本
        ])
        for c in cands:
            if c.is_file():
                h = "sha256:" + hashlib.sha256(c.read_bytes()).hexdigest()
                if h == want:
                    return c
        raise DocContextError(
            f"{self.doc_name}：{len(cands)} 個候選都對不上 source_content_hash。"
            "來源 PDF 會被 archive_source 搬動，不得依賴固定路徑。"
        )

    # ---- 一致性 ----

    def assert_known_types(self) -> None:
        types = {i.get("type") for i in self.items}
        unknown = types - KNOWN_TYPES
        if unknown:
            raise DocContextError(
                f"{self.doc_name}：未知的項目型別 {sorted(unknown)} —— "
                "版面型態超出規則涵蓋範圍，過濾與修補的判斷可能不適用"
            )

    def preflight(self) -> None:
        """動任何東西之前必跑。任何一項不成立就丟例外，讓呼叫端擋下這份文件。"""
        for p in (self.content_list_path, self.manifest_path, self.raw_dir / "layout.json"):
            if not p.is_file():
                raise DocContextError(f"{self.doc_name}：缺少 {p.name}")
        self.assert_layout_aligned()
        self.assert_known_types()
        _ = self.page_size
        _ = self.source_pdf
