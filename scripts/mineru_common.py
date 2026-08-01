"""MinerU 產物的共用偵測器與磁碟契約。

單一來源：parse-check.py、compat-check.py、postprocess 都從這裡拿偵測邏輯。
分散成三份的話會漂移 —— 而且漂移時不會有錯誤，只是三支腳本對同一份資料給出
不同答案，然後你不知道該信哪個。

本檔案的偵測器已經因為誤判修過三次，每次的原因都寫在對應常數的註解裡。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# content_list.json 的項目型別。出現沒見過的 = 版面型態超出規則涵蓋範圍。
KNOWN_TYPES = {
    "text", "header", "footer", "table", "equation", "image",
    "page_number", "page_footnote", "code", "list",
}

# 會進 IR 正文的型別。header / footer 也在內 —— LightRAG 的 ir_builder 把它們
# 落到 fallback「serialize unknown items as plain text」，所以它們確實會進索引。
PROSE_TYPES = ("text", "header")
BODY_TYPES = ("text", "header", "footer")

# 掉字偵測器。務必用 \b 這種非消耗性邊界；寫成兩側都是 \s 的
# (\s[a-z]{1,2}\s){5,} 會因為前一次匹配吃掉後一次的前導空白而永遠回 0。
MANGLED = re.compile(r"(?:\s+[a-z]{1,2}\b){5,}")

# 行內數學。LaTeX 會把字母拆開排版（\mathrm { i n t e r i o r }），長得跟掉字
# 一模一樣，套 MANGLED 之前必須先剝掉。
MATH = re.compile(r"\$[^$]*\$|\\\(.*?\\\)|\\\[.*?\\\]", re.S)

TAG = re.compile(r"<[^>]+>")

# prompt 洩漏。1.5.5 上游已把 few-shot 範例換成純佔位符，這組留著防退化。
LEAK = re.compile(
    r"Noah Carter|World Athletics|Carbon-Fiber Spikes|100m Sprint|Knowledge Graph Specialist",
    re.I,
)


def strip_math(t: str) -> str:
    return MATH.sub(" ", t or "")


def table_text(body: str | None) -> str:
    """表格的實質文字。剝掉標籤是必要的 —— MinerU 會產出
    <table><tr><td></td></tr></table> 這種空殼，字串非空但內容為零。
    <img> 也不算內容，那只是指向圖片檔的參照。"""
    return TAG.sub("", body or "").strip()


def is_mangled(text: str, item_type: str) -> bool:
    """掉字偵測。只跑散文 —— equation 的 text 是沒有 $ 包裹的裸 LaTeX，
    table_body 整片是標記，兩者本來就長得像掉字。在數學密集的文件上不設限
    會讓每一份都變 ERROR（實測 12 個命中裡 11 個是誤判）。"""
    if item_type not in PROSE_TYPES:
        return False
    return bool(MANGLED.search(strip_math(text)))


def item_body(item: dict) -> str:
    """項目的正文欄位。順序與 ir_builder._coerce_text 一致（已由 compat-check A-06 斷言）。"""
    for k in ("text", "content", "body", "code_body"):
        v = item.get(k)
        if isinstance(v, str) and v:
            return v
    return ""


def bbox_to_points(bbox: list, page_w: float, page_h: float) -> tuple[float, float, float, float]:
    """content_list 的 bbox 是每軸正規化到 0–1000，換算成 PDF 點。

    已驗證：content_list [93,136,906,277] 與 page_size (439,666) 換算得
    [40.8, 90.6, 397.7, 184.5]，與 layout.json 記錄的 [41,91,398,185] 吻合。
    注意不是均勻縮放 —— x 與 y 各自正規化，用單一比例會錯。
    """
    x0, y0, x1, y1 = bbox
    return (x0 / 1000 * page_w, y0 / 1000 * page_h,
            x1 / 1000 * page_w, y1 / 1000 * page_h)


def load_env(repo: Path) -> dict:
    p = repo / ".env"
    if not p.exists():
        return {}
    out = {}
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip("'\"")
    return out


def read_json(p: Path):
    return json.loads(p.read_text())
