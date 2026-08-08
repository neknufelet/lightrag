#!/usr/bin/env python3
"""量測符號型實體在真實檢索結果中佔用的格位；全程唯讀。"""
from __future__ import annotations

import argparse
import json
import logging
import socket
import sys
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Mapping
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mineru_common import add_workspace_arg, load_env  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
VERDICTS = ("restated", "correct", "wrong")
Z_95 = 1.959963984540054
LOG = logging.getLogger(__name__)


class SymbolHitsError(Exception):
    """可預期的輸入或輸出錯誤，交由 CLI 轉成簡短訊息。"""


class QueryFailure(Exception):
    """單筆查詢失敗；category 保留給不完整母體的報告。"""

    def __init__(self, category: str, detail: str) -> None:
        super().__init__(detail)
        self.category = category


class _ReadOnlyRag:
    """刻意不 import entity-merge.py 的唯讀最小 client。

    entity-merge.py 有破壞性的 apply 路徑，不應被本工具牽動；但 seeds 與
    /query/data 的參數必須逐項維持一致，才能與它的格位判準互相比較。
    """

    def __init__(self, env: Mapping[str, str]) -> None:
        self.host = f"http://{env.get('BIND_ADDR', '100.87.88.7')}:{env.get('HOST_PORT', '9621')}"
        self.key = env.get("LIGHTRAG_API_KEY", "")

    def _request(self, path: str, method: str = "GET", body: dict[str, object] | None = None) -> object:
        request = urllib.request.Request(
            self.host + path, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"X-API-Key": self.key, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=240) as response:
                return json.loads(response.read() or "{}")
        except urllib.error.HTTPError as exc:
            raise QueryFailure("http", f"HTTP {exc.code}") from exc
        except TimeoutError as exc:
            raise QueryFailure("timeout", str(exc) or type(exc).__name__) from exc
        except urllib.error.URLError as exc:
            category = "timeout" if isinstance(exc.reason, socket.timeout) else "network"
            raise QueryFailure(category, str(exc.reason)) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise QueryFailure("parse", str(exc)) from exc

    def labels(self) -> list[str]:
        return _string_list(self._request("/graph/label/list"), "label list")

    def popular(self, count: int) -> list[str]:
        return _string_list(self._request(f"/graph/label/popular?limit={count}"), "popular labels")

    def entities_for(self, query: str, top_k: int) -> list[str]:
        # 與 entity-merge.py Rag.entities_for 刻意逐項相同；chunk_top_k=1 不是 0。
        response = self._request("/query/data", "POST", {
            "query": query, "mode": "mix", "only_need_context": True,
            "top_k": top_k, "chunk_top_k": 1,
        })
        if not isinstance(response, dict):
            raise QueryFailure("parse", "query response is not an object")
        data = response.get("data") or {}
        if not isinstance(data, dict) or not isinstance(data.get("entities") or [], list):
            raise QueryFailure("parse", "query response lacks data.entities list")
        return [entry["entity_name"] for entry in data.get("entities") or []
                if isinstance(entry, dict) and isinstance(entry.get("entity_name"), str)
                and entry["entity_name"]]


def _string_list(value: object, source: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise SymbolHitsError(f"{source} 必須是字串陣列")
    return value


def _load_names(path: Path, key: str, required: tuple[str, ...]) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8") as handle:
            root: object = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise SymbolHitsError(f"無法讀取 {path}：{exc}") from exc
    if not isinstance(root, dict) or not isinstance(root.get(key), list):
        raise SymbolHitsError(f"{path} 缺少 {key} 陣列")
    rows: list[dict[str, str]] = []
    for position, item in enumerate(root[key], 1):
        if not isinstance(item, dict) or any(not isinstance(item.get(field), str) or not item[field]
                                             for field in required):
            raise SymbolHitsError(f"{path} 的 {key}[{position}] 缺少必要字串欄位")
        rows.append({field: item[field] for field in required})
    names = [row["name"] for row in rows]
    if len(names) != len(set(names)):
        raise SymbolHitsError(f"{path} 的 {key} 有重複 name，拒絕靜默改變母體")
    return rows


def _wilson(hits: int, total: int) -> list[float] | None:
    if total == 0:
        return None
    proportion = hits / total
    denominator = 1 + Z_95 ** 2 / total
    centre = (proportion + Z_95 ** 2 / (2 * total)) / denominator
    margin = Z_95 * (proportion * (1 - proportion) / total + Z_95 ** 2 / (4 * total ** 2)) ** .5 / denominator
    return [centre - margin, centre + margin]


def _near_matches(names: list[str], labels: set[str]) -> list[dict[str, object]]:
    folded: dict[str, list[str]] = {}
    for label in labels:
        folded.setdefault("".join(label.split()).casefold(), []).append(label)
    return [{"name": name, "labels": sorted(folded.get("".join(name.split()).casefold(), []))}
            for name in names if name not in labels and folded.get("".join(name.split()).casefold())]


def _health(answer_names: list[str], symbolic_names: list[str], labels: list[str]) -> dict[str, object]:
    label_set = set(labels)
    answer_missing = [name for name in answer_names if name not in label_set]
    symbolic_missing = [name for name in symbolic_names if name not in label_set]
    return {"exact_matching": True, "label_count": len(labels),
            "answer_key": {"n": len(answer_names), "not_in_labels": answer_missing,
                           "near_matches": _near_matches(answer_names, label_set)},
            "symbolic_bucket": {"n": len(symbolic_names), "not_in_labels": symbolic_missing,
                                "near_matches": _near_matches(symbolic_names, label_set)},
            "answer_key_not_in_symbolic": sorted(set(answer_names) - set(symbolic_names))}


def _group_rows(answer: list[dict[str, str]], slots: Counter[str], label_set: set[str]) -> dict[str, dict[str, object]]:
    groups: dict[str, dict[str, object]] = {}
    for verdict in VERDICTS:
        names = [row["name"] for row in answer if row["verdict"] == verdict]
        eligible = [name for name in names if name in label_set]
        hit_entities = sum(slots[name] > 0 for name in eligible)
        groups[verdict] = {"n": len(names), "label_matched_n": len(eligible),
                           "label_unmatched_names": [name for name in names if name not in label_set],
                           "hit_slots": sum(slots[name] for name in eligible), "hit_entities": hit_entities,
                           "hit_entity_wilson_95": _wilson(hit_entities, len(eligible)),
                           "average_slots_per_label_matched_entity": sum(slots[name] for name in eligible) / max(len(eligible), 1)}
    return groups


def _measure(rag: _ReadOnlyRag, answer: list[dict[str, str]], symbolic: list[dict[str, str]],
             queries: int, top_k: int) -> dict[str, object]:
    labels = rag.labels()
    seeds = rag.popular(queries)
    symbolic_names = [row["name"] for row in symbolic]
    symbolic_set, label_set = set(symbolic_names), set(labels)
    slots: Counter[str] = Counter()
    entity_slots = symbolic_slots = 0
    failures: list[dict[str, object]] = []
    for index, query in enumerate(seeds, 1):
        try:
            entities = rag.entities_for(query, top_k)
        except QueryFailure as exc:
            LOG.warning("[%d/%d] %s 查詢失敗 (%s): %s", index, len(seeds), query[:40], exc.category, exc)
            failures.append({"index": index, "query": query, "category": exc.category, "detail": str(exc)})
            continue
        slots.update(entities)
        entity_slots += len(entities)
        symbolic_slots += sum(name in symbolic_set for name in entities)
    health = _health([row["name"] for row in answer], symbolic_names, labels)
    groups = _group_rows(answer, slots, label_set)
    hit_symbolic = sum(slots[name] > 0 for name in symbolic_names if name in label_set)
    coverage_n = len(symbolic_names) - len(health["symbolic_bucket"]["not_in_labels"])
    return {"queries": seeds, "entity_slots": entity_slots,
            "query_execution": {"requested": len(seeds), "successful": len(seeds) - len(failures),
                                "complete": not failures, "failure_counts": dict(Counter(f["category"] for f in failures)),
                                "failures": failures}, "view_1_answer_key": {"groups": groups},
            "view_2_symbolic_bucket": {"population": len(symbolic_names), "label_matched_n": coverage_n,
                "symbolic_slots": symbolic_slots, "symbolic_slot_share": symbolic_slots / max(entity_slots, 1),
                "hit_entities": hit_symbolic, "hit_entity_wilson_95": _wilson(hit_symbolic, coverage_n),
                "never_hit_entities": coverage_n - hit_symbolic,
                "label_unmatched_names": health["symbolic_bucket"]["not_in_labels"]}, "health_checks": health}


def _percent(value: float) -> str:
    return f"{value:.1%}"


def _interval(value: list[float] | None) -> str:
    return "N/A" if value is None else f"{_percent(value[0])}–{_percent(value[1])}"


def _print_report(report: dict[str, object]) -> None:
    groups = report["view_1_answer_key"]["groups"]
    print("答案卷受控對照（命中率為有被命中的實體比例；Wilson 95% CI）")
    print(f"{'verdict':<10}{'n':>5} {'命中總格數':>10} {'有被命中的實體數':>31} {'每實體平均格數':>16}")
    for verdict in VERDICTS:
        row = groups[verdict]
        eligible = row["label_matched_n"]
        print(f"{verdict:<10}{row['n']:>5} {row['hit_slots']:>10} "
              f"{row['hit_entities']}/{eligible} ({_percent(row['hit_entities']/max(eligible, 1))}; {_interval(row['hit_entity_wilson_95'])}) "
              f"{row['average_slots_per_label_matched_entity']:>16.2f}")
    bucket = report["view_2_symbolic_bucket"]
    print("\n全符號桶佔格位")
    print(f"總實體格位 {report['entity_slots']}；符號桶 {bucket['symbolic_slots']} ({_percent(bucket['symbolic_slot_share'])})")
    print(f"符號桶有被命中 {bucket['hit_entities']}/{bucket['label_matched_n']} "
          f"({_percent(bucket['hit_entities']/max(bucket['label_matched_n'], 1))}; {_interval(bucket['hit_entity_wilson_95'])})；"
          f"從未被命中 {bucket['never_hit_entities']}")
    health = report["health_checks"]
    print("\n健全性檢查（名稱一律精確比對）")
    for source in ("answer_key", "symbolic_bucket"):
        check = health[source]
        print(f"{source}: 對不上 {len(check['not_in_labels'])}；大小寫/空白近似名 {len(check['near_matches'])}")
        for name in check["not_in_labels"]:
            print(f"  對不上：{name}")
    execution = report["query_execution"]
    if not execution["complete"]:
        print(f"⚠ 本次統計母體不完整：{len(execution['failures'])}/{execution['requested']} 個查詢失敗 {execution['failure_counts']}")
    restated, correct = groups["restated"], groups["correct"]
    print(f"\n結論：restated {restated['hit_slots']} 格／{restated['hit_entities']} 個，"
          f"correct {correct['hit_slots']} 格／{correct['hit_entities']} 個；以同一批熱門標籤查詢可直接比較。")


def _positive(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("必須是正整數")
    return parsed


def _build_parser(env: Mapping[str, str]) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="量測符號型實體實際被檢索命中的格位（唯讀）")
    parser.add_argument("--symbolic", type=Path, required=True, help="extract-check.py --dump-symbolic 的 JSON")
    parser.add_argument("--answer-key", type=Path, default=REPO / "tests" / "symbol1-answer-key.json")
    add_workspace_arg(parser, dict(env))
    parser.add_argument("--queries", type=_positive, default=30)
    parser.add_argument("--top-k", type=_positive, default=40)
    parser.add_argument("--out", type=Path, help="JSON 輸出檔")
    parser.add_argument("--force", action="store_true", help="允許覆寫既有 --out")
    return parser


def _write_report(path: Path, report: dict[str, object]) -> None:
    try:
        with path.open("w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except OSError as exc:
        raise SymbolHitsError(f"無法寫入 {path}：{exc}") from exc


def main(argv: list[str] | None = None) -> int:
    """解析 CLI、執行唯讀量測，並選擇性寫出不覆蓋的 JSON 報告。"""
    env = load_env(REPO)
    parser = _build_parser(env)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        if args.out and args.out.exists() and not args.force:
            raise SymbolHitsError(f"輸出檔已存在：{args.out}（若要覆寫請加 --force）")
        symbolic = _load_names(args.symbolic, "entities", ("name",))
        answer = _load_names(args.answer_key, "items", ("name", "verdict"))
        if any(row["verdict"] not in VERDICTS for row in answer):
            raise SymbolHitsError(f"答案卷 verdict 必須是 {', '.join(VERDICTS)}")
        report = _measure(_ReadOnlyRag(env), answer, symbolic, args.queries, args.top_k)
        report.update({"generated_from": "symbol-hits.py", "workspace": args.workspace,
                       "inputs": {"symbolic": str(args.symbolic), "answer_key": str(args.answer_key)},
                       "config": {"requested_queries": args.queries, "top_k": args.top_k}})
        _print_report(report)
        if args.out:
            _write_report(args.out, report)
            print(f"JSON 報告：{args.out}")
    except (SymbolHitsError, QueryFailure) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
