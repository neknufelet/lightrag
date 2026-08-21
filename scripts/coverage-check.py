#!/usr/bin/env python3
"""coverage 閘門：PDF 的文字層 vs content_list 的全部文字欄位。

為什麼是這個對照源：`pdftotext` 抽的是 PDF 自己帶的文字層 —— 免費、確定性、
不呼叫模型、全覆蓋。它是**獨立於 MinerU 的第二個證人**，所以能回答「MinerU 有
沒有把內容整段弄丟」這個 MinerU 自己絕對答不出來的問題。

實測代價：這支檢查在整批索引完成後才第一次跑，一跑就抓到全庫最大的洞
（C Equivalent Networks 漏詞 15.2%，分佈在 p15–p46 的表格內容）。所以它現在
是階段 1 的閘門，解析一結束就跑，不等抽取。

## 為什麼只比 ≥4 字母的英文詞

短詞與非字母記號在兩邊的切法根本不同，比了只會量到切法差異：

  - 行內 LaTeX 會把字母拆開排版（`\\mathrm { i n t e r i o r }`），單字母、
    雙字母的碎片在 content 側滿地都是。
  - 數學符號、單位、頁碼在文字層與 MinerU 的 Unicode 正規化不一致。

限制成 4 個字母以上的純英文詞，剩下的就都是真正的**詞彙**，兩邊該有的都有。
這不是把門檻調鬆 —— 是把量錯的東西剔掉（鐵則 5）。

## 偵測器版本

**v2（2026-08-02）：加 LaTeX 字母間隔正規化**（`latex_unspace`）。上面那條
「行內 LaTeX 會把字母拆開排版」原本只被拿來當「所以不比短詞」的理由，但它同時
也把**長詞**打碎了：`\\mathrm { w i t h : ~ }` 裡的 `with`、被吞進顯示式的整句
散文，`[a-z]{4,}` 全部配不到，於是記成漏詞。與階段 1 的 `ﬂ` 合字同族。
20 份重量的結果見體檢表 note；v1 與 v2 的數字不可混用。

**v3（2026-08-02）：`_pp_original_*` 改成有條件讀回**（`pp_skip`）。
下面「為什麼要把 _pp_original_text 讀回來」寫的是消音那一類 —— 現值被清空、
原文搬進 sidecar 欄位，不讀回來就會把我們自己的決定誤記成上游缺陷。但**修補**
那一類的形狀正好相反：現值有新內容、`_pp_original_*` 還留著舊內容，兩份**同時**
被數進 content 側，同一段文字算兩次。多重集合差是 `pdf - content`，content 側
虛胖只會讓漏詞變少 —— **往看不見的方向錯**。

實測（N Flow）：152 個項目同時有 `_pp_original_*` 與非空現值（∂ 誤讀修補寫回
的方程式），重複計數把 4.796% 壓成 4.8% 以下並讓它跨過 5% 門檻；G Porous 4 個、
C 2 個。其餘 17 份沒有這種項目，數字必須完全不變 —— 那是這次改動的對照錨點。

判準是**現值有沒有內容**，不是項目型別：
    現值已清空（消音）      → 讀回 `_pp_original_*`（否則消音被量成掉字）
    現值仍有內容（修補過）  → 跳過 `_pp_original_*`（否則同一段算兩次）
用型別判會錯：消音打的是 `text`，文字修補打的也是 `text`。

## 為什麼用多重集合而不是集合

`{pdftotext 的詞} - {content 的詞}` 會漏掉最重要的一類失敗：同一個詞在文字層
出現 47 次、content 只有 3 次。整段表格內容流失時，詞彙本身多半還在別處出現
過一次，用集合差集看起來完全正常。所以兩邊都數次數，漏詞 = 逐詞的次數差。

## 為什麼要把 _pp_original_text 讀回來

消音規則會把 header/footer 的 `text` 清空、原文存進 `_pp_original_text`。
那是**後處理刻意做的**，不是解析漏掉的。不讀回來的話，同一份文件在消音前後
會量出兩個 coverage，而且消音後那個看起來像 MinerU 變爛了 —— 把我們自己的
決定誤記成上游的缺陷。讀回來之後這支量的才真的是「MinerU 產出了什麼」，
v155（已消音）與 v2（全新解析）也才可比。

用法：
    ./coverage-check.py                          # 本 checkout 的 workspace，全部文件
    ./coverage-check.py --doc 'Equivalent'       # 只看某一份，附漏最多的詞
    ./coverage-check.py --workspace <workspace>     # 對照組（唯讀）
    ./coverage-check.py --json                   # 給 ledger.py 之類的程式讀

超過門檻的文件存在時 exit 1。
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mineru_common import add_workspace_arg, load_env  # noqa: E402
from pp import findings  # noqa: E402
from pp.paths import DEFAULT_DATA_ROOT, DataPaths  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DEFAULT_ROOT = DEFAULT_DATA_ROOT
DEFAULT_THRESHOLD = 0.05

# ≥4 字母的純英文詞。理由見檔頭。
WORD = re.compile(r"[a-z]{4,}")

# LaTeX 命令的單層引數：`\mathrm { w i t h : ~ }`。刻意只吃 `[^{}]*`（不含巢狀
# 大括號）—— 正則剖析不了配對括號，硬要吃巢狀只會在別的地方咬錯（judgement-flow
# 第 3 節記過同一件事：`\hat{σ}` 的分類前兩版都敗在用正則找配對括號）。
CMD_ARG = re.compile(r"(\\[A-Za-z]+\s*\{)([^{}]*)(\})")

# content_list 裡**不算文字**的欄位。少列一個的代價只是漏詞被藏起來
# （多出來的詞只會抵銷掉真正的缺漏），所以這裡寧可列滿：
#   img_path          圖檔名，是 uuid/雜湊，字母碎片會假裝成詞彙
#   type/sub_type     結構標籤（'code'、'list'、'table'）不是內容
#   text_format       'latex' 這類格式註記
#   _pp_original_type chart→image 轉換前的型別，同樣是標籤
#   _pp_repaired_at   修補時間戳
#   _pp_had_table_body 布林旗標，不是內容
#   _pp_table_additive 布林旗標（走的是定點補格那條路），不是內容
# 注意 `_pp_original_<內容欄位>` **不在**這裡 —— 它是消音前的原文，多數情況要
# 讀回來。哪些該讀、哪些該跳，是**逐項**決定的，見 pp_skip()。
SKIP_KEYS = {
    "img_path", "type", "sub_type", "text_format",
    "_pp_original_type", "_pp_repaired_at", "_pp_had_table_body",
    "_pp_table_additive",
}

# 後處理會就地改動、並把原文搬進 `_pp_original_<欄位>` 的內容欄位。
# 前四個順序照 `_coerce_text`（compat-check A-06），第五個是表格修補。
PP_FIELDS = ("text", "content", "body", "code_body", "table_body")

TAGS = re.compile(r"<[^>]*>")


def pp_skip(it: dict) -> set[str]:
    """這個項目要**額外**跳過哪些 `_pp_original_*` 欄位（v3，見檔頭）。

    只看現值有沒有內容，不看項目型別 —— 消音與文字修補打的是同一個 `text` 欄位，
    用型別分不開。現值為空＝消音（原文要讀回來，否則消音被量成掉字）；
    現值有內容＝修補過（原文要跳過，否則同一段被算兩次，漏詞被虛假地抵銷掉）。
    """
    out = set()
    for f in PP_FIELDS:
        k = f"_pp_original_{f}"
        if k not in it:
            continue
        cur = it.get(f)
        if isinstance(cur, str) and TAGS.sub("", cur).strip():
            out.add(k)
    return out


def _glue_letters(arg: str) -> str:
    """把一個 LaTeX 引數裡「被拆成單字母」的排版黏回單字。

    `~` 是 LaTeX 的不斷行空白，在這種排版裡當的是**詞**的分隔；一般空白當的是
    **字母**的分隔。所以先照 `~` 切成詞段，段內才把連續的單字母 token 黏起來。
    分不清這兩層的後果實測過（本函式第一版）：
    `\\mathrm{ ~ f l u c t u a t i n g ~ q u a n t i t y }` 會被黏成
    `fluctuatingquantity` 一個詞，兩個字都還是配不到 —— 假訊號沒消掉，只是換了形狀。

    不是單字母的 token（標點、`-`、多字母片段）原樣留下當邊界。`p o s s i b l y
    a l s o` 這種原文就沒有分隔符的會黏成 `possiblyalso`，救不回來 ——
    **寧可少救，不可亂黏**：黏出來的假詞會抵銷掉真正的缺漏，那是靜默少報。
    """
    out = []
    for seg in arg.split("~"):
        merged, buf = [], []
        for t in seg.split():
            if len(t) == 1 and t.isalpha():
                buf.append(t)
                continue
            if buf:
                merged.append("".join(buf))
                buf = []
            merged.append(t)
        if buf:
            merged.append("".join(buf))
        out.append(" ".join(merged))
    return " ".join(x for x in out if x)


def latex_unspace(text: str) -> str:
    """只在 LaTeX 命令引數內做字母黏合，**一般散文的空白一個都不動**。

    實測踩過（2026-08-02，N Flow）：MinerU 把整句散文吞進顯示式，寫成
    `\\mathrm { v e c t o r ~ f r o m ~ o r i g i n ~ o f ~ c o - o r d i n a t e s … }`。
    那些字**在 content_list 裡，只是被逐字母拆開排版**，`[a-z]{4,}` 一個都配不到，
    於是整段被記成「MinerU 弄丟了」。與階段 1 的 `ﬂ` 合字同族：偵測器量到的是
    排版差異，不是內容缺漏（鐵則 5）。

    範圍限制在 `\\cmd{…}` 之內是刻意的。若對整份文字無差別黏合，散文裡
    `a b c` 這類真正分開的單字母也會被黏起來，那就從「修正假訊號」變成
    「製造假內容」—— 而它會讓漏詞數變小，是往看不見的方向錯。
    """
    return CMD_ARG.sub(lambda m: m.group(1) + _glue_letters(m.group(2)) + m.group(3), text)


# 軟連字號（U+00AD）＋換行 ＝ 排版斷字，不是內容。
# **NFKC 不會處理它** —— 它是格式字元不是相容字元。
SOFT_HYPHEN = re.compile("\u00ad\\s*")


def desoft(text: str) -> str:
    """把排版斷字接回去：`absorp<U+00AD>\\ntion` → `absorption`。

    實測踩過（2026-08-13）：`2025 - Incorporating extended neck …` 量出漏詞
    5.6%，漏最多的是 `tion(10)`、`quency(7)`、`absorp(6)`、`sorption(6)`、
    `asurface(4)` —— 看起來像 MinerU 把整段內容弄丟了。實際上 pdftotext 吐的是
    **軟連字號**（隱形字元），`[a-z]{4,}` 配不到它，於是把 `absorp­tion` 從中間
    切成兩個「詞」；MinerU 那邊是正確接好的 `absorption`。**解析是對的，
    量測工具錯了。**

    ⚠ 這與檔頭記的 `ﬂ` 連字（U+FB02）是**同一個形狀的第二次**：偵測器量到的是
    文字層的排版產物，不是內容缺漏（鐵則 5：覺得數字不對時先查偵測器量了什麼）。

    ⚠ 兩邊都做，理由同 `words()` 的說明 —— 單邊正規化正是「同一份資料兩個答案」
    的來源。content 側本來就沒有軟連字號，所以對稱套用不會動到分子。
    """
    return SOFT_HYPHEN.sub("", text or "")


def words(text: str) -> collections.Counter:
    """斷詞前**必須先做 NFKC 正規化**，再做 LaTeX 字母間隔正規化。

    實測踩過（本檔第一版）：`N Flow Acoustics` 量出 10.1%，已知答案是 8.7%，
    漏最多的詞是 `uctuations(41)`、`uctuating(20)`。看起來像 MinerU 把整段
    「fluctuations」弄丟了 —— 實際上 pdftotext 吐的是**連字字元** `ﬂ`（U+FB02），
    `[a-z]{4,}` 配不到它，於是把 `ﬂuctuations` 從中間切成 `uctuations`；
    MinerU 那邊吐的是 ASCII 的 `fl`，兩邊其實都有這個字。

    也就是說偵測器量到的是 Unicode 正規化差異，不是內容缺漏（鐵則 5：
    門檻用量的不要用調的，而覺得數字不對時先查偵測器量了什麼）。
    NFKC 會把 ﬁ ﬂ ﬀ ﬃ ﬄ 這些相容字元攤回 ASCII 字母，兩邊才在同一個字母表上比。

    兩道正規化**兩邊都做**，不是只做 content 側。實測驗過 `latex_unspace` 對
    20 份的 pdftotext 輸出全部是 no-op（文字層本來就沒有 LaTeX 命令），所以
    對稱套用不會動到分母；但寫成對稱的才不會有人日後把它挪成單邊而不自知 ——
    單邊正規化正是「同一份資料兩個答案」的來源。
    """
    t = latex_unspace(unicodedata.normalize("NFKC", desoft(text)))
    return collections.Counter(WORD.findall(t.lower()))


def _strings(v: object) -> list[str]:
    """遞迴收字串。captions / footnotes / list_items 都是清單，
    有的還是清單包字典，一律走到底。"""
    if isinstance(v, str):
        return [v]
    if isinstance(v, list):
        return [s for x in v for s in _strings(x)]
    if isinstance(v, dict):
        return [s for k, x in v.items() if k not in SKIP_KEYS for s in _strings(x)]
    return []


def content_words(content_list: Path) -> tuple[collections.Counter, int]:
    items = json.loads(content_list.read_text())
    c = collections.Counter()
    for it in items:
        skip = SKIP_KEYS | pp_skip(it)
        for k, v in it.items():
            if k in skip:
                continue
            for s in _strings(v):
                c.update(words(s))
    return c, len(items)


def pdf_words(pdf: Path) -> collections.Counter:
    """pdftotext 的文字層。-q 吞掉字型警告，那些會混進 stdout 之外但很吵。"""
    p = subprocess.run(["pdftotext", "-q", str(pdf), "-"],
                       capture_output=True, text=True, timeout=300, check=False)
    if p.returncode != 0:
        raise RuntimeError(f"pdftotext exit {p.returncode}: {p.stderr.strip()[:200]}")
    return words(p.stdout)


def find_source_pdf(raw_dir: Path, source_dir: Path | None = None) -> Path | None:
    """來源 PDF 的位置**不得寫死**：LightRAG 的 archive_source 會把它從
    inputs/<workspace>/ 搬進 work/parsed/，所以同一份文件在解析前後路徑不同。
    有 manifest 就用 source_content_hash 內容定址確認（與 compat-check A-13
    同一套判準），沒有就退回檔名比對。
    """
    name = raw_dir.name.removesuffix(".mineru_raw")
    cands = []
    if source_dir is not None:
        cands.append(source_dir / name)
    cands.extend([raw_dir.parent / name, *sorted(raw_dir.glob("*_origin.pdf"))])
    want = None
    mf = raw_dir / "_manifest.json"
    if mf.is_file():
        try:
            want = json.loads(mf.read_text()).get("source_content_hash")
        except Exception:  # noqa: BLE001
            want = None
    fallback = None
    for c in cands:
        if not (c.exists() and c.is_file()):
            continue
        if want:
            h = "sha256:" + hashlib.sha256(c.read_bytes()).hexdigest()
            if h == want:
                return c
            fallback = fallback or c
        else:
            return c
    # 雜湊對不上時仍回報找到的那個，但呼叫端會標記出來 —— 「找不到來源」與
    # 「來源換了內容」是兩件事，不能混成同一種失敗。
    return fallback


def check_doc(raw_dir: Path, source_dir: Path | None = None) -> dict:
    cl = raw_dir / "content_list.json"
    name = raw_dir.name.removesuffix(".pdf.mineru_raw")
    if not cl.is_file():
        return {"doc": name, "error": "缺少 content_list.json（解析未完成或失敗）"}
    pdf = find_source_pdf(raw_dir, source_dir)
    if pdf is None:
        return {"doc": name, "error": "找不到來源 PDF，無法取得文字層對照"}
    try:
        a = pdf_words(pdf)
    except Exception as e:  # noqa: BLE001
        return {"doc": name, "error": f"pdftotext 失敗：{e}"}
    b, n_items = content_words(cl)

    total = sum(a.values())
    if total == 0:
        # 文字層本身是空的（純掃描件）。這時候比不出東西來 —— 是「驗不了」，
        # 不是「0% 漏詞」。把它報成 pass 會讓掃描件全部無聲通過閘門。
        return {"doc": name, "error": "PDF 沒有文字層（純掃描件？），無對照源",
                "unverifiable": True, "pdf": str(pdf)}

    missing = a - b            # 多重集合差：逐詞的次數差，負的自動歸零
    n_missing = sum(missing.values())
    return {
        "doc": name,
        "pdf": str(pdf),
        "items": n_items,
        "pdf_words": total,
        "content_words": sum(b.values()),
        "missing": n_missing,
        "rate": n_missing / total,
        "top": missing.most_common(10),
    }


def scan(root: Path, workspace: str, doc: str | None) -> list[dict]:
    paths = DataPaths(root)
    pdir = paths.parsed_dir
    source_dir = paths.inputs_dir(workspace)
    if not pdir.is_dir():
        print(f"coverage-check: 找不到解析目錄 {pdir}", file=sys.stderr)
        return []
    out = []
    for raw in sorted(pdir.glob("*.mineru_raw")):
        if doc and doc.lower() not in raw.name.lower():
            continue
        out.append(check_doc(raw, source_dir))
    return out


def report(results: list[dict], threshold: float, show_top: bool) -> int:
    if not results:
        print("沒有已解析的文件。")
        return 0
    results = sorted(results, key=lambda r: -r.get("rate", -1))

    print(f"{'文件':<44} {'漏詞率':>7} {'漏/總':>16}  狀態")
    print("-" * 92)
    n_over = n_unver = 0
    for r in results:
        if r.get("error"):
            state = "驗不了" if r.get("unverifiable") else " ERROR"
            n_unver += 1 if r.get("unverifiable") else 0
            n_over += 0 if r.get("unverifiable") else 1
            print(f"{r['doc'][:43]:<44} {'':>7} {'':>16}  {state} {r['error']}")
            continue
        over = r["rate"] > threshold
        n_over += over
        print(f"{r['doc'][:43]:<44} {r['rate']*100:>6.1f}% "
              f"{r['missing']:>7,}/{r['pdf_words']:>7,}  {'超標' if over else 'ok'}")
    print("-" * 92)
    print(f"共 {len(results)} 份：門檻 {threshold*100:.0f}%，"
          f"超標 {n_over} 份、驗不了 {n_unver} 份、"
          f"通過 {len(results)-n_over-n_unver} 份")

    if show_top:
        for r in results:
            if r.get("error") or not r.get("top"):
                continue
            if show_top != "all" and r["rate"] <= threshold:
                continue
            print(f"\n=== {r['doc']}　漏詞率 {r['rate']*100:.1f}% ===")
            print("  漏最多的詞：" + "、".join(f"{w}({n})" for w, n in r["top"]))

            # 超標時把「這份查過了、結論是什麼」印在旁邊。2026-08-07 實測缺這段的
            # 代價：C 的 10.6% 超標，而它 2026-08-02 就已逐詞歸因完（表格黏連 117、
            # 圖裡 73、bbox 未覆蓋 91），結論在 ledger 裡 —— 但工具沒說，於是又查了
            # 一次。verified-findings.json 的 _rule 明寫「不要求任何人記得去哪裡找」，
            # extract-check 接了、這支沒接。
            if r["rate"] > threshold:
                hit = findings.lookup("coverage-check", "missing_word_rate", r["doc"],
                                      current={"rate": r["rate"], "missing": r["missing"],
                                               "pdf_words": r["pdf_words"]})
                if hit:
                    for line in hit.lines():
                        print(line)
    return 1 if n_over else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="coverage 閘門：pdftotext vs content_list")
    # 預設 workspace 走 mineru_common.add_workspace_arg —— 與所有其他腳本
    # 同一個推導處。各自 f-string 或各自讀 shell 環境變數，就會出現「在某個
    # checkout 跑，卻安靜地驗了另一個 workspace 的產物」這種不會報錯的錯。
    add_workspace_arg(ap, load_env(REPO))
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    ap.add_argument("--doc", help="檔名關鍵字，只檢查符合的文件")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    ap.add_argument("--all-top", action="store_true",
                    help="每份都印漏最多的詞（預設只印超標的）")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    results = scan(a.root, a.workspace, a.doc)
    # 分母：這次比對了幾份。`check-levels.py` 看到 rc=0 卻沒有這一行（或 0），
    # 會**拒發綠燈**改判「驗不了」。約定見 daily-check.sh。
    #
    # ⚠ **印在這裡，不是印在 `report()` 裡。** `--json` 會提早 return，
    # 根本走不到 `report()` —— 而 daily-check 用的正是 `--json`。
    # 2026-08-21 第一版就是放錯地方，橫幅當場寫「PDF 的字有沒有漏掉
    # (rc=1、沒報分母)」把自己的缺口叫出來了。
    # ⚠ 走 stderr：`--json` 的 stdout 整份是 JSON，混一行進去會讓解析壞掉。
    print(f"#scope {len(results)}", file=sys.stderr)
    if a.json:
        print(json.dumps(results, ensure_ascii=False, indent=1))
        return 1 if any(r.get("rate", 0) > a.threshold for r in results) else 0
    # 指定單一文件時就是在看那一份，漏詞清單一律印出來。
    show = "all" if (a.all_top or a.doc) else True
    return report(results, a.threshold, show)


if __name__ == "__main__":
    sys.exit(main())
