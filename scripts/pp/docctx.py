"""DocContext：一份文件的所有相關檔案，以及它們之間該有的一致性。

來源 PDF 在掃描前位於 `inputs/<workspace>/`，LightRAG 歸檔後與 bundle 一起位於
`work/parsed/`。唯一可靠的識別是 manifest 記錄的 source_content_hash；用內容定址
找檔案，找不到就停，不猜。
"""
from __future__ import annotations

import hashlib
import sys
from collections import Counter
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mineru_common import KNOWN_TYPES, read_json  # noqa: E402


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

        尺寸**混雜**時 bbox 換算會錯，而且錯得很安靜（裁出來的圖看起來像張表，
        只是位置不對）—— 所以要擋。但判準是「落在 `PAGE_SIZE_TOLERANCE_PT` 之內」
        而不是「完全相同」：同一份 PDF 的各頁常有 1 點的捨入差，那不影響換算。

        回傳**最常見的那組尺寸**，不是第一頁的。一份 22 頁的文件若 14 頁是
        594×842、8 頁是 595×842，用多數那組會讓換算誤差最小。
        """
        raw = [tuple(p.get("page_size") or ()) for p in self.layout["pdf_info"]]
        sizes = [(float(w), float(h)) for w, h in raw if len((w, h)) == 2]
        if not sizes:
            raise DocContextError(f"{self.doc_name}：layout.json 沒有 page_size")
        if page_sizes_compatible(sizes):
            return Counter(sizes).most_common(1)[0][0]

        # ── 封面頁例外 ────────────────────────────────────────────────
        # 出版社常在論文前面蓋一張自己產生的封面，紙張跟內頁不一樣。
        # 2026-08-09 進料 30 份遇到 3 份，形狀完全一致：**只有第 0 頁不同、
        # 內頁彼此一致**（595×793/595×841、612×809/612×792、595×842/612×809）。
        #
        # 這不是放寬容差 —— 容差 2 點是刻意的，要擋的是 A4 混 Letter 那種
        # **內文頁之間**混排。這裡加的是一個**有訊號的例外**：分界剛好在第 0 頁。
        #
        # ⚠ 但仍然要擋一種情況：第 0 頁上有表格。裁圖是拿 `page_size`（＝內頁尺寸）
        # 換算 bbox 的，封面頁的表格會被用錯的尺寸裁 —— 裁出來看起來還是像一張表，
        # 只是位置不對，而那正是這道檢查存在的理由（安靜地錯）。
        # ⚠ 已知限制：`eq-check.py` 會裁方程式，它對封面頁上的方程式同樣會錯。
        # 封面頁通常沒有方程式，而 eq-check 是診斷工具不在主流程上，所以不擋 ——
        # 但真的遇到時症狀會是「那一條裁圖對不上」。
        body = sizes[1:]
        if len(sizes) > 1 and page_sizes_compatible(body):
            cover_tables = [i for i, it in enumerate(self.items)
                            if it.get("page_idx") == 0 and it.get("type") == "table"]
            if not cover_tables:
                return Counter(body).most_common(1)[0][0]
            raise DocContextError(
                f"{self.doc_name}：封面頁尺寸與內頁不同（{sizes[0]} vs {body[0]}），"
                f"而第 0 頁上有 {len(cover_tables)} 張表格 {cover_tables[:5]} —— "
                "裁圖會用內頁尺寸換算封面頁的 bbox，裁出來的位置是錯的")

        dw, dh = page_size_spread(sizes)
        raise DocContextError(
            f"{self.doc_name}：頁面尺寸不一致 {sorted(set(sizes))}"
            f"（寬差 {dw:g}、高差 {dh:g} 點，容差 {PAGE_SIZE_TOLERANCE_PT:g}）")

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
