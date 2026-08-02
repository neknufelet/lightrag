#!/usr/bin/env python3
"""實體碎片化：找出同一個概念被抽成多個節點的情形，並**照實際代價排序**。

為什麼不是「找出重複就合併」：

1. 碎片化**不會讓你查不到東西**。實測查 "wavenumber k0"，10 個變體全部回到
   結果裡 —— 向量檢索用的是名稱與描述的 embedding，這些名字在向量空間裡
   本來就緊鄰。「問 k₀ 只會找到其中一個」是錯的直覺。

2. 真正的代價是**佔格位**，而格位會直接擠掉原文：
       operate.py:5230
       available_chunk_tokens = max_total_tokens - (… + kg_context_tokens + …)
   實測 5 個查詢平均浪費 4.8% 的實體格位，但分布極不平均 —— 符號密集的
   查詢 18%，散文查詢 0%。

3. 合併不可逆（來源節點被刪除，關係搬到目標）。用 4.8% 的平均值去換 388 次
   不可逆操作不划算，而且數學裡 `S_n` 與 `S_N` 可能真的是兩回事。

所以這支做的是：分層 → 跑代表性查詢 → **只把真的出現在檢索結果裡的組**列成
候選，按浪費的格位數排序。沒被檢索到的長尾不值得冒險。

用法：
    ./entity-merge.py plan                 # 唯讀，產出候選清單
    ./entity-merge.py plan --queries 30    # 多跑幾個查詢，統計更穩

輸出：DATA_ROOT/<ws>/postprocess/entity-merge.json（含分層、代價、建議正規名）
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
import unicodedata
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mineru_common import load_env  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DATA_ROOT = Path(os.environ.get("PP_DATA_ROOT", "/data/rag/lightrag"))
SEP = re.compile(r"[\s_\-.,()]+")


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def toks(s: str) -> list[str]:
    """在**原字串**上斷詞。

    先拿掉分隔符再找詞邊界會毀掉「這個字元是下標」的訊息 —— 實測第一版就是
    這樣：`Eta_N` 去掉底線變成 `EtaN`，於是 `N` 落在一個四字母的「詞」裡，
    `Eta_N` 與 `Eta_n` 被判成「只差英文詞大小寫」的安全組。它們差的正是下標。
    """
    return [t for t in SEP.split(fold(s)) if t]


def group_key(s: str) -> str:
    return "".join(toks(s)).lower()


def tier(group: list[str]) -> str:
    """A：只差分隔符（大小寫完全一致）—— 純排版差異，沒有語意風險
       B：只差長度 >= 3 的英文詞大小寫 —— 標題式大寫，安全
       C：差在下標／短記號，或 token 數對不齊 —— 數學裡那是意義，要人看

    C 不是「壞的候選」，是「不能自動判斷的候選」。實測最貴的一組
    （Wavenumber / Wave Number 家族，單一查詢就佔 10 格）正是落在 C ——
    token 數不同。所以 C 必須人工過目，不能因為它需要人力就跳過。
    """
    ts = [toks(x) for x in group]
    if len({"".join(t) for t in ts}) == 1:
        return "A"
    if len({len(t) for t in ts}) != 1:
        return "C"
    ref = ts[0]
    for other in ts[1:]:
        for a, b in zip(ref, other):
            if a == b:
                continue
            if a.lower() != b.lower() or len(a) < 3 or not a.isalpha():
                return "C"
    return "B"


def canonical(group: list[str]) -> str:
    """建議保留哪一個。

    偏好：有分隔符的（`k_0` 讀得出下標，`k0` 讀不出）> 長的 > 字典序。
    這只是建議，最終由人決定 —— 合併會刪掉其餘節點。
    """
    return sorted(group, key=lambda s: (-len(SEP.findall(s)), -len(s), s))[0]


class Rag:
    def __init__(self, env: dict):
        self.host = f"http://{env.get('BIND_ADDR', '100.87.88.7')}:{env.get('HOST_PORT', '9621')}"
        self.key = env.get("LIGHTRAG_API_KEY", "")

    def _req(self, path: str, method="GET", body=None, timeout=240):
        r = urllib.request.Request(
            self.host + path, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"X-API-Key": self.key, "Content-Type": "application/json"})
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return json.loads(resp.read() or "{}")

    def labels(self) -> list[str]:
        return self._req("/graph/label/list")

    def popular(self, n: int) -> list[str]:
        return self._req(f"/graph/label/popular?limit={n}")

    def entities_for(self, query: str, top_k: int) -> list[str]:
        # chunk_top_k=1：我們只要實體清單，不需要原文。設 0 會被當成「不限制」，
        # 所以給 1 —— 少搬幾十 KB 的 chunk 過來。
        d = self._req("/query/data", "POST",
                      {"query": query, "mode": "mix", "only_need_context": True,
                       "top_k": top_k, "chunk_top_k": 1}).get("data") or {}
        return [e.get("entity_name") for e in (d.get("entities") or []) if e.get("entity_name")]


def cmd_plan(a, env) -> int:
    rag = Rag(env)
    labels = rag.labels()
    print(f"實體 {len(labels)} 個")

    groups: dict[str, list[str]] = collections.defaultdict(list)
    for l in labels:
        groups[group_key(l)].append(l)
    dups = {k: sorted(v) for k, v in groups.items() if len(v) > 1}
    by_tier = collections.Counter(tier(v) for v in dups.values())
    extra = sum(len(v) - 1 for v in dups.values())
    print(f"重複組 {len(dups)}、多餘節點 {extra}（{extra/len(labels):.1%}）"
          f"　A {by_tier['A']}　B {by_tier['B']}　C {by_tier['C']} 組")

    # ── 查詢集：用高分支度的實體名當種子 ──
    # 不自己編查詢 —— 編出來的會偏向我想得到的主題。用圖譜自己回報的熱門標籤，
    # 反映的是這個知識庫實際被檢索時的樣子。
    seeds = rag.popular(a.queries)
    print(f"\n跑 {len(seeds)} 個查詢統計實際佔用（每個都要 LLM 抽關鍵詞，會慢）…")

    cost: dict[str, int] = collections.Counter()      # group_key → 浪費的格位數
    hits: dict[str, set] = collections.defaultdict(set)
    slots = 0
    for i, q in enumerate(seeds, 1):
        try:
            ents = rag.entities_for(q, a.top_k)
        except Exception as e:                        # noqa: BLE001
            print(f"  [{i}/{len(seeds)}] {q[:40]:42s} 查詢失敗：{type(e).__name__}")
            continue
        slots += len(ents)
        c = collections.Counter(group_key(e) for e in ents)
        waste = 0
        for k, n in c.items():
            if n > 1 and k in dups:
                cost[k] += n - 1
                hits[k].update(e for e in ents if group_key(e) == k)
                waste += n - 1
        print(f"  [{i}/{len(seeds)}] {q[:40]:42s} 實體 {len(ents):3d}　浪費 {waste:2d}")

    ranked = []
    for k, w in cost.most_common():
        g = dups[k]
        ranked.append({"tier": tier(g), "wasted_slots": w, "members": g,
                       "seen_together": sorted(hits[k]), "suggest_keep": canonical(g)})
    silent = [k for k in dups if k not in cost]

    out_dir = DATA_ROOT / a.workspace / "postprocess"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "entity-merge.json"
    out.write_text(json.dumps({
        "entities": len(labels), "duplicate_groups": len(dups), "extra_nodes": extra,
        "queries": len(seeds), "entity_slots": slots,
        "wasted_slots": sum(cost.values()),
        "candidates": ranked,
        "never_retrieved": [{"tier": tier(dups[k]), "members": dups[k]} for k in silent],
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n{'-'*74}")
    print(f"{slots} 個實體格位中浪費 {sum(cost.values())} 格"
          f"（{sum(cost.values())/max(slots,1):.1%}）")
    print(f"真的被檢索到的重複組 {len(ranked)}／{len(dups)}；"
          f"另外 {len(silent)} 組從未出現在結果裡 —— 那些合併了也不會改善什麼")
    print(f"\n── 值得處理的（按浪費格位排序，前 20）──")
    for r in ranked[:20]:
        print(f"  {r['wasted_slots']:2d} 格  [{r['tier']}]  保留 {r['suggest_keep']!r}")
        print(f"          {r['members']}")
    print(f"\n候選清單：{out}")
    print("這一步完全唯讀。合併是破壞性的（來源節點會被刪掉），"
          "動手前要先把受影響節點的邊 dump 下來。")
    return 0


def main() -> int:
    env = load_env(REPO)
    ap = argparse.ArgumentParser(description="實體碎片化：分層 + 依實際代價排序")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="唯讀，產出候選清單")
    p.add_argument("--workspace", default=env.get("WORKSPACE", "acoustics_v155"))
    p.add_argument("--queries", type=int, default=30, help="用幾個熱門標籤當查詢種子")
    p.add_argument("--top-k", type=int, default=40, help="每個查詢取幾筆圖譜內容")
    a = ap.parse_args()
    return {"plan": cmd_plan}[a.cmd](a, env)


if __name__ == "__main__":
    sys.exit(main())
