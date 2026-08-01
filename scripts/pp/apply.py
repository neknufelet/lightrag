"""把計畫寫進 content_list.json，並更新 manifest 讓 LightRAG 繼續認可這份 bundle。

這是整條流程唯一會改磁碟的地方。前面所有步驟都是唯讀的。

為什麼要更新 manifest：is_bundle_valid() 會比對 critical_file 的 size 與 sha256。
只改內容不改 manifest，快取立刻失效，下次 /scan 會重新向 MinerU 抓一份，把修補
整個覆蓋掉 —— 而且不會有錯誤訊息，只是白花錢又白做工。實測順序：

    改動前                      is_bundle_valid = True
    消音 110 個 header          is_bundle_valid = False   ← 快取失效
    更新 manifest 後            is_bundle_valid = True    ← 重新認可

為什麼備份不是可選的：消音走 _pp_original_text 可以就地還原，但表格修補會覆蓋
原本的 table_body。原始檔存進 DATA_ROOT（restic 會備份），以時間戳命名，
還原時用得到。

寫檔的安全條件（任何一條不成立就拒絕）：
  1. preflight 通過（型別、頁序、來源 PDF 對得上）
  2. 現在 is_bundle_valid 為真 —— 本來就壞的東西不要動
  3. 消音比例未超標
  4. pipeline 閒置 —— 掃描中改檔會跟 LightRAG 搶同一份檔案
  5. 寫完後項目數必須不變、is_bundle_valid 必須回到真
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pp.docctx import DocContext  # noqa: E402
from pp.oracle import Oracle, OracleError  # noqa: E402
from pp.rules import chart_type, empty_table, layout_noise  # noqa: E402


class ApplyError(RuntimeError):
    pass


@dataclass
class ApplyResult:
    doc: str
    muted: int = 0
    tables: int = 0
    charts: int = 0
    backup: Path | None = None
    items_before: int = 0
    items_after: int = 0
    valid_after: bool | None = None
    notes: list[str] = field(default_factory=list)

    def line(self) -> str:
        v = {True: "認可", False: "**未認可**", None: "未檢查"}[self.valid_after]
        return (f"消音 {self.muted}、修補表格 {self.tables}、chart→image {self.charts}；"
                f"項目 {self.items_before} → {self.items_after}；bundle {v}")


def _sha256(p: Path) -> str:
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def bundle_valid(ctx: DocContext, oracle: Oracle) -> bool:
    """問 LightRAG 本人這份 bundle 還算不算數。不要自己重算 —— 驗證邏輯
    包含 options_signature 等我們不該複製的東西。"""
    code = r'''
import json, sys
from pathlib import Path
from lightrag.parser.external.mineru import is_bundle_valid
print(json.dumps({"valid": bool(is_bundle_valid(Path(sys.argv[1]), Path(sys.argv[2]), overrides=None))}))
'''
    ws = ctx.raw_dir.parent.parent.name
    c_raw = f"/app/data/inputs/{ws}/__parsed__/{ctx.raw_dir.name}"
    c_src = f"/app/data/inputs/{ws}/__parsed__/{ctx.doc_name}"
    if not (ctx.raw_dir.parent / ctx.doc_name).is_file():
        c_src = f"/app/data/inputs/{ws}/{ctx.doc_name}"
    return bool(oracle.py_argv(code, [c_raw, c_src])["valid"])


def pipeline_idle(oracle: Oracle) -> bool:
    """掃描中改檔會跟 LightRAG 搶同一份檔案。這條由 compat-check A-19 守著，
    這裡再問一次 —— 檢查與動工之間可能隔了很久。"""
    try:
        out = oracle.sh(
            "python -c \"import json,urllib.request,os;"
            "r=urllib.request.Request('http://localhost:9621/health',"
            "headers={'X-API-Key':os.environ['LIGHTRAG_API_KEY']});"
            "print(json.load(urllib.request.urlopen(r,timeout=10)).get('pipeline_busy'))\"")
        return "False" in out
    except OracleError:
        return False


def apply_doc(raw_dir: Path, *, out_root: Path, verified_tables: dict[str, str] | None = None,
              oracle: Oracle | None = None, commit: bool = False) -> ApplyResult:
    """verified_tables: {content_list 索引(字串): 已通過交叉比對的 table HTML}

    只寫**已驗證**的表格。沒有通過兩雙眼睛逐格比對的一律不寫 —— 拿沒把握的
    轉錄覆蓋原本的空表格，是把「明顯缺失」換成「看起來正常但可能是錯的」，
    那比缺失更難發現。
    """
    o = oracle or Oracle()
    ctx = DocContext(raw_dir)
    ctx.preflight()
    r = ApplyResult(ctx.doc_name)

    items = json.loads(ctx.content_list_path.read_text())
    r.items_before = len(items)

    noise = layout_noise.plan(items, ctx.n_pages)
    if noise.suspicious:
        raise ApplyError(f"{ctx.doc_name}：消音比例 {noise.ratio:.1%} 超標，拒絕自動套用")

    tables = empty_table.plan(items, *ctx.page_size)
    want = verified_tables or {}
    targets = [t for t in tables.repairable if str(t.index) in want]

    # 所有計畫都在動手之前算完 —— chart→image 會改 type，先算好才不會讓後面的
    # 規則看到被自己改過的狀態。
    charts = chart_type.plan(items, ctx.raw_dir)

    if not commit:
        r.muted = len(noise.mutes)
        r.tables = len(targets)
        r.charts = len(charts.convert)
        r.items_after = r.items_before
        if charts.dangling:
            r.notes.append(f"{len(charts.dangling)} 個 chart 的 img_path 指不到檔案，不轉")
        r.notes.append("dry-run，沒有寫任何檔案")
        return r

    # ── 寫檔前的安全條件 ──
    if not pipeline_idle(o):
        raise ApplyError("pipeline 忙碌中，拒絕改檔（掃描會跟我們搶同一份檔案）")
    if not bundle_valid(ctx, o):
        raise ApplyError(f"{ctx.doc_name}：bundle 目前就不被 LightRAG 認可，先修好再說")

    # ── 備份 ──
    home = out_root / ctx.doc_name / "backup"
    home.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    r.backup = home / f"content_list.{stamp}.json"
    shutil.copy2(ctx.content_list_path, r.backup)
    shutil.copy2(ctx.manifest_path, home / f"_manifest.{stamp}.json")

    # ── 改動 ──
    r.muted = layout_noise.apply_to_items(items, noise)
    for t in targets:
        it = items[t.index]
        # 必須記下「原本有沒有這個鍵」。10 張待修表格裡有 9 張是連 table_body
        # 都沒有（MISSING_KEY），只存 _pp_original_table_body 的話那 9 張沒有
        # 還原依據 —— 實測第一版就是這樣，revert 只還原了消音，表格 0 張。
        it["_pp_had_table_body"] = "table_body" in it
        if "table_body" in it:
            it["_pp_original_table_body"] = it["table_body"]
        it["table_body"] = want[str(t.index)]
        it["_pp_repaired_at"] = stamp
        r.tables += 1
    r.charts = chart_type.apply_to_items(items, charts)
    if charts.dangling:
        r.notes.append(f"{len(charts.dangling)} 個 chart 的 img_path 指不到檔案，未轉")

    # 項目數不得改變 —— sidecar 的 self_ref 是陣列索引，少一個就整串錯位
    if len(items) != r.items_before:
        raise ApplyError(f"項目數改變了（{r.items_before} → {len(items)}），這不該發生")

    ctx.content_list_path.write_text(json.dumps(items, ensure_ascii=False, indent=1))
    r.items_after = len(items)

    # ── 更新 manifest，否則快取失效、下次 /scan 會重抓覆蓋掉修補 ──
    man = json.loads(ctx.manifest_path.read_text())
    cf = man.get("critical_file") or {}
    if cf.get("path") != "content_list.json":
        raise ApplyError(f"critical_file 不是 content_list.json（{cf.get('path')!r}），"
                         "契約改了，停下來")
    cf["size"] = ctx.content_list_path.stat().st_size
    cf["sha256"] = _sha256(ctx.content_list_path)
    man["critical_file"] = cf
    ctx.manifest_path.write_text(json.dumps(man, ensure_ascii=False, indent=1))

    # ── 寫完必須再問一次 ──
    ctx2 = DocContext(raw_dir)
    r.valid_after = bundle_valid(ctx2, o)
    if not r.valid_after:
        r.notes.append("⚠ 寫完後 LightRAG 不認可這份 bundle —— 用 revert 還原")
    return r


def revert_doc(raw_dir: Path, *, oracle: Oracle | None = None) -> ApplyResult:
    """就地還原：消音讀 _pp_original_text，表格讀 _pp_original_table_body，
    圖片型別讀 _pp_original_type。不需要備份檔 —— 但備份仍然存在，用於查帳。

    注意這是**全部撤回**，不是「撤銷上一次 apply」。所有 _pp_* 欄位一起清掉，
    所以拿它當 undo 用會連好幾輪之前的消音一起還原。實測 K Muffler：只想撤掉
    3 個 chart 轉換，結果連同上一輪的 61 個 header 消音一起復原了。要回到
    「撤掉某一項、其餘保留」就再跑一次 apply（規則是冪等的）。"""
    o = oracle or Oracle()
    ctx = DocContext(raw_dir)
    items = json.loads(ctx.content_list_path.read_text())
    r = ApplyResult(ctx.doc_name, items_before=len(items))

    r.muted = layout_noise.revert_items(items)
    r.charts = chart_type.revert_items(items)
    for it in items:
        if "_pp_repaired_at" not in it:
            continue
        had = it.pop("_pp_had_table_body", "_pp_original_table_body" in it)
        if had:
            it["table_body"] = it.pop("_pp_original_table_body")
        else:
            # 原本連鍵都沒有 —— 還原就是把鍵拿掉，不是留一個空字串
            it.pop("table_body", None)
            it.pop("_pp_original_table_body", None)
        it.pop("_pp_repaired_at", None)
        r.tables += 1

    ctx.content_list_path.write_text(json.dumps(items, ensure_ascii=False, indent=1))
    r.items_after = len(items)

    man = json.loads(ctx.manifest_path.read_text())
    man["critical_file"]["size"] = ctx.content_list_path.stat().st_size
    man["critical_file"]["sha256"] = _sha256(ctx.content_list_path)
    ctx.manifest_path.write_text(json.dumps(man, ensure_ascii=False, indent=1))

    r.valid_after = bundle_valid(DocContext(raw_dir), o)
    return r
