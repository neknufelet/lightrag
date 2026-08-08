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

    postprocess.py canary                  # 規則漂移偵測（改規則後必跑）
    postprocess.py canary --update         # 認可目前結果為新基準

    postprocess.py prepare --commit        # 新文件：解析 → 修補 → 掃描（只抽取一次）
    postprocess.py apply --doc X           # 只算不寫（預設 dry-run）
    postprocess.py apply --doc X --commit  # **真的寫檔**
    postprocess.py revert --doc X          # 還原

check 會呼叫外部模型（本機 qwen + 雲端 luna），結果快取在
DATA_ROOT/work/crops/<doc>/cache/，重跑不會重複付費。
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mineru_common import LEAK, add_workspace_arg, load_env  # noqa: E402
from pp.docctx import DocContext, DocContextError  # noqa: E402
from pp.paths import DataPaths, configured_data_root  # noqa: E402
from pp.rules import (  # noqa: E402
    chart_type,
    empty_table,
    latex_fix,
    layout_noise,
    reference_section,
)

REPO = Path(__file__).resolve().parent.parent
DATA_ROOT = configured_data_root()


def _paths() -> DataPaths:
    return DataPaths(DATA_ROOT)


def _postprocess_passed(raw: Path) -> bool:
    """只用 manifest 的 pass marker 判斷是否已跑過後處理。"""
    from pp.apply import POSTPROCESS_PASS_KEY, POSTPROCESS_PASS_VERSION

    manifest_path = raw / "_manifest.json"
    if not manifest_path.is_file():
        return False
    marker = json.loads(manifest_path.read_text()).get(POSTPROCESS_PASS_KEY)
    return isinstance(marker, dict) and marker.get("version") == POSTPROCESS_PASS_VERSION


def _prepare_inventory(workspace: str) -> tuple[list[Path], list[Path], list[Path]]:
    """回傳待解析、已解析未修補、以及已完成後處理 pass 的 bundle。"""
    paths = _paths()
    inputs = paths.inputs_dir(workspace)
    parsed = paths.parsed_dir
    pending = [p for p in sorted(inputs.glob("*.pdf"))
               if not (paths.parsed_bundle_dir(p.name) / "content_list.json").is_file()]
    ready: list[Path] = []
    passed: list[Path] = []
    for raw in sorted(parsed.glob("*.mineru_raw")):
        if not (raw / "content_list.json").is_file():
            continue
        (passed if _postprocess_passed(raw) else ready).append(raw)
    return pending, ready, passed


def _prepare_target_state(bundles: list[Path]) -> str:
    """描述本輪 prepare 目標在未送 scan 前的狀態。"""
    if not bundles:
        return "沒有本輪待修補的 bundle"
    passed = sum(1 for raw in bundles if _postprocess_passed(raw))
    pending = len(bundles) - passed
    states = []
    if pending:
        states.append(f"已解析未修補 {pending} 份")
    if passed:
        states.append(f"已修補未索引 {passed} 份")
    return "、".join(states)


def _scan_was_skipped_pipeline_busy(response: object) -> bool:
    """從 scan JSON 的任意巢狀欄位辨識「沒有排程」的回應。"""
    if isinstance(response, dict):
        return any(_scan_was_skipped_pipeline_busy(value) for value in response.values())
    if isinstance(response, list):
        return any(_scan_was_skipped_pipeline_busy(value) for value in response)
    return response == "scanning_skipped_pipeline_busy"


def find_bundles(workspace: str, doc: str | None, *, allow_empty: bool = False) -> list[Path]:
    """找出 workspace 的 bundle；只有明確允許時才回傳空集合。"""
    pdir = _paths().parsed_dir
    if not pdir.is_dir():
        sys.exit(f"postprocess: 找不到解析目錄 {pdir}")
    hits = sorted(pdir.glob("*.mineru_raw"))
    if doc:
        hits = [h for h in hits if doc.lower() in h.name.lower()]
    if not hits and not allow_empty:
        sys.exit(f"postprocess: 沒有符合的 bundle（doc={doc!r}）")
    return hits


def plan_one(raw: Path, *, source_dir: Path | None = None) -> dict:
    ctx = DocContext(raw, source_dir=source_dir)
    ctx.preflight()
    w, h = ctx.page_size
    noise = layout_noise.plan(ctx.items, ctx.n_pages)
    refs = reference_section.plan(ctx.items)
    tables = empty_table.plan(ctx.items, w, h)
    charts = chart_type.plan(ctx.items, ctx.raw_dir)
    # LaTeX 正規化在唯讀階段也要算出來。`apply` 本來就會算一次，但那時已經在
    # 寫檔 —— 唯讀看不到的修改等於沒有人審過，而 σ̂→∂ 一份文件就改 138 處公式符號。
    # 這裡傳的是 ctx.items，`latex_fix.plan` 只讀不寫。
    latex = latex_fix.plan(ctx.items)
    return {"ctx": ctx, "noise": noise, "refs": refs, "tables": tables,
            "charts": charts, "latex": latex}


def render(p: dict, details: bool) -> None:
    ctx, noise, tables = p["ctx"], p["noise"], p["tables"]
    refs = p["refs"]
    print(f"\n=== {ctx.doc_name} ===")
    print(f"  {ctx.n_pages} 頁、{len(ctx.items)} 個項目、頁面 {ctx.page_size[0]:.0f}×{ctx.page_size[1]:.0f} pt")
    print(f"  過濾：{noise.summary()}")
    print(f"  文獻：{refs.summary()}")
    print(f"  表格：{tables.summary()}")
    print(f"  圖片：{p['charts'].line()}")
    print(f"  LaTeX：{p['latex'].summary()}")

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
        "charts": {
            "convert": [{"index": c.index, "page": c.page, "img_path": c.img_path,
                         "caption": c.caption} for c in p["charts"].convert],
            "dangling": [{"index": c.index, "page": c.page, "img_path": c.img_path}
                         for c in p["charts"].dangling],
        },
    }


def cmd_check(a, env) -> int:
    from pp import eyes  # 只有 check 需要，延後載入

    paths = _paths()
    out_root = paths.crops_dir
    source_dir = paths.inputs_dir(a.workspace)
    n_auto = n_need = n_err = 0
    for raw in find_bundles(a.workspace, a.doc):
        try:
            ctx, results = eyes.check_doc(raw, env, out_root, source_dir=source_dir,
                                          workers=a.workers)
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


CANARY = REPO / "tests" / "canary-baseline.json"

# 金絲雀只比這幾個數字。比全部欄位會被無關的變動洗版（頁數、caption 文字），
# 比太少又抓不到漂移。這幾個是「規則改動一定會反映在上面」的量。
_CANARY_KEYS = ("pages", "items", "mute", "held", "ratio",
                "tables_total", "repairable", "review",
                "charts_convert", "charts_dangling",
                "latex_items", "latex_times", "latex_partials", "latex_glued",
                "latex_vetoed")


def canary_row(p: dict) -> dict:
    ctx, noise, tables = p["ctx"], p["noise"], p["tables"]
    return {"pages": ctx.n_pages, "items": len(ctx.items),
            "mute": len(noise.mutes), "held": len(noise.held),
            "ratio": round(noise.ratio, 4),
            "tables_total": tables.total,
            "repairable": len(tables.repairable),
            "review": len(tables.review),
            # 套用後這個數字會歸零（chart 都變成 image 了）。那是預期中的變化，
            # 記在基準裡就是為了讓「什麼時候轉的、轉了幾個」留在 git diff 上。
            "charts_convert": len(p["charts"].convert),
            "charts_dangling": len(p["charts"].dangling),
            # LaTeX 正規化的三個量。**在此之前這三條規則完全沒有被金絲雀守著**
            # —— `\times`（§7.4）與逐字母排版（§7.5）從落地到現在，改了多少
            # 位元組都不會出現在任何基準裡。σ̂→∂ 一份 138 處，補上這一格之後
            # 規則行為的變化才真的賴不掉。
            "latex_items": p["latex"].items,
            "latex_times": p["latex"].times,
            "latex_partials": p["latex"].partials,
            "latex_glued": p["latex"].glued,
            # 統計記號否決的項數。**這一格是探針**：本語料是 0，一旦拉進含
            # 統計分析的論文就會非 0，而那正是「有一項需要人看」的訊號。
            "latex_vetoed": len(p["latex"].vetoed)}


def cmd_canary(a, env) -> int:
    """比對目前的 plan 結果與記錄的基準。

    存在的理由：規則是一份一份文件逼出來的，每次改動都可能無意間動到別份。
    手動逐份比對數字會漏，而漏掉的漂移不會有錯誤訊息。基準進版控，
    所以規則改動造成的行為變化會直接出現在 git diff 裡，賴不掉。
    """
    paths = _paths()
    source_dir = paths.inputs_dir(a.workspace)
    cur = {}
    bundles = find_bundles(a.workspace, None, allow_empty=True)
    if not bundles:
        print("金絲雀驗不了：目前沒有任何 bundle，沒有母體可供規則漂移比對。")
        return 0
    for raw in bundles:
        try:
            cur[DocContext(raw, source_dir=source_dir).doc_name] = canary_row(
                plan_one(raw, source_dir=source_dir))
        except DocContextError as e:
            cur[raw.name.removesuffix(".mineru_raw")] = {"error": str(e)[:200]}

    if a.update:
        CANARY.parent.mkdir(parents=True, exist_ok=True)
        CANARY.write_text(json.dumps(cur, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
        print(f"基準已更新：{len(cur)} 份 → {CANARY}")
        print("記得在 commit 訊息說明每個數字為什麼變 —— 沒說明的變動等同未被察覺的漂移。")
        return 0

    if not CANARY.is_file():
        sys.exit(f"沒有基準檔 {CANARY}，先跑 `postprocess.py canary --update`")
    base = json.loads(CANARY.read_text())

    drift, added, gone = [], [], []
    for name, row in cur.items():
        if name not in base:
            added.append(name)
            continue
        for k in _CANARY_KEYS:
            if row.get(k) != base[name].get(k):
                drift.append((name, k, base[name].get(k), row.get(k)))
        if ("error" in row) != ("error" in base[name]):
            drift.append((name, "error", base[name].get("error"), row.get("error")))
    gone = [n for n in base if n not in cur]

    for n in added:
        print(f"  新增   {n}")
    for n in gone:
        print(f"  消失   {n}　← 基準有但現在找不到")
    for name, k, b, c in drift:
        print(f"  漂移   {name}\n           {k}: {b} → {c}")

    if not drift and not gone:
        print(f"金絲雀通過：{len(base)} 份基準文件的數字都沒變"
              + (f"（另有 {len(added)} 份新文件尚未納入基準）" if added else ""))
        return 0
    print(f"\n金絲雀失敗：{len(drift)} 處漂移、{len(gone)} 份消失。"
          "\n若是預期中的改動，跑 `canary --update` 並在 commit 訊息說明原因。")
    return 2


def cmd_prepare(a: argparse.Namespace, env: dict[str, str]) -> int:
    """新文件的正確順序：解析 → 修補 → 才掃描。

    為什麼順序重要：/scan 會把解析與實體抽取綁在一起跑完，之後再修補就得
    reindex，等於**抽取兩次**。抽取是本機序列的，20 份要 1.5–2 小時，
    390 份約 30 小時 —— 白跑一輪的代價太大。

    先 apply 再 scan 就只抽一次。已經索引過的文件沒有這個選擇（要走
    apply + reindex），所以這條路只適用於還沒進索引的新文件。
    """
    pending, ready, _ = _prepare_inventory(a.workspace)

    print(f"待解析 {len(pending)} 份、待修補 {len(ready)} 份")
    if not a.commit:
        for p in pending:
            print(f"  解析  {p.name[:64]}")
        for r in ready:
            print(f"  修補  {r.name.removesuffix('.mineru_raw')[:64]}")
        print("\n（dry-run。加 --commit 才會執行）")
        return 0

    if pending:
        print("\n[1/3] 解析（不觸發抽取）")
        command = [sys.executable, str(REPO / "scripts" / "parse-only.py"),
                   "--workspace", a.workspace]
        try:
            parsed = subprocess.run(command, check=False)
        except OSError as e:
            _, ready_after, _ = _prepare_inventory(a.workspace)
            print(f"\n✗ 解析失敗（{type(e).__name__}: {e}），流程停止。")
            print(f"  資料目前處於：待解析 {len(pending)} 份、已解析未修補 "
                  f"{len(ready_after)} 份；未發出 scan。")
            return 2
        if parsed.returncode != 0:
            _, ready_after, _ = _prepare_inventory(a.workspace)
            print(f"\n✗ 解析失敗（parse-only exit {parsed.returncode}），流程停止。")
            print(f"  資料目前處於：待解析 {len(_prepare_inventory(a.workspace)[0])} 份、"
                  f"已解析未修補 {len(ready_after)} 份；未發出 scan。")
            return parsed.returncode if parsed.returncode > 0 else 2

    _, ready_after, _ = _prepare_inventory(a.workspace)
    targets = ready_after
    print("\n[2/3] 修補")
    rc = cmd_apply(argparse.Namespace(workspace=a.workspace, doc=None, commit=True,
                                      no_tables=a.no_tables, workers=a.workers), env,
                    bundles=targets)
    if rc != 0:
        print(f"\n✗ 修補失敗（exit {rc}），流程停止。")
        print(f"  資料目前處於：{_prepare_target_state(targets)}；未發出 scan。")
        return rc if rc > 0 else 2

    print("\n[3/3] 掃描（此時才進抽取，只跑一次）")
    try:
        response = _api(env, "/documents/scan", "POST")
    except Exception as e:  # noqa: BLE001
        print(f"\n✗ scan 呼叫失敗（{type(e).__name__}: {e}）。")
        print(f"  資料目前處於：{_prepare_target_state(targets)}；請重跑 prepare --commit。")
        return 2
    print(" ", json.dumps(response, ensure_ascii=False)[:200])
    if _scan_was_skipped_pipeline_busy(response):
        print("\n✗ scan 沒有排程（scanning_skipped_pipeline_busy）；請等 pipeline 閒置後重跑 "
              "prepare --commit。")
        print(f"  資料目前處於：{_prepare_target_state(targets)}。")
        return 2
    return 0


def _api(env: dict, path: str, method: str = "GET", body=None):
    import urllib.request
    host = f"http://{env.get('BIND_ADDR','127.0.0.1')}:{env.get('HOST_PORT','9621')}"
    req = urllib.request.Request(
        host + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"X-API-Key": env.get("LIGHTRAG_API_KEY", ""),
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read() or "{}")


IMG_TAG = re.compile(r"<img\b[^>]*>", re.I)
# 「既有的本地參照」長這樣：`<img src="images/<sha>.jpg"/>`，MinerU 自己抽出來、
# 檔案真的在 bundle 裡。src 只准是 `images/` 底下的相對路徑，不含 `..`、不含協定
# 前綴 —— 一放行任意 src，`https://…` 只要改寫成 `images/../..` 就繞過去了。
LOCAL_IMG = re.compile(r'^<img\b[^>]*\bsrc="images/(?!.*\.\.)[^"<>]+"[^>]*/?>$', re.I)


def _gate_imgs(body: str, current: str, where: str) -> None:
    """`<img>` 的准入判準：**與現值逐位元相同的既有本地參照**才准留。

    閘門原本是「見到 `<img` 就拒絕」，擋的是**捏造**：qwen 對「這格是示意圖」的
    預設行為就是編一個 `src` 出來（C 57 張表裡 24 張吐 `<img>`，其中 8 張是不存在
    的 `https://i.imgur.com/…`）。但 C 有 26 張表的現值本來就帶 MinerU 抽出來的
    `<img src="images/<sha>.jpg">`，而「定點補格」的前提是**現值對的格一個字不動**
    —— 於是「保留既有參照」被「拒絕一切 `<img>`」一起擋掉了。

    這兩件事不是同一件：一個是**新增**一條沒人見過的參照，一個是**原樣抄回**
    現值已經有的那條。所以判準改成兩個條件同時成立：

      1. 形狀是本地的 `images/…`（外部網址、`placeholder_figure_1.png` 這種
         假檔名一律拒絕）；
      2. 這個 tag 在**該表的現值**裡逐位元存在，而且用多重集合扣 —— 現值有一個
         就只准出現一次。少了這條，「把現值的 img 複製貼上到第二格」也會通過。

    現值為空（真正的空表格，自動採用走的那條路）時 `current` 是空字串，任何
    `<img>` 都扣不到，行為與改動前完全相同。
    """
    have = collections.Counter(IMG_TAG.findall(current or ""))
    for tag in IMG_TAG.findall(body):
        if not LOCAL_IMG.match(tag):
            sys.exit(f"{where} 含 {tag[:80]} —— 拒絕使用（只准保留 MinerU 既有的"
                     "本地 images/ 參照；外部網址與假檔名一律不收，示意圖格寫 [FIGURE]）")
        if have[tag] <= 0:
            sys.exit(f"{where} 含 {tag[:80]} —— 拒絕使用（現值沒有這個參照，"
                     "或出現次數比現值多；既有參照只准原樣保留，不得新增）")
        have[tag] -= 1


def gate_table_html(body: str, where: str, current: str = "") -> str:
    """寫進 content_list 之前的最後三道閘門。**自動採用與人工裁定走同一道**。

    實測踩過（2026-08-02，C #525）：qwen 對含示意圖的儲存格**捏造了一個外部
    圖片網址** `<img src="https://i.imgur.com/…">`。`crosscheck.compare` 只比
    兩眼一不一致，完全不看 HTML 裡多出來什麼 —— 兩眼要是剛好都幻覺同一格，
    這串網址就會靜靜進索引。`vlm.py` 的 V3/V4 本來就防這個，但 apply 走的是
    快取直取那條路，沒有經過它們。第二輪（57 張全表重轉錄）又收到 8 個 imgur
    網址、16 個假本地檔名，證明那不是偶發，是 qwen 對「這格是圖」的預設行為。

    `current` 是**該表在 content_list 裡的現值**，只給 `<img>` 那一道用
    （見 `_gate_imgs`）。不傳就等於「現值沒有任何既有參照」，也就是改動前的行為。
    """
    if not re.match(r"(?s)^<table\b.*</table>$", body, re.I):
        sys.exit(f"{where} 不是單一完整的 <table>…</table>，拒絕使用")
    _gate_imgs(body, current, where)
    if LEAK.search(body):
        sys.exit(f"{where} 含 prompt 洩漏字樣，拒絕使用")
    return body


def _curated(home: Path, current: dict[str, str] | None = None,
             ) -> tuple[dict[str, str], dict[str, str], list[str]]:
    """讀人工裁定過的修補內容。

    為什麼需要這條路：兩雙眼睛比對只回答「兩邊一不一致」，寫進去的一律是眼睛 A
    的轉錄。實測 C #507 兩眼**穩定分歧**且 A 的結構是錯的（把 2 列切成 3 列），
    #439 兩眼各對一半（羅馬數字下標 I/II 兩邊錯的方向相反）—— 這兩種都不是
    「換一隻眼睛」能解決的，是要人看圖之後**定點修補**。

    裁定結果以檔案落在 `work/crops/<doc>/verified/<idx>.html|.txt`：
      - 進得了 restic 備份範圍
      - 內容可被 diff、可被重看，不是藏在某次執行的記憶體裡
      - 換模型重跑時它仍然成立（它記的是圖上寫什麼，不是哪隻眼睛比較準）

    第一行若是 `<!-- … -->` 註解，視為裁定依據，會被印出來但不寫進資料。

    `current` 是 {索引: 該表現值}，只給 `gate_table_html` 的 `<img>` 那一道用。
    """
    current = current or {}
    tables: dict[str, str] = {}
    texts: dict[str, str] = {}
    notes: list[str] = []
    d = home / "verified"
    if not d.is_dir():
        return tables, texts, notes
    for f in sorted(d.iterdir()):
        if f.suffix not in (".html", ".txt") or not f.stem.isdigit():
            continue
        body = f.read_text()
        m = re.match(r"\s*<!--(.*?)-->\s*", body, re.S)
        if m:
            notes.append(f"#{f.stem} {' '.join(m.group(1).split())[:160]}")
            body = body[m.end():]
        body = body.strip()
        if f.suffix == ".html":
            tables[f.stem] = gate_table_html(body, f"裁定檔 {f}",
                                             current.get(f.stem, ""))
        else:
            if not body or LEAK.search(body):
                sys.exit(f"裁定檔 {f} 是空的或含 prompt 洩漏字樣，拒絕使用")
            texts[f.stem] = body
    return tables, texts, notes


def _rollback_batch(
    ap_mod,
    done: list,
    o,
    *,
    workspace: str,
    source_dir: Path,
) -> None:
    """單份失敗時，把這一輪**已經寫下去**的份全部退回去。

    judgement-flow 第 9 節：「任何一條不成立就拒絕，而且是整批拒絕 —— 做到一半
    停下來比不做更糟，因為你不知道停在哪裡。」原本這條只擋在單份之內（六個條件
    任一不成立就不寫那一份），批次層卻是「壞的跳過、好的留下」：20 份跑到第 12 份
    炸掉，磁碟上就是 11 份新、9 份舊，而**沒有任何地方記著分界線在哪**。下一個人
    看到的是一個沒有名字的中間狀態。

    回滾順序刻意反過來（後寫的先退），這樣中途再失敗時，還沒退的都是較早的份，
    與備份檔的時間戳順序一致，查帳時看得懂。
    """
    if not done:
        return
    print(f"\n  ⟲ 批次回滾：本輪已寫入 {len(done)} 份，全部退回這一輪之前的狀態")
    stuck = []
    for res in reversed(done):
        try:
            print(f"      {ap_mod.rollback_from_backup(
                res, workspace=workspace, source_dir=source_dir, oracle=o)}")
        except Exception as e:  # noqa: BLE001
            stuck.append(f"{res.doc}：{e}")
    if stuck:
        # 回滾失敗是最糟的狀態：磁碟上是半套，而且自動路徑已經用盡。
        # 必須吵得夠大聲，並且把人工還原需要的路徑直接印出來。
        print("\n  ✗✗ 有文件回滾失敗，磁碟處於混合狀態，**不要再跑任何寫入指令**：")
        for s in stuck:
            print(f"        {s}")
        print("      人工還原：把上列備份檔複製回 <bundle>/content_list.json 與 _manifest.json")


def cmd_apply(a: argparse.Namespace, env: dict[str, str],
              bundles: list[Path] | None = None) -> int:
    from pp import apply as ap_mod
    from pp import eyes
    from pp.oracle import Oracle, container_for, force_reparse_is_on

    paths = _paths()
    out_root = paths.crops_dir
    source_dir = paths.inputs_dir(a.workspace)
    # 容器跟著 --workspace 走。指定了 workspace 卻 exec 進另一個 workspace 的
    # 容器，等於拿 A 的 LightRAG 去認可 B 的 bundle —— 而且會成功。
    o = Oracle(container=container_for(a.workspace))

    # 修補在生效前被刪掉：這道鎖擋的就是它。旗標開著時 LightRAG 重抓前會無條件
    # 清空 raw_dir，於是現在寫進去的東西在下一次 scan 消失，而**索引照樣建成功、
    # 沒有任何錯誤訊息**。三條進料路徑都收束到這個函式（CLI `apply`、
    # `prepare --commit` 的第二步、審核台的 admit），所以一道鎖擋住全部。
    # 問的是容器的環境變數，不是宿主的 —— 旗標只在容器裡有意義。
    force_reparse = o.force_reparse_flag()
    if force_reparse_is_on(force_reparse):
        print(f"  ✗ 拒絕執行：容器的 LIGHTRAG_FORCE_REPARSE_MINERU = "
              f"{force_reparse!r}（視為開啟）\n"
              "\n"
              "      這個旗標開著時，LightRAG 在重抓解析結果前會無條件清空快取目錄。\n"
              "      現在寫進去的修補會在下一次 scan 被刪掉，而索引照樣建成功、\n"
              "      不會有任何錯誤訊息 —— 整份文件的解析成果（6–10 小時）一起沒了。\n"
              "\n"
              "      正確做法：\n"
              "        1. 關掉容器的 LIGHTRAG_FORCE_REPARSE_MINERU（.env 移除或設 0），\n"
              "           然後 docker compose up -d --force-recreate lightrag\n"
              "           （restart 不會重讀環境變數）\n"
              "        2. 要讓已索引文件的修補生效，走 delete_document(delete_file=False)\n"
              "           → 放回 PDF → /scan，並確認 log 出現 `raw cache hit`\n"
              "\n"
              "      絕不可 force reparse，絕不可在 UI 刪文件時勾 delete file。")
        return 2

    rc = 0
    # 本輪已經 commit 成功的份，用來在後面任何一份失敗時整批退回。
    done: list = []
    targets = find_bundles(a.workspace, a.doc) if bundles is None else bundles
    for raw in targets:
        try:
            doc_home = out_root / raw.name.removesuffix(".mineru_raw")
            # 每張表在 content_list 裡的現值。閘門要拿它來分辨「保留既有的本地
            # `images/` 參照」與「捏造一條新的」——兩者長得一樣，差別只在現值有沒有。
            cur_body = {str(i): (it.get("table_body") or "")
                        for i, it in enumerate(DocContext(raw, source_dir=source_dir).items)
                        if it.get("type") == "table"}
            cur_tbl, cur_txt, cur_notes = _curated(doc_home, cur_body)
            verified: dict[str, str] = {}
            if not a.no_tables:
                # 只採用兩雙眼睛逐格一致的。沒把握的轉錄一律不寫 ——
                # 拿它覆蓋空表格，是把「明顯缺失」換成「看起來正常但可能是錯的」。
                ctx, results = eyes.check_doc(raw, env, out_root, source_dir=source_dir,
                                              workers=a.workers)
                for r_ in results:
                    if r_.ok and str(r_.index) not in cur_tbl:
                        html, err = eyes.look(eyes.eyes_from_env(env)[0], r_.png,
                                              out_root / ctx.doc_name / "cache")
                        if not err:
                            verified[str(r_.index)] = gate_table_html(
                                html.strip(), f"{ctx.doc_name} #{r_.index} 的自動採用轉錄",
                                cur_body.get(str(r_.index), ""))
            n_auto = len(verified)
            verified.update(cur_tbl)          # 人工裁定優先於自動採用
            res = ap_mod.apply_doc(raw, workspace=a.workspace, source_dir=source_dir,
                                   out_root=out_root, verified_tables=verified,
                                   verified_text=cur_txt, curated_idx=set(cur_tbl),
                                   oracle=o, commit=a.commit)
            if cur_tbl or cur_txt:
                res.notes.append(
                    f"表格 {n_auto} 張自動採用、{len(cur_tbl)} 張人工裁定；"
                    f"文字 {len(cur_txt)} 處人工裁定")
                res.notes += [f"  裁定依據 {n}" for n in cur_notes]
        except (DocContextError, ap_mod.ApplyError) as e:
            print(f"  ✗ {raw.name.removesuffix('.mineru_raw')}：{e}")
            _rollback_batch(ap_mod, done, o, workspace=a.workspace, source_dir=source_dir)
            return 2
        mark = "✓" if (res.valid_after is not False) else "✗"
        print(f"  {mark} {res.doc}\n      {res.line()}")
        if res.backup:
            print(f"      備份 {res.backup}")
        for n in res.notes:
            print(f"      {n}")
        if res.valid_after is False:
            # 「寫完 LightRAG 不認可」跟丟例外一樣是失敗，處置必須一樣 ——
            # 只把 rc 設成 2 卻繼續跑下一份，正是「做到一半」。
            # 這一份自己也已經寫下去了，所以要先進 done 才回滾得到它。
            if a.commit:
                done.append(res)
            _rollback_batch(ap_mod, done, o, workspace=a.workspace, source_dir=source_dir)
            return 2
        if a.commit:
            done.append(res)
    if not a.commit:
        print("\n（dry-run。確認無誤後加 --commit 才會寫檔）")
    return rc


def cmd_reindex(a, env) -> int:
    """讓修補進索引。

    修補**不會自動生效**：已索引的文件在 /scan 時會被 _archive + continue
    直接跳過，parse() 根本不會被呼叫。「解析完、建 IR 前」這個插入時間窗
    在程式上不存在。唯一的辦法是刪掉文件記錄再重新掃描。

    刪除時 delete_file=false（PDF 留著）、delete_llm_cache=false（抽取快取
    留著）。快取留著的話，沒改到的 chunk 會直接命中，重抽只跑真正變動的部分。
    解析快取（.mineru_raw）也還在且已通過 is_bundle_valid，所以不會再向
    MinerU 付費重抓。
    """
    import urllib.request

    host = f"http://{env.get('BIND_ADDR','127.0.0.1')}:{env.get('HOST_PORT','9621')}"
    key = env.get("LIGHTRAG_API_KEY", "")

    def api(path, method="GET", body=None):
        req = urllib.request.Request(
            host + path, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"X-API-Key": key, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read() or "{}")

    docs = api("/documents/paginated", "POST",
               {"page": 1, "page_size": 200})
    rows = docs.get("documents") or []
    keys = [k.lower() for k in (a.doc or [])]
    want = [d for d in rows
            if not keys or any(k in (d.get("file_path") or "").lower() for k in keys)]
    for k in keys:                       # 打錯字會靜靜地少重建一份，所以先擋下來
        if not any(k in (d.get("file_path") or "").lower() for d in rows):
            sys.exit(f"--doc {k!r} 對不到任何已索引文件")
    if not want:
        print("沒有符合的已索引文件")
        return 0

    print(f"將刪除索引並重新掃描 {len(want)} 份：")
    for d in want:
        print(f"  {(d.get('file_path') or '?')[:60]}  [{d.get('status')}]")
    if not a.commit:
        print("\n（dry-run。加 --commit 才會真的執行）")
        return 0

    ids = [d["id"] for d in want]

    # 把 PDF 從 work/parsed/ 搬回 inputs/<workspace>/。第一次索引時 archive_source
    # 會把來源搬進 work/parsed/，所以掃描目錄是空的 —— 刪掉記錄後直接 /scan 會找不到
    # 任何檔案，「成功」執行但什麼都沒做，文件就這樣從索引消失。
    # 實測踩過：C Equivalent Networks 被刪掉後索引從 20 剩 19。
    paths = _paths()
    inputs = paths.inputs_dir(a.workspace)
    parsed = paths.parsed_dir
    moved = 0
    for d in want:
        name = Path(d.get("file_path") or "").name
        src, dst = parsed / name, inputs / name
        if src.is_file() and not dst.is_file():
            shutil.move(str(src), str(dst))
            moved += 1
    print(f"\n把 {moved} 份 PDF 從 work/parsed/ 搬回 inputs/{a.workspace}/")
    print("刪除索引記錄…（保留 PDF 與 LLM 快取）")
    print(" ", json.dumps(api("/documents/delete_document", "DELETE",
                              {"doc_ids": ids, "delete_file": False,
                               "delete_llm_cache": False}), ensure_ascii=False)[:200])
    # 刪除是背景執行的，而且會讓 pipeline 進入忙碌狀態 —— 立刻掃描會被
    # scanning_skipped_pipeline_busy 擋掉，然後修補靜靜地沒有生效。等它閒下來。
    for _ in range(120):
        if not api("/health").get("pipeline_busy"):
            break
        time.sleep(5)
    else:
        print("  ⚠ 等了 10 分鐘 pipeline 仍忙碌，請稍後自行觸發 /documents/scan")
        return 2
    print("觸發重新掃描…")
    response = api("/documents/scan", "POST")
    print(" ", json.dumps(response, ensure_ascii=False)[:200])
    if _scan_was_skipped_pipeline_busy(response):
        print("\n✗ scan 沒有排程（scanning_skipped_pipeline_busy）；請等 pipeline 閒置後重跑 "
              "reindex --commit。")
        return 2
    print("\n解析快取仍有效，不會重新向 MinerU 付費；抽取快取命中的 chunk 會直接跳過。")
    if a.no_wait:
        print(f"⚠ --no-wait：{moved} 份 PDF 留在 inputs/{a.workspace}/，"
              "**必須**在索引完成後自己搬回 work/parsed/，否則審核台的放行會被擋下。")
        return 0
    return _reindex_settle(api, want, inputs, parsed)


def _reindex_settle(api, want: list, inputs: Path, parsed: Path) -> int:
    """等文件真的重新索引完，然後把 PDF 從 inputs 搬回 work/parsed。

    **誰把檔案放進 inputs，誰負責拿回來。** 少了這一步，inputs 會殘留 PDF，
    而審核台的 `_assert_inputs_empty()` 看到不乾淨就拒絕放行 —— 於是下一份
    新文件會失敗，錯誤訊息指向 inputs，跟 reindex 差了好幾個小時，沒有人會
    把兩件事連起來。實測踩過（2026-08-04：B/D/E 重建後 G Porous 放行被擋）。

    等的是「文件回到 processed」而不是「pipeline 閒置」—— 後者在抽取開始前
    就會短暫為真，會提早搬走檔案讓掃描找不到來源。
    """
    names = {Path(d.get("file_path") or "").name for d in want}
    deadline = time.monotonic() + 7200          # 12 份 × 各約 30 分鐘的上限
    while time.monotonic() < deadline:
        rows = (api("/documents/paginated", "POST",
                    {"page": 1, "page_size": 200}).get("documents") or [])
        done = {Path(r.get("file_path") or "").name for r in rows
                if str(r.get("status") or "").lower() == "processed"}
        if names <= done:
            break
        time.sleep(15)
    else:
        print(f"\n⚠ 等了 2 小時仍有文件沒回到 processed，PDF 留在 inputs/。"
              f"索引完成後請自行搬回 work/parsed/：{sorted(names - done)}")
        return 2

    back = 0
    for name in sorted(names):
        src, dst = inputs / name, parsed / name
        if src.is_file() and not dst.is_file():
            shutil.move(str(src), str(dst))
            back += 1
    left = [q.name for q in inputs.iterdir() if q.is_file()]
    print(f"\n重新索引完成，{back} 份 PDF 搬回 work/parsed/。")
    if left:
        # 沉默地留下殘檔會在幾小時後變成一個對不上因果的放行失敗。
        print(f"⚠ inputs/ 仍有檔案，審核台會拒絕放行：{left}")
        return 2
    print("inputs/ 已淨空（只剩 __parsed__ 掛載點）。")
    return 0


def cmd_revert(a, env) -> int:
    from pp import apply as ap_mod
    from pp.oracle import Oracle, container_for
    source_dir = _paths().inputs_dir(a.workspace)
    o = Oracle(container=container_for(a.workspace))
    for raw in find_bundles(a.workspace, a.doc):
        res = ap_mod.revert_doc(raw, workspace=a.workspace, source_dir=source_dir, oracle=o)
        print(f"  ✓ {res.doc}：還原消音 {res.muted}、表格 {res.tables}；"
              f"bundle {'認可' if res.valid_after else '**未認可**'}")
    return 0


def main():
    env = load_env(REPO)
    ap = argparse.ArgumentParser(description="MinerU 解析輸出的後處理")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("plan", help="只讀，算出打算改什麼")
    add_workspace_arg(p, env)
    p.add_argument("--doc", help="檔名關鍵字，預設全部")
    p.add_argument("--details", action="store_true")
    p.add_argument("--json", action="store_true")

    c = sub.add_parser("check", help="兩雙眼睛轉錄 + 逐格比對")
    add_workspace_arg(c, env)
    c.add_argument("--doc", help="檔名關鍵字，預設全部")
    c.add_argument("--workers", type=int, default=3)

    n = sub.add_parser("canary", help="比對 plan 結果與記錄的基準，抓規則漂移")
    add_workspace_arg(n, env)
    n.add_argument("--update", action="store_true", help="把目前結果寫成新基準")

    ap2 = sub.add_parser("apply", help="寫進 content_list.json 並更新 manifest")
    add_workspace_arg(ap2, env)
    ap2.add_argument("--doc", help="檔名關鍵字，預設全部")
    ap2.add_argument("--commit", action="store_true", help="真的寫檔（預設只算不寫）")
    ap2.add_argument("--no-tables", action="store_true", help="只做消音，不碰表格")
    ap2.add_argument("--workers", type=int, default=3)

    ri = sub.add_parser("reindex", help="刪索引記錄並重新掃描，讓修補生效")
    ri.add_argument("--no-wait", action="store_true",
                    help="觸發掃描後立刻返回，不等索引完成、不把 PDF 搬回 "
                         "work/parsed。**留下的殘檔會擋住審核台的放行**，要自己收尾")
    add_workspace_arg(ri, env)
    ri.add_argument("--doc", action="append",
                    help="檔名關鍵字，可重複指定；預設全部。"
                         "只重建真正改過的那幾份，其餘的索引不必動")
    ri.add_argument("--commit", action="store_true")

    pr = sub.add_parser("prepare", help="新文件：解析 → 修補 → 掃描（只抽取一次）")
    add_workspace_arg(pr, env)
    pr.add_argument("--commit", action="store_true")
    pr.add_argument("--no-tables", action="store_true")
    pr.add_argument("--workers", type=int, default=3)

    rv = sub.add_parser("revert", help="還原（讀 _pp_original_* 欄位）")
    add_workspace_arg(rv, env)
    rv.add_argument("--doc", help="檔名關鍵字，預設全部")

    a = ap.parse_args()

    if a.cmd == "apply":
        sys.exit(cmd_apply(a, env))
    if a.cmd == "prepare":
        sys.exit(cmd_prepare(a, env))
    if a.cmd == "reindex":
        sys.exit(cmd_reindex(a, env))
    if a.cmd == "revert":
        sys.exit(cmd_revert(a, env))
    if a.cmd == "check":
        sys.exit(cmd_check(a, env))
    if a.cmd == "canary":
        sys.exit(cmd_canary(a, env))

    source_dir = _paths().inputs_dir(a.workspace)
    plans, failed = [], []
    for raw in find_bundles(a.workspace, a.doc):
        try:
            plans.append(plan_one(raw, source_dir=source_dir))
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
