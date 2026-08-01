#!/usr/bin/env python3
"""方程式正確性：三方比對。

結構檢查（括號配對、$ 成對）全綠不代表內容對 —— PDF 上是 η_n、索引裡是
\\gamma_n，結構完美但意思錯了，沒有任何字串規則抓得到。只有拿去對圖才知道。

三方：
    MinerU 的 LaTeX   ← 現在索引裡的那份，被檢驗的對象
    qwen   看圖轉錄   ← 本機，免費
    luna   看圖轉錄   ← 雲端，不同家族

判讀的關鍵是**兩個模型彼此一致，但都跟 MinerU 不同** —— 那才是 MinerU 錯了。
只有一個模型不同，多半是那個模型自己看錯（我們已知 qwen 會誤讀羅馬數字、
luna 會看錯字元）。

抽樣刻意偏向可疑的文件：均勻亂抽會低估錯誤率，因為問題集中在數學密集
且已知有解析瑕疵的那幾份。

用法：
    eq-check.py --n 50
    eq-check.py --n 20 --doc Equivalent
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mineru_common import bbox_to_points, load_env  # noqa: E402
from pp import crosscheck, eyes, pdfcrop  # noqa: E402
from pp.docctx import DocContext, DocContextError  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DATA_ROOT = Path(os.environ.get("PP_DATA_ROOT", "/data/rag/lightrag"))

# 兩份轉錄視為一致的門檻。方程式沒有列結構，比表格單純，用整體記號集合即可。
T_AGREE = 0.85

PROMPT_EQ = (
    "Transcribe the mathematical expression in this image into LaTeX. "
    "Output only the LaTeX, no delimiters, no commentary, no explanation. "
    "Preserve subscripts, superscripts, Greek letters, integrals and fractions exactly. "
    "Roman numeral sub/superscripts (I, II, III) must be transcribed as Roman numerals, "
    "not as pipes, letters l/H, or digits."
)


def pick(workspace: str, n: int, doc: str | None, seed: int = 7) -> list[tuple]:
    """挑樣本。偏向數學密集與已知有瑕疵的文件 —— 均勻抽會低估錯誤率。"""
    pdir = DATA_ROOT / workspace / "inputs" / workspace / "__parsed__"
    pool: list[tuple] = []
    for raw in sorted(pdir.glob("*.mineru_raw")):
        if doc and doc.lower() not in raw.name.lower():
            continue
        try:
            ctx = DocContext(raw)
            ctx.preflight()
            w, h = ctx.page_size
        except (DocContextError, Exception):            # noqa: BLE001
            continue
        eqs = [(i, it) for i, it in enumerate(ctx.items)
               if it.get("type") == "equation" and len(it.get("bbox") or []) == 4]
        if not eqs:
            continue
        density = len(eqs) / max(len(ctx.items), 1)
        for i, it in eqs:
            pool.append((density, ctx, i, it, bbox_to_points(it["bbox"], w, h)))

    rng = random.Random(seed)
    rng.shuffle(pool)
    # 依數學密度加權：密度高的文件多抽一些
    pool.sort(key=lambda x: -x[0])
    head = pool[: max(1, len(pool) // 3)]
    rest = pool[max(1, len(pool) // 3):]
    take = head[: int(n * 0.6)] + rest[: n - int(n * 0.6)]
    return take[:n]


def main() -> int:
    env = load_env(REPO)
    ap = argparse.ArgumentParser(description="方程式三方比對")
    ap.add_argument("--workspace", default=env.get("WORKSPACE", "acoustics_v155"))
    ap.add_argument("--doc")
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--show", type=int, default=8)
    a = ap.parse_args()

    out_root = DATA_ROOT / a.workspace / "postprocess" / "_equations"
    eye_a, eye_b = eyes.eyes_from_env(env)
    # 方程式的 prompt 跟表格不同（沒有列結構，而且要特別交代羅馬數字）
    eyes.vlm.PROMPT = PROMPT_EQ

    sample = pick(a.workspace, a.n, a.doc)
    print(f"抽樣 {len(sample)} 條方程式（偏向數學密集文件）\n")

    agree_ab = mineru_ok = flagged = errs = 0
    rows = []
    for k, (dens, ctx, idx, it, bbox) in enumerate(sample, 1):
        crops = out_root / ctx.doc_name / "crops"
        try:
            c = pdfcrop.crop_region(ctx.source_pdf, int(it["page_idx"]), bbox,
                                    crops, f"eq{idx}", *ctx.page_size)
        except pdfcrop.CropError as e:
            errs += 1
            continue
        cache = out_root / ctx.doc_name / "cache"
        ha, ea = eyes.look(eye_a, c.png, cache)
        hb, eb = eyes.look(eye_b, c.png, cache)
        if ea or eb:
            errs += 1
            continue

        mineru = it.get("text") or ""
        # 用方程式專用的序列比對，不要用表格那套抽記號 —— 同一條式子的等價
        # LaTeX 寫法太多（T_{12} vs \mathrm{T}_{1 2}、p_1 vs {\bf p}_{1}），
        # 正規表示式抓不完，實測 30 條裡 20 條被誤判成不一致。
        s_ab = crosscheck.eq_similar(ha, hb)
        s_am = crosscheck.eq_similar(ha, mineru)
        s_bm = crosscheck.eq_similar(hb, mineru)
        if s_ab >= T_AGREE:
            agree_ab += 1
            # 兩眼一致才有資格評 MinerU
            if max(s_am, s_bm) >= T_AGREE:
                mineru_ok += 1
            else:
                flagged += 1
                rows.append((ctx.doc_name, idx, it.get("page_idx"), s_ab,
                             max(s_am, s_bm), mineru, hb))
        if k % 10 == 0:
            print(f"  …{k}/{len(sample)}", flush=True)

    judged = agree_ab
    print(f"\n{'='*76}")
    print(f"  抽樣            {len(sample)}　（取得失敗 {errs}）")
    print(f"  兩眼一致        {agree_ab}　← 只有這些有資格評判 MinerU")
    print(f"  MinerU 相符     {mineru_ok}　（{mineru_ok/max(judged,1):.1%}）")
    print(f"  MinerU 可疑     {flagged}　（{flagged/max(judged,1):.1%}）← 兩眼一致但都跟它不同")

    for doc, idx, pg, s_ab, s_m, mineru, hb in rows[:a.show]:
        print(f"\n── {doc[:40]} #{idx} p{pg}　兩眼 {s_ab:.2f} / 對 MinerU {s_m:.2f}")
        print(f"   MinerU: {mineru[:150]}")
        print(f"   兩眼  : {hb[:150]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
