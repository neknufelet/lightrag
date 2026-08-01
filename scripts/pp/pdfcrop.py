"""從來源 PDF 裁出表格區域，並抽出該區域的文字層當交叉驗證的 ground truth。

一律自己裁，不用 MinerU 已截好的 img_path：十張表用同一種方式產生的圖，VLM 的
表現才可比，抽驗時也不必分兩種情況判斷。MinerU 的圖只有部分表格有，且裁切邊界
與解析度未知。

文字層抽取是免費的正確性證明：如果 bbox 換算錯了，抽出來的會是別的段落。實測
p26 的表格區域抽到 'Modes in (II) – average over s=a2'、'Orifice partition
impedance'，與渲染出來的頁面吻合。

文字層不能取代 VLM —— 數學結構被壓平、希臘字母壞掉（η→†、σ→消失），但英文字
乾淨，正好當 alpha recall 的比對基準。
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

# 裁切時往外擴的邊界（PDF 點）。表格外框線常落在 bbox 邊緣上，切齊會削掉。
PAD_PT = 6.0

# 方程式要用不同的 padding，而且**垂直方向幾乎不擴**。
#
# 表格的 6 點是為外框線留的；方程式沒有框線，而且顯示式的行距很密 ——
# 實測 K Muffler p27 的 T_a/T_b/T_c/T_d 四條式子，bbox 各只有 18 單位高、
# 上下緊貼。往外擴 6 點等於把上下鄰居都框進圖裡，六個模型於是各自決定
# 要轉幾條，看起來像模型分歧，實際是裁圖把題目出錯了。
#
# 這一條先前被我誤判成「三方皆異、真的無解」——實際上六個模型對共同部分
# 完全一致，差別只在轉了幾行。左右仍然擴，因為公式編號與括號會貼邊。
EQ_PAD_X = 4.0
EQ_PAD_Y = 1.0

# 送 VLM 的解析度。300 DPI 在試點時足以讓本機模型正確辨識下標與積分符號。
DPI = 300


class CropError(RuntimeError):
    pass


@dataclass
class Crop:
    png: Path
    gt_text: str            # 該區域文字層抽出的文字，交叉驗證用
    page_1based: int
    rect_pt: tuple[float, float, float, float]   # 實際使用的矩形（含 padding）

    @property
    def gt_alpha(self) -> set[str]:
        """ground truth 的英文詞集合。希臘字母與數學符號在文字層是壞的，
        排掉非 ASCII 即可；剩下的英文字是可靠的比對基準。"""
        import re
        return {w.lower() for w in re.findall(r"[A-Za-z]{3,}", self.gt_text)}

    @property
    def gt_numbers(self) -> set[str]:
        import re
        return set(re.findall(r"\d+(?:\.\d+)?", self.gt_text))


def _require_tools() -> None:
    for t in ("pdftoppm", "pdftotext"):
        if not shutil.which(t):
            raise CropError(f"缺少 {t}（poppler-utils）")


def _run(argv: list[str], timeout: int = 120) -> str:
    p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise CropError(f"{argv[0]} exit {p.returncode}: {p.stderr.strip()[:300]}")
    return p.stdout


def crop_region(pdf: Path, page_idx: int, bbox_pt: tuple, out_dir: Path,
                stem: str, page_w: float, page_h: float,
                pad: float = PAD_PT, dpi: int = DPI,
                pad_y: float | None = None) -> Crop:
    """裁出一塊區域。page_idx 是 0-based（content_list 的慣例），poppler 要 1-based。

    pad_y 分開指定時垂直方向用它 —— 方程式的行距很密，垂直擴太多會框進鄰居。
    """
    _require_tools()
    out_dir.mkdir(parents=True, exist_ok=True)

    py = pad if pad_y is None else pad_y
    x0, y0, x1, y1 = bbox_pt
    # 往外擴，但不超出頁面
    x0 = max(0.0, x0 - pad)
    y0 = max(0.0, y0 - py)
    x1 = min(page_w, x1 + pad)
    y1 = min(page_h, y1 + py)
    if x1 <= x0 or y1 <= y0:
        raise CropError(f"矩形無效：{(x0, y0, x1, y1)}")

    page = page_idx + 1
    scale = dpi / 72.0

    # pdftoppm 的 -x/-y/-W/-H 是輸出影像的像素座標，所以要先換算
    _run(["pdftoppm", "-f", str(page), "-l", str(page), "-r", str(dpi), "-png",
          "-x", str(int(x0 * scale)), "-y", str(int(y0 * scale)),
          "-W", str(int((x1 - x0) * scale)), "-H", str(int((y1 - y0) * scale)),
          str(pdf), str(out_dir / stem)])

    # pdftoppm 會在檔名後面補頁碼，位數隨總頁數而定，所以用萬用字元找
    hits = sorted(out_dir.glob(f"{stem}-*.png")) or sorted(out_dir.glob(f"{stem}.png"))
    if not hits:
        raise CropError(f"pdftoppm 沒有產出檔案（{stem}）")
    png = hits[0]

    # pdftotext 的 -x/-y/-W/-H 是 PDF 點，不必換算
    gt = _run(["pdftotext", "-f", str(page), "-l", str(page),
               "-x", str(int(x0)), "-y", str(int(y0)),
               "-W", str(int(x1 - x0)), "-H", str(int(y1 - y0)),
               str(pdf), "-"])

    return Crop(png=png, gt_text=gt, page_1based=page, rect_pt=(x0, y0, x1, y1))


def assert_rect_plausible(c: Crop, min_alpha: int = 3) -> None:
    """裁出來的區域至少要有幾個英文詞。完全抽不到文字通常代表 bbox 換算錯了 ——
    整體位移時仍會裁出「一張看起來像表的圖」，只是位置不對，光看圖看不出來。"""
    if len(c.gt_alpha) < min_alpha:
        raise CropError(
            f"p{c.page_1based} {c.rect_pt} 只抽到 {len(c.gt_alpha)} 個英文詞 —— "
            "bbox 換算可能錯位，或該區域確實沒有文字層"
        )
