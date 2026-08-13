#!/usr/bin/env python3
"""位置標記節點的確定性清除：`equation 22`、`table i`、`reference 1` 那種。

**為什麼要有這支**：規則 2a（不要把 Figure N／Equation N 抽成節點）寫在抽取提示詞
裡，2026-08-08、08-09 實測三次都沒守住。而受控比對量到，守不住的程度**隨後端而變**
（同樣的規則與解析成果，llama.cpp 與 vLLM 的人名機構是 35 對 49）。提示詞是請求不是
保證：換模型、換量化、換溫度都會改變遵守度。

所以這條改用確定性的方式補：抽完之後照樣式掃一遍，把確定是位置標記的節點刪掉。
**不管抽取跑在本機 llama.cpp 還是雲端 vLLM，這一步都一樣跑、一樣的結果。**

樣式在 `pp/graph_labels.py`，與 `graph-shape.py`（量測）、`compat-check` A-33（警報）
共用同一份 —— 三處各寫一份的話，「清完了」與「還有殘留」會同時成立而沒人發現。

用法：
    ./graph-clean.py plan                      # 唯讀，列出來
    ./graph-clean.py plan --out plan.json      # 存成檔案給 apply 用
    ./graph-clean.py apply --plan plan.json --yes

**apply 是唯一會改圖譜的地方，而 LightRAG 沒有 undo。** 動手前的檢查一條都不能省，
任何一條不成立就整批拒絕 —— 刪到一半停下來比不做更糟，因為你不知道停在哪裡。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mineru_common import add_workspace_arg, load_env  # noqa: E402
from pp.graph_labels import ALL_RE, CERTAIN_RE, classify  # noqa: E402
from pp.paths import DataPaths, configured_data_root  # noqa: E402
from pp.pg import psql, sql_literal  # noqa: E402
from pp.ragapi import Rag  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
GRAPH_NODES = "lightrag_graph_nodes"


def survey(env: dict[str, str], workspace: str) -> tuple[list[tuple[str, str]],
                                                         list[tuple[str, str]]]:
    """撈出圖譜裡所有位置標記節點，分成「確定可刪」與「待裁定」。

    回傳 (certain, suspect)，每項是 (節點名, 型別)。

    ⚠ **同一份樣式要在兩個引擎上跑**：Postgres 的 `~*` 撈候選、Python 的 `re`
    做分組。兩個引擎對同一個樣式理論上可能不一致，而不一致的那天不會有錯誤訊息
    —— 所以下面用 `ALL_RE` 撈、用 `classify()` 分，撈到卻分不出組的一律列為
    異常讓呼叫端拒絕，不默默跳過。
    """
    ws = sql_literal(workspace)
    rows = psql(env, f"""
        select id, coalesce(properties->>'entity_type', '?')
        from {GRAPH_NODES}
        where workspace={ws} and id ~* {sql_literal(ALL_RE)}
        order by 1;""")
    certain: list[tuple[str, str]] = []
    suspect: list[tuple[str, str]] = []
    unclassified: list[str] = []
    for r in rows:
        name, etype = r[0], (r[1] if len(r) > 1 else "?")
        bucket = classify(name)
        if bucket == "certain":
            certain.append((name, etype))
        elif bucket == "suspect":
            suspect.append((name, etype))
        else:
            unclassified.append(name)
    if unclassified:
        raise RuntimeError(
            f"SQL 撈到 {len(unclassified)} 個節點，Python 卻分不出組：{unclassified[:5]}。"
            "兩個引擎對同一份樣式的解讀不一致 —— 在查清楚之前不要刪任何東西")
    return certain, suspect


def _by_type(rows: list[tuple[str, str]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for _, t in rows:
        out[t] = out.get(t, 0) + 1
    return out


def _show(title: str, rows: list[tuple[str, str]], limit: int) -> None:
    print(f"\n{title}　{len(rows)} 個")
    if not rows:
        return
    dist = "、".join(f"{k} {v}" for k, v in sorted(_by_type(rows).items(), key=lambda kv: -kv[1]))
    print(f"  型別分佈：{dist}")
    for name, etype in rows[:limit]:
        print(f"    {name:<28} {etype}")
    if len(rows) > limit:
        # 收合時必須報出未列出的筆數（鐵則第 6 條）：「沒印出來」與「沒有」
        # 在畫面上長得一樣。
        print(f"    … 另 {len(rows) - limit} 項未列出（--limit 調整，或看 --out 的 JSON）")


def cmd_plan(a: argparse.Namespace, env: dict[str, str]) -> int:
    certain, suspect = survey(env, a.workspace)
    print(f"workspace={a.workspace!r}　圖節點表 {GRAPH_NODES}")
    _show("確定可刪（apply 會刪這些）", certain, a.limit)
    _show("待裁定（PO 2026-08-09 裁決先不動）", suspect, a.limit)

    print("\n樣式來源：pp/graph_labels.py")
    print(f"  確定可刪　{CERTAIN_RE}")
    if not certain:
        print("\n沒有要刪的東西。")

    if a.out:
        out = Path(a.out)
        payload = {
            "workspace": a.workspace,
            "certain": [{"name": n, "entity_type": t} for n, t in certain],
            "suspect": [{"name": n, "entity_type": t} for n, t in suspect],
            "certain_re": CERTAIN_RE,
        }
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n計畫寫入 {out}")
    return 0


def backup(rag: Rag, names: list[str], dest_dir: Path) -> Path:
    """把要刪的節點與它們的邊完整存下來 —— 刪除前唯一的回頭路。

    邊的 source/target 在 API 裡是數值 id，換一次索引就變了，所以一律翻成 label
    再存 —— 存 id 的備份在重建時等於沒有。需要時用 `/graph/entity/create` 與
    `/graph/relation/create` 重建。

    ⚠ 檔名帶時間戳而且**不覆蓋既有的**。實測踩過（entity-merge，2026-08-08）：
    動完之後為了驗證又跑了一次 dump，直接蓋掉動作**前**那份，被刪掉的節點連同
    它們的邊就沒有記錄了。備份被自己的工具蓋掉，是最沒必要的損失。
    """
    out: dict[str, object] = {"entities": {}, "relations": []}
    entities: dict[str, object] = {}
    relations: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    truncated: list[str] = []

    for i, n in enumerate(names, 1):
        sub = rag.subgraph(n)
        nodes = sub.get("nodes") or []
        if not isinstance(nodes, list):
            raise RuntimeError(f"{n!r} 的 nodes 不是陣列")
        if len(nodes) >= rag.SUBGRAPH_CAP:
            truncated.append(n)
        by_id = {str(x.get("id")): x["labels"][0] for x in nodes if x.get("labels")}
        me = next((x for x in nodes if x.get("labels") and x["labels"][0] == n), None)
        if me is None:
            raise RuntimeError(f"{n!r} 在圖譜裡找不到 —— 計畫與現況已經對不上")
        entities[n] = me.get("properties") or {}
        mine = str(me.get("id"))
        edges = sub.get("edges") or []
        for e in edges if isinstance(edges, list) else []:
            sid, tid = str(e.get("source")), str(e.get("target"))
            if mine not in (sid, tid):
                continue
            src_l, tgt_l = by_id.get(sid), by_id.get(tid)
            if not src_l or not tgt_l or (src_l, tgt_l) in seen:
                continue
            seen.add((src_l, tgt_l))
            relations.append({"source": src_l, "target": tgt_l,
                              "properties": e.get("properties") or {}})
        print(f"  [{i}/{len(names)}] {n:<28} 邊 {len(relations)} 累計")

    if truncated:
        raise RuntimeError(
            f"這些節點的鄰居數打到 {rag.SUBGRAPH_CAP} 上限，備份不完整：{truncated}。"
            "不要拿這份備份當回頭路")

    out["entities"] = entities
    out["relations"] = relations
    dest_dir.mkdir(parents=True, exist_ok=True)
    dst = dest_dir / f"graph-clean-backup.{time.strftime('%Y%m%d-%H%M%S')}.json"
    if dst.exists():
        raise RuntimeError(f"{dst} 已存在，拒絕覆蓋")
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n備份 {len(entities)} 個節點、{len(relations)} 條邊 → {dst}")
    return dst


def cmd_apply(a: argparse.Namespace, env: dict[str, str]) -> int:
    """依計畫刪除。動手前的五道檢查，任何一條不成立就整批拒絕。

      1. 計畫的 workspace 與 --workspace 相符（拿 A 的計畫刪 B 是災難）
      2. 現況與計畫一致 —— 產計畫之後圖譜若動過，重產
      3. 每個要刪的名字都仍然通過 `classify() == "certain"`
      4. pipeline 閒置 —— 抽取中改圖譜會跟 LightRAG 搶同一批節點
      5. 備份寫成功
    """
    plan = json.loads(Path(a.plan).read_text(encoding="utf-8"))
    if plan.get("workspace") != a.workspace:
        print(f"✗ 計畫是給 workspace={plan.get('workspace')!r} 的，"
              f"現在指定 {a.workspace!r}", file=sys.stderr)
        return 2

    planned = [e["name"] for e in plan.get("certain", [])]
    if not planned:
        print("計畫裡沒有要刪的節點。")
        return 0

    certain, _ = survey(env, a.workspace)
    current = [n for n, _ in certain]
    if current != planned:
        added = sorted(set(current) - set(planned))
        gone = sorted(set(planned) - set(current))
        print("✗ 現況與計畫不一致 —— 產計畫之後圖譜動過了。重跑 plan。",
              file=sys.stderr)
        if added:
            print(f"  計畫裡沒有、現在有：{added[:10]}", file=sys.stderr)
        if gone:
            print(f"  計畫裡有、現在沒有：{gone[:10]}", file=sys.stderr)
        return 2

    bad = [n for n in planned if classify(n) != "certain"]
    if bad:
        print(f"✗ 這些名字現在不再屬於「確定可刪」：{bad[:10]}　"
              f"（樣式改過？）整批拒絕。", file=sys.stderr)
        return 2

    rag = Rag(env)
    if not rag.pipeline_idle():
        print("✗ LightRAG 的 pipeline 正在跑 —— 抽取中改圖譜會跟它搶同一批節點。"
              "等它閒下來再來。", file=sys.stderr)
        return 2

    print(f"要刪 {len(planned)} 個節點（workspace={a.workspace!r}）。先備份：")
    # **備份要放 `records/`，不要放 `work/crops/`。**
    #
    # 2026-08-13 踩到：第一次實跑（刪 376 個）的備份寫進了 `crops_dir`，而
    # `verdicts/README.md` 把 `work/crops/<doc>/crops` 列為「可再生、刻意不進版控」。
    # 也就是說那份**唯一能還原被刪節點的東西**，被放在一個「隨時可以清掉」的目錄裡。
    # 被刪掉的節點是 LLM 抽出來的，重跑要花錢，備份沒了就只剩重抽這條路。
    dest = DataPaths(configured_data_root()).records_dir / "graph-clean"
    try:
        backup(rag, planned, dest)
    except RuntimeError as e:
        print(f"✗ 備份失敗，一個都不刪：{e}", file=sys.stderr)
        return 2

    if not a.yes:
        print("\n備份完成。真的要刪請加 --yes。")
        return 0

    deleted, failed = [], []
    for i, n in enumerate(planned, 1):
        try:
            rag.delete_entity(n)
            deleted.append(n)
            print(f"  [{i}/{len(planned)}] 刪除 {n}")
        except Exception as e:                                   # noqa: BLE001
            failed.append((n, f"{type(e).__name__}: {e}"))
            print(f"  [{i}/{len(planned)}] ✗ {n} —— {type(e).__name__}: {e}",
                  file=sys.stderr)
            break

    after, _ = survey(env, a.workspace)
    print(f"\n刪掉 {len(deleted)} 個，圖譜裡的「確定可刪」剩 {len(after)} 個")
    if failed:
        print(f"✗ 在 {failed[0][0]!r} 停下來：{failed[0][1]}", file=sys.stderr)
        print(f"  已刪的 {len(deleted)} 個在備份檔裡。剩下的重跑 plan 再 apply。",
              file=sys.stderr)
        return 2
    if after:
        print(f"⚠ 還剩 {len(after)} 個 —— 刪除回報成功但節點還在，去查 LightRAG 的日誌",
              file=sys.stderr)
        return 2
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    env = load_env(REPO)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("plan", help="唯讀，列出位置標記節點")
    add_workspace_arg(p1, env)
    p1.add_argument("--out", help="把計畫寫成 JSON（apply 要用）")
    p1.add_argument("--limit", type=int, default=20, help="每組列出幾項（預設 20）")
    p1.set_defaults(fn=cmd_plan)

    p2 = sub.add_parser("apply", help="依計畫刪除（會改圖譜）")
    add_workspace_arg(p2, env)
    p2.add_argument("--plan", required=True, help="plan --out 產生的 JSON")
    p2.add_argument("--yes", action="store_true", help="確認刪除；不加只做到備份")
    p2.set_defaults(fn=cmd_apply)

    a = ap.parse_args()
    try:
        return int(a.fn(a, env))
    except RuntimeError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
