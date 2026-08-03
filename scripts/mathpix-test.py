#!/usr/bin/env python3
"""用少量額度測 Mathpix 值不值得當第三隻眼睛。

免費方案只有 10 snips，所以挑題必須有策略。兩類最有價值：

  已確認 MinerU 錯的     ← 驗證 Mathpix 本身。它站兩眼那邊才代表可信
  兩眼分歧最大的         ← 這些目前無解，第三方直接打破僵局

均勻亂抽會把額度花在沒有爭議的式子上，問了也不會改變任何結論。

判讀：
  Mathpix 與兩眼一致  → 三方共識，MinerU 錯，可以放心修
  Mathpix 與 MinerU 一致 → 是兩眼一起看錯（同樣是有用的資訊）
  三方都不同          → 這條交人工

用法：
    mathpix-test.py --dry-run      # 只列出要問哪幾條，不花額度
    mathpix-test.py --limit 10
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mineru_common import add_workspace_arg, load_env  # noqa: E402
from pp import crosscheck, mathpix  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DATA_ROOT = Path(os.environ.get("PP_DATA_ROOT", "/data/rag/lightrag"))


def eq_dir(workspace: str) -> Path:
    """eq-check 的裁圖與轉錄快取。路徑跟著 workspace 走，不寫死 —— 寫死的話
    在 v2 的 checkout 跑會去讀 v155 的快取，然後把 v155 的式子當成 v2 的結論。"""
    return DATA_ROOT / workspace / "postprocess" / "_equations"


def collect(eq: Path) -> list[dict]:
    """把快取裡有兩份轉錄的都收起來，按兩眼分歧排序（分歧大的優先）。"""
    out = []
    for doc in sorted(eq.iterdir()):
        cache = doc / "cache"
        crops = doc / "crops"
        if not cache.is_dir():
            continue
        by_sha: dict[str, dict] = {}
        for f in cache.glob("*.json"):
            d = json.loads(f.read_text())
            by_sha.setdefault(f.name.split(".")[0], {})[d["model"]] = d["html"]
        # 用 sha 對回裁圖檔
        png_by_sha = {}
        import hashlib
        for p in crops.glob("*.png"):
            png_by_sha[hashlib.sha256(p.read_bytes()).hexdigest()[:16]] = p
        for sha, v in by_sha.items():
            if len(v) != 2 or sha not in png_by_sha:
                continue
            (ma, ha), (mb, hb) = list(v.items())
            out.append({"doc": doc.name, "png": png_by_sha[sha],
                        "a": ha, "b": hb,
                        "sim_ab": crosscheck.eq_similar(ha, hb)})
    out.sort(key=lambda r: r["sim_ab"])
    return out


def main() -> int:
    env = load_env(REPO)
    ap = argparse.ArgumentParser(description="Mathpix 小額度驗證")
    add_workspace_arg(ap, env)
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    eq = eq_dir(a.workspace)
    if not eq.is_dir():
        sys.exit(f"找不到 {eq}，先跑 eq-check.py")
    rows = collect(eq)[: a.limit]
    if not rows:
        sys.exit("找不到快取的方程式轉錄，先跑 eq-check.py")

    print(f"打算問 {len(rows)} 條（依兩眼分歧排序，分歧大的優先）：")
    for r in rows:
        print(f"  兩眼 {r['sim_ab']:.2f}  {r['doc'][:28]:<30} {r['png'].name}")
    if a.dry_run:
        print("\n（dry-run，沒有花額度）")
        return 0

    print()
    agree_eyes = agree_neither = errs = 0
    for i, r in enumerate(rows, 1):
        try:
            mp, _ = mathpix.transcribe(r["png"], env)
        except mathpix.MathpixError as e:
            print(f"  ✗ {r['png'].name}: {e}")
            errs += 1
            continue
        s_a = crosscheck.eq_similar(mp, r["a"])
        s_b = crosscheck.eq_similar(mp, r["b"])
        side = "A" if s_a > s_b else ("B" if s_b > s_a else "平手")
        best = max(s_a, s_b)
        verdict = "站其中一眼" if best >= 0.85 else "三方都不同"
        agree_eyes += best >= 0.85
        agree_neither += best < 0.85
        print(f"── {i}. {r['doc'][:26]} {r['png'].name}　兩眼 {r['sim_ab']:.2f}")
        print(f"   Mathpix : {mp[:120]}")
        print(f"   對 A {s_a:.2f} / 對 B {s_b:.2f}　→ {verdict}（{side}）")
        r["mathpix"] = mp

    print(f"\n{'='*70}")
    print(f"  Mathpix 與其中一眼一致  {agree_eyes}　← 這些僵局被打破了")
    print(f"  三方都不同              {agree_neither}　← 交人工")
    print(f"  呼叫失敗                {errs}")
    json.dump([{k: (str(v) if isinstance(v, Path) else v) for k, v in r.items()}
               for r in rows], open("/tmp/mathpix_result.json", "w"),
              ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
