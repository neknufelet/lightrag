#!/usr/bin/env python3
"""回填體檢表：把**已經有的判定**補進現有文件的表，不重跑任何檢查、不花錢。

## 為什麼需要這支

`intake.py` 從 2026-08-10 起會在計畫判完時自動寫 `pp.preflight` 與 `pp.tables`，
但那**只對之後進來的文件有效**。庫裡 259 份是那之前進的，表上一片空白 ——
2026-08-11 實測 2072 格裡 1940 格未設定（93.6%）。

材料本來就在磁碟上：每個 job 的 `job.json` 都留著當時的 `plan`。這支把它讀回來，
套用**同一段判定**（`intake.ledger_entries_from_plan`）寫進表。

⚠ **判定不在這裡實作。** 抄一份就是再造第二條會漂移的路 —— 這個專案已經被
「兩條路」咬過（十二道閘門的 V1／V2 在兩個地方各寫一份，其中一份沒人叫）。

## 填哪幾格

    pp.preflight    job.json 的 decision
    pp.tables       job.json 的 plan.tables
    pp.equations    scan-partial 的命中數（那一格當初就是這樣驗的，見既有表的備註）
    extract.grounding  `extract-check.py --json` 的逐份統計（要用 --extract-json 餵進來）

其餘四格要跑別的檢查，不在這支的範圍。**沒跑過的閘門一格都不填** ——
填 `pass` 就是說謊，而三態設計正是為了不讓「不知道」偽裝成「查過了」。

## 用法

    ledger-backfill.py                                    # 乾跑，只印會寫什麼
    ledger-backfill.py --apply                            # 真的寫
    extract-check.py --json > /tmp/eg.json                # 接地那格的材料（3 秒）
    ledger-backfill.py --extract-json /tmp/eg.json --apply
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter
from collections.abc import Mapping
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import intake  # noqa: E402
import ledger  # noqa: E402
from mineru_common import add_workspace_arg, load_env  # noqa: E402
from pp.paths import DEFAULT_DATA_ROOT, DataPaths  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def _load_scan_partial() -> object:
    """`scan-partial.py` 的檔名有連字號，只能用 loader 載。"""
    spec = importlib.util.spec_from_file_location(
        "scan_partial", Path(__file__).resolve().parent / "scan-partial.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def latest_job_per_document(jobs: list[Mapping[str, object]]) -> dict[str, Mapping[str, object]]:
    """同一份文件可能有好幾個 job（重試、重置過的）。**取最後更新的那個。**

    取錯的話會拿一次失敗的重試蓋掉成功那次的判定 —— 而表上看不出來。
    沒有 `updated_at` 的排在最前面（當成最舊），不讓缺欄位的意外勝出。
    """
    best: dict[str, Mapping[str, object]] = {}
    for job in sorted(jobs, key=lambda j: str(j.get("updated_at") or "")):
        name = str(job.get("filename") or "")
        if name:
            best[name] = job
    return best


def grounding_entry(
    stats: Mapping[str, int], threshold: float,
) -> tuple[str, str, float | None]:
    """`extract-check` 的一份逐份統計 →（三態, 理由, 比率）。

    ⚠ **分母只算「字串比對有鑑別力」的那些**（接得回原文的 ＋ 可疑的）。
    - 符號型（來源 chunk 全是表格／公式）算進分母會稀釋比例，而一份幾乎全是
      公式的文件永遠不會超標 —— 那正是最需要被看的那種。
    - 來源 chunk 找不到的是**簿記問題不是幻覺**，兩邊都不算；算成可疑的話，
      索引重建期間的一次不一致會在表上看起來像模型在編東西。

    分母 0 ⇒ **沒得驗**，不是通過。
    """
    total = int(stats.get("total") or 0)
    ok = int(stats.get("ok") or 0)
    missing = int(stats.get("missing_chunk") or 0)
    symbolic = int(stats.get("symbolic") or 0)
    suspect = total - ok - missing - symbolic
    denom = ok + suspect

    if denom <= 0:
        if total == 0:
            return "unverifiable", "這份沒有抽出任何實體 —— 沒東西可驗", None
        return ("unverifiable",
                f"全部 {total} 個實體的來源都是表格／公式（符號型 {symbolic}、"
                f"來源不見 {missing}），字串比對沒有鑑別力", None)

    ratio = suspect / denom
    note = (f"{suspect}/{denom} 個字串比對有鑑別力的實體接不回原文"
            f"（總計 {total} 個：符號型 {symbolic} 驗不了、來源不見 {missing}）")
    return ("pass" if ratio <= threshold else "fail"), note, ratio


def main() -> int:
    env = load_env(REPO)
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_workspace_arg(ap, env)
    ap.add_argument("--root", type=Path,
                    default=Path(env.get("DATA_ROOT", str(DEFAULT_DATA_ROOT))))
    ap.add_argument("--apply", action="store_true", help="真的寫進去（預設只乾跑）")
    ap.add_argument("--extract-json", type=Path, metavar="FILE",
                    help="`extract-check.py --json` 的輸出，用來填 extract.grounding")
    ap.add_argument("--threshold", type=float, default=0.10,
                    help="接地可疑率門檻（預設同 extract-check 的 T_UNGROUNDED）")
    a = ap.parse_args()

    paths = DataPaths(a.root)
    parsed = paths.parsed_dir
    # **母體是「現在還在的文件」**，不是所有 job。拿已經不存在的文件去填表，
    # 就是 2026-08-11 讓總表整個停用的那個幽靈問題（`archive-ledger.py` 的理由）。
    live = {d.name.removesuffix(".mineru_raw") for d in parsed.glob("*.mineru_raw")}
    if not live:
        sys.exit(f"{parsed} 底下沒有解析結果，先確認路徑")

    jobs = []
    for jf in sorted((a.root / "intake" / "jobs").glob("*/job.json")):
        try:
            jobs.append(json.loads(jf.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"⚠ 讀不到 {jf}：{exc}", file=sys.stderr)

    by_doc = latest_job_per_document(jobs)
    sp = _load_scan_partial()
    hits_by_doc = Counter(h["doc"] for h in sp.scan(parsed)[0])

    grounding: dict[str, Mapping[str, int]] = {}
    if a.extract_json:
        payload = json.loads(a.extract_json.read_text(encoding="utf-8"))
        grounding = payload.get("per_doc") or {}
        print(f"接地資料：{a.extract_json}（{len(grounding)} 份）\n")

    planned: list[tuple[str, str, str, str, float | None]] = []
    skipped_no_job: list[str] = []
    for doc in sorted(live):
        job = by_doc.get(doc)
        if job is None:
            skipped_no_job.append(doc)
        else:
            plan = job.get("plan")
            if isinstance(plan, dict):
                for gate, state, note in intake.ledger_entries_from_plan(
                        accepted=job.get("decision") == "clean",
                        reasons=[str(r) for r in (job.get("reasons") or [])],
                        plan=plan,
                        # 被擋下**而且已經進知識庫** ⇒ 人看過放行了。
                        # 計畫那一刻不知道這件事，只有回填才知道。
                        admitted=job.get("status") == "indexed"):
                    planned.append((doc, gate, state, note, None))
        # `pp.equations` 當初就是用這個掃描驗的（見既有體檢表的備註）：
        # 「accent 類 token 站在 frac 首位或行內除法算子位置、且非 \partial」。
        n = hits_by_doc.get(doc, 0)
        planned.append((doc, "pp.equations", "pass" if n == 0 else "fail",
                        f"∂ 誤讀探針（上下同形＋行內斜線）命中 {n} 處", float(n)))
        if doc in grounding:
            state, note, ratio = grounding_entry(grounding[doc], a.threshold)
            planned.append((doc, "extract.grounding", state, note, ratio))

    tally = Counter((g, s) for _, g, s, _, _ in planned)
    print(f"現役文件 {len(live)} 份；會寫 {len(planned)} 格\n")
    for (gate, state), n in sorted(tally.items()):
        print(f"  {gate:<16} {state:<14} {n}")
    if skipped_no_job:
        print(f"\n⚠ {len(skipped_no_job)} 份找不到 job 紀錄（只填得起 pp.equations）：")
        for doc in skipped_no_job[:5]:
            print(f"    {doc}")
        if len(skipped_no_job) > 5:
            print(f"    …另外 {len(skipped_no_job) - 5} 份")

    if not a.apply:
        print("\n乾跑：什麼都沒寫。真的要寫請加 --apply")
        return 0

    written = failed = 0
    for doc, gate, state, note, value in planned:
        try:
            ledger.record(a.root, a.workspace, doc, gate, state, note=note,
                          value=value,
                          threshold=a.threshold if gate == "extract.grounding" else None)
            written += 1
        except ValueError as exc:
            print(f"⚠ {doc} / {gate}：{exc}", file=sys.stderr)
            failed += 1
    print(f"\n寫入 {written} 格" + (f"，失敗 {failed} 格" if failed else ""))
    print("接下來：python3 scripts/ledger.py summary")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
