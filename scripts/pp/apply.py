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


# `_coerce_text` 讀的欄位，順序照 compat-check 的 A-06 斷言。文字修補必須寫進
# **LightRAG 實際會讀的那一個**，否則改了等於沒改：N Flow #8 是 `code` 項，
# 內容在 `code_body`，硬塞一個 `text` 欄位反而會讓它蓋掉原本的 code_body
# （`text` 在這串裡排第一）。
TEXT_FIELDS = ("text", "content", "body", "code_body")


def text_field(it: dict) -> str | None:
    """這個項目的內容放在哪個欄位。找不到就回 None —— 由呼叫端拒絕，不猜。"""
    for f in TEXT_FIELDS:
        if isinstance(it.get(f), str):
            return f
    return None


@dataclass
class ApplyResult:
    doc: str
    muted: int = 0
    tables: int = 0
    texts: int = 0
    charts: int = 0
    backup: Path | None = None
    backup_manifest: Path | None = None
    raw_dir: Path | None = None
    items_before: int = 0
    items_after: int = 0
    valid_after: bool | None = None
    notes: list[str] = field(default_factory=list)

    def line(self) -> str:
        v = {True: "認可", False: "**未認可**", None: "未檢查"}[self.valid_after]
        return (f"消音 {self.muted}、修補表格 {self.tables}、修補文字 {self.texts}、"
                f"chart→image {self.charts}；"
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


def _backup(src: Path, dst: Path) -> None:
    """備份一個檔案。**打到任何一個「做不到」就直接失敗**，不留「備份了一半」。

    judgement-flow 第 9 節記的兩個靜默失敗都在這裡擋：
      - `dump` 直接覆蓋同名檔 → 拒絕覆蓋（同秒重跑會撞名，撞到就停）
      - 截斷/部分寫入不報錯 → 寫完重讀算 sha256，跟來源不符就刪掉並失敗

    不完整卻宣稱成功比沒有備份更危險 —— 你會因此放心動手。
    """
    if dst.exists():
        raise ApplyError(f"備份檔已存在，拒絕覆蓋：{dst}")
    shutil.copy2(src, dst)
    if _sha256(dst) != _sha256(src):
        dst.unlink(missing_ok=True)
        raise ApplyError(f"備份內容與來源不符（複製途中被截斷？）：{dst}")


def apply_doc(raw_dir: Path, *, out_root: Path, verified_tables: dict[str, str] | None = None,
              verified_text: dict[str, str] | None = None,
              oracle: Oracle | None = None, commit: bool = False) -> ApplyResult:
    """verified_tables: {content_list 索引(字串): 已通過交叉比對的 table HTML}
    verified_text:   {content_list 索引(字串): 人工裁定過的 text}

    只寫**已驗證**的表格。沒有通過兩雙眼睛逐格比對的一律不寫 —— 拿沒把握的
    轉錄覆蓋原本的空表格，是把「明顯缺失」換成「看起來正常但可能是錯的」，
    那比缺失更難發現。

    verified_text 是給「文字層有正確答案、MinerU 讀成亂碼」那一類的單點修補
    （實測 C p64 的旋轉 90° 說明文字被 OCR 讀成 "Ab = = ze = etsosbd) te se…"）。
    原文一律存進 `_pp_original_text`，還原路徑與消音共用同一條。
    """
    o = oracle or Oracle()
    ctx = DocContext(raw_dir)
    ctx.preflight()
    r = ApplyResult(ctx.doc_name, raw_dir=raw_dir)

    items = json.loads(ctx.content_list_path.read_text())
    r.items_before = len(items)

    noise = layout_noise.plan(items, ctx.n_pages)
    if noise.suspicious:
        raise ApplyError(f"{ctx.doc_name}：消音比例 {noise.ratio:.1%} 超標，拒絕自動套用")

    tables = empty_table.plan(items, *ctx.page_size)
    want = verified_tables or {}
    want_text = verified_text or {}
    targets = [t for t in tables.repairable if str(t.index) in want]

    # 兩條規則不得打到同一個項目：消音會把 text 清空並寫 _pp_original_text，
    # 文字修補會寫同一組欄位 —— 撞在一起時後跑的那條贏，而且不會有訊息。
    muted_idx = {m.index for m in noise.mutes}
    clash = sorted(muted_idx & {int(k) for k in want_text})
    if clash:
        raise ApplyError(f"{ctx.doc_name}：項目 {clash} 同時是消音目標與文字修補目標，拒絕")
    # 原本這裡寫死 `type != "text"` 就拒收。方程式的 ∂ 誤讀修補要走同一條路
    # （型別是 `equation`，內容一樣在 `text`），所以判準改成「這個項目有沒有
    # `_coerce_text` 讀得到的內容欄位」—— 那才是「改了會不會生效」的真條件。
    # 表格/圖片沒有這些欄位，仍然被擋下。
    for k in want_text:
        if not (0 <= int(k) < len(items)) or text_field(items[int(k)]) is None:
            raise ApplyError(f"{ctx.doc_name}：文字修補目標 #{k} 不存在，"
                             f"或沒有 _coerce_text 讀得到的內容欄位（{TEXT_FIELDS}）")
    # 「不在可修補集合裡」有兩個完全不同的原因，混成同一種失敗會很難用：
    #   a) **我們自己上一輪已經修好了** —— 修好的表格當然不再是空表格。
    #      這是正常的重跑，該安靜跳過（規則本來就該冪等）。
    #   b) 規則或解析產物變了 —— 拿舊索引硬寫會改到別的項目，必須停。
    # 分辨的訊號是該項目上有沒有我們蓋的 `_pp_repaired_at`。
    # 不分辨的代價實測到了：C 的 5 張表在階段 2 修完後，再跑一次 apply 就整份
    # 報錯；批次原子性加上去之後，這個假失敗會把同一輪已寫入的十幾份**一起回滾**。
    repairable_idx = {str(t.index) for t in tables.repairable}
    done_tbl = {k for k in want
                if k not in repairable_idx and items[int(k)].get("_pp_repaired_at")}
    missing_tbl = sorted(set(want) - repairable_idx - done_tbl)
    if missing_tbl:
        raise ApplyError(f"{ctx.doc_name}：表格修補目標 {missing_tbl} 不在可修補集合裡，"
                         "且沒有被本流程修補過的痕跡 —— 規則或解析產物變了，先重跑 plan")

    # 文字修補同理：內容與裁定檔一致且已標記過的，就是上一輪的成果，不重寫。
    done_txt = {k for k, v in want_text.items()
                if items[int(k)].get("_pp_repaired_at")
                and items[int(k)].get(text_field(items[int(k)]), "") == v}

    # 所有計畫都在動手之前算完 —— chart→image 會改 type，先算好才不會讓後面的
    # 規則看到被自己改過的狀態。
    charts = chart_type.plan(items, ctx.raw_dir)

    if not commit:
        r.muted = len(noise.mutes)
        r.tables = len(targets)
        r.texts = len(want_text) - len(done_txt)
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
    # 涵蓋範圍：要改的對象只有 content_list.json 與 _manifest.json 兩個檔，
    # 而這裡備份的是**整個檔的位元組**，所以「涵蓋每一個要改的項目」由構造保證，
    # 不必逐項列舉。兩個檔缺一份就整批停 —— 只備份到一半是最糟的狀態。
    home = out_root / ctx.doc_name / "backup"
    home.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    r.backup = home / f"content_list.{stamp}.json"
    r.backup_manifest = home / f"_manifest.{stamp}.json"
    _backup(ctx.content_list_path, r.backup)
    try:
        _backup(ctx.manifest_path, r.backup_manifest)
    except ApplyError:
        r.backup.unlink(missing_ok=True)      # 不留半套備份
        r.backup_manifest = None
        raise

    # ── 改動 ──
    r.muted = layout_noise.apply_to_items(items, noise)
    for k, txt in sorted(want_text.items(), key=lambda kv: int(kv[0])):
        if k in done_txt:                 # 上一輪就是這個內容，不重寫
            continue
        it = items[int(k)]
        fld = text_field(it)
        # `setdefault`：`_pp_original_*` 只記**第一次**的原文。裁定檔被改過而
        # 重跑時，直接覆寫會把 MinerU 的原始輸出換成上一輪的修補結果 ——
        # 還原路徑看起來還在，還原出來的卻已經不是原文了。
        it.setdefault(f"_pp_original_{fld}", it.get(fld, ""))
        it[fld] = txt
        it["_pp_repaired_at"] = stamp
        r.texts += 1
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


def rollback_from_backup(res: ApplyResult, *, oracle: Oracle | None = None) -> str:
    """把一份文件還原成這一輪 apply **之前**的位元組。回傳一行說明。

    為什麼不用 `revert_doc`：那支是「撤回全部 `_pp_*` 欄位」，會把好幾輪之前的
    消音一起還原（它自己的 docstring 就記了 K Muffler 那次實測）。批次回滾要的是
    「回到這一輪開始前」，唯一忠實的來源是這一輪剛照下來的時間戳備份。

    還原後**重新算 sha256 比對備份**，不符就 raise —— 回滾自己也會靜默失敗，
    而一個宣稱成功卻沒還原的回滾，比不回滾更危險（judgement-flow 第 9 節）。
    """
    if not (res.raw_dir and res.backup and res.backup_manifest):
        raise ApplyError(f"{res.doc}：沒有完整的備份路徑，無法回滾")
    ctx = DocContext(res.raw_dir)
    for src, dst in ((res.backup, ctx.content_list_path),
                     (res.backup_manifest, ctx.manifest_path)):
        if not src.is_file():
            raise ApplyError(f"{res.doc}：備份檔不存在，無法回滾：{src}")
        shutil.copy2(src, dst)
        if _sha256(dst) != _sha256(src):
            raise ApplyError(f"{res.doc}：回滾後內容與備份不符：{dst}")
    valid = bundle_valid(DocContext(res.raw_dir), oracle or Oracle())
    return f"{res.doc}：已回滾到 {res.backup.name}；bundle {'認可' if valid else '**未認可**'}"


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
    # `layout_noise.revert_items` 只認 `_pp_original_text`（消音與大多數文字修補
    # 都走那個欄位）。`code_body` 之類的其餘內容欄位在這裡補還原 —— 少了這段，
    # 還原會宣稱成功卻把 #8 那種項目留在修補後的狀態。
    for it in items:
        for f in TEXT_FIELDS[1:]:
            if f"_pp_original_{f}" in it:
                it[f] = it.pop(f"_pp_original_{f}")
    r.charts = chart_type.revert_items(items)
    for it in items:
        if "_pp_repaired_at" not in it:
            continue
        # 判斷「這是文字修補還是表格修補」用**形狀**不用型別：表格修補一定留下
        # `_pp_had_table_body`。原本寫 `type == "text"` 時，`equation` / `code`
        # 會掉進表格那條分支，把 table_body 相關的鍵當成有東西可還原。
        if "_pp_had_table_body" not in it and "_pp_original_table_body" not in it:
            # 內容欄位已在上面（或 layout_noise）還原，這裡只收時間戳。
            it.pop("_pp_repaired_at", None)
            r.texts += 1
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
