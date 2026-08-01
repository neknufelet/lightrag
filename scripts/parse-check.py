#!/usr/bin/env python3
"""檢查 MinerU 把 PDF 拆得好不好 —— 不需要等 LLM 抽取。

MinerU 的原始輸出會快取在 inputs/<workspace>/__parsed__/<檔名>.mineru_raw/，
所以解析一結束就能驗，不必等後面幾十小時的實體抽取跑完。整批重新 parsing 時，
先跑這個確認拆得對，再讓 LLM 上工。

用法：
    ./scripts/parse-check.py                        # 檢查預設 workspace 全部文件
    ./scripts/parse-check.py --workspace foo
    ./scripts/parse-check.py --details              # 印出問題的實際位置與內文
    ./scripts/parse-check.py --watch                # 邊跑邊看，有新文件就檢查

有文件被判定 ERROR 時 exit 1，方便接在自動化後面擋下去。
"""
import argparse, collections, json, os, re, sys, time
from pathlib import Path

DEFAULT_ROOT = Path("/data/lightrag")

# 掉字偵測器 —— 已驗證版本。務必用 \b 這種非消耗性邊界；
# 寫成兩側都是 \s 的 (\s[a-z]{1,2}\s){5,} 會因為前一次匹配吃掉後一次的前導空白而永遠回 0。
MANGLED = re.compile(r"(?:\s+[a-z]{1,2}\b){5,}")

# 這些 prompt 範例字串若出現在正文，代表模型把提示詞當成內容（1.5.5 上游已移除，留著防退化）
LEAK = re.compile(r"Noah Carter|World Athletics|Carbon-Fiber Spikes|100m Sprint|Knowledge Graph Specialist", re.I)


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
        # 各類型的正文欄位不同
        body = it.get("text") or it.get("table_body") or it.get("code_body") or ""
        if t in ("text", "header"):
            r["字元數"] += len(body)
            text_by_page[it.get("page_idx")] += len(body)

        loc = {"i": idx, "type": t, "page": it.get("page_idx")}

        if body and MANGLED.search(body):
            m = MANGLED.search(body)
            r["mangled"].append({**loc, "snippet": body[max(0, m.start() - 40): m.end() + 40]})
        if body and LEAK.search(body):
            r["洩漏"].append({**loc, "snippet": body[:120]})

        if t in ("text", "header") and not body.strip():
            r["空文字"].append(loc)
        elif t == "table" and not (it.get("table_body") or "").strip():
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


def scan(root: Path, workspace: str):
    pdir = root / workspace / "inputs" / workspace / "__parsed__"
    if not pdir.exists():
        print(f"找不到解析目錄：{pdir}", file=sys.stderr)
        return []
    out = []
    for raw in sorted(pdir.glob("*.mineru_raw")):
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
    ap = argparse.ArgumentParser(description="檢查 MinerU 的 PDF 拆解品質")
    ap.add_argument("--workspace", default=os.environ.get("WORKSPACE", "acoustics_v155"))
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    ap.add_argument("--details", action="store_true", help="印出問題的實際位置與內文")
    ap.add_argument("--watch", action="store_true", help="每 60 秒重掃一次，適合邊解析邊看")
    a = ap.parse_args()

    if not a.watch:
        sys.exit(report(scan(a.root, a.workspace), a.details))

    seen = None
    while True:
        results = scan(a.root, a.workspace)
        sig = [(n, s) for n, _, s in results]
        if sig != seen:
            print(f"\n--- {time.strftime('%H:%M:%S')} ---")
            report(results, a.details)
            seen = sig
        time.sleep(60)


if __name__ == "__main__":
    main()
