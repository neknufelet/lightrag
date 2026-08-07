#!/usr/bin/env python3
"""命名規則探針：同一批真實抽取請求，加/不加命名規則各跑一次，比對抽出來的實體名。

不寫任何 DB、不動容器。只打 llama.cpp 的 /v1/chat/completions。
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

S = pathlib.Path(__file__).resolve().parent
HOST = "http://100.71.26.77:8080"
KEY = (pathlib.Path.home()
       / "ghq/github.com/neknufelet/lightrag-v1/deploy/llama-qwen36-moe/.env"
       ).read_text().split("LLAMA_API_KEY=")[1].strip()

# 要塞進 ---Entity Types--- 那一段的命名規則。
# 官方開關 ENTITY_TYPE_PROMPT_FILE 會**整段取代**，所以正式使用時這段前面
# 必須連原本的型別清單一起帶——探針這裡是「附加」，等價於取代後保留原清單。
NAMING_RULE = """
---Entity Naming (takes precedence over the type list above)---
An entity name must be the NAME OF THE CONCEPT, never a transliteration of notation.
Do NOT produce names that merely spell out symbols (bad: "S Sub 0 N Squared",
"Nn,v, (II)", "Z0 V11x", "Coefficient Dn").

If the concept name for a symbol appears anywhere nearby -- in the same table cell,
in the row or column header, in the sentence that defines it, or in the surrounding
text -- USE THAT NAME as the entity name.
  Example: a row header reads "Mode norms in (II)" and the cell holds N_{n,v}^{(II)};
  the entity name is "Mode Norm", NOT "Nn,v, (II)".

Only fall back to naming an entity after the symbol itself when no concept name is
present anywhere in the context; in that case state in the description what the
symbol denotes.
"""

def names(text: str) -> list[str]:
    """從抽取輸出裡取出實體名。

    輸出是 JSON（LightRAG 1.5.5 走 entity_extraction_json_* 那組 prompt），
    不是 `<|>` 分隔格式 —— 第一版探針就是在這裡判錯，兩組都解析出 0 個，
    看起來像「規則沒效」其實是解析器對不上。**控制組解析出 0 個就是壞了。**
    """
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.S)
    try:
        d = json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", s, re.S)
        if not m:
            return []
        try:
            d = json.loads(m.group())
        except json.JSONDecodeError:
            return []
    ents = d.get("entities") if isinstance(d, dict) else None
    if not isinstance(ents, list):
        return []
    return [str(e.get("name", "")).strip() for e in ents if isinstance(e, dict) and e.get("name")]


def ask(prompt: str) -> str:
    body = json.dumps({
        "model": "qwen3.6-35b-a3b",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0, "seed": 20260803, "max_tokens": 4096,
        "cache_prompt": False, "stream": False,
    }).encode()
    req = urllib.request.Request(f"{HOST}/v1/chat/completions", data=body,
                                 headers={"Authorization": f"Bearer {KEY}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"]


def treated(prompt: str) -> str:
    """把命名規則插進每一處 ---Entity Types--- 區段的結尾。"""
    parts = prompt.split("---Entity Types---")
    out = [parts[0]]
    for seg in parts[1:]:
        # 段落結束於下一個 --- 標題
        m = re.search(r"\n---[A-Z]", seg)
        cut = m.start() if m else len(seg)
        out.append("---Entity Types---" + seg[:cut] + NAMING_RULE + seg[cut:])
    return "".join(out)


def main() -> int:
    rows = json.loads((S / "probe-prompts.json").read_text())
    first: dict[str, dict] = {}
    for r in rows:
        if r["original_prompt"].lstrip().startswith("---Task---\nBased on the last extraction"):
            continue
        first.setdefault(r["chunk_id"], r)
    targets = json.loads(
        (pathlib.Path.home() / "ghq/github.com/neknufelet/lightrag-v1"
         / "tests/symbol1-answer-key.json").read_text())["items"]
    want: dict[str, list[str]] = {}
    for t_ in targets:
        if t_["verdict"] == "restated":
            want.setdefault(t_["chunk_ids"][0], []).append(t_["name"])

    jobs = []
    for cid, row in first.items():
        jobs.append((cid, "control", row["original_prompt"]))
        jobs.append((cid, "treat", treated(row["original_prompt"])))
    print(f"送出 {len(jobs)} 個請求（{len(first)} 個 chunk × 2）…\n", flush=True)
    with ThreadPoolExecutor(max_workers=4) as ex:
        outs = list(ex.map(lambda j: ask(j[2]), jobs))

    raw: dict[str, dict[str, str]] = {}
    res: dict[str, dict[str, list[str]]] = {}
    for (cid, arm, _), o in zip(jobs, outs):
        raw.setdefault(cid, {})[arm] = o
        res.setdefault(cid, {})[arm] = names(o)
    # **原始輸出先落地**：解析器錯過一次了，不要再為了解析 bug 重打一次模型。
    (S / "naming-probe-raw.json").write_text(
        json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")

    report = []
    for cid, arms in res.items():
        c, t = arms.get("control", []), arms.get("treat", [])
        bads = want.get(cid, [])
        in_c = [b for b in bads if b in c]
        in_t = [b for b in bads if b in t]
        print(f"── {cid[-14:]}　當初的爛名字：{bads}")
        print(f"   原樣抽出 {len(c):>2} 個｜加規則抽出 {len(t):>2} 個"
              + ("　⚠ 控制組 0 個＝解析或請求壞了" if not c else ""))
        print(f"   原樣仍含：{in_c or '（無）'}")
        print(f"   加規則仍含：{in_t or '（無）'}")
        only_t = [n for n in t if n not in c][:6]
        gone = [n for n in c if n not in t][:6]
        if gone:   print(f"   加規則後消失的名字：{gone}")
        if only_t: print(f"   加規則後新出現的名字：{only_t}")
        print()
        report.append({"chunk": cid, "target_bad_names": bads,
                       "control": c, "treat": t,
                       "bad_in_control": in_c, "bad_in_treat": in_t})

    tot = sum(len(r["target_bad_names"]) for r in report)
    n_bad_c = sum(len(r["bad_in_control"]) for r in report)
    n_bad_t = sum(len(r["bad_in_treat"]) for r in report)
    n_ent_c = sum(len(r["control"]) for r in report)
    n_ent_t = sum(len(r["treat"]) for r in report)
    print("=" * 62)
    print(f"抽出的實體總數：原樣 {n_ent_c}　→　加規則 {n_ent_t}")
    print(f"當初那些爛名字仍出現：原樣 {n_bad_c}/{tot}　→　加規則 {n_bad_t}/{tot}")
    if n_ent_c == 0:
        print("⚠ 控制組一個都沒抽到 —— 這不是結果，是探針壞了，別採信")
    (S / "naming-probe-result.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"明細：{S / 'naming-probe-result.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
