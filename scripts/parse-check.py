#!/usr/bin/env python3
"""檢查 MinerU 把 PDF 拆得好不好 —— 不需要等 LLM 抽取。

MinerU 的原始輸出會快取在 work/parsed/<檔名>.pdf.mineru_raw/，
所以解析一結束就能驗，不必等後面幾十小時的實體抽取跑完。整批重新 parsing 時，
先跑這個確認拆得對，再讓 LLM 上工。

用法：
    ./scripts/parse-check.py                        # 檢查預設 workspace 全部文件
    ./scripts/parse-check.py --workspace foo
    ./scripts/parse-check.py --details              # 印出問題的實際位置與內文
    ./scripts/parse-check.py --watch                # 邊跑邊看，有新文件就檢查

有文件被判定 ERROR 時 exit 1，方便接在自動化後面擋下去。
"""
import argparse
import collections
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# 偵測器一律從 mineru_common 拿，不要在這裡另外定義一份。
# 這支腳本曾經自己複製 MANGLED，結果 mineru_common 修好了誤判、這裡還在用舊
# 規則，同一份資料兩個答案 —— 正是 mineru_common 檔頭警告的漂移。
from mineru_common import (  # noqa: E402
    LEAK,
    MANGLED,
    is_mangled,
    load_env,
    strip_math,
    table_text,
)
from pp.paths import DEFAULT_DATA_ROOT, DataPaths  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DEFAULT_ROOT = DEFAULT_DATA_ROOT




# 這些 prompt 範例字串若出現在正文，代表模型把提示詞當成內容（1.5.5 上游已移除，留著防退化）


def body_of(it: dict) -> str:
    """項目的正文，**消音過的要把原文讀回來**。

    這支腳本驗的是「MinerU 把 PDF 拆得好不好」，而消音是**我們自己**在後處理裡
    把書眉/頁尾的 `text` 清空、原文存進 `_pp_original_text`。不讀回來的話，同一份
    解析產物在後處理前後會量出兩個答案，而且後處理後那個看起來像 MinerU 變爛了
    ——把自己的決定誤記成上游的缺陷。實測：階段 2 寫回後全庫空塊 11→111、
    C 的無文字頁 0→36，全部是這個假訊號（coverage-check 早就修好了同一個 bug，
    這支漏掉，於是兩支腳本對同一份資料給兩個答案）。

    **只在現值是空的時候才讀回。** `_pp_original_text` 有兩種寫入者：
      - 消音 → `text` 清空，原文在 `_pp_original_text`　→ 要讀回
      - 文字修補（verified_text）→ `text` 是人工裁定的**正確**內容，
        `_pp_original_text` 是 MinerU 的亂碼　→ **絕對不能讀回**
    無條件讀回會把 C p64 那段 OCR 亂碼 "Ab = = ze = etsosbd) te se…" 請回來，
    掉字偵測立刻再度紅燈——修好的東西被檢查自己還原成壞的。
    """
    body = it.get("text") or it.get("table_body") or it.get("code_body") or ""
    if not body.strip():
        body = it.get("_pp_original_text") or ""
    return body


def check_doc(raw_dir: Path) -> dict:
    """檢查單一文件的 MinerU 輸出。回傳問題統計與細節。"""
    cl = raw_dir / "content_list.json"
    if not cl.exists():
        return {"error": "缺少 content_list.json（解析未完成或失敗）"}

    items = json.loads(cl.read_text())
    by_type = collections.Counter(i.get("type") for i in items)
    pages = {i.get("page_idx") for i in items if i.get("page_idx") is not None}
    n_pages = max(pages) + 1 if pages else 0

    r = {
        "區塊": len(items), "頁數": n_pages, "類型": dict(by_type),
        "mangled": [], "空文字": [], "空表格": [], "空公式": [], "洩漏": [],
        "無文字頁": [], "字元數": 0,
    }

    text_by_page = collections.Counter()
    for idx, it in enumerate(items):
        t = it.get("type")
        # 各類型的正文欄位不同；消音過的要還原（見 body_of）
        body = body_of(it)
        if t in ("text", "header"):
            r["字元數"] += len(body)
            text_by_page[it.get("page_idx")] += len(body)

        loc = {"i": idx, "type": t, "page": it.get("page_idx")}

        # 掉字偵測只跑散文（text / header）。equation 的 text 是沒有 $ 包裹的裸 LaTeX，
        # table_body 也整片是標記，兩者本來就長得像掉字（\mathrm { e n t r a n c e }），
        # 在數學密集的文件上會讓每一份都變 ERROR。散文內的行內數學仍要先剝掉。
        # 判斷一律走 mineru_common.is_mangled —— 這裡曾經自己複製一份 MANGLED，
        # 結果 mineru_common 修好了誤判、這支還在用舊規則，同一份資料兩個答案。
        # 那正是 mineru_common 檔頭警告的漂移。
        if is_mangled(body, t):
            clean = strip_math(body)
            m = MANGLED.search(clean)
            r["mangled"].append({**loc, "snippet":
                clean[max(0, m.start() - 40): m.end() + 40] if m else clean[:120]})
        if body and LEAK.search(body):
            r["洩漏"].append({**loc, "snippet": body[:120]})

        if t in ("text", "header") and not body.strip():
            r["空文字"].append(loc)
        elif t == "table" and not table_text(it.get("table_body")):
            r["空表格"].append(loc)
        elif t == "equation" and not (it.get("text") or "").strip():
            r["空公式"].append(loc)

    # 完全沒有正文的頁面 —— 可能是整頁圖表（正常），也可能是該頁解析失敗
    for p in range(n_pages):
        if text_by_page.get(p, 0) == 0:
            r["無文字頁"].append(p)

    return r


def severity(r: dict) -> str:
    if r.get("error"):                                   return "ERROR"
    if r["mangled"] or r["洩漏"]:                        return "ERROR"
    if r["字元數"] == 0:                                 return "ERROR"
    if r["空文字"] or r["空表格"] or r["空公式"]:        return "WARN"
    if len(r["無文字頁"]) > max(3, r["頁數"] * 0.2):     return "WARN"
    return "OK"


def scan(root: Path, workspace: str, doc: str | None = None):
    paths = DataPaths(root)
    pdir = paths.parsed_dir
    if not pdir.exists():
        print(f"找不到解析目錄：{pdir}", file=sys.stderr)
        return []
    out = []
    for raw in sorted(pdir.glob("*.mineru_raw")):
        # --doc 只是**縮小範圍**，預設仍然掃全部。不可以把檢查本身關在
        # `if doc:` 底下——那樣它就只驗「你已經在懷疑的那一份」，而你不會對
        # 沒想到的那份指定關鍵字（鐵則 6：A-16 的 184 個 chart 就是這樣漏掉的）。
        if doc and doc.lower() not in raw.name.lower():
            continue
        r = check_doc(raw)
        out.append((raw.name.removesuffix(".pdf.mineru_raw"), r, severity(r)))
    # 最嚴重的排前面
    order = {"ERROR": 0, "WARN": 1, "OK": 2}
    out.sort(key=lambda x: (order[x[2]], -len(x[1].get("mangled", []))))
    return out


def report(results, details=False):
    if not results:
        print("沒有已解析的文件。")
        return 0

    print(f"{'文件':<42} {'狀態':<6} {'頁':>4} {'字元':>8} {'掉字':>5} {'空塊':>5} {'無文字頁':>8}")
    print("-" * 90)
    for name, r, sev in results:
        if r.get("error"):
            print(f"{name[:41]:<42} {sev:<6} {r['error']}")
            continue
        empties = len(r["空文字"]) + len(r["空表格"]) + len(r["空公式"])
        print(f"{name[:41]:<42} {sev:<6} {r['頁數']:>4} {r['字元數']:>8,} "
              f"{len(r['mangled']):>5} {empties:>5} {len(r['無文字頁']):>8}")

    n_err = sum(1 for _, _, s in results if s == "ERROR")
    n_warn = sum(1 for _, _, s in results if s == "WARN")
    print("-" * 90)
    print(f"共 {len(results)} 份： OK {len(results)-n_err-n_warn} ／ WARN {n_warn} ／ ERROR {n_err}")
    # 分母：這次比對了幾件事。`check-levels.py` 看到 rc=0 卻沒有這一行
    # （或 0），會**拒發綠燈**改判「驗不了」—— 近 30 天 17 次「燈說假話」
    # 裡最大的一族，全部是綠燈在空集合上算出來的。約定見 daily-check.sh。
    print(f"#scope {len(results)}")

    if details:
        for name, r, sev in results:
            if sev == "OK" or r.get("error"):
                continue
            print(f"\n=== {name} [{sev}] ===")
            for label in ("mangled", "洩漏"):
                for h in r.get(label, [])[:5]:
                    print(f"  {label} p{h['page']} ({h['type']}): {h['snippet']!r}")
            for label in ("空文字", "空表格", "空公式"):
                hits = r.get(label, [])
                if hits:
                    print(f"  {label} {len(hits)} 處，頁: {sorted({h['page'] for h in hits})[:12]}")
            if r["無文字頁"]:
                print(f"  無正文的頁: {r['無文字頁'][:20]}")

    return 1 if n_err else 0


def main():
    env = load_env(REPO)
    ap = argparse.ArgumentParser(description="檢查 MinerU 的 PDF 拆解品質")
    # 這支原本只看 shell 的 WORKSPACE，不讀本 checkout 的 .env —— 全 scripts/ 裡
    # 唯一的例外。後果是在 v2 的 checkout 直接跑會靜靜地去檢查 v155 的 bundle，
    # 數字看起來完全正常。改成與其他腳本一致：shell 環境變數優先，其次 .env。
    workspace = os.environ.get("WORKSPACE") or env.get("WORKSPACE") or None
    ap.add_argument("--workspace", default=workspace, required=workspace is None)
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    ap.add_argument("--doc", help="檔名關鍵字，只檢查符合的文件（預設全部）")
    ap.add_argument("--details", action="store_true", help="印出問題的實際位置與內文")
    ap.add_argument("--watch", action="store_true", help="每 60 秒重掃一次，適合邊解析邊看")
    a = ap.parse_args()

    if not a.watch:
        # 指定單一文件時就是在看那一份，細節一律印出來。
        sys.exit(report(scan(a.root, a.workspace, a.doc), a.details or bool(a.doc)))

    seen = None
    while True:
        results = scan(a.root, a.workspace, a.doc)
        sig = [(n, s) for n, _, s in results]
        if sig != seen:
            print(f"\n--- {time.strftime('%H:%M:%S')} ---")
            report(results, a.details)
            seen = sig
        time.sleep(60)


if __name__ == "__main__":
    main()
