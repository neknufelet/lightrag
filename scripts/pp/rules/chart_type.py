"""把 MinerU 的 chart 型別改成 image，讓論文圖進得了索引。

MinerU 對「有數據的圖」標 chart、對「照片示意圖」標 image。兩者在 content_list
裡長得幾乎一樣，但 LightRAG 只認得後者：

    ir_builder.py:371   if item_type in {"image", "picture", "drawing"}:
                            drawing, asset = self._build_ir_drawing(...)
    ir_builder.py:387   # fallback：其餘型別當純文字處理
                        if _append_text(_coerce_text(item)):

chart 落到 fallback，而 _coerce_text 依序讀 text / content / body / code_body ——
chart 的 content 固定是空字串，所以回傳 ""，_append_text 回 False。結果是不建
佔位符、不登資產、連 page_idx 都不記，整個項目在索引裡不存在。

實測全庫 187 個 image、184 個 chart —— 將近一半的圖等於沒有。

為什麼不能只改 type：_build_ir_drawing 讀的是 image_caption / image_footnote，
chart 用的是 chart_caption / chart_footnote。只改 type 圖會進去，但 caption 會
掉光 —— 而 caption（"Figure 8.13 Effect of background noise on decay curves…"）
正是這個項目唯一有檢索價值的文字。所以欄位一起改名。

還原靠 _pp_original_type：有這個鍵才是我們轉過的，天生的 image 不會被動到。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

SOURCE_TYPE = "chart"
TARGET_TYPE = "image"

# chart 的欄位 → _build_ir_drawing 真正會讀的欄位
FIELD_MAP = {
    "chart_caption": "image_caption",
    "chart_footnote": "image_footnote",
}


@dataclass
class Conversion:
    index: int
    page: int
    img_path: str
    caption: str


@dataclass
class ChartPlan:
    convert: list[Conversion] = field(default_factory=list)
    # img_path 指不到磁碟上的檔案。轉了會登記一個沒有內容的資產，
    # 所以寧可留著不動 —— 少一張圖，好過索引裡多一個壞參照。
    dangling: list[Conversion] = field(default_factory=list)

    @property
    def with_caption(self) -> int:
        return sum(1 for c in self.convert if c.caption)

    def line(self) -> str:
        s = f"chart→image {len(self.convert)}（其中 {self.with_caption} 有 caption）"
        if self.dangling:
            s += f"；圖檔不存在故跳過 {len(self.dangling)}"
        return s


def _caption_of(item: dict) -> str:
    for key in ("chart_caption", "image_caption", "captions"):
        v = item.get(key)
        if isinstance(v, list):
            for x in v:
                if str(x).strip():
                    return str(x).strip()
        elif isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def plan(items: list[dict], raw_dir: Path | None = None) -> ChartPlan:
    p = ChartPlan()
    for i, it in enumerate(items):
        if it.get("type") != SOURCE_TYPE:
            continue
        img = str(it.get("img_path") or "")
        c = Conversion(i, int(it.get("page_idx") or 0), img, _caption_of(it))
        if not img or (raw_dir is not None and not (raw_dir / img).is_file()):
            p.dangling.append(c)
        else:
            p.convert.append(c)
    return p


def apply_to_items(items: list[dict], plan_: ChartPlan) -> int:
    """就地改型別並把 caption / footnote 改成 _build_ir_drawing 讀得到的欄位名。

    content 這個鍵留著不動 —— image 分支不讀它，而留著讓 revert 不必猜
    「原本有沒有 content」。
    """
    n = 0
    for c in plan_.convert:
        it = items[c.index]
        if it.get("type") != SOURCE_TYPE:      # 已經轉過了，冪等
            continue
        it["_pp_original_type"] = it["type"]
        it["type"] = TARGET_TYPE
        for src, dst in FIELD_MAP.items():
            if src in it:
                it[dst] = it.pop(src)
        n += 1
    return n


def revert_items(items: list[dict]) -> int:
    """只還原帶 _pp_original_type 的項目。天生的 image 沒有這個鍵，不會被誤傷。"""
    n = 0
    for it in items:
        if "_pp_original_type" not in it:
            continue
        it["type"] = it.pop("_pp_original_type")
        for src, dst in FIELD_MAP.items():
            if dst in it:
                it[src] = it.pop(dst)
        n += 1
    return n
