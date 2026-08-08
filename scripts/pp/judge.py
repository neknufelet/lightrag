"""用第二個模型當裁判，判斷 VLM 的轉錄是否對應到該區域的原文。

為什麼需要它：vlm.py 的十二道閘門是純量指標，面對「同一張跨頁續表的片段」沒有
鑑別力 —— V8 負向控制實測 margin 只有 +0.04 ~ -0.10，於是誠實地回報「無法驗證」。
10 張表裡 8 張落到人工佇列。390 份文件不可能這樣做。

裁判為什麼能補上：純量指標比的是「詞彙集合重疊多少」，共用詞彙會讓分數一起虛高。
語言模型比的是**具體內容對應**——「轉錄第 3 列寫 partition impedance，原文這區只有
orifice」——這種判斷不會被詞彙重疊稀釋。

為什麼不能用 qwen 自己當裁判：它就是轉錄者。同一模型的錯誤是相關的，它會認同自己的
幻覺。裁判必須換模型家族，這是 DeepSeek 存在的理由（實測 deepseek-v4 不吃 image_url，
純文字；但比對的另一邊 gt_text 本來就是文字層，兩邊都是文字）。

**裁判本身必須先過負向控制才能信任。** 沒驗過的裁判會把 vlm.py 誠實的「我驗不了」
換成自信的「看起來沒問題」—— 那是退步。跑 `negative_control()` 量它的鑑別力。
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_HOST = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"

# deepseek-v4 是推理模型：completion_tokens 大半是 reasoning_tokens，而推理內容
# 走 message.reasoning_content，不佔 content。預算給太小的話推理把額度吃光，
# content 回空字串 —— 看起來像「解析失敗」，實際是被截斷。
MAX_TOKENS = 4000

# 限制推理深度不是為了省錢，是為了正確性。實測同一組錯配案例：
#   預設 effort：8000 tokens 全部燒在推理上，finish_reason=length，沒有結論
#   effort=low ：2981 tokens 收斂，答對（different, conf 0.85）
# 不設限時模型在「兩份都提到 impedance/orifice，但細節對不上」這種案例上會反覆
# 自我推翻而發散。正確配對兩種設定都是 same/0.95，所以 low 沒有換來品質損失。
REASONING_EFFORT = "low"

# 裁判判定「不符」所需的信心。低於此值當作無法判定，繼續往上游送人工，
# 不當成通過 —— 這條規則的方向是刻意的：裁判的棄權不可以變成放行。
T_CONFIDENCE = 0.7

# 這段是整個 prompt 最要緊的部分。gt_text 是 pdftotext 直接吐的文字層：
# 數學結構被壓平（Z_Mi → zmi）、希臘字母壞掉或消失（η → †、σ → 空）、
# 閱讀順序可能按版面欄位而非邏輯列。不講清楚的話，裁判會把每一處數學差異
# 都當成不符，於是「正確配對」也全部判錯 —— catch rate 看起來 100%，但毫無用處。
SYSTEM = """You compare two representations of the same table region from a PDF.

REFERENCE is a raw text-layer dump (pdftotext). It is known to be degraded:
- Mathematical structure is flattened: `Z_{Mi}` may appear as `zmi`, `ZMi`, or `Z Mi`.
- Greek letters are often corrupted or dropped entirely (eta, sigma may be missing).
- Reading order may follow visual columns rather than logical rows.
- Subscripts and superscripts are inlined without markers.

CANDIDATE is an HTML transcription produced by a vision model from an image of the
same region.

Your ONLY question: are these two describing THE SAME TABLE?

Judge on correspondence of English words, row/column labels, captions, and numeric
values. DO NOT judge on mathematical notation, symbols, LaTeX, or formatting -- the
reference cannot represent those, so differences there are expected and meaningless.

These tables often come from the same document and share vocabulary (impedance,
orifice, mode, partition). Shared topic vocabulary is NOT evidence of a match.
Look for SPECIFIC content: distinctive labels, particular numbers, caption text.

Respond with JSON only:
{"verdict": "same" | "different" | "uncertain",
 "confidence": 0.0-1.0,
 "evidence": ["specific item in one but not the other, quoted"]}

Use "uncertain" when the reference is too degraded to tell. Do not guess."""


@dataclass
class Ruling:
    verdict: str                  # same / different / uncertain
    confidence: float
    evidence: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def says_different(self) -> bool:
        """裁判有信心地說「不是同一張表」。信心不足不算 —— 見 T_CONFIDENCE。"""
        return self.verdict == "different" and self.confidence >= T_CONFIDENCE

    @property
    def says_same(self) -> bool:
        return self.verdict == "same" and self.confidence >= T_CONFIDENCE


def _api_key() -> str:
    k = os.environ.get("DEEPSEEK_API_KEY")
    if k:
        return k
    # 金鑰目前落在另一個專案的 .env。讀它而不是複製一份，避免同一把金鑰散落多處。
    p = Path.home() / "ghq/github.com/neknufelet/vibevoice-v2/.env"
    if p.is_file():
        for line in p.read_text().splitlines():
            if line.startswith("DEEPSEEK_API_KEY="):
                return line.split("=", 1)[1].strip()
    raise RuntimeError("找不到 DEEPSEEK_API_KEY")


def ask(gt_text: str, html: str, caption: str = "", *,
        model: str = DEFAULT_MODEL, host: str = DEFAULT_HOST,
        api_key: str | None = None, timeout: int = 120) -> Ruling:
    """問裁判一組 (原文, 轉錄) 是否為同一張表。"""
    user = (f"CAPTION (from parser, may be empty): {caption[:200]}\n\n"
            f"=== REFERENCE (text layer) ===\n{gt_text[:6000]}\n\n"
            f"=== CANDIDATE (HTML transcription) ===\n{html[:6000]}")
    body = json.dumps({
        "model": model, "temperature": 0, "max_tokens": MAX_TOKENS,
        "reasoning_effort": REASONING_EFFORT,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": user}],
    }).encode()
    req = urllib.request.Request(
        f"{host.rstrip('/')}/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {api_key or _api_key()}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read())
        ch = d["choices"][0]
        raw = ch["message"]["content"]
    except urllib.error.HTTPError as e:
        return Ruling("uncertain", 0.0, error=f"HTTP {e.code}: {e.read()[:200].decode(errors='replace')}")
    except Exception as e:                                   # noqa: BLE001
        return Ruling("uncertain", 0.0, error=f"{type(e).__name__}: {e}")

    # 空 content 幾乎都是推理吃光額度。必須跟「模型判不出來」分開回報 ——
    # 混在一起會讓「預算設太小」長得像「裁判沒有鑑別力」，指向完全錯誤的結論。
    if not (raw or "").strip():
        u = d.get("usage") or {}
        return Ruling("uncertain", 0.0, error=(
            f"content 空（finish_reason={ch.get('finish_reason')}、"
            f"completion={u.get('completion_tokens')}、"
            f"reasoning={(u.get('completion_tokens_details') or {}).get('reasoning_tokens')}）"
            f" —— 推理額度不足，調高 MAX_TOKENS"))

    try:
        m = re.search(r"\{.*\}", raw, re.S)
        o = json.loads(m.group(0) if m else raw)
        return Ruling(str(o.get("verdict", "uncertain")).lower(),
                      float(o.get("confidence", 0.0)),
                      [str(x) for x in (o.get("evidence") or [])])
    except Exception as e:                                   # noqa: BLE001
        return Ruling("uncertain", 0.0, error=f"解析失敗 {type(e).__name__}: {raw[:150]}")


# ---------------------------------------------------------------- 負向控制

def _wordset(t: str) -> set[str]:
    return {w.lower() for w in re.findall(r"[A-Za-z]{4,}", t or "")}


def jaccard(a: str, b: str) -> float:
    """兩份原文的詞彙重疊。用來把配對分難易度：重疊越高，越像同一張跨頁續表的
    片段，也就越難分辨 —— 那正是 V8 失效的地方，裁判必須在這一段證明自己。"""
    x, y = _wordset(a), _wordset(b)
    return len(x & y) / max(len(x | y), 1)


@dataclass
class ControlResult:
    matched: list[tuple[str, Ruling]]                  # (key, 裁判說法)
    mismatched: list[tuple[str, str, float, Ruling]]   # (key_gt, key_html, jaccard, 說法)

    def report(self) -> str:
        L = []
        # 呼叫失敗要先講、而且不能混進「棄權」。失敗的呼叫長得像「裁判判不出來」，
        # 會把基礎設施問題誤讀成鑑別力問題 —— 第一次跑就是這樣 95/100 都是空回應。
        n_err = sum(1 for _, r in self.matched if r.error) + \
                sum(1 for *_, r in self.mismatched if r.error)
        if n_err:
            e = next(r.error for r in
                     [r for _, r in self.matched] + [r for *_, r in self.mismatched] if r.error)
            L.append(f"⚠ 呼叫失敗 {n_err}/{len(self.matched)+len(self.mismatched)}"
                     f"，以下統計不可信。例：{e[:150]}\n")

        ok_m = [(k, r) for k, r in self.matched if not r.error]
        n_m = len(ok_m)
        pass_m = sum(1 for _, r in ok_m if r.says_same)
        wrong_m = sum(1 for _, r in ok_m if r.says_different)
        L.append(f"正確配對 {n_m} 組（成功）：判同 {pass_m}、判異 {wrong_m}（誤殺）、"
                 f"棄權 {n_m - pass_m - wrong_m}")

        ok_x = [t for t in self.mismatched if not t[3].error]
        n_x = len(ok_x)
        caught = sum(1 for *_, r in ok_x if r.says_different)
        missed = sum(1 for *_, r in ok_x if r.says_same)
        L.append(f"錯配 {n_x} 組（成功）：抓到 {caught}（{caught/max(n_x,1):.0%}）、"
                 f"放行 {missed}（{missed/max(n_x,1):.0%}）、"
                 f"棄權 {n_x - caught - missed}")

        # 依詞彙重疊分箱 —— 難的那一箱才是重點
        L.append("\n  錯配抓到率（依原文詞彙重疊度分箱）")
        bins = [(0.0, 0.3, "低 <0.3　不同表"), (0.3, 0.5, "中 0.3–0.5"),
                (0.5, 0.7, "高 0.5–0.7"), (0.7, 1.01, "極高 >0.7　同一張續表")]
        for lo, hi, lab in bins:
            grp = [r for _, _, j, r in ok_x if lo <= j < hi]
            if not grp:
                continue
            c = sum(1 for r in grp if r.says_different)
            mi = sum(1 for r in grp if r.says_same)
            L.append(f"    {lab:<20} {len(grp):>3} 組 → 抓到 {c:>3}（{c/len(grp):>4.0%}）、"
                     f"放行 {mi}")
        return "\n".join(L)


def negative_control(cases: dict[str, dict], *, model: str = DEFAULT_MODEL,
                     workers: int = 6,
                     progress: Callable[[], None] | None = None) -> ControlResult:
    """cases: {key: {"gt": 原文, "html": 轉錄, "caption": ...}}

    對每張表做 1 組正確配對 + (n-1) 組錯配。兩個方向都要量：
    只量抓到率的話，一個永遠回答「different」的裁判會拿到 100%，卻毫無用處。
    """
    keys = list(cases)
    key = _api_key()
    jobs = []
    for i in keys:
        jobs.append(("match", i, i))
        for j in keys:
            if i != j:
                jobs.append(("mismatch", i, j))

    def run(job: tuple[str, str, str]) -> tuple[str, str, str, object]:
        kind, gt_k, html_k = job
        r = ask(cases[gt_k]["gt"], cases[html_k]["html"],
                cases[gt_k].get("caption", ""), model=model, api_key=key)
        if progress:
            progress()
        return kind, gt_k, html_k, r

    with ThreadPoolExecutor(max_workers=workers) as ex:
        out = list(ex.map(run, jobs))

    matched = [(g, r) for k, g, h, r in out if k == "match"]
    mismatched = [(g, h, jaccard(cases[g]["gt"], cases[h]["gt"]), r)
                  for k, g, h, r in out if k == "mismatch"]
    return ControlResult(matched, mismatched)
