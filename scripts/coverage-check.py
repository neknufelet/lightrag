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
    ./coverage-check.py --workspace acoustics_v155   # 對照組（唯讀）
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
from pp.oracle import env_workspace  # noqa: E402

DEFAULT_ROOT = Path("/data/rag/lightrag")
DEFAULT_THRESHOLD = 0.05

# ≥4 字母的純英文詞。理由見檔頭。
WORD = re.compile(r"[a-z]{4,}")

# content_list 裡**不算文字**的欄位。少列一個的代價只是漏詞被藏起來
# （多出來的詞只會抵銷掉真正的缺漏），所以這裡寧可列滿：
#   img_path          圖檔名，是 uuid/雜湊，字母碎片會假裝成詞彙
#   type/sub_type     結構標籤（'code'、'list'、'table'）不是內容
#   text_format       'latex' 這類格式註記
#   _pp_original_type chart→image 轉換前的型別，同樣是標籤
#   _pp_repaired_at   修補時間戳
# 注意 _pp_original_text **不在**這裡 —— 它是被消音的原文，要讀回來（見檔頭）。
SKIP_KEYS = {
    "img_path", "type", "sub_type", "text_format",
    "_pp_original_type", "_pp_repaired_at",
}


def words(text: str) -> collections.Counter:
    """斷詞前**必須先做 NFKC 正規化**。

    實測踩過（本檔第一版）：`N Flow Acoustics` 量出 10.1%，已知答案是 8.7%，
    漏最多的詞是 `uctuations(41)`、`uctuating(20)`。看起來像 MinerU 把整段
    「fluctuations」弄丟了 —— 實際上 pdftotext 吐的是**連字字元** `ﬂ`（U+FB02），
    `[a-z]{4,}` 配不到它，於是把 `ﬂuctuations` 從中間切成 `uctuations`；
    MinerU 那邊吐的是 ASCII 的 `fl`，兩邊其實都有這個字。

    也就是說偵測器量到的是 Unicode 正規化差異，不是內容缺漏（鐵則 5：
    門檻用量的不要用調的，而覺得數字不對時先查偵測器量了什麼）。
    NFKC 會把 ﬁ ﬂ ﬀ ﬃ ﬄ 這些相容字元攤回 ASCII 字母，兩邊才在同一個字母表上比。
    """
    return collections.Counter(WORD.findall(unicodedata.normalize("NFKC", text).lower()))


def _strings(v) -> list[str]:
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
        for k, v in it.items():
            if k in SKIP_KEYS:
                continue
            for s in _strings(v):
                c.update(words(s))
    return c, len(items)


def pdf_words(pdf: Path) -> collections.Counter:
    """pdftotext 的文字層。-q 吞掉字型警告，那些會混進 stdout 之外但很吵。"""
    p = subprocess.run(["pdftotext", "-q", str(pdf), "-"],
                       capture_output=True, text=True, timeout=300)
    if p.returncode != 0:
        raise RuntimeError(f"pdftotext exit {p.returncode}: {p.stderr.strip()[:200]}")
    return words(p.stdout)


def find_source_pdf(raw_dir: Path) -> Path | None:
    """來源 PDF 的位置**不得寫死**：LightRAG 的 archive_source 會把它從
    inputs 根層搬進 __parsed__/，所以同一份文件在解析前後路徑不同。
    有 manifest 就用 source_content_hash 內容定址確認（與 compat-check A-13
    同一套判準），沒有就退回檔名比對。
    """
    name = raw_dir.name.removesuffix(".mineru_raw")
    cands = [raw_dir.parent / name, raw_dir.parent.parent / name,
             *sorted(raw_dir.glob("*_origin.pdf"))]
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


def check_doc(raw_dir: Path) -> dict:
    cl = raw_dir / "content_list.json"
    name = raw_dir.name.removesuffix(".pdf.mineru_raw")
    if not cl.is_file():
        return {"doc": name, "error": "缺少 content_list.json（解析未完成或失敗）"}
    pdf = find_source_pdf(raw_dir)
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
    pdir = root / workspace / "inputs" / workspace / "__parsed__"
    if not pdir.is_dir():
        print(f"coverage-check: 找不到解析目錄 {pdir}", file=sys.stderr)
        return []
    out = []
    for raw in sorted(pdir.glob("*.mineru_raw")):
        if doc and doc.lower() not in raw.name.lower():
            continue
        out.append(check_doc(raw))
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
            if not show_top == "all" and r["rate"] <= threshold:
                continue
            print(f"\n=== {r['doc']}　漏詞率 {r['rate']*100:.1f}% ===")
            print("  漏最多的詞：" + "、".join(f"{w}({n})" for w, n in r["top"]))
    return 1 if n_over else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="coverage 閘門：pdftotext vs content_list")
    # 預設 workspace 走 pp/oracle.env_workspace() —— 與所有其他腳本同一個推導處。
    # 各自 f-string 或各自讀 shell 環境變數，就會出現「在 v2 的 checkout 跑，
    # 卻安靜地驗了 v155 的產物」這種不會報錯的錯。
    ap.add_argument("--workspace", default=env_workspace())
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    ap.add_argument("--doc", help="檔名關鍵字，只檢查符合的文件")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    ap.add_argument("--all-top", action="store_true",
                    help="每份都印漏最多的詞（預設只印超標的）")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    results = scan(a.root, a.workspace, a.doc)
    if a.json:
        print(json.dumps(results, ensure_ascii=False, indent=1))
        return 1 if any(r.get("rate", 0) > a.threshold for r in results) else 0
    # 指定單一文件時就是在看那一份，漏詞清單一律印出來。
    show = "all" if (a.all_top or a.doc) else True
    return report(results, a.threshold, show)


if __name__ == "__main__":
    sys.exit(main())
