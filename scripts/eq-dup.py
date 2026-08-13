#!/usr/bin/env python3
r"""同一條公式在庫裡出現幾次，係數一不一致。

## 這支在找什麼

**不是找錯，是找分歧。** 259 篇同領域論文放在一起，同一條公式會被寫好幾次；
係數不一樣的地方就浮出來。2026-08-12 手動查到一個實例：Maa 的微穿孔板電阻
公式出現在三篇，其中一篇的第二項係數是 `√2/8` 而另外兩篇是 `√2/32`。

⚠⚠ **產出是「這裡有分歧」，不是「這裡有錯」。** 分歧可能來自 MinerU 讀錯、
原文本來就不同（不同的端點修正）、或兩篇用了不同的假設。
**不要把這份報告當成待修清單。**

## 兩層，刻意分開

    Tier A  骨架逐字相同 —— 天然的等價類，字典分組，O(n)
    Tier B  骨架相近     —— **只輸出成對**，永遠不做傳遞閉包

⚠ **不做傳遞閉包**是刻意的：a 像 b、b 像 c 不代表 a 像 c，串起來會造出幾十條
一群的假等價類，而人根本讀不了那種東西。

⚠ **短式子不丟，分桶。** `#=#` 這種瑣碎骨架另表列出並給數字（BASELINE 第 2 條：
不得無聲消失），不是排除掉 —— 排除掉的那批裡有真重複。

## Tier B 的排序：證據強度優先於相似度

**「兩邊各有幾個常數可比」排在相似度前面。** 只有一個數字對不上的匹配，分不清是
同一條公式的係數分歧還是兩條不同的公式碰巧長得像；五個常數只差一位就幾乎沒有
別的解釋。2026-08-13 實跑：係數不一致的那批裡九成以上只有 0～1 個常數，
按相似度排會讓它們整個佔滿前排，而驗收案例（Maa 那條，相似度只有 0.897）沉在下面。

⚠ **這只改排序不改判準** —— 一對都沒少，`--min-ratio` 仍然是排序起點不是門檻。

## 「跨來源」不是「跨文件」

同一本書的 §10.2 與 §10.8 重複一條公式，不算「兩篇文獻都這樣寫」。
⚠ 來源分組是**從檔名猜的**，`--source-map` 印出來給人核過再信。

用法：
    eq-dup.py                    # 給人看的報告
    eq-dup.py --json             # 結構化（⚠ 後面還會接一段給人看的報告）
    eq-dup.py --source-map       # 印出來源分組，核對用
    eq-dup.py --min-ratio 0.9    # Tier B 的下限（預設 0.8，排序輸出，不是門檻）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mineru_common import add_workspace_arg, load_env  # noqa: E402
from pp.eqkey import constants, skeleton, structure_profile  # noqa: E402
from pp.paths import DEFAULT_DATA_ROOT, DataPaths  # noqa: E402

REPO = Path(__file__).resolve().parent.parent

# 瑣碎骨架：列出來、給數字，但不進主報告。**不是丟掉。**
TRIVIAL = re.compile(r"^[#N=,.;:()\[\]{}+\-*/^_\s]*$")

_BOOK_SLICE = re.compile(r"^0(\d)(\d{3})_")          # 01405_5.5 …
_CH_SLICE = re.compile(r"^(.*?)_CH\d+", re.I)         # …_CH01


def source_key(doc: str) -> str:
    """同一本書的章節切片算同一個來源。

    ⚠ **這個函式是猜的。** 體檢表裡沒有來源欄位，只能從檔名推。
    用 `--source-map` 把 259 份的分組印出來核過再信。
    """
    if m := _BOOK_SLICE.match(doc):
        return f"book:0{m.group(1)}xxx"
    if m := _CH_SLICE.match(doc):
        return f"book:{m.group(1)}"
    return f"doc:{doc}"


def collect(parsed: Path) -> list[dict]:
    """全庫的方程式項目。"""
    out: list[dict] = []
    for d in sorted(parsed.glob("*.mineru_raw")):
        doc = d.name.removesuffix(".pdf.mineru_raw")
        cl = d / "content_list.json"
        if not cl.is_file():
            continue
        for n, it in enumerate(json.loads(cl.read_text(encoding="utf-8"))):
            if it.get("type") != "equation":
                continue
            latex = it.get("text") or ""
            if not latex.strip():
                continue
            out.append({"doc": doc, "item": n, "latex": latex,
                        "skeleton": skeleton(latex), "nums": constants(latex),
                        "source": source_key(doc)})
    return out


def pair_evidence(pair: dict) -> int:
    """一對匹配有多少常數可比 —— **排序用的證據強度，不是判準。**

    取兩邊的**小值**：一邊 5 個、一邊 1 個只有 1 個位置可比，而長度不同本身
    就說明它們可能不是同一條式子。取大值會把這種弱匹配捧到前排。
    """
    return min(len(pair["a"]["nums"]), len(pair["b"]["nums"]))


def first_difference(a: list[str], b: list[str]) -> int | None:
    """常數序列第一個差開的位置；長度不同也算差。"""
    for i, (x, y) in enumerate(zip(a, b, strict=False)):
        if x != y:
            return i
    return len(min(a, b, key=len)) if len(a) != len(b) else None


def tier_a(eqs: list[dict]) -> list[dict]:
    """骨架逐字相同的等價類，**且跨越一個以上的來源**。"""
    by_skel: dict[str, list[dict]] = defaultdict(list)
    for e in eqs:
        if not TRIVIAL.match(e["skeleton"]):
            by_skel[e["skeleton"]].append(e)

    groups = []
    for skel, members in by_skel.items():
        if len({m["source"] for m in members}) < 2:
            continue
        seqs = {tuple(m["nums"]) for m in members}
        groups.append({
            "skeleton": skel, "size": len(members),
            "sources": sorted({m["source"] for m in members}),
            "constants_agree": len(seqs) == 1,
            "members": [{"doc": m["doc"], "item": m["item"], "nums": m["nums"]}
                        for m in members],
        })
    # 係數不一致的排前面 —— 那才是要看的
    groups.sort(key=lambda g: (g["constants_agree"], -g["size"]))
    return groups


def tier_b(eqs: list[dict], min_ratio: float) -> list[dict]:
    """骨架相近的**成對**。用結構輪廓分塊，避免兩兩全比。"""
    by_profile: dict[tuple, list[dict]] = defaultdict(list)
    for e in eqs:
        if not TRIVIAL.match(e["skeleton"]):
            by_profile[structure_profile(e["latex"])].append(e)

    pairs = []
    for members in by_profile.values():
        if len(members) < 2 or len(members) > 400:      # 太大的塊先跳過並記數
            continue
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = members[i], members[j]
                if a["skeleton"] == b["skeleton"] or a["source"] == b["source"]:
                    continue
                r = SequenceMatcher(None, a["skeleton"], b["skeleton"],
                                    autojunk=False).ratio()
                if r < min_ratio:
                    continue
                pairs.append({
                    "ratio": round(r, 4),
                    "a": {"doc": a["doc"], "item": a["item"], "nums": a["nums"]},
                    "b": {"doc": b["doc"], "item": b["item"], "nums": b["nums"]},
                    "constants_agree": a["nums"] == b["nums"],
                    "first_diff": first_difference(a["nums"], b["nums"]),
                })
    # **證據強度優先於相似度。** 只按相似度排的話前排全是「只有一個數字對不上」的
    # 弱匹配（2026-08-13 實跑：465 對裡 431 對只有 0～1 個常數），而五個常數只差
    # 一位的強匹配沉在下面 —— 那正是這支存在的理由（Maa 那條）。
    pairs.sort(key=lambda p: (p["constants_agree"], -pair_evidence(p), -p["ratio"]))
    return pairs


def main() -> int:
    env = load_env(REPO)
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_workspace_arg(ap, env)
    ap.add_argument("--root", type=Path,
                    default=Path(env.get("DATA_ROOT", str(DEFAULT_DATA_ROOT))))
    ap.add_argument("--min-ratio", type=float, default=0.80,
                    help="Tier B 的下限。**這不是門檻是排序起點** —— "
                         "在有標註集之前不要拿它當判準")
    ap.add_argument("--source-map", action="store_true", help="印出來源分組供人核")
    ap.add_argument("--show", type=int, default=12)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    parsed = DataPaths(a.root).parsed_dir
    if not parsed.is_dir():
        sys.exit(f"找不到 {parsed}")
    eqs = collect(parsed)

    if a.source_map:
        by_src: dict[str, list[str]] = defaultdict(list)
        for d in sorted({e["doc"] for e in eqs}):
            by_src[source_key(d)].append(d)
        print(f"來源分組（{len(by_src)} 組 / {sum(len(v) for v in by_src.values())} 份）"
              "　⚠ 這是從檔名猜的，請核對\n")
        for src, docs in sorted(by_src.items(), key=lambda kv: -len(kv[1])):
            print(f"  {src:<28} {len(docs):>3} 份　{docs[0][:44]}"
                  + (f" …+{len(docs) - 1}" if len(docs) > 1 else ""))
        return 0

    trivial = [e for e in eqs if TRIVIAL.match(e["skeleton"])]
    groups = tier_a(eqs)
    pairs = tier_b(eqs, a.min_ratio)
    disagree_a = [g for g in groups if not g["constants_agree"]]
    disagree_b = [p for p in pairs if not p["constants_agree"]]

    if a.json:
        print(json.dumps({"workspace": a.workspace, "equations": len(eqs),
                          "trivial": len(trivial), "tier_a": groups, "tier_b": pairs},
                         ensure_ascii=False, indent=1))

    print(f"=== 公式交叉比對：{a.workspace} ===")
    print(f"掃過 {len({e['doc'] for e in eqs})} 份、{len(eqs)} 條公式"
          f"（其中 {len(trivial)} 條骨架瑣碎，另計不進比對）\n")
    print(f"Tier A（骨架逐字相同、跨來源）：{len(groups)} 組，"
          f"其中係數不一致 **{len(disagree_a)}** 組")
    print(f"Tier B（骨架相近、跨來源、成對）：{len(pairs)} 對，"
          f"其中係數不一致 **{len(disagree_b)}** 對")
    print("\n⚠ 這是「哪裡有分歧」不是「哪裡有錯」——"
          "分歧可能是 MinerU 讀錯、原文本來就不同、或兩篇假設不同。\n")

    for g in disagree_a[:a.show]:
        print(f"── Tier A　{g['size']} 處，{len(g['sources'])} 個來源　係數不一致")
        for m in g["members"][:6]:
            print(f"     {m['doc'][:44]:<46} #{m['item']:<5} {m['nums']}")
        print()
    for p in disagree_b[:a.show]:
        pos = p["first_diff"]
        # 常數個數要印出來 —— 它是現在的第一排序鍵，看不到就沒辦法判斷排序對不對。
        head = f"── Tier B　可比常數 {pair_evidence(p)} 個　相似度 {p['ratio']}"
        print(f"{head}　常數第 {pos} 位差開" if pos is not None else head)
        print(f"     {p['a']['doc'][:44]:<46} #{p['a']['item']:<5} {p['a']['nums']}")
        print(f"     {p['b']['doc'][:44]:<46} #{p['b']['item']:<5} {p['b']['nums']}")
        print()

    return 2 if (disagree_a or disagree_b) else 0


if __name__ == "__main__":
    sys.exit(main())
