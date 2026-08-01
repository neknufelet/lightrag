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
        print("\n  ── 版面雜訊的文字分布 ──")
        for text, n in sorted(noise.distinct.items(), key=lambda kv: -kv[1]):
            act = "消音" if n >= layout_noise.RUNNING_HEAD_MIN_REPEAT else ("略過" if not text else "保留待查")
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


def main():
    env = load_env(REPO)
    ap = argparse.ArgumentParser(description="MinerU 解析輸出的後處理")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("plan", help="只讀，算出打算改什麼")
    p.add_argument("--workspace", default=env.get("WORKSPACE", "acoustics_v155"))
    p.add_argument("--doc", help="檔名關鍵字，預設全部")
    p.add_argument("--details", action="store_true")
    p.add_argument("--json", action="store_true")

    a = ap.parse_args()

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
