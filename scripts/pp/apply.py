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

import difflib
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
from pp.rules import chart_type, empty_table, latex_fix, layout_noise  # noqa: E402


class ApplyError(RuntimeError):
    pass


# 顶層 manifest 的 pass marker：內容沒有任何改動時，仍能記住這份 bundle 已經完整
# 跑過後處理，避免用「有沒有 _pp_* 改動痕跡」反推執行歷史。
POSTPROCESS_PASS_KEY = "_pp_pass"
POSTPROCESS_PASS_VERSION = 1


# `_coerce_text` 讀的欄位，順序照 compat-check 的 A-06 斷言。文字修補必須寫進
# **LightRAG 實際會讀的那一個**，否則改了等於沒改：N Flow #8 是 `code` 項，
# 內容在 `code_body`，硬塞一個 `text` 欄位反而會讓它蓋掉原本的 code_body
# （`text` 在這串裡排第一）。
TEXT_FIELDS = ("text", "content", "body", "code_body")

# 標記這張表是**定點補格**寫的（在既有內容上只插入），不是整張寫入。
# 兩條路的重跑判準相反，靠內容分不出來 —— 整張寫入之後現值就等於裁定檔，
# 定點補格之後現值還會被機械規則動，所以要在資料上留下走過哪一條的痕跡。
ADDITIVE = "_pp_table_additive"


def text_field(it: dict) -> str | None:
    """這個項目的內容放在哪個欄位。找不到就回 None —— 由呼叫端拒絕，不猜。"""
    for f in TEXT_FIELDS:
        if isinstance(it.get(f), str):
            return f
    return None


def _is_subsequence(a: str, b: str) -> bool:
    """a 的每一個字元都能在 b 裡依序找到 —— 等價於「b 是由 a 只做插入得到的」。

    刻意不用 `difflib` 判定：`SequenceMatcher` 找的是**某一組**匹配區塊
    （貪婪遞迴，不是最佳 LCS），純插入的情況它照樣可能回報 `replace`。
    那會變成偶發的假失敗，而假失敗會逼人去放寬檢查 —— 判定必須是確定的。
    difflib 只拿來**印給人看**，不參與判定。
    """
    it = iter(b)
    return all(ch in it for ch in a)


def additive_diff(current: str, new: str) -> list[str]:
    """把 `new` 相對於 `current` 的每一段插入列出來（給人審）。

    只在已經確定是純插入之後呼叫，所以 `replace`/`delete` 不該出現；真的出現時
    照樣列進去，因為這個函式也被拿來印**失敗**時的證據。
    """
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, current, new, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        head = current[max(0, i1 - 40):i1].replace("\n", " ")
        out.append(f"{tag} @{i1}　…{head}⟦{new[j1:j2][:200]}⟧"
                   + (f"　（刪/改掉：{current[i1:i2][:120]!r}）" if tag != "insert" else ""))
    return out


def assert_additive(current: str, new: str, where: str) -> list[str]:
    """curated 表格補格的**只加不改**判準：現值的位元組一個都不准動。

    定案（c-tables-disputes §7.2）沒有放寬 `empty_table` 的「不得覆蓋非空表格」
    —— idx 7 的證據還在（完整五欄表、799 字元實質內容，拿 VLM 的猜測覆蓋它就是
    製造靜默損壞）。放行的是另一條路：**填空格／截斷格前接前綴／新增格**，
    三者的共同形狀就是「只插入，不刪不改」，所以判準直接寫成那個不變量，
    而不是去枚舉三種操作 —— 枚舉會漏掉第四種形狀（實測到了：#373 的說明格是
    中間漏字，要在句子當中插回去，不是前綴也不是新增格）。

    回傳插入清單給呼叫端記進 notes：**每一段插入都要被看見**。
    通過檢查但沒人看過的插入，跟沒有檢查的插入沒有差別。
    """
    if not _is_subsequence(current, new):
        raise ApplyError(
            f"{where}：裁定檔動到了現值已有的內容，拒絕（curated 補格只准插入）\n"
            + "\n".join("        " + s for s in additive_diff(current, new)[:12]))
    return additive_diff(current, new)


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
    latex: "latex_fix.LatexPlan | None" = None
    notes: list[str] = field(default_factory=list)

    def line(self) -> str:
        v = {True: "認可", False: "**未認可**", None: "未檢查"}[self.valid_after]
        tex = f"、LaTeX 正規化 {self.latex.items}" if self.latex else ""
        return (f"消音 {self.muted}、修補表格 {self.tables}、修補文字 {self.texts}、"
                f"chart→image {self.charts}{tex}；"
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
              curated_idx: set[str] | None = None,
              oracle: Oracle | None = None, commit: bool = False) -> ApplyResult:
    """verified_tables: {content_list 索引(字串): 已通過交叉比對的 table HTML}
    verified_text:   {content_list 索引(字串): 人工裁定過的 text}
    curated_idx:     上面哪些索引來自**人工裁定檔**（其餘是自動採用的轉錄）

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
    curated = curated_idx or set()

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
    # 「不在可修補集合裡」現在有三個完全不同的原因，混成同一種失敗會很難用：
    #   a) **我們自己上一輪已經修好了**（內容與裁定檔一致且有 `_pp_repaired_at`）
    #      —— 修好的表格當然不再是空表格。正常重跑，安靜跳過（規則本來就該冪等）。
    #      不分辨的代價實測到了：C 的 5 張表在階段 2 修完後，再跑一次 apply 就整份
    #      報錯；批次原子性加上去之後，這個假失敗會把同輪已寫入的十幾份一起回滾。
    #   b) **人工裁定的定點補格**：現值有內容，裁定檔只在上面插入。走 assert_additive。
    #   c) 其餘 —— 規則或解析產物變了，拿舊索引硬寫會改到別的項目，必須停。
    repairable_idx = {str(t.index) for t in tables.repairable}
    add_notes: dict[str, list[str]] = {}
    for k in sorted(want, key=int):
        it = items[int(k)]
        if it.get("type") != "table":
            raise ApplyError(f"{ctx.doc_name}：表格修補目標 #{k} 不是 table 項目")
        if k in repairable_idx or (it.get("_pp_repaired_at") and ADDITIVE not in it):
            # 「整張寫入」那一條：現在是空表格，或上一輪就是被整張寫入的
            # （所以現在當然不再是空表格 —— 冪等的重跑不該變成失敗。實測到過：
            # C 的 5 張表在階段 2 修完後再跑一次 apply 就整份報錯，而批次原子性
            # 會讓這個假失敗把同輪已寫入的十幾份一起回滾）。
            continue
        if k not in curated:
            # 自動採用的轉錄永遠不准碰非空表格。`empty_table` 的耐久規則
            # （不得覆蓋非空表格）由這一行在 apply 層原樣守住。
            raise ApplyError(
                f"{ctx.doc_name}：表格修補目標 #{k} 不在可修補集合裡，也不是人工裁定 —— "
                "自動採用的轉錄不得寫進已有內容的表格，先重跑 plan")
        # 比對基準是 **MinerU 的原值**，不是現值。後面還有機械規則會就地正規化
        # `table_body`（\times 誤讀、格內逐字母排版），拿現值當基準的話，第二次
        # 跑 apply 時裁定檔相對於「已被正規化的現值」就不再是純插入，會假失敗。
        # 原值在第一次寫入時存進 `_pp_original_table_body`，之後不再變動。
        base = it.get("_pp_original_table_body", it.get("table_body") or "")
        ins = assert_additive(base, want[k], f"{ctx.doc_name} #{k}")
        if not ins:
            raise ApplyError(f"{ctx.doc_name}：裁定檔 #{k} 與 MinerU 原值完全相同，"
                             "沒有補進任何東西 —— 先確認裁定檔是不是產錯了")
        # **每一輪都重驗**（不只在會寫的時候）：裁定檔是磁碟上可以被人改的檔案，
        # 「這一輪剛好不用寫」不代表它還是當初那份。
        add_notes[k] = [f"#{k} 定點補格 {len(ins)} 段插入："] + [f"    {s}" for s in ins]

    # 判「已完成」看內容而不只看時間戳：只看時間戳的話，裁定檔改過之後會被當成
    # 已完成而**靜靜不生效**——改了東西卻沒有任何訊號，是這個專案一路在防的形狀。
    #
    # 比的是「裁定檔**經過機械正規化之後**長什麼樣」。裁定檔記的是圖上寫什麼，
    # 停在正規化之前（定點補格的 diff 基準也是那個位元組串）；磁碟上的現值則是
    # 正規化之後的。直接比裸位元組的話，每跑一次 apply 都會覺得「還沒寫」，
    # 於是把同一批項目寫過來又正規化回去 —— 收斂到同一組位元組，但永遠報不出
    # 「這一輪沒事可做」，而「沒事可做」正是重跑時唯一該看的訊號。
    done_tbl = {k for k in want
                if items[int(k)].get("_pp_repaired_at")
                and items[int(k)].get("table_body") in (want[k], latex_fix.fix_one(want[k])[0])}

    # 文字修補同理（包含上面那條「比正規化之後的樣子」）。
    done_txt = {k for k, v in want_text.items()
                if items[int(k)].get("_pp_repaired_at")
                and items[int(k)].get(text_field(items[int(k)]), "")
                in (v, latex_fix.fix_one(v)[0])}

    # 這一輪真的要寫的表格：可修補的空表格 ∪ 通過只加不改的定點補格，扣掉已完成的。
    write_tbl = sorted(set(want) - done_tbl, key=int)

    # 所有計畫都在動手之前算完 —— chart→image 會改 type，先算好才不會讓後面的
    # 規則看到被自己改過的狀態。
    charts = chart_type.plan(items, ctx.raw_dir)

    if not commit:
        # 機械正規化跑在人工裁定寫完之後，dry-run 沒有寫檔，所以拿「裁定寫進去
        # 之後」的副本去算，數字才跟 --commit 那條路一致。
        preview = [dict(x) for x in items]
        for k in write_tbl:
            preview[int(k)]["table_body"] = want[k]
        for k, txt in want_text.items():
            if k not in done_txt:
                preview[int(k)][text_field(preview[int(k)])] = txt
        r.latex = latex_fix.plan(preview)
        r.muted = len(noise.mutes)
        r.tables = len(write_tbl)
        for k in write_tbl:
            r.notes += add_notes.get(k, [])
        r.notes.append(r.latex.summary())
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
    for k in write_tbl:
        it = items[int(k)]
        # 必須記下「原本有沒有這個鍵」。10 張待修表格裡有 9 張是連 table_body
        # 都沒有（MISSING_KEY），只存 _pp_original_table_body 的話那 9 張沒有
        # 還原依據 —— 實測第一版就是這樣，revert 只還原了消音，表格 0 張。
        # 與文字修補同一條理由：只記**第一次**的原文。裁定檔改過而重跑時，
        # 無條件覆寫會把 MinerU 的原始輸出換成上一輪的修補結果，還原路徑看起來
        # 還在，還原出來的卻已經不是原文了。
        if "_pp_had_table_body" not in it:
            it["_pp_had_table_body"] = "table_body" in it
            if "table_body" in it:
                it["_pp_original_table_body"] = it["table_body"]
        if k in add_notes:               # 走定點補格那條路的痕跡
            it[ADDITIVE] = True
        it["table_body"] = want[k]
        it["_pp_repaired_at"] = stamp
        r.tables += 1
    for k in write_tbl:
        r.notes += add_notes.get(k, [])
    # 機械正規化**最後**跑：人工裁定記的是「圖上寫什麼」，這條記的是「同一件事
    # 怎麼寫才對」。順序反過來的話，下一輪裁定檔相對於現值就不再是純插入。
    r.latex = latex_fix.plan(items)
    latex_fix.apply_to_items(items, r.latex, stamp)
    r.notes.append(r.latex.summary())
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
    else:
        man[POSTPROCESS_PASS_KEY] = {
            "version": POSTPROCESS_PASS_VERSION,
            "completed_at": stamp,
        }
        ctx.manifest_path.write_text(json.dumps(man, ensure_ascii=False, indent=1))
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
        it.pop(ADDITIVE, None)
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
    man.pop(POSTPROCESS_PASS_KEY, None)
    ctx.manifest_path.write_text(json.dumps(man, ensure_ascii=False, indent=1))

    r.valid_after = bundle_valid(DocContext(raw_dir), o)
    return r
