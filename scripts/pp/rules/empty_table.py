"""空表格的分類與修補目標選擇。

最重要的一條是**不修什麼**：`table_body` 存在且含 `<img>` 的表格，多數是正常的表 ——
`<img>` 是儲存格內的電路符號圖。實測 idx 7（caption `Table 2 & 3 Passive electrical
and mechanical circuit components`）是完整的五欄表，數學是正確的 inline LaTeX
`$R = \\frac{\\Delta U}{I}$`，有 799 字元實質內容。拿 VLM 的猜測覆蓋它，就是製造
本專案一路在防的那種靜默損壞。

只修真正沒有內容的：`table_body` 鍵不存在，或存在但剝掉標籤後是空的。
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from mineru_common import bbox_to_points, table_text  # noqa: E402

# 含 <img> 但實質文字低於此值，才視為「可能只是圖片參照」而列入待查。
# 不自動修補 —— 只提示人看一眼。
IMG_ONLY_TEXT_MAX = 200


class TableClass(Enum):
    MISSING_KEY = "missing_key"    # 連 table_body 鍵都沒有
    EMPTY_SHELL = "empty_shell"    # <table><tr><td></td></tr></table>
    IMG_THIN = "img_thin"          # 有 <img> 且實質文字很少 —— 待查，不自動修
    OK = "ok"


@dataclass
class TableTarget:
    index: int
    page: int
    bbox_norm: list          # content_list 的 0–1000 正規化座標
    bbox_pt: tuple           # 換算後的 PDF 點座標，供裁圖用
    klass: TableClass
    caption: str
    text_len: int

    @property
    def repairable(self) -> bool:
        return self.klass in (TableClass.MISSING_KEY, TableClass.EMPTY_SHELL)


@dataclass
class TablePlan:
    targets: list[TableTarget]
    total: int

    @property
    def repairable(self) -> list[TableTarget]:
        return [t for t in self.targets if t.repairable]

    @property
    def review(self) -> list[TableTarget]:
        return [t for t in self.targets if t.klass is TableClass.IMG_THIN]

    def summary(self) -> str:
        n = {k: sum(1 for t in self.targets if t.klass is k) for k in TableClass}
        return (f"表格 {self.total}：缺鍵 {n[TableClass.MISSING_KEY]}、"
                f"空殼 {n[TableClass.EMPTY_SHELL]}、"
                f"圖片型待查 {n[TableClass.IMG_THIN]} "
                f"→ 可修補 {len(self.repairable)} 張")


def _caption(it: dict) -> str:
    c = it.get("table_caption")
    if isinstance(c, list):
        return " ".join(str(x) for x in c if str(x).strip())
    return str(c or "")


def classify(it: dict) -> TableClass:
    if "table_body" not in it:
        return TableClass.MISSING_KEY
    txt = table_text(it.get("table_body"))
    if not txt:
        return TableClass.EMPTY_SHELL
    if "<img" in (it.get("table_body") or "") and len(txt) < IMG_ONLY_TEXT_MAX:
        return TableClass.IMG_THIN
    return TableClass.OK


def plan(items: list[dict], page_w: float, page_h: float) -> TablePlan:
    """只讀不寫。回傳所有非 OK 的表格，含裁圖需要的 PDF 點座標。"""
    targets: list[TableTarget] = []
    total = 0
    for i, it in enumerate(items):
        if it.get("type") != "table":
            continue
        total += 1
        k = classify(it)
        if k is TableClass.OK:
            continue
        bbox = it.get("bbox") or []
        if len(bbox) != 4:
            # 沒有 bbox 就無從裁圖。列出來讓人知道，但不當成可修補。
            targets.append(TableTarget(i, it.get("page_idx"), bbox, (), k,
                                       _caption(it), len(table_text(it.get("table_body")))))
            continue
        targets.append(TableTarget(
            index=i,
            page=int(it.get("page_idx")),
            bbox_norm=bbox,
            bbox_pt=bbox_to_points(bbox, page_w, page_h),
            klass=k,
            caption=_caption(it),
            text_len=len(table_text(it.get("table_body"))),
        ))
    return TablePlan(targets, total)
