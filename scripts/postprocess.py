#!/usr/bin/env python3
"""對 MinerU 的解析輸出做後處理：過濾版面雜訊、修補空表格。

在容器外操作磁碟上的 .mineru_raw/，不修改 LightRAG 任何程式碼。

重要：修補**不會自動生效**。已索引的文件在 /scan 時會被 _archive + continue 直接
跳過，parse() 根本不會被呼叫。修補要進索引必須刪掉文件記錄再重新掃描（見 reindex
子命令）。「解析完、建 IR 前」這個插入時間窗在程式上不存在。

用法：
    postprocess.py plan                    # 只讀，印出打算改什麼
    postprocess.py plan --doc Equivalent --details
    postprocess.py plan --json             # 給程式解析

    postprocess.py check --doc Equivalent  # 兩雙眼睛轉錄 + 逐格比對，產出 review.md
    postprocess.py check                   # 整個 workspace

check 會呼叫外部模型（本機 qwen + 雲端 luna），結果快取在
DATA_ROOT/<ws>/postprocess/<doc>/cache/，重跑不會重複付費。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mineru_common import load_env  # noqa: E402
from pp.docctx import DocContext, DocContextError  # noqa: E402
from pp.rules import empty_table, layout_noise  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DATA_ROOT = Path(os.environ.get("PP_DATA_ROOT", "/data/rag/lightrag"))


def find_bundles(workspace: str, doc: str | None) -> list[Path]:
    pdir = DATA_ROOT / workspace / "inputs" / workspace / "__parsed__"
    if not pdir.is_dir():
        sys.exit(f"postprocess: 找不到解析目錄 {pdir}")
    hits = sorted(pdir.glob("*.mineru_raw"))
    if doc:
        hits = [h for h in hits if doc.lower() in h.name.lower()]
    if not hits:
        sys.exit(f"postprocess: 沒有符合的 bundle（doc={doc!r}）")
    return hits


def plan_one(raw: Path) -> dict:
    ctx = DocContext(raw)
    ctx.preflight()
    w, h = ctx.page_size
    noise = layout_noise.plan(ctx.items)
    tables = empty_table.plan(ctx.items, w, h)
    return {"ctx": ctx, "noise": noise, "tables": tables}


def render(p: dict, details: bool) -> None:
    ctx, noise, tables = p["ctx"], p["noise"], p["tables"]
    print(f"\n=== {ctx.doc_name} ===")
    print(f"  {ctx.n_pages} 頁、{len(ctx.items)} 個項目、頁面 {ctx.page_size[0]:.0f}×{ctx.page_size[1]:.0f} pt")
    print(f"  過濾：{noise.summary()}")
    print(f"  表格：{tables.summary()}")

    if not details:
        return

    if noise.distinct:
        # 標籤直接讀計畫，不要在這裡重算規則 —— 重算過一次就會跟 layout_noise
        # 漂移（aside_text 用的是「是不是語言」而非重複次數，重算會標錯）。
        muted = {m.text.strip() for m in noise.mutes}
        held = {m.text.strip() for m in noise.held}
        print("\n  ── 版面雜訊的文字分布 ──")
        for text, n in sorted(noise.distinct.items(), key=lambda kv: -kv[1]):
            k = text.strip()
            act = "消音" if k in muted else ("保留待查" if k in held else "略過")
            print(f"    ×{n:>3}  [{act}]  {text[:60]!r}")

    if noise.held:
        print("\n  ── 保留待查（重複次數不足，可能是真標題）──")
        for m in noise.held:
            print(f"    p{m.page} ×{m.repeat}  {m.text[:70]!r}")

    if tables.repairable:
        print("\n  ── 待修補的表格 ──")
        for t in tables.repairable:
            bb = "、".join(f"{v:.0f}" for v in t.bbox_pt) if t.bbox_pt else "無 bbox"
            print(f"    #{t.index:<4} p{t.page:<3} {t.klass.value:<12} bbox_pt({bb})"
                  + (f"  caption={t.caption[:40]!r}" if t.caption else ""))

    if tables.review:
        print("\n  ── 圖片型表格（不自動修補，供人工確認）──")
        for t in tables.review:
            print(f"    #{t.index:<4} p{t.page:<3} 實質文字 {t.text_len} 字元"
                  + (f"  caption={t.caption[:40]!r}" if t.caption else ""))


def as_json(p: dict) -> dict:
    ctx, noise, tables = p["ctx"], p["noise"], p["tables"]
    return {
        "doc": ctx.doc_name,
        "pages": ctx.n_pages,
        "items": len(ctx.items),
        "page_size": list(ctx.page_size),
        "noise": {
            "mute": [{"index": m.index, "page": m.page, "repeat": m.repeat, "text": m.text}
                     for m in noise.mutes],
            "held": [{"index": m.index, "page": m.page, "repeat": m.repeat, "text": m.text}
                     for m in noise.held],
            "body_chars_before": noise.body_chars_before,
            "body_chars_after": noise.body_chars_after,
            "ratio": round(noise.ratio, 4),
            "suspicious": noise.suspicious,
        },
        "tables": {
            "total": tables.total,
            "repair": [{"index": t.index, "page": t.page, "class": t.klass.value,
                        "bbox_pt": list(t.bbox_pt), "caption": t.caption}
                       for t in tables.repairable],
            "review": [{"index": t.index, "page": t.page, "text_len": t.text_len,
                        "caption": t.caption}
                       for t in tables.review],
        },
    }


def cmd_check(a, env) -> int:
    from pp import eyes                                    # 只有 check 需要，延後載入

    out_root = DATA_ROOT / a.workspace / "postprocess"
    n_auto = n_need = n_err = 0
    for raw in find_bundles(a.workspace, a.doc):
        try:
            ctx, results = eyes.check_doc(raw, env, out_root, workers=a.workers)
        except DocContextError as e:
            print(f"\n=== 略過 ===\n  {e}")
            n_err += 1
            continue
        rv = eyes.write_review(ctx, results, out_root)
        auto = sum(1 for r in results if r.ok)
        need = len(results) - auto
        n_auto += auto
        n_need += need
        print(f"\n=== {ctx.doc_name} ===")
        for r in results:
            mark = "✅" if r.ok else "⚠️ "
            what = r.error or (r.check.line() if r.check else "?")
            print(f"  {mark} #{r.index:<5} p{r.page:<4} {what}")
        print(f"  → 自動採用 {auto}、待判 {need}　報表 {rv}")

    print(f"\n{'-'*70}")
    print(f"合計：自動採用 {n_auto}、待判 {n_need}" + (f"、略過 {n_err} 份" if n_err else ""))
    # 待判不是失敗，只有真的處理不了才給非零 exit
    return 1 if n_err else 0


def main():
    env = load_env(REPO)
    ap = argparse.ArgumentParser(description="MinerU 解析輸出的後處理")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("plan", help="只讀，算出打算改什麼")
    p.add_argument("--workspace", default=env.get("WORKSPACE", "acoustics_v155"))
    p.add_argument("--doc", help="檔名關鍵字，預設全部")
    p.add_argument("--details", action="store_true")
    p.add_argument("--json", action="store_true")

    c = sub.add_parser("check", help="兩雙眼睛轉錄 + 逐格比對")
    c.add_argument("--workspace", default=env.get("WORKSPACE", "acoustics_v155"))
    c.add_argument("--doc", help="檔名關鍵字，預設全部")
    c.add_argument("--workers", type=int, default=3)

    a = ap.parse_args()

    if a.cmd == "check":
        sys.exit(cmd_check(a, env))

    plans, failed = [], []
    for raw in find_bundles(a.workspace, a.doc):
        try:
            plans.append(plan_one(raw))
        except DocContextError as e:
            failed.append(str(e))

    if a.json:
        print(json.dumps({"plans": [as_json(p) for p in plans], "failed": failed},
                         ensure_ascii=False, indent=1))
    else:
        for p_ in plans:
            render(p_, a.details)
        for f in failed:
            print(f"\n=== 略過 ===\n  {f}")
        n_mute = sum(len(p_["noise"].mutes) for p_ in plans)
        n_rep = sum(len(p_["tables"].repairable) for p_ in plans)
        n_susp = sum(1 for p_ in plans if p_["noise"].suspicious)
        print(f"\n{'-'*70}")
        print(f"共 {len(plans)} 份可處理、{len(failed)} 份略過；"
              f"待消音 {n_mute} 項、待修補 {n_rep} 張表"
              + (f"；{n_susp} 份比例異常需人工確認" if n_susp else ""))

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
