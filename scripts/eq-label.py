#!/usr/bin/env python3
r"""公式比對的標註樣本：抽一批給人看，標完才有資格談門檻。

## 這支在解什麼問題

`eq-dup.py` 的 `--min-ratio` 目前是 `0.8`，而**那個數字沒有任何依據** ——
它是隨手挑的排序起點。要讓它變成「0.8 以上就算同一條」這種判準，必須先有一批
人看過的答案，否則就是拿一個猜的數字去裁決別人的公式。

## 抽什麼

```
Tier A  5 組    對照組。骨架逐字相同，應該「一定是同一條」——
                **這裡如果就錯了，底下整套都不用談。**
Tier B  16 對   要決定門檻的那批。相似度分四段（0.80／0.85／0.90／0.95）各抽 4 對。
```

⚠ **確定性抽樣（等距取樣，不用亂數）。** 重跑要拿到同一批，否則標註對不回去 ——
而「標註對不回去」會安靜地發生：檔案還在、只是指到別條公式了。

⚠ 只取每一段的前 4 個會全部落在同一個角落（相似度最高的那頭），
所以是**等距取樣**不是取前 N。

## 這支不做的事

不判對錯，也不訂門檻。產出是一份給人填的表；填完的答案凍結成
`verdicts/eq-labels.json`，那才是權威。

用法：
    eq-label.py sample                 # 印出樣本（markdown）
    eq-label.py sample --out FILE      # 寫檔
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mineru_common import load_env  # noqa: E402
from pp.paths import DEFAULT_DATA_ROOT, DataPaths  # noqa: E402
from pp.sources import DEFAULT_MAP_PATH, SourceMap, ledger_hashes  # noqa: E402

REPO = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location("eq_dup", Path(__file__).parent / "eq-dup.py")
assert _spec and _spec.loader
eqdup = importlib.util.module_from_spec(_spec)
sys.modules["eq_dup"] = eqdup
_spec.loader.exec_module(eqdup)

BANDS = ((0.95, 1.01), (0.90, 0.95), (0.85, 0.90), (0.80, 0.85))
PER_BAND = 4
TIER_A_SAMPLES = 5


def spaced(seq: list, n: int) -> list:
    """等距取 n 個。**不是取前 n 個** —— 那會全部落在同一個角落。"""
    if len(seq) <= n:
        return list(seq)
    step = len(seq) / n
    return [seq[int(i * step)] for i in range(n)]


def display(latex: str) -> str:
    """給人看的形狀：剝定界符與 `\\tag`、把 MinerU 逐 token 的空白壓掉。"""
    t = re.sub(r"^\$\$|\$\$$", "", (latex or "").strip()).strip()
    return re.sub(r"\s+", " ", re.sub(r"\\tag\{[^}]*\}", "", t))


def _member_lines(eq: dict, labels: dict[str, str]) -> list[str]:
    out = [f"- `{eq['doc'][:52]}` #{eq['item']}　常數 {eq['nums']}"]
    if who := labels.get(eq["doc"]):
        out.append(f"  《{who[:44]}》")
    out.append(f"  ```latex\n  {display(eq['latex'])[:300]}\n  ```")
    return out


def render(eqs: list[dict], groups: list[dict], pairs: list[dict],
           labels: dict[str, str]) -> str:
    """樣本本文。`eqs` 只用來把 (doc, item) 換回 LaTeX。"""
    text = {(e["doc"], e["item"]): e for e in eqs}
    out: list[str] = ["## 第一部分：Tier A 是不是真的可信（對照組，"
                      f"{TIER_A_SAMPLES} 組）\n",
                      "骨架**逐字相同**才會進 Tier A，所以它應該是「一定同一條」。"
                      "**如果這裡就錯了，底下整套都不用談。**\n"]
    for i, g in enumerate(spaced(sorted(groups, key=lambda x: -x["size"]), TIER_A_SAMPLES), 1):
        out.append(f"### A{i}　{g['size']} 處、{len(g['sources'])} 個來源"
                   f"　係數{'一致' if g['constants_agree'] else '**不一致**'}\n")
        for m in g["members"][:3]:
            out += _member_lines(text[(m["doc"], m["item"])], labels)
        if g["size"] > 3:
            out.append(f"- …其餘 {g['size'] - 3} 處省略")
        out.append("\n**標註：同一條 / 不是同一條**\n")

    out.append(f"\n## 第二部分：Tier B 按相似度分層（{len(BANDS) * PER_BAND} 對）\n")
    out.append("這是**要決定門檻的那批**。現在 `--min-ratio 0.8` 只是排序起點，"
               "沒有任何依據說 0.8 以上就算同一條。\n")
    n = 0
    for lo, hi in BANDS:
        inband = sorted([p for p in pairs if lo <= p["ratio"] < hi],
                        key=lambda p: (-p["ratio"], p["a"]["doc"], p["a"]["item"]))
        out.append(f"\n### 相似度 {lo:.2f}–{min(hi, 1.0):.2f}"
                   f"（這一段共 {len(inband)} 對，抽 {PER_BAND} 對）\n")
        for p in spaced(inband, PER_BAND):
            n += 1
            out.append(f"#### B{n}　相似度 {p['ratio']}　可比常數 "
                       f"{eqdup.pair_evidence(p)} 個"
                       f"　係數{'一致' if p['constants_agree'] else '**不一致**'}")
            for side in ("a", "b"):
                out += _member_lines(text[(p[side]["doc"], p[side]["item"])], labels)
            out.append("\n**標註：同一條 / 不是同一條 / 看不出來**\n")
    return "\n".join(out)


def control_sets(eqs: list[dict], groups: list[dict],
                 n: int = 12) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """兩個對照組，**都從資料裡來，不用人先標**。

    ```
    一定是同一條   Tier A 的成員兩兩配對 —— 骨架逐字相同、而且跨來源
    一定不是同一條 骨架相似度極低、又跨來源的兩條
    ```

    ⚠ 「一定不是」那組刻意取**相似度極低**的：模型在這裡都會亂點頭的話，
    它在 0.8～0.95 那段只會更糟，後面不用測。
    """
    text = {(e["doc"], e["item"]): e["latex"] for e in eqs}
    same: list[tuple[str, str]] = []
    for g in spaced(sorted(groups, key=lambda x: -x["size"]), n):
        ms = g["members"]
        a, b = ms[0], ms[-1]
        same.append((text[(a["doc"], a["item"])], text[(b["doc"], b["item"])]))

    from difflib import SequenceMatcher
    pool = spaced(sorted(eqs, key=lambda e: (e["doc"], e["item"])), n * 6)
    diff: list[tuple[str, str]] = []
    for i, x in enumerate(pool):
        for y in pool[i + 1:]:
            if x["source"] == y["source"] or len(diff) >= n:
                continue
            if SequenceMatcher(None, x["skeleton"], y["skeleton"],
                               autojunk=False).ratio() < 0.35:
                diff.append((x["latex"], y["latex"]))
                break
    return same, diff[:n]


def cmd_control(eqs: list[dict], groups: list[dict], n: int) -> int:
    """模型投票之前的體檢。**沒過的不准拿去擴大樣本。**"""
    from pp import eqjudge
    from pp.eyes import assert_distinct, eye_c_from_env, eyes_from_env

    env = load_env(REPO)
    panel = [*eyes_from_env(env)]
    if (third := eye_c_from_env(env)) is not None:
        panel.append(third)
    assert_distinct(panel)          # 同家族＝一個人投三票

    same, diff = control_sets(eqs, groups, n)
    print(f"=== 裁判體檢：{len(panel)} 隻眼睛 × "
          f"（已知同一條 {len(same)} 組 ＋ 已知不同 {len(diff)} 組）===")
    print("⚠ **兩個方向都要看。** 只看「判同率」的話，一隻永遠回答 same 的模型會拿 100%。\n")
    ok, misses = True, []
    for eye in panel:
        res = eqjudge.control(eye, same, diff)
        print(res.line())
        print(f"{'':<14} → {'堪用' if res.usable else '**不堪用，不要拿它擴大樣本**'}"
              f"（模型 {eye.model}，家族 {eye.family}）\n")
        ok &= res.usable
        if res.same_ok or res.same_wrong:      # 有跑起來的才算數
            misses.append(set(res.same_misses))
    print("結論：" + ("三隻都堪用，可以往下做投票擴樣。" if ok else
                     "**有眼睛沒過體檢** —— 先處理它，不要用它的票。"))

    # **三家獨立地打槍同一題，指的多半不是模型太嚴。**
    if len(misses) >= 2:
        agreed = sorted(set.intersection(*misses))
        print(f"\n── 幾隻眼睛都說「不是同一條」的題號（已知同一條那組）：{agreed or '無'}")
        if agreed:
            print("   ⚠ 不同家族獨立地打槍同一題 —— **要先懷疑「骨架逐字相同就是同一條」**"
                  "\n     這個假設有例外，那是關於 eq-dup 的發現，不是模型的問題。")
            for i in agreed[:3]:
                print(f"\n   題 {i}：")
                for tag, tex in zip("AB", same[i], strict=True):
                    print(f"     {tag}  {eqjudge._show(tex)[:150]}")
    return 0 if ok else 2


_STRUCT = re.compile(r"\\[A-Za-z]+")


def specificity(skeleton: str) -> dict:
    """骨架有多「具體」。**這裡只量，不下判準** —— 判準要等量完才有依據。

    三個候選一起量，因為它們會分歧：`#=\\frac{#}{#}` 三個都低，
    而 `#^#(#,#)=\\sum^{#}#^#(#^#,#)#^#(#)` 結構命令只有 1 個卻很長很 specific。
    **只數結構命令會把後者一起殺掉**，所以不能只看一個數字。
    """
    return {"struct": len(_STRUCT.findall(skeleton)),
            "chars": len(skeleton),
            "slots": skeleton.count("#")}


def _cross_source_pair(group: dict, eqs_by_key: dict) -> tuple[str, str] | None:
    """從一組裡挑**跨來源**的兩條。同來源的兩條不能拿來問「兩篇是否都這樣寫」。"""
    seen: dict[str, dict] = {}
    for m in group["members"]:
        e = eqs_by_key[(m["doc"], m["item"])]
        seen.setdefault(e["source"], e)
        if len(seen) == 2:
            a, b = seen.values()
            return a["latex"], b["latex"]
    return None


def cmd_audit(eqs: list[dict], groups: list[dict], out: Path | None) -> int:
    """讓模型把每一組 Tier A 都審一遍，看骨架具體度與「是不是同一條」在哪裡分開。"""
    from pp import eqjudge
    from pp.eyes import assert_distinct, eye_c_from_env, eyes_from_env

    env = load_env(REPO)
    panel = [*eyes_from_env(env)]
    if (third := eye_c_from_env(env)) is not None:
        panel.append(third)
    assert_distinct(panel)
    by_key = {(e["doc"], e["item"]): e for e in eqs}

    rows = []
    print(f"=== Tier A 審計：{len(groups)} 組 × {len(panel)} 隻眼睛 ===")
    for i, g in enumerate(groups, 1):
        pair = _cross_source_pair(g, by_key)
        if pair is None:
            continue
        rulings = [eqjudge.ask_pair(*pair, eye) for eye in panel]
        verdict = eqjudge.panel_verdict(rulings)
        rows.append({"skeleton": g["skeleton"], "size": g["size"],
                     "sources": len(g["sources"]), "verdict": verdict,
                     **specificity(g["skeleton"]),
                     "votes": [r.verdict if not r.error else "ERR" for r in rulings]})
        print(f"  [{i:>3}/{len(groups)}] {verdict:<10} {g['skeleton'][:56]}")

    print("\n── 骨架具體度 × 多數決")
    for name in ("struct", "chars", "slots"):
        print(f"\n  依 {name} 分箱：")
        for lo, hi in ((0, 2), (2, 4), (4, 8), (8, 16), (16, 10**6)) if name != "chars" \
                else ((0, 20), (20, 40), (40, 80), (80, 10**6), (10**6, 10**7)):
            grp = [r for r in rows if lo <= r[name] < hi]
            if not grp:
                continue
            d = sum(1 for r in grp if r["verdict"] == "different")
            s = sum(1 for r in grp if r["verdict"] == "same")
            print(f"    {name} {lo}–{hi if hi < 10**6 else '∞'}　{len(grp):>3} 組"
                  f" → 判同 {s}、**判異 {d}**、沒共識 {len(grp) - s - d}")
    if out:
        out.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"\n逐組結果寫到 {out}")
    return 0


def main() -> int:
    env = load_env(REPO)
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path,
                    default=Path(env.get("DATA_ROOT", str(DEFAULT_DATA_ROOT))))
    ap.add_argument("--map", type=Path, default=DEFAULT_MAP_PATH)
    ap.add_argument("--min-ratio", type=float, default=0.80)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("sample", help="抽一批給人標註")
    p.add_argument("--out", type=Path)
    c = sub.add_parser("control", help="裁判體檢：模型分不分得出來（沒過就不准用它的票）")
    c.add_argument("-n", type=int, default=12, help="每個對照組幾題")
    d = sub.add_parser("audit", help="讓模型把每組 Tier A 審一遍（量骨架具體度 × 是不是同一條）")
    d.add_argument("--out", type=Path)
    a = ap.parse_args()

    parsed = DataPaths(a.root).parsed_dir
    if not parsed.is_dir():
        sys.exit(f"找不到 {parsed}")
    smap = SourceMap.load(a.map)
    corpus = sorted(x.name.removesuffix(".pdf.mineru_raw") for x in parsed.glob("*.mineru_raw"))
    rec = smap.reconcile(corpus, ledger_hashes(a.root))
    eqs, skipped = eqdup.collect(parsed, smap)
    if not eqs:
        sys.exit(f"比對母體是空的 —— {rec.line()}")

    if a.cmd == "control":
        return cmd_control(eqs, eqdup.tier_a(eqs), a.n)
    if a.cmd == "audit":
        return cmd_audit(eqs, eqdup.tier_a(eqs), a.out)

    smap_raw = json.loads(a.map.read_text(encoding="utf-8")) if a.map.is_file() else {}
    labels = {d: (smap_raw.get("sources", {}).get(v.get("source"), {}) or {}).get("label", "")
              for d, v in (smap_raw.get("documents") or {}).items()}
    body = render(eqs, eqdup.tier_a(eqs), eqdup.tier_b(eqs, a.min_ratio), labels)
    header = (f"<!-- {rec.line()}；排除 {len(skipped)} 份 -->\n\n")
    if a.out:
        a.out.write_text(header + body + "\n", encoding="utf-8")
        print(f"寫出 {a.out}")
    else:
        print(header + body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
