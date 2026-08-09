#!/usr/bin/env python3
r"""實體碎片化：找出同一個概念被抽成多個節點的情形，並**照實際代價排序**。

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
    ./entity-merge.py review --top 8       # 產人工審查表（附原文段落）

輸出：DATA_ROOT/work/crops/entity-merge.json（含分層、代價、建議正規名）
      DATA_ROOT/work/crops/entity-merge-review.md（審查表）

為什麼審查表一定要附原文：實測第一組 `Z m` / `ZM` / `Zm`，三個節點的
description 看起來像三個相關概念，撈出原文才發現

    Z m   chunk-008  電-力學類比表          → 真的是力學阻抗
    ZM    chunk-019  \mathrm{Z_{Ma}, Z_{Mi}}  → 一整族的截斷
    Zm    chunk-102  $Z_{\mathrm{Mi}} = …$    → 其實是 Z_Mi，讀掉了 i

合併它們是錯的，而 `Zm` 該併的是**另一組** `Z Mi / ZMi / Z_Mi / Zmi`。
description 是模型的轉述，會錯；原文不會。所以兩欄並列，不一致時以原文為準。
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mineru_common import add_workspace_arg, load_env  # noqa: E402
from pp.paths import DataPaths, configured_data_root  # noqa: E402
from pp.ragapi import Rag  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DATA_ROOT = configured_data_root()


def _paths() -> DataPaths:
    return DataPaths(DATA_ROOT)
SEP = re.compile(r"[\s_\-.,()]+")
# LightRAG 用這個字串串接多值欄位（source_id、file_path）
def SEPS(v: str) -> list[str]:
    return [x for x in (v or "").split("<SEP>") if x.strip()]


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
        # 長度不同是設計：比共同前綴，短的先停就是要的行為。
        for a, b in zip(ref, other, strict=False):
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


# `Rag` 2026-08-09 搬到 `pp/ragapi.py`（見檔頭說明）。行為逐字不變，只補了型別註解
# 與 `delete_entity` / `entity_exists`。搬出去是因為 `graph-clean.py` 也要動圖譜 ——
# 兩支各寫一份 `_req`，逾時、標頭、錯誤處理就會各自漂走。


def cmd_plan(a, env) -> int:
    rag = Rag(env)
    labels = rag.labels()
    print(f"實體 {len(labels)} 個")

    groups: dict[str, list[str]] = collections.defaultdict(list)
    for label in labels:
        groups[group_key(label)].append(label)
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

    out_dir = _paths().crops_dir
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
    print("\n── 值得處理的（按浪費格位排序，前 20）──")
    for r in ranked[:20]:
        print(f"  {r['wasted_slots']:2d} 格  [{r['tier']}]  保留 {r['suggest_keep']!r}")
        print(f"          {r['members']}")
    print(f"\n候選清單：{out}")
    print("這一步完全唯讀。合併是破壞性的（來源節點會被刪掉），"
          "動手前要先把受影響節點的邊 dump 下來。")
    return 0



# ── 讓原文讀得懂 ──────────────────────────────────────────────
# chunk 裡的數學是 MinerU 吐的 LaTeX，字體指令多到蓋掉內容：
#   $\mathsf { Z } _ { \mathsf { M i } } = \mathsf { Z } _ { \mathsf { s h } }$
# 直接貼進審查表，人得先在腦裡剝一層才看得到符號。剝掉字體指令、把
# `_ { M i }` 收成 `_Mi` 之後變成 `$Z_Mi = Z_sh$`，一眼就認得出來。
# 這裡只為了**閱讀**，不參與任何比對判斷 —— 比對用 crosscheck.eq_normalize。
_FONT = re.compile(
    r"\\(?:displaystyle|textstyle|scriptstyle|mathrm|mathit|mathbf|mathsf|mathcal|"
    r"mathtt|mathfrak|mathbb|mathnormal|boldsymbol|boldmath|pmb|"
    r"bf|rm|it|sf|tt|text|left|right|Bigg|bigg|Big|big|,|;|!|:|quad|qquad)"
    r"(?![a-zA-Z])")


def readable(latex: str) -> str:
    t = _FONT.sub("", latex or "")
    t = re.sub(r"\{\s*([^{}]*?)\s*\}", lambda m: m.group(1).replace(" ", ""), t)
    t = re.sub(r"\s*([_^])\s*", r"\1", t)
    return re.sub(r"\s{2,}", " ", t).strip()


def _runs(tok: str) -> list[str]:
    """把一個 token 拆成字母／數字的連續段，並在大寫後接小寫處斷開。

    `J0` → ['J','0']、`Zm` → ['Z','m']、`Bessel` → ['Bessel']。
    因為原文寫的是 `$J_{0}$`、`Z_{m}`，實體名卻是 `J0`、`Zm` —— 不拆就永遠
    對不上，審查表整欄變成「找不到原樣字串」而那是假的。
    """
    return re.findall(r"[A-Z][a-z]+|[A-Z]+(?![a-z])|[a-z]+|\d+", tok) or [tok]


_GLUE = r"(?:[\s_^{}$()\\]|\\[a-zA-Z]+)*"


def variant_patterns(name: str) -> list[tuple[str, re.Pattern]]:
    """由嚴到寬的幾種找法。回傳 (層級說明, pattern)，第一個命中的就用。

    嚴格比對對多詞概念名沒有用：`Bessel Function J0` 在原文裡是
    「Bessel function $J_{0}$」，中間隔著 `$` 與 `_{}`。所以 token 之間允許
    任何分隔／括號／字體指令。真的找不到時才退到只找符號尾巴 —— 那才是
    同組成員之間唯一不同的地方。
    """
    runs = [r for t in toks(name) for r in _runs(t)]
    out = [("完整名稱", re.compile(_GLUE.join(map(re.escape, runs)) + r"(?![A-Za-z])", re.I))]
    if len(runs) > 1:
        tail = runs[-2:]
        out.append(("符號部分 " + "".join(tail),
                    re.compile(_GLUE.join(map(re.escape, tail)) + r"(?![A-Za-z])", re.I)))
    # 最後一層：拿掉「後面不可以接字母」這個限制。命中代表原文其實是更長的
    # 符號，實體名是被截斷的 —— 那不是該合併，是該改名。
    # 實測 `Zm` 的來源寫的是 $Z_{Mi}$、`ZM` 的來源寫的是 Z_{Ma}, Z_{Mi}；
    # 只報「找不到」的話，看的人不知道原文到底寫了什麼，也就無從判斷。
    # 逐字元拆。`Zm` 用 _runs 會被 [A-Z][a-z]+ 整個吃成一個「詞」，於是 Z 與 m
    # 中間插不進 `_{\mathrm{`，永遠對不到原文的 $Z_{Mi}$ —— 實測就是這樣。
    # 黏著長度封在 12 以內，否則兩個字母可以隔半個 chunk 相認。
    chars = [c for c in "".join(toks(name)) if c.strip()]
    loose = "(?:[\\s_^{}$()\\\\]|\\\\[a-zA-Z]+){0,12}"
    out.append(("延伸形式（原文比這個名字長）",
                re.compile(loose.join(map(re.escape, chars)), re.I)))
    return out


class Pg:
    """chunk 原文只在 Postgres 裡，而 Postgres 只在 docker 網路內（host 解不到
    這個名字，也沒有 psycopg2）。POSTGRES_HOST 剛好就是容器名，直接 exec。"""

    def __init__(self, env: dict):
        self.c = env.get("POSTGRES_HOST", "")
        self.env = env

    def chunks(self, ids: list[str]) -> dict[str, str]:
        if not ids or not self.c:
            return {}
        lst = ",".join("'" + i.replace("'", "''") + "'" for i in ids)
        sql = (f"SELECT id || E'\\x01' || content || E'\\x02' "
               f"FROM lightrag_doc_chunks WHERE id IN ({lst});")
        out = subprocess.run(
            ["docker", "exec", "-i", "-e", f"PGPASSWORD={self.env.get('POSTGRES_PASSWORD','')}",
             self.c, "psql", "-U", self.env.get("POSTGRES_USER", ""),
             "-d", self.env.get("POSTGRES_DATABASE", ""), "-At", "-c", sql],
            capture_output=True, text=True, timeout=120, check=False)
        res = {}
        for blk in out.stdout.split("\x02"):
            if "\x01" in blk:
                k, _, v = blk.partition("\x01")
                res[k.strip()] = v
        return res



# ── 手機版 ──────────────────────────────────────────────────
# markdown 表格在手機上會爆版：五欄、其中兩欄是長 LaTeX。改成每個變體一個
# 區塊、原文獨立成引文，決定用大按鈕。點完按「複製決定」產生純文字貼回來，
# 不必在手機上編輯檔案。
_PAGE = r"""<title>實體合併審查</title>
<style>
:root{
  --ground:#F6F7F9; --panel:#FFFFFF; --ink:#171B21; --muted:#666E79;
  --rule:#DCE0E6; --accent:#1F4E79; --accent-soft:#E8EFF6;
  --safe:#3D7A5B; --care:#9A6A21; --weak:#A3453A; --quote:#F1F3F6;
}
@media (prefers-color-scheme:dark){
  :root{
    --ground:#101317; --panel:#171B21; --ink:#E2E6EB; --muted:#8A929C;
    --rule:#262C34; --accent:#7FB0DC; --accent-soft:#1B2A38;
    --safe:#71B58F; --care:#D2A45B; --weak:#D98177; --quote:#1B2027;
  }
}
:root[data-theme="dark"]{
  --ground:#101317; --panel:#171B21; --ink:#E2E6EB; --muted:#8A929C;
  --rule:#262C34; --accent:#7FB0DC; --accent-soft:#1B2A38;
  --safe:#71B58F; --care:#D2A45B; --weak:#D98177; --quote:#1B2027;
}
:root[data-theme="light"]{
  --ground:#F6F7F9; --panel:#FFFFFF; --ink:#171B21; --muted:#666E79;
  --rule:#DCE0E6; --accent:#1F4E79; --accent-soft:#E8EFF6;
  --safe:#3D7A5B; --care:#9A6A21; --weak:#A3453A; --quote:#F1F3F6;
}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);
  font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans TC",
  "PingFang TC","Microsoft JhengHei",sans-serif;
  -webkit-text-size-adjust:100%;padding-bottom:88px}
.wrap{max-width:640px;margin:0 auto;padding:0 16px}
code,.mono{font-family:ui-monospace,SFMono-Regular,"SF Mono",Menlo,
  "Cascadia Mono","Roboto Mono",monospace}
h1{font-size:22px;line-height:1.3;margin:28px 0 6px;text-wrap:balance;
  letter-spacing:-.01em}
.lede{color:var(--muted);font-size:14.5px;margin:0 0 20px}
.label{font-size:11px;letter-spacing:.09em;text-transform:uppercase;
  color:var(--muted);font-weight:600}
.how{background:var(--panel);border:1px solid var(--rule);padding:14px 16px;
  margin-bottom:26px}
.how dl{margin:10px 0 0;display:grid;grid-template-columns:auto 1fr;
  gap:6px 12px;font-size:14px}
.how dt{font-weight:650;white-space:nowrap}
.how dd{margin:0;color:var(--muted)}
.note{font-size:13.5px;color:var(--muted);border-left:2px solid var(--care);
  padding:2px 0 2px 10px;margin:12px 0 0}
.grp{background:var(--panel);border:1px solid var(--rule);margin-bottom:22px}
.grp>header{padding:13px 16px;border-bottom:1px solid var(--rule);
  display:flex;flex-wrap:wrap;gap:8px;align-items:baseline}
.rank{font-variant-numeric:tabular-nums;font-weight:700;font-size:13px;
  color:var(--accent)}
.cost{font-size:13px;color:var(--muted);font-variant-numeric:tabular-nums}
.chip{font-size:11px;letter-spacing:.06em;text-transform:uppercase;
  font-weight:650;padding:2px 7px;border:1px solid currentColor}
.chip.safe{color:var(--safe)} .chip.care{color:var(--care)}
.v{padding:14px 16px;border-bottom:1px solid var(--rule)}
.v:last-of-type{border-bottom:0}
.vname{font-size:16px;font-weight:650;word-break:break-word}
.vmeta{font-size:12.5px;color:var(--muted);margin-top:3px;
  font-variant-numeric:tabular-nums}
.vdesc{font-size:14px;margin-top:9px}
.q{margin-top:9px;background:var(--quote);border-left:2px solid var(--rule);
  padding:9px 11px;font-size:13px;overflow-x:auto;white-space:pre-wrap;
  word-break:break-word}
.q .src{display:block;font-size:11px;letter-spacing:.06em;
  text-transform:uppercase;font-weight:650;margin-bottom:5px}
.lvl-ok .src{color:var(--safe)} .lvl-loose .src{color:var(--care)}
.lvl-none{border-left-color:var(--weak)} .lvl-none .src{color:var(--weak)}
.decide{padding:12px 16px;background:var(--accent-soft)}
.opt{display:flex;gap:10px;align-items:flex-start;padding:11px 12px;
  border:1px solid var(--rule);background:var(--panel);margin-bottom:7px;
  cursor:pointer;font-size:14.5px;min-height:44px}
.opt:last-child{margin-bottom:0}
.opt input{margin:3px 0 0;accent-color:var(--accent);width:18px;height:18px;
  flex:none}
.opt:has(input:checked){border-color:var(--accent);
  box-shadow:inset 0 0 0 1px var(--accent)}
.opt:focus-within{outline:2px solid var(--accent);outline-offset:1px}
.free{width:100%;margin-top:8px;padding:9px 10px;font-size:14px;
  border:1px solid var(--rule);background:var(--panel);color:var(--ink)}
.free[hidden]{display:none}
footer{position:fixed;left:0;right:0;bottom:0;background:var(--panel);
  border-top:1px solid var(--rule);padding:10px 16px;display:flex;
  gap:12px;align-items:center;justify-content:space-between}
.prog{font-size:13.5px;color:var(--muted);font-variant-numeric:tabular-nums}
button{font:inherit;font-size:14.5px;font-weight:650;padding:11px 16px;
  border:1px solid var(--accent);background:var(--accent);color:var(--panel);
  cursor:pointer;min-height:44px}
button:disabled{opacity:.45;cursor:default}
.toast{position:fixed;left:50%;transform:translateX(-50%);bottom:96px;
  background:var(--ink);color:var(--ground);padding:10px 16px;font-size:14px;
  opacity:0;pointer-events:none;transition:opacity .18s}
.toast.on{opacity:1}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
</style>
<div class="wrap">
<h1>實體合併審查</h1>
<p class="lede">前 8 組，依實際浪費的檢索格位排序。點完按最下面的「複製決定」。</p>
<div class="how">
  <span class="label">怎麼判</span>
  <dl>
    <dt>是同一個</dt><dd>合併 —— 關係搬到你選的名字，其餘節點刪除，不可逆</dd>
    <dt>不是</dt><dd>不動 —— 維持現狀，繼續各佔一格</dd>
    <dt>名字讀錯</dt><dd>改名 —— 不刪節點</dd>
  </dl>
  <p class="note"><b>抽取器認為</b>是模型寫的描述，<b>原文</b>是它實際讀到的字。
  兩者不一致時以原文為準 —— 描述是轉述，會錯。<br>
  標<b>延伸形式</b>的比對放得很寬，可能配到不相干的位置；看起來不像的就當作沒找到。</p>
</div>
<div id="groups"></div>
</div>
<footer><span class="prog" id="prog">已決定 0 / 8</span>
<button id="copy" disabled>複製決定</button></footer>
<div class="toast" id="toast">已複製</div>
<script>
const DATA = __DATA__;
const KEY = "entity-merge-decisions-v1";
const state = JSON.parse(localStorage.getItem(KEY) || "{}");
const esc = s => String(s).replace(/[&<>"]/g, c =>
  ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

function lvlClass(l){
  if (l === "找不到") return "lvl-none";
  if (l.startsWith("延伸")) return "lvl-loose";
  return "lvl-ok";
}
document.getElementById("groups").innerHTML = DATA.map((g, i) => `
<section class="grp">
  <header>
    <span class="rank">第 ${i + 1} 名</span>
    <span class="cost">浪費 ${g.wasted} 格</span>
    <span class="chip ${g.tier === "C" ? "care" : "safe"}">${
      g.tier === "C" ? "需人看" : "格式差異"}</span>
  </header>
  ${g.rows.map(r => `
  <div class="v">
    <div class="vname mono">${esc(r.name)}</div>
    <div class="vmeta">${esc(r.docs.join("、"))} · ${esc(r.chunk)} · ${
      r.degree} 條關係${r.n_chunks > 1 ? ` · ${r.n_chunks} 個來源` : ""}</div>
    <div class="vdesc">${esc(r.desc)}</div>
    <div class="q ${lvlClass(r.level)}"><span class="src">${
      r.level === "找不到" ? "原文找不到" : "原文 · " + esc(r.level)
    }</span><span class="mono">${esc(r.quote)}</span></div>
  </div>`).join("")}
  <div class="decide">
    ${[["merge", `合併成 <code>${esc(g.keep)}`+"</code>"],
       ["keep", "不合併（是不同的東西）"],
       ["other", "合併成別的 / 改名 / 其他"]].map(([v, t]) => `
    <label class="opt"><input type="radio" name="g${i}" value="${v}"
      ${state[i] && state[i].choice === v ? "checked" : ""}><span>${t}</span></label>`).join("")}
    <input class="free" id="f${i}" placeholder="寫下你的決定，例如：Zm 改名成 Z_Mi"
      value="${state[i] ? esc(state[i].free || "") : ""}"
      ${state[i] && state[i].choice === "other" ? "" : "hidden"}>
  </div>
</section>`).join("");

function sync(){
  const n = DATA.filter((_, i) => state[i] && state[i].choice).length;
  document.getElementById("prog").textContent = `已決定 ${n} / ${DATA.length}`;
  document.getElementById("copy").disabled = n === 0;
  localStorage.setItem(KEY, JSON.stringify(state));
}
document.addEventListener("change", e => {
  const m = /^g(\d+)$/.exec(e.target.name || "");
  if (!m) return;
  const i = m[1];
  state[i] = Object.assign({}, state[i], {choice: e.target.value});
  document.getElementById("f" + i).hidden = e.target.value !== "other";
  sync();
});
document.addEventListener("input", e => {
  const m = /^f(\d+)$/.exec(e.target.id || "");
  if (!m) return;
  state[m[1]] = Object.assign({}, state[m[1]], {free: e.target.value});
  sync();
});
document.getElementById("copy").addEventListener("click", async () => {
  const lines = ["實體合併決定："];
  DATA.forEach((g, i) => {
    const st = state[i];
    if (!st || !st.choice) return;
    const what = st.choice === "merge" ? `合併成 ${g.keep}`
      : st.choice === "keep" ? "不合併"
      : (st.free || "其他（未填）");
    lines.push(`${i + 1}. ${g.members.join(" / ")} → ${what}`);
  });
  const text = lines.join("\n");
  try { await navigator.clipboard.writeText(text); }
  catch (_) {
    const t = document.createElement("textarea");
    t.value = text; document.body.appendChild(t); t.select();
    document.execCommand("copy"); t.remove();
  }
  const el = document.getElementById("toast");
  el.classList.add("on"); setTimeout(() => el.classList.remove("on"), 1600);
});
sync();
</script>
"""


def render_html(groups: list[dict]) -> str:
    payload = json.dumps(groups, ensure_ascii=False).replace("</", "<\\/")
    return _PAGE.replace("__DATA__", payload)


def cmd_review(a, env) -> int:
    rag, pg = Rag(env), Pg(env)
    src = _paths().crops_dir / "entity-merge.json"
    if not src.is_file():
        sys.exit(f"找不到 {src}，先跑 `entity-merge.py plan`")
    plan = json.loads(src.read_text())
    cands = plan["candidates"][: a.top]
    print(f"審查前 {len(cands)} 組（共 {len(plan['candidates'])} 組被檢索到）")

    # 先把節點資料抓齊，再一次向 Postgres 要 chunk —— 每組各問一次會開 N 個
    # docker exec，慢且吵。
    info: dict[str, dict] = {}
    for g in cands:
        for m in g["members"]:
            if m in info:
                continue
            try:
                ns = rag.subgraph(m)
            except Exception:                                  # noqa: BLE001
                ns = {"nodes": [], "edges": []}
            node = next((n for n in (ns.get("nodes") or []) if n["labels"][0] == m), None)
            p = (node or {}).get("properties") or {}
            # 邊的 source/target 是**數值節點 id**，不是 label。拿 label 去比
            # 永遠不相等，度數整欄變成 0 —— 而 0 看起來像「這個節點沒關係、
            # 合併很安全」，剛好是最會誤導人的方向。
            nid = str((node or {}).get("id", ""))
            deg = sum(1 for e in (ns.get("edges") or [])
                      if nid and nid in (str(e.get("source")), str(e.get("target"))))
            # source_id / file_path 是 **<SEP> 串接的清單**，不是單一值 ——
            # 一個實體可能被多個 chunk 提到。實測拿整串當 id 查，26 個只回 14 個，
            # 而缺的那些不會報錯，只是審查表上出現「找不到原文」。
            info[m] = {"docs": SEPS(p.get("file_path", "")),
                       "chunks": SEPS(p.get("source_id", "")),
                       "desc": p.get("description", ""), "degree": deg,
                       "type": p.get("entity_type", "")}
    want = sorted({c for v in info.values() for c in v["chunks"]})
    texts = pg.chunks(want)
    print(f"取得 {len(texts)}／{len(want)} 個 chunk 原文")

    groups = []
    for g in cands:
        rows = []
        for m in g["members"]:
            d = info[m]
            quote, where, level = "", "", "找不到"
            for lv, pat in variant_patterns(m):
                for cid in d["chunks"]:
                    body = texts.get(cid, "")
                    hit = pat.search(body)
                    if not hit:
                        continue
                    lo, hi = max(0, hit.start() - 160), min(len(body), hit.end() + 160)
                    quote, where, level = readable(body[lo:hi]), cid[-9:], lv
                    break
                if quote:
                    break
            if not quote:
                where = d["chunks"][0][-9:] if d["chunks"] else "?"
                quote = f"{len(d['chunks'])} 個來源 chunk 都找不到"
            rows.append({"name": m, "docs": sorted({Path(x).stem for x in d["docs"]}),
                         "chunk": where, "degree": d["degree"], "desc": d["desc"],
                         "quote": quote, "level": level,
                         "n_chunks": len(d["chunks"])})
        groups.append({"members": g["members"], "tier": g["tier"],
                       "wasted": g["wasted_slots"], "keep": g["suggest_keep"],
                       "rows": rows})

    out_dir = _paths().crops_dir
    (out_dir / "entity-merge-review.json").write_text(
        json.dumps(groups, ensure_ascii=False, indent=1), encoding="utf-8")

    L = ["# 實體合併審查", "",
         f"前 {len(cands)} 組，來自 `entity-merge.py plan` 的代價排序。", "",
         "## 怎麼判", "",
         "每組要決定的是：**這幾個名字指的是同一個東西嗎?**", "",
         "| 判斷 | 動作 | 後果 |",
         "|---|---|---|",
         "| 是同一個 | 合併 | 關係搬到你選的名字，其餘節點**刪除**，不可逆 |",
         "| 不是 | 不動 | 維持現狀，繼續各佔一格 |",
         "| 名字讀錯了 | 改名 | 用 `/graph/entity/edit`，不刪節點 |", "",
         "看兩欄：**抽取器認為**是模型寫的描述，**原文寫的**是它實際讀到的字。",
         "兩者不一致時**以原文為準** —— 描述是模型的轉述，會錯。已經標了 ⚠️。", "",
         "> 標「比對到延伸形式」的那幾列，比對規則放得很寬（允許符號中間插入",
         "> LaTeX 指令），**可能配到不相干的位置**。看起來不像的就當作沒找到，",
         "> 不要拿它當證據。標「完整名稱」「符號部分」的才是可靠的命中。", "",
         "`關係數` 是這個節點連著幾條邊。合併時這些邊會搬到目標節點。", "", "---", ""]

    for i, g in enumerate(groups, 1):
        L += [f"## {i}. {' / '.join(g['members'])}", "",
              f"浪費 **{g['wasted']} 格**　層級 **{g['tier']}**"
              f"　建議保留 `{g['keep']}`", "",
              "| 名字 | 出處 | 關係數 | 抽取器認為 | 原文寫的 |",
              "|---|---|---|---|---|"]
        mismatch = False
        for r in g["rows"]:
            q = r["quote"].replace("|", chr(92) + "|")
            if r["level"] == "找不到":
                q = f"**{q}**"
                mismatch = True
            elif r["level"] != "完整名稱":
                q = f"（{r['level']}）…{q}…"
            else:
                q = f"…{q}…"
            docs = "、".join(x[:18] for x in r["docs"]) or "?"
            L.append(f"| `{r['name']}` | {docs}<br>`{r['chunk']}` | {r['degree']} | "
                     f"{r['desc'][:90].replace('|', chr(92) + '|')} | {q[:200]} |")
        L += ["", "**選一個**（打勾）", "",
              f"- [ ] 合併成 `{g['keep']}`",
              "- [ ] 合併成別的：`________`",
              "- [ ] 不合併（是不同的東西）",
              "- [ ] 改名：`________` → `________`", ""]
        if mismatch:
            L += ["> ⚠️ 有成員在來源 chunk 裡找不到原樣的字串。",
                  "> 那代表名字是模型「推」出來的，不是照抄 —— 特別要看原文再決定。", ""]
        L += ["---", ""]

    out = _paths().crops_dir / "entity-merge-review.md"
    out.write_text("\n".join(L), encoding="utf-8")
    html = out.with_suffix(".html")
    html.write_text(render_html(groups), encoding="utf-8")
    print(f"\n審查表：{out}\n手機版：{html}")
    print("全程唯讀。勾完把檔案給我，我再做邊的 dump 與實際合併。")
    return 0


def cmd_dump(a, env) -> int:
    """把指定節點與它們的邊完整存下來 —— 合併前唯一的回頭路。

    merge 會刪掉來源節點，關係搬到目標。LightRAG 沒有 undo，Neo4j 也沒有為
    這件事做快照。但要回復的其實只有這幾十個節點，不是整個圖譜 —— 所以備份
    它們自己與所有相鄰的邊（含 description / keywords / weight），需要時可以
    用 /graph/entity/create 與 /graph/relation/create 重建。

    邊的 source/target 在 API 裡是數值 id，換一次索引就變了，所以這裡一律
    翻成 label 再存 —— 存 id 的備份在重建時等於沒有。
    """
    rag = Rag(env)
    names = a.name or []
    if a.from_review:
        src = _paths().crops_dir / "entity-merge-review.json"
        if not src.is_file():
            sys.exit(f"找不到 {src}，先跑 review")
        names += [r["name"] for g in json.loads(src.read_text()) for r in g["rows"]]
    names = sorted(set(names))
    if not names:
        sys.exit("沒有指定節點：用 --name 或 --from-review")

    out = {"entities": {}, "relations": []}
    seen_edges, truncated = set(), []
    for i, n in enumerate(names, 1):
        try:
            sub = rag.subgraph(n)
        except Exception as e:                                   # noqa: BLE001
            print(f"  [{i}/{len(names)}] {n!r} 取不到：{type(e).__name__}")
            continue
        nodes = sub.get("nodes") or []
        if len(nodes) >= rag.SUBGRAPH_CAP:
            # 打到上限就是被截斷了。備份不完整卻宣稱成功，比沒有備份更危險。
            truncated.append(n)
        by_id = {str(x.get("id")): x["labels"][0] for x in nodes}
        me = next((x for x in nodes if x["labels"][0] == n), None)
        if me is None:
            print(f"  [{i}/{len(names)}] {n!r} 圖譜裡找不到")
            continue
        out["entities"][n] = me.get("properties") or {}
        mine = str(me.get("id"))
        k = 0
        for e in (sub.get("edges") or []):
            sid, tid = str(e.get("source")), str(e.get("target"))
            if mine not in (sid, tid):
                continue
            src_l, tgt_l = by_id.get(sid), by_id.get(tid)
            if not src_l or not tgt_l:
                continue
            key = (src_l, tgt_l)
            if key in seen_edges:
                continue
            seen_edges.add(key)
            out["relations"].append({"source": src_l, "target": tgt_l,
                                     "properties": e.get("properties") or {}})
            k += 1
        print(f"  [{i}/{len(names)}] {n:34s} 屬性 ✓　新增邊 {k}")

    # 檔名帶時間戳，而且不覆蓋既有的。實測踩過：合併完之後為了驗證又跑了一次
    # dump，直接蓋掉合併**前**那份 —— 新的那份只剩活著的 9 個節點，被刪掉的
    # 20 個連同它們的邊就沒有記錄了。備份被自己的工具蓋掉，是最沒必要的損失。
    home = _paths().crops_dir
    home.mkdir(parents=True, exist_ok=True)
    dst = home / f"entity-merge-backup.{time.strftime('%Y%m%d-%H%M%S')}.json"
    if dst.exists():
        sys.exit(f"{dst} 已存在，拒絕覆蓋")
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    latest = home / "entity-merge-backup.json"
    latest.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n備份 {len(out['entities'])} 個節點、{len(out['relations'])} 條邊 → {dst}")
    if truncated:
        print(f"  ✗ 這些節點的鄰居數打到 {rag.SUBGRAPH_CAP} 上限，備份不完整：{truncated}")
        print("    不要拿這份備份當回頭路。")
        return 2
    print("這是合併前唯一的回頭路。動手前確認這個檔案存在且節點數符合預期。")
    return 0



def cmd_apply(a, env) -> int:
    """依決定檔合併實體。**這是唯一會改圖譜的地方。**

    merge 會刪掉來源節點、把關係搬到目標，而 LightRAG 沒有 undo。所以動手前
    的檢查一條都不能省，任何一條不成立就整批拒絕 —— 合併到一半停下來比不做
    更糟，因為你不知道停在哪裡。

      1. 每個來源與目標都真的存在（打錯字會靜靜跳過那一組）
      2. 每個**要刪的**節點都在備份檔裡，否則刪掉就回不去
      3. 目標不在自己的來源清單裡
      4. 同一個名字沒有出現在兩組（先併去 A 再被 B 併走，結果看順序）
      5. pipeline 閒置 —— 抽取中改圖譜會跟 LightRAG 搶同一批節點
    """
    rag = Rag(env)
    dec = json.loads(Path(a.decisions).read_text(encoding="utf-8"))
    # 找所有時間戳備份，合起來看有沒有涵蓋要刪的節點。只看 latest 的話，
    # 一次無心的 dump 就會讓「有備份」這件事變成假的。
    home = _paths().crops_dir
    bkps = sorted(home.glob("entity-merge-backup.*.json"))

    srcs = [x for g in dec for x in g["from"]]
    tgts = [g["into"] for g in dec]
    problems = []

    if not bkps:
        problems.append(f"{home} 底下沒有備份檔 —— 先跑 `dump --from-review`")
    else:
        have = set()
        for b in bkps:
            have |= set(json.loads(b.read_text())["entities"])
        missing = [x for x in srcs if x not in have]
        if missing:
            problems.append(f"這些要刪的節點在 {len(bkps)} 份備份裡都找不到：{missing}")

    labels = set(rag.labels())
    for x in srcs + tgts:
        if x not in labels:
            problems.append(f"圖譜裡沒有 {x!r}")
    for g in dec:
        if g["into"] in g["from"]:
            problems.append(f"{g['into']!r} 同時是目標與來源")
    dup = {x for x in srcs if srcs.count(x) > 1}
    if dup:
        problems.append(f"這些名字出現在多組，結果會取決於執行順序：{sorted(dup)}")
    if a.commit and not rag.pipeline_idle():
        problems.append("pipeline 忙碌中 —— 抽取會跟我們搶同一批節點")

    print(f"實體 {len(labels)} 個；打算把 {len(srcs)} 個併進 {len(tgts)} 個")
    for g in dec:
        print(f"\n  → {g['into']}")
        for x in g["from"]:
            print(f"      {x}")
        if g.get("why"):
            print(f"      理由：{g['why']}")

    if problems:
        print("\n" + "-" * 70)
        for x in problems:
            print(f"  ✗ {x}")
        print("有問題，整批不執行。")
        return 2

    if not a.commit:
        print("\n（dry-run。檢查全過，加 --commit 才會真的合併）")
        return 0

    print("\n" + "-" * 70)
    ok = fail = 0
    for g in dec:
        try:
            rag.merge(g["from"], g["into"])
            ok += 1
            print(f"  ✓ {g['into']}　併入 {len(g['from'])} 個")
        except Exception as e:                                   # noqa: BLE001
            fail += 1
            print(f"  ✗ {g['into']}：{type(e).__name__} {str(e)[:120]}")

    after = set(rag.labels())
    left = [x for x in srcs if x in after]
    print(f"\n合併 {ok} 組、失敗 {fail} 組；實體 {len(labels)} → {len(after)}"
          f"（預期 -{len(srcs)}）")
    if left:
        print(f"  ⚠ 這些來源節點還在：{left}")
    return 2 if (fail or left) else 0


def main() -> int:
    env = load_env(REPO)
    ap = argparse.ArgumentParser(description="實體碎片化：分層 + 依實際代價排序")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="唯讀，產出候選清單")
    add_workspace_arg(p, env)
    p.add_argument("--queries", type=int, default=30, help="用幾個熱門標籤當查詢種子")
    p.add_argument("--top-k", type=int, default=40, help="每個查詢取幾筆圖譜內容")

    r = sub.add_parser("review", help="產人工審查表（附原文段落）")
    add_workspace_arg(r, env)
    r.add_argument("--top", type=int, default=8, help="審查前幾組")

    dp = sub.add_parser("dump", help="備份節點與邊（合併前必做）")
    add_workspace_arg(dp, env)
    dp.add_argument("--name", action="append", help="節點名稱，可重複")
    dp.add_argument("--from-review", action="store_true",
                    help="備份審查表裡出現過的所有節點")

    apy = sub.add_parser("apply", help="依決定檔合併（唯一會改圖譜的地方）")
    add_workspace_arg(apy, env)
    apy.add_argument("--decisions", required=True, help="決定檔（JSON）")
    apy.add_argument("--commit", action="store_true", help="真的合併（預設只檢查）")

    a = ap.parse_args()
    return {"plan": cmd_plan, "review": cmd_review,
            "dump": cmd_dump, "apply": cmd_apply}[a.cmd](a, env)


if __name__ == "__main__":
    sys.exit(main())
