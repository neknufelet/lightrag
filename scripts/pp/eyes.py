"""兩雙眼睛：兩個不同家族的視覺模型各自獨立轉錄同一張裁圖。

為什麼要兩個而不是挑一個好的：實測 C Equivalent Networks 的 10 張空表格，
qwen 對 1 次、luna 對 2 次，而且錯法不同 ——
    luna 看錯字元（S_n 讀成 S_h）
    qwen 切錯結構（該分的併、該併的分，兩次都錯在列的切分）
只用其中一個，另一個抓得到的那類錯誤就會靜靜進索引。互相取代不了。

結果一律寫到 DATA_ROOT 底下（restic 會備份），而且**先看快取**：轉錄是這條
流程唯一要付錢的部分，重跑報表不該重新付費。快取以裁圖的 sha256 為鍵 ——
bbox 或 padding 改了會自然失效，改了 prompt 也要手動清。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pp import crosscheck, pdfcrop, vlm  # noqa: E402
from pp.docctx import DocContext  # noqa: E402
from pp.rules import empty_table  # noqa: E402


@dataclass
class Eye:
    name: str
    host: str
    api_key: str
    model: str
    reasoning: bool = False          # gpt-5 系列要 max_completion_tokens
    max_out: int = 3072


def eyes_from_env(env: dict) -> tuple[Eye, Eye]:
    """A = 轉錄者，B = 交叉驗證者。兩者必須不同家族，否則錯誤相關、驗證失效。"""
    a = Eye("qwen",
            env.get("LLM_BINDING_HOST", "http://localhost:8080/v1"),
            env.get("LLM_BINDING_API_KEY", ""),
            env.get("LLM_MODEL", "qwen3.6-35b-a3b"))
    b = Eye("luna",
            env.get("PP_EYE_B_HOST", "https://api.openai.com/v1"),
            # 預設沿用 embedding 那把 OpenAI 金鑰，不另外散一份出去
            env.get("PP_EYE_B_API_KEY") or env.get("EMBEDDING_BINDING_API_KEY", ""),
            env.get("PP_EYE_B_MODEL", "gpt-5.6-luna"),
            reasoning=env.get("PP_EYE_B_REASONING", "true").lower() == "true",
            max_out=int(env.get("PP_EYE_B_MAX_OUT", "6000")))
    if a.model == b.model:
        raise RuntimeError("兩雙眼睛不能是同一個模型 —— 錯誤會相關，交叉驗證失去意義")
    return a, b


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def _cached(cache: Path, eye: Eye, png_sha: str) -> str | None:
    f = cache / f"{png_sha}.{eye.name}.{eye.model.replace('/', '_')}.json"
    if f.is_file():
        return json.loads(f.read_text())["html"]
    return None


def _store(cache: Path, eye: Eye, png_sha: str, html: str, raw: str, fin: str) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    f = cache / f"{png_sha}.{eye.name}.{eye.model.replace('/', '_')}.json"
    f.write_text(json.dumps({"model": eye.model, "html": html, "raw": raw,
                             "finish_reason": fin}, ensure_ascii=False, indent=1))


def look(eye: Eye, png: Path, cache: Path) -> tuple[str, str | None]:
    """回傳 (html, 錯誤訊息)。失敗不拋例外 —— 一張表看不了不該中斷整份文件。"""
    sha = _sha(png)
    hit = _cached(cache, eye, sha)
    if hit is not None:
        return hit, None
    try:
        raw, fin = vlm.transcribe(png, eye.host, eye.api_key, eye.model,
                                  reasoning=eye.reasoning, max_out=eye.max_out)
    except Exception as e:                                    # noqa: BLE001
        return "", f"{eye.name}: {type(e).__name__}: {e}"
    if not (raw or "").strip():
        return "", (f"{eye.name}: 回傳空內容（finish_reason={fin}）—— "
                    "推理模型的額度可能不足，調高 PP_EYE_B_MAX_OUT")
    html = vlm.extract_html(raw)
    _store(cache, eye, sha, html, raw, fin)
    return html, None


@dataclass
class TableResult:
    index: int
    page: int                    # 1-based，對得上 PDF 閱讀器
    caption: str
    png: Path
    check: crosscheck.TableCheck | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.check is not None and self.check.ok


def check_doc(raw_dir: Path, env: dict, out_root: Path,
              workers: int = 3) -> tuple[DocContext, list[TableResult]]:
    """對一份文件的所有可修補表格跑「裁圖 → 兩雙眼睛 → 逐格比對」。"""
    ctx = DocContext(raw_dir)
    ctx.preflight()
    w, h = ctx.page_size
    eye_a, eye_b = eyes_from_env(env)

    home = out_root / ctx.doc_name
    crops, cache = home / "crops", home / "cache"

    targets = empty_table.plan(ctx.items, w, h).repairable

    def one(t) -> TableResult:
        r = TableResult(t.index, t.page + 1, t.caption, Path())
        try:
            c = pdfcrop.crop_region(ctx.source_pdf, t.page, t.bbox_pt, crops,
                                    f"t{t.index}", w, h)
            pdfcrop.assert_rect_plausible(c)
        except pdfcrop.CropError as e:
            r.error = f"裁圖失敗：{e}"
            return r
        r.png = c.png
        ha, ea = look(eye_a, c.png, cache)
        hb, eb = look(eye_b, c.png, cache)
        if ea or eb:
            r.error = "；".join(x for x in (ea, eb) if x)
            return r
        r.check = crosscheck.compare(str(t.index), ha, hb)
        return r

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(one, targets))
    return ctx, results


def write_review(ctx: DocContext, results: list[TableResult], out_root: Path) -> Path:
    """只列需要人看的東西。全部一致的表不佔版面 —— 報表要能一眼看完待辦。"""
    home = out_root / ctx.doc_name
    home.mkdir(parents=True, exist_ok=True)
    p = home / "review.md"
    need = [r for r in results if not r.ok]
    L = [f"# {ctx.doc_name}", "",
         f"可修補表格 {len(results)} 張："
         f"自動採用 {sum(1 for r in results if r.ok)}、待判 {len(need)}", ""]
    if not need:
        L.append("沒有需要人工判定的項目。")
    for r in need:
        L += [f"## #{r.index}　第 {r.page} 頁", ""]
        if r.caption:
            L.append(f"caption：`{r.caption[:120]}`")
        L.append(f"裁圖：`{r.png}`")
        if r.error:
            L += ["", f"**錯誤**：{r.error}", ""]
            continue
        c = r.check
        L += ["", f"**{c.line()}**", ""]
        if c.structural:
            L.append(f"A（{c.rows_a} 列）與 B（{c.rows_b} 列）切法不同，需看圖判斷實際列數。")
        for d in c.diffs:
            L += [f"- 第 {d.row} 列第 {d.col} 格（相似度 {d.sim:.2f}）",
                  f"  - A：`{d.a[:300]}`",
                  f"  - B：`{d.b[:300]}`"]
        L.append("")
    p.write_text("\n".join(L))
    return p
