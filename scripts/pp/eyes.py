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
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pp import crosscheck, pdfcrop, vlm  # noqa: E402
from pp.docctx import DocContext  # noqa: E402
from pp.rules import empty_table  # noqa: E402

LOGGER = logging.getLogger(__name__)


@dataclass
class Eye:
    name: str
    host: str
    api_key: str
    model: str
    reasoning: bool = False          # gpt-5 系列要 max_completion_tokens
    max_out: int = 3072
    # OpenRouter 會把同一個模型路由到不同供應商，輸出行為因此會變。
    # 交叉驗證的前提是「模型固定」，所以必須釘住 —— 不釘的話，兩次呼叫
    # 可能來自不同部署，比對出來的差異分不清是模型錯還是換了後端。
    provider: str = ""
    # `max_out` 是哪個環境變數設的。**只給錯誤訊息用**：轉錄被截斷時要能直接
    # 說出「調哪一個鍵」，而 `name`（qwen／luna／eye_c）對不上 A／B／C。
    max_out_key: str = ""

    @property
    def family(self) -> str:
        """訓練血統。多數決要求家族不同 —— 同家族的系統性誤讀會一起發生，
        投票就變成一個人投三票。"""
        m = self.model.lower()
        for key, fam in (("gemini", "google"), ("gemma", "google"),
                         ("claude", "anthropic"), ("gpt", "openai"),
                         ("o1", "openai"), ("o3", "openai"), ("luna", "openai"),
                         ("qwen", "qwen"), ("llama", "meta"), ("grok", "xai"),
                         ("mistral", "mistral"), ("pixtral", "mistral"),
                         ("deepseek", "deepseek")):
            if key in m:
                return fam
        return m.split("/")[0]


def eye_c_from_env(env: dict) -> Eye | None:
    """第三隻眼睛。只在需要打破僵局時才呼叫，所以是可選的 ——
    沒設定時流程照跑，三方皆異的項目留給人工。

    走 OpenRouter：一把金鑰通吃多個家族，換模型是改設定不是寫 adapter。
    這一點跟「綁模型的觀察會過期」那條規則直接相關（見 A-23）—— 換代成本
    趨近於零，才有可能真的定期換。
    """
    model = (env.get("PP_EYE_C_MODEL") or "").strip()
    key = (env.get("PP_EYE_C_API_KEY") or "").strip()
    if not model or not key or key.startswith("貼在") or key in ("...", "TODO"):
        return None
    return Eye("eye_c",
               env.get("PP_EYE_C_HOST", "https://openrouter.ai/api/v1"),
               key, model,
               reasoning=env.get("PP_EYE_C_REASONING", "false").lower() == "true",
               max_out=int(env.get("PP_EYE_C_MAX_OUT", "3072")),
               provider=(env.get("PP_EYE_C_PROVIDER") or "").strip(),
               max_out_key="PP_EYE_C_MAX_OUT")


def eyes_from_env(env: dict) -> tuple[Eye, Eye]:
    """A = 轉錄者，B = 交叉驗證者。兩者必須不同家族，否則錯誤相關、驗證失效。

    **眼睛 A 與抽取用的 LLM 從 2026-08-09 起可以分開設。** 在此之前它直接讀
    `LLM_BINDING_*`／`LLM_MODEL` —— 也就是說，改抽取模型會**連帶改掉看圖的那一隻**。

    那是一顆地雷：`pp/judge.py` 的檔頭記著實測結果「deepseek-v4 不吃 image_url，
    純文字」。所以把抽取換成 DeepSeek 的那一刻，眼睛 A 會靜靜變成一個看不見圖的
    模型，表格轉錄整條壞掉**而且不會有錯誤訊息**。

    現在 `PP_EYE_A_*` 沒設時 fallback 回原本那三個鍵，**行為逐欄位不變**
    （`tests/test_eye_a_split.py` 釘住這件事）。要拆才拆，不拆就跟以前一樣。

    ⚠ `name` 一律是 `"qwen"`，即使模型換掉也不改 —— 它是**轉錄快取檔名的一部分**
    （`{png_sha}.{name}.{model}.json`），改掉會讓既有快取全部 miss 而重新付費。
    模型是誰由 `model` 決定，家族由 `family` 從 `model` 算，都不看 `name`。
    """
    a = Eye("qwen",
            env.get("PP_EYE_A_HOST") or env.get("LLM_BINDING_HOST", "http://localhost:8080/v1"),
            env.get("PP_EYE_A_API_KEY") or env.get("LLM_BINDING_API_KEY", ""),
            env.get("PP_EYE_A_MODEL") or env.get("LLM_MODEL", "qwen3.6-35b-a3b"),
            max_out=int(env.get("PP_EYE_A_MAX_OUT", "3072")),
            # 走 OpenRouter 時**一定要釘**：同一個模型 ID 會被路由到不同供應商，
            # 輸出行為因此會變，而交叉驗證的前提是「模型固定」。不釘的話兩次
            # 呼叫可能來自不同部署，比對出來的差異分不清是模型錯還是換了後端。
            # 指向本機時留空即可（只有一個部署，沒有路由問題）。
            provider=(env.get("PP_EYE_A_PROVIDER") or "").strip(),
            max_out_key="PP_EYE_A_MAX_OUT")
    b = Eye("luna",
            env.get("PP_EYE_B_HOST", "https://api.openai.com/v1"),
            # 預設沿用 embedding 那把 OpenAI 金鑰，不另外散一份出去
            env.get("PP_EYE_B_API_KEY") or env.get("EMBEDDING_BINDING_API_KEY", ""),
            env.get("PP_EYE_B_MODEL", "gpt-5.6-luna"),
            reasoning=env.get("PP_EYE_B_REASONING", "true").lower() == "true",
            max_out=int(env.get("PP_EYE_B_MAX_OUT", "6000")),
            max_out_key="PP_EYE_B_MAX_OUT")
    if a.model == b.model:
        raise RuntimeError("兩雙眼睛不能是同一個模型 —— 錯誤會相關，交叉驗證失去意義")
    if a.family == b.family:
        raise RuntimeError(
            f"兩雙眼睛同屬 {a.family} 家族（{a.model} / {b.model}）—— "
            "同家族的系統性誤讀會一起發生，交叉驗證等於沒驗")
    return a, b


def assert_distinct(eyes_: list[Eye]) -> None:
    """多數決前的前提檢查。家族重複時投票會失真 —— 一個血統投兩票。"""
    fams = [e.family for e in eyes_]
    dup = {f for f in fams if fams.count(f) > 1}
    if dup:
        raise RuntimeError(
            f"眼睛家族重複：{sorted(dup)}（{', '.join(e.model for e in eyes_)}）—— "
            "多數決要求各票獨立")


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def _cache_file(cache: Path, eye: Eye, png_sha: str) -> Path:
    """快取檔路徑。**檔名規則是契約**：改了等於既有快取全部 miss、重新付一次錢
    （`tests/test_eye_a_split.py` 用一個舊檔名釘住這件事）。"""
    return cache / f"{png_sha}.{eye.name}.{eye.model.replace('/', '_')}.json"


def _cached(cache: Path, eye: Eye, png_sha: str) -> dict | None:
    """回傳整包快取內容，**不只 `html`** —— 截斷檢查要 `raw` 與 `finish_reason`。

    以前這裡只挑 `["html"]` 出來，於是 `vlm.transcribe` 正確回報、`_store` 也正確
    存下的 `finish_reason` 在快取這條路上被丟掉，V1 無從判斷。存了、寫了檢查，
    就是沒接起來 —— 這一行就是那個斷點。
    """
    f = _cache_file(cache, eye, png_sha)
    if f.is_file():
        return json.loads(f.read_text())
    return None


def _store(cache: Path, eye: Eye, png_sha: str, html: str, raw: str, fin: str) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    _cache_file(cache, eye, png_sha).write_text(
        json.dumps({"model": eye.model, "html": html, "raw": raw,
                    "finish_reason": fin}, ensure_ascii=False, indent=1))


def _truncation_error(eye: Eye, f: Path, raw: str | None, fin: str | None,
                      closing: str | None) -> str | None:
    """跑 V1／V2（`vlm.truncation_failures`）。沒有截斷跡象時回 None。

    **缺欄位不算截斷。** `_store` 一定會寫 `raw` 與 `finish_reason`，走到這一支
    代表快取檔來自沒見過的格式或別的東西寫的 —— 那是「驗不了」不是「壞了」，
    當成壞了會無端重付一輪轉錄費。但要出聲（鐵則 6：探針要在沒人問的時候會響），
    否則「沒檢查」跟「檢查通過」在畫面上長得一樣。
    """
    if raw is None or fin is None:
        LOGGER.warning("%s 缺 raw／finish_reason，截斷檢查（V1／V2）驗不了", f)
        return None
    bad = vlm.truncation_failures(raw, fin, closing)
    if not bad:
        return None
    key = eye.max_out_key or "該眼睛的 PP_EYE_*_MAX_OUT"
    return (f"{eye.name}: 轉錄被截斷（{'、'.join(bad)}）—— 不採用。"
            f"原始輸出留在 {f}；若是額度不足，調高 {key}（現值 {eye.max_out}）之後"
            "**必須把那個檔刪掉**才會重打 —— 快取的鍵是「裁圖 sha ＋ 眼睛 ＋ 模型」，"
            "不含 max_out，所以調大不會自動失效。")


def look(eye: Eye, png: Path, cache: Path, *,
         closing: str | None = "</table>") -> tuple[str, str | None]:
    """回傳 (html, 錯誤訊息)。失敗不拋例外 —— 一張表看不了不該中斷整份文件。

    **截斷的轉錄算失敗**（V1／V2，見 `vlm.truncation_failures`）。真正會靜靜通過
    的形狀是「模型把一張表拆成兩塊、寫到第二塊被切斷」：`extract_html` 的非貪婪
    正則只取第一個完整的 `<table>`，於是半張表會被當成整張表採用，而
    `gate_table_html` 看到的是一個結構完整的表，放行。

    **快取命中那條路也要驗。** 以前 `_cached` 只回 html，舊快取裡的截斷永遠不會
    被發現；而轉錄是會被長期沿用的（快取以裁圖 sha 為鍵）。

    `closing` 隨 `vlm.PROMPT` 一起變 —— 轉錄表格時是 `</table>`，`eq-check.py`
    換成方程式 prompt 之後輸出是裸 LaTeX，要傳 `None`（只跑 V1）。
    """
    sha = _sha(png)
    f = _cache_file(cache, eye, sha)
    hit = _cached(cache, eye, sha)
    if hit is not None:
        err = _truncation_error(eye, f, hit.get("raw"), hit.get("finish_reason"), closing)
        return ("", err) if err else (hit["html"], None)
    try:
        raw, fin = vlm.transcribe(png, eye.host, eye.api_key, eye.model,
                                  reasoning=eye.reasoning, max_out=eye.max_out,
                                  provider=eye.provider)
    except Exception as e:                                    # noqa: BLE001
        return "", f"{eye.name}: {type(e).__name__}: {e}"
    if not (raw or "").strip():
        return "", (f"{eye.name}: 回傳空內容（finish_reason={fin}）—— "
                    "推理模型的額度可能不足，調高 PP_EYE_B_MAX_OUT")
    html = vlm.extract_html(raw)
    # **先存再驗**（PO 2026-08-09 定案）：被截斷的原始輸出也要留在磁碟上 ——
    # 可以 diff、可以重看、restic 會備份，而且下次重跑直接從快取判失敗，
    # 不對同一張圖重複付費。代價是調大 max_out 之後要手動刪檔，錯誤訊息會講。
    _store(cache, eye, sha, html, raw, fin)
    err = _truncation_error(eye, f, raw, fin, closing)
    return ("", err) if err else (html, None)


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


def check_doc(
    raw_dir: Path,
    env: dict,
    out_root: Path,
    *,
    source_dir: Path,
    workers: int = 3,
) -> tuple[DocContext, list[TableResult]]:
    """對一份文件的所有可修補表格跑「裁圖 → 兩雙眼睛 → 逐格比對」。"""
    ctx = DocContext(raw_dir, source_dir=source_dir)
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
