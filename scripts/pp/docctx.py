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


class DocContextError(RuntimeError):
    pass


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
        """PDF 點座標的頁面尺寸。要求所有頁一致 —— 尺寸混雜時 bbox 換算會錯，
        而且錯得很安靜（裁出來的圖看起來像張表，只是位置不對）。"""
        sizes = {tuple(p.get("page_size") or ()) for p in self.layout["pdf_info"]}
        if len(sizes) != 1:
            raise DocContextError(f"{self.doc_name}：頁面尺寸不一致 {sizes}")
        w, h = sizes.pop()
        return float(w), float(h)

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
