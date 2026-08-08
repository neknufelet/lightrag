#!/usr/bin/env python3
"""量圖譜的「形狀」：抽取規則有沒有奏效，靠這些數字比對，不靠印象。

**為什麼需要這支**：2026-08-08 改抽取規則之前，如果沒有先量下來，重抽之後就
沒有基準可比——「泛用標籤歸零」「人名機構從 47 降下來」這兩個驗收判準會變成
無從驗證。而重抽是不可逆的，事後補不了「之前」。

量四件事，每件都對應一條規則：

  總節點與邊數        規模有沒有崩掉（規則太嚴會讓圖譜變空）
  泛用標籤節點        規則 2a（Figure N／Equation N 那類）→ 目標 0
  疑似人名／機構      規則 1（參考文獻的作者）→ 目標大幅下降
  標題大小寫變體      規則 3（Region II vs Region Ii）→ 目標 0

用法：
    ./graph-shape.py                # 印出來
    ./graph-shape.py --json         # 存成基準
    ./graph-shape.py --compare 檔案  # 與基準比對
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mineru_common import add_workspace_arg, load_env, postgres_container  # noqa: E402

REPO = Path(__file__).resolve().parent.parent

# 規則 2a 要消滅的那些：常見名詞 ＋ 編號／字母／羅馬數字。
# 字首清單是 2026-08-08 從圖譜**實際撈出來的**，不是憑印象列的。
LABEL_PREFIXES = ("fig", "figure", "table", "tab", "eq", "equation", "formula",
                  "section", "sec", "appendix", "chapter", "scheme", "panel",
                  "case", "sample", "step", "model", "type", "region", "zone",
                  "mode", "phase", "part", "stage", "item", "note", "example",
                  "reference", "ref", "configuration", "config")
LABEL_RE = (r"^(" + "|".join(LABEL_PREFIXES) + r")[\s._\-#]*[0-9ivxIVX]+[a-z)]?\s*$")

# 規則 1 要消滅的：型別是 person／organization 的節點。
# 用型別而不是猜名字 —— 名字看起來像人名的判斷會誤傷「Helmholtz resonator」。
PERSON_TYPES = ("person", "organization")


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def psql(env: dict[str, str], sql: str) -> list[list[str]]:
    p = subprocess.run(
        ["docker", "exec", postgres_container(env), "psql", "-U",
         env.get("POSTGRES_USER", "deeptutor"), "-d",
         env.get("POSTGRES_DATABASE", "lightrag"), "-tAF|", "-c", sql],
        capture_output=True, text=True, timeout=60, check=False)
    if p.returncode != 0:
        raise RuntimeError(f"psql 失敗：{p.stderr.strip()[:300]}")
    return [ln.split("|") for ln in p.stdout.strip().splitlines() if ln.strip()]


def measure(env: dict[str, str], workspace: str, table: str) -> dict:
    ws = _sql_literal(workspace)
    nodes = int(psql(env, f"select count(*) from {table} where workspace={ws};")[0][0])

    labels = psql(env, f"""
        select entity_name from {table}
        where workspace={ws} and entity_name ~* {_sql_literal(LABEL_RE)}
        order by 1;""")
    label_names = [r[0] for r in labels]

    # 型別存在 content 的 JSON 裡；用 ILIKE 找 "type": "person" 這種樣式
    people = 0
    for t in PERSON_TYPES:
        rows = psql(env, f"""
            select count(*) from {table}
            where workspace={ws} and content ilike {_sql_literal('%"type": "' + t + '"%')};""")
        people += int(rows[0][0])

    # 只差在大小寫的成對節點（規則 3）
    dupes = psql(env, f"""
        select lower(entity_name), count(*), string_agg(entity_name, ' | ' order by entity_name)
        from {table} where workspace={ws}
        group by 1 having count(*) > 1 order by 2 desc;""")

    return {
        "table": table,
        "nodes": nodes,
        "label_nodes": len(label_names),
        "label_examples": label_names[:12],
        "person_org_nodes": people,
        "case_variant_groups": len(dupes),
        "case_variant_examples": [r[2] for r in dupes[:8]],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    env = load_env(REPO)
    add_workspace_arg(ap, env)
    ap.add_argument("--json", action="store_true", help="輸出 JSON（存基準用）")
    ap.add_argument("--compare", help="與這份基準比對")
    a = ap.parse_args()

    tables = [r[0] for r in psql(env, """
        select tablename from pg_tables
        where tablename like 'lightrag_vdb_entity%' order by 1;""")]
    if not tables:
        print("找不到實體向量表", file=sys.stderr)
        return 2
    # 現行的那張：表名帶模型與維度，用 .env 的設定挑
    model = env.get("EMBEDDING_MODEL", "")
    dim = env.get("EMBEDDING_DIM", "")
    suffix = re.sub(r"[^0-9a-z]+", "_", f"{model}_{dim}d".lower())
    active = next((t for t in tables if t.endswith(suffix)), tables[0])

    result = measure(env, a.workspace, active)

    if a.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"實體表　{result['table']}")
    print(f"  節點總數　　　　　{result['nodes']:>6,}")
    print(f"  泛用標籤節點　　　{result['label_nodes']:>6}"
          f"　（規則 2a 目標：0）")
    if result["label_examples"]:
        print(f"      例：{', '.join(result['label_examples'][:8])}")
    print(f"  person／organization {result['person_org_nodes']:>4}"
          f"　（規則 1 目標：大幅下降）")
    print(f"  只差大小寫的組　　{result['case_variant_groups']:>6}"
          f"　（規則 3 目標：0）")
    for ex in result["case_variant_examples"][:5]:
        print(f"      {ex}")

    if a.compare:
        old = json.loads(Path(a.compare).read_text(encoding="utf-8"))
        print("\n── 與基準比對 ──")
        for key, label in (("nodes", "節點總數"), ("label_nodes", "泛用標籤"),
                           ("person_org_nodes", "person／org"),
                           ("case_variant_groups", "大小寫變體組")):
            before, after = old.get(key, 0), result.get(key, 0)
            delta = after - before
            print(f"  {label:<14} {before:>6,} → {after:>6,}"
                  f"　{delta:+,}"
                  f"　{'' if before == 0 else f'({delta / before:+.0%})'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
