#!/usr/bin/env python3
"""只解析，不抽取。

為什麼需要：/scan 會把「MinerU 解析」和「實體抽取」綁在一起跑，但兩者的性質
完全不同 ——

    MinerU 解析   雲端、可並行、約 1–2 分/份
    實體抽取      本機 LLM、序列、大章節 30 分以上

規則建立期只需要 .mineru_raw/，根本用不到抽取。綁在一起的結果是每加一份文件
都要等抽取跑完才能繼續驗規則，而 390 份要跑 6–10 小時解析加上遠多於此的抽取。

做法：在容器裡直接呼叫 MinerU client 的 download_into()。它不需要 rag 實例或
doc_id，會自己寫 manifest。**不重新實作任何契約** —— 呼叫的就是 pipeline 用的
那份程式碼，在同一個容器、同一組環境變數下，所以 options 簽章一致。

驗證：產出後立刻問 LightRAG 自己 is_bundle_valid()。它說有效，之後 /scan 才會
命中快取直接跳到抽取；說無效就是白花錢，要當場知道而不是等到下次掃描。

用法：
    parse-only.py --workspace <workspace>               # 掃描 inputs 裡所有未解析的
    parse-only.py --workspace <workspace> --source-kind parsed
                                                        # 審核台的 work/parsed 暫存來源
    parse-only.py --doc <關鍵字>
    parse-only.py --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mineru_common import add_workspace_arg, load_env  # noqa: E402
from pp.oracle import Oracle, OracleError, container_for  # noqa: E402
from pp.paths import ContainerPaths, DataPaths, configured_data_root  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DATA_ROOT = configured_data_root()

_SNIPPET = r'''
import asyncio, json, sys
from pathlib import Path
from lightrag.parser.external.mineru.client import MinerURawClient
from lightrag.parser.external.mineru import is_bundle_valid

src  = Path(sys.argv[1])
raw  = Path(sys.argv[2])
name = sys.argv[3]

out = {"source": str(src), "raw_dir": str(raw)}
if not src.is_file():
    print(json.dumps({**out, "ok": False, "error": "來源檔不存在"})); raise SystemExit

# 已經有有效 bundle 就不要重抓 —— 重抓要錢，而且會覆蓋掉後處理可能已經改過的內容
if raw.is_dir() and is_bundle_valid(raw, src, overrides=None):
    print(json.dumps({**out, "ok": True, "skipped": "已有有效 bundle"})); raise SystemExit

raw.mkdir(parents=True, exist_ok=True)
try:
    asyncio.run(MinerURawClient().download_into(raw, src, upload_name=name))
except Exception as e:
    print(json.dumps({**out, "ok": False, "error": f"{type(e).__name__}: {e}"})); raise SystemExit

# 產完立刻問 LightRAG 本人算不算數。不算數就是白花錢，要當場知道。
valid = is_bundle_valid(raw, src, overrides=None)
n = None
cl = raw / "content_list.json"
if cl.is_file():
    try: n = len(json.loads(cl.read_text()))
    except Exception: pass
print(json.dumps({**out, "ok": valid, "items": n,
                  "error": None if valid else "產出的 bundle 未通過 is_bundle_valid —— "
                                              "簽章不符，/scan 時會重抓"}))
'''


def main() -> int:
    env = load_env(REPO)
    ap = argparse.ArgumentParser(description="只跑 MinerU 解析，不觸發實體抽取")
    add_workspace_arg(ap, env)
    ap.add_argument("--doc", help="檔名關鍵字，預設全部未解析的")
    ap.add_argument("--source-kind", choices=("inputs", "parsed"), default="inputs",
                    help="來源只能是 inputs 或 work/parsed；審核台解析用 parsed")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--timeout", type=int, default=1800,
                    help="單份解析的容器呼叫上限（秒）。預設 1800 —— 超過這個"
                         "還沒 content_list 才算真的卡住")
    a = ap.parse_args()

    ws = a.workspace
    paths = DataPaths(DATA_ROOT)
    source_dir = paths.inputs_dir(ws) if a.source_kind == "inputs" else paths.parsed_dir
    if not source_dir.is_dir():
        sys.exit(f"parse-only: 找不到 {source_dir}")

    todo = []
    for pdf in sorted(source_dir.glob("*.pdf")):
        raw = paths.parsed_bundle_dir(pdf.name)
        if (raw / "content_list.json").is_file():
            continue
        if a.doc and a.doc.lower() not in pdf.name.lower():
            continue
        todo.append(pdf)

    if not todo:
        print("沒有待解析的文件（掃描目錄裡的 PDF 都已有 content_list.json）")
        return 0

    print(f"待解析 {len(todo)} 份：")
    for p in todo:
        print(f"  {p.name}")
    if a.dry_run:
        return 0

    # 容器跟著 --workspace 走：解析要寫進該 workspace 掛載的 inputs，
    # 打錯容器的話 c_src 路徑在容器內根本不存在（或更糟，指到另一份同名檔）。
    #
    # timeout 一定要放大。Oracle 預設 120 秒是為契約探針設的（問一個常數、算一個
    # 簽章），而這裡是**整份 PDF 送雲端解析**，大檔要好幾分鐘。實測踩過：v2 的
    # 20 份裡最大的兩份（3.8MB、33.7MB）都在 120 秒撞上限，回報「容器呼叫失敗：
    # 逾時」——但 docker exec 逾時只殺掉客戶端，容器內的解析照跑完、bundle 也
    # 照樣寫進去且 is_bundle_valid 通過。也就是說**訊息是假的失敗**：照著它重跑
    # 會再付一次 MinerU 的錢，而且看不出上一次其實成功了。
    o = Oracle(container=container_for(ws), timeout=a.timeout)
    ok = bad = 0
    for pdf in todo:
        # compose 的兩個 mount 對齊為：宿主 DATA_ROOT/inputs/<ws> →
        # /app/data/inputs/<ws>；宿主 DATA_ROOT/work/parsed →
        # /app/data/inputs/<ws>/__parsed__。這些是容器內 LightRAG 契約路徑，
        # coder 沒有容器，實際 mount 生效與否必須在 dker 回程確認（未驗,推測）。
        container = ContainerPaths()
        c_src_root = (container.inputs_dir(ws) if a.source_kind == "inputs"
                      else container.parsed_dir(ws))
        c_src = c_src_root / pdf.name
        c_raw = container.parsed_bundle_dir(ws, pdf.name)
        print(f"\n→ {pdf.name}")
        try:
            r = o.py_argv(_SNIPPET, [str(c_src), str(c_raw), pdf.name])
        except OracleError as e:
            print(f"   ✗ 容器呼叫失敗：{e}")
            bad += 1
            continue
        if r.get("ok"):
            ok += 1
            why = r.get("skipped") or f"{r.get('items')} 個項目，is_bundle_valid 通過"
            print(f"   ✓ {why}")
        else:
            bad += 1
            print(f"   ✗ {r.get('error')}")

    print(f"\n{'-'*60}\n完成 {ok} 份、失敗 {bad} 份")
    if ok:
        print("這些 bundle 已可被 postprocess.py 處理。之後 /scan 會命中快取，"
              "直接進抽取階段，不會重新付費解析。")
    return 2 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
