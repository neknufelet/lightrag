r"""問模型：這兩條公式是不是同一條。**先過負向控制才准信。**

## 為什麼需要它

`eq-dup` 用骨架相似度找「同一條公式係數不一致」，而**相似度多少才算同一條，
沒有依據** —— `--min-ratio 0.8` 是隨手挑的。要訂門檻就要有標註集，
而人一次只標得動二十來題。模型可以把樣本擴大兩個數量級。

## ⛔ 不要拿它去篩「係數不一致」的配對（2026-08-13 實測）

**它會刪掉真發現。** 拿它讀庫裡唯一那條已驗證的分歧（Maa 微穿孔板電阻，
兩篇的係數是 `32` 與 `8`），三隻模型一致回答「不是同一條」。

原因是**負向控制出得太簡單**：對照組用的是「完全不相干的兩條」（相似度 <0.35），
模型當然分得出來。而真正的任務是「很像、只有係數不同」—— 模型在那裡會**把係數
不同本身當成理由**判「不是同一條」，正好與這支工具的目的相反。

⇒ **負向控制的難度必須對應真正的任務。** `judge.py` 的檔頭早就寫過同一件事
（它的控制組按詞彙重疊度分箱，並註明「難的那一箱才是重點」），我沒照做。

⇒ 目前它只證明堪用於**一件事**：判斷「骨架逐字相同的兩條是不是同一條公式」
（Tier A 審計）。那個任務的難點在「骨架太短所以撞在一起」，不在係數。

## 為什麼不能直接信模型

⚠ **一個永遠回答「same」的模型，在「這兩條是不是同一條」上會拿到 100% 的召回率，
卻毫無用處。** 所以兩個方向都要量（這句話與作法照抄 `judge.py` 的負向控制，
那支的檔頭把理由寫得很清楚）。

⚠ **投票的模型必須來自不同家族。** 同家族的系統性誤讀會一起發生，
投票就變成一個人投三票（理由見 `eyes.Eye.family`）。

## 對照組從資料裡來，不用自己編

```
一定是同一條   Tier A 的成員兩兩配對 —— 骨架逐字相同、而且跨來源
一定不是同一條 結構輪廓不同、相似度極低、又跨來源的兩條
```

**兩組都是現成的**，不需要人先標。模型在這兩組上的表現就是它的鑑別力。

## 這支不做的事

不訂門檻、不裁決。產出是「模型怎麼說」，而模型的說法**是啟發式**——
照本專案的通則，啟發式的結果不得直接當數字報，要有權威訊號覆驗（人的標註）。
"""
from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from .eyes import Eye
from .judge import Ruling, ask_json

# 判準跟人拿到的那張表**逐字相同**（`docs/eq-label-review-20260813.md` 的開頭）——
# 兩邊問不同的問題，答案就沒得比。
SYSTEM = """You compare two LaTeX equations extracted from acoustics papers by a PDF parser.

Your ONLY question: do these two express THE SAME physical relationship?

Rules for judging:
- Variable NAMES do not matter. Different papers use different symbols for the same
  quantity (k / chi / k_1 for the same wavenumber; l / d / t for the same length).
- Notation and formatting do not matter (\\sqrt{x} vs x^{1/2}, \\dfrac vs \\frac).
- NUMERIC COEFFICIENTS may differ and the answer can still be "same": a coefficient
  disagreement between two papers is exactly what we are looking for.
- If one equation is a SPECIAL CASE of the other, a LIMIT of it, or the NEXT STEP in
  a derivation, answer "different". Same topic is NOT the same relationship.
- The parser is imperfect: subscripts may be lost, digits may be split ("3 2" = 32),
  symbols may be misread. Do not answer "different" solely because of parser damage.

These equations all come from acoustics papers and share vocabulary (impedance,
density, wavenumber). Shared topic is NOT evidence of a match.

Respond with JSON only:
{"verdict": "same" | "different" | "uncertain",
 "confidence": 0.0-1.0,
 "evidence": ["the specific structural feature that decided it, quoted"]}

Use "uncertain" when the extraction is too damaged to tell. Do not guess."""


def _show(latex: str) -> str:
    t = re.sub(r"^\$\$|\$\$$", "", (latex or "").strip()).strip()
    return re.sub(r"\s+", " ", re.sub(r"\\tag\{[^}]*\}", "", t))[:1500]


def ask_pair(a: str, b: str, eye: Eye, *, timeout: int = 120, tries: int = 3) -> Ruling:
    """問一隻眼睛：這兩條是不是同一條。

    ⚠ 限流要重試，**而且不能把它算成「模型判不出來」**。眼睛 A 只有一個供應商
    （2026-08-13 實測），併發稍高就回 429 —— 那是基礎設施，不是鑑別力。
    """
    user = f"=== EQUATION A ===\n{_show(a)}\n\n=== EQUATION B ===\n{_show(b)}"
    for attempt in range(tries):
        r = ask_json(SYSTEM, user, model=eye.model, host=eye.host,
                     api_key=eye.api_key, timeout=timeout, provider=eye.provider,
                     reasoning=eye.reasoning)
        if not r.error or ("429" not in r.error and "rate" not in r.error.lower()):
            return r
        time.sleep(2 ** attempt * 3)
    return r


@dataclass
class ControlResult:
    """一隻眼睛在兩個對照組上的表現。**兩個方向都要有，缺一個就看不出亂點頭。**"""

    eye: str
    same_ok: int = 0            # 已知同一條 → 判同（對）
    same_wrong: int = 0         # 已知同一條 → 判異（誤殺）
    same_abstain: int = 0
    diff_ok: int = 0            # 已知不同 → 判異（對）
    diff_wrong: int = 0         # 已知不同 → 判同（**亂點頭，最致命**）
    diff_abstain: int = 0
    errors: int = 0
    first_error: str = ""
    # 「已知同一條」裡被判異的題號。**留著才問得出下一個問題**：
    # 三隻不同家族的眼睛如果打槍的是同一批，那多半不是模型太嚴，
    # 是「骨架一樣就是同一條」這個假設本身有例外 —— 而那是關於 eq-dup 的發現。
    same_misses: list[int] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        """兩個方向都要有鑑別力才算堪用。

        門檻取 0.7 是**下限不是目標**：低於七成的話，投票結果比骨架相似度
        還不可靠，那就不該拿它去擴大樣本。
        """
        n_s = self.same_ok + self.same_wrong + self.same_abstain
        n_d = self.diff_ok + self.diff_wrong + self.diff_abstain
        return (n_s and n_d and self.same_ok / n_s >= 0.7 and self.diff_ok / n_d >= 0.7)

    def line(self) -> str:
        n_s = self.same_ok + self.same_wrong + self.same_abstain
        n_d = self.diff_ok + self.diff_wrong + self.diff_abstain
        err = f"　⚠ 呼叫失敗 {self.errors}（{self.first_error[:60]}）" if self.errors else ""
        return (f"{self.eye:<14} 已知同一條 {n_s} 組 → 判同 {self.same_ok}"
                f"（{self.same_ok / max(n_s, 1):.0%}）、誤殺 {self.same_wrong}、"
                f"棄權 {self.same_abstain}　｜　"
                f"已知不同 {n_d} 組 → 判異 {self.diff_ok}"
                f"（{self.diff_ok / max(n_d, 1):.0%}）、**亂點頭 {self.diff_wrong}**、"
                f"棄權 {self.diff_abstain}{err}")


def panel_verdict(rulings: list[Ruling]) -> str:
    """多數決。**平手或票數不足一律回 `uncertain`** —— 沒有多數就是沒有結論。

    ⚠ 不要把「棄權」算進任何一邊。棄權是模型說「我看不出來」，
    當成任何一種答案都是把不知道講成知道。
    """
    ok = [r for r in rulings if not r.error]
    same = sum(1 for r in ok if r.says_same)
    diff = sum(1 for r in ok if r.says_different)
    if same > diff and same >= 2:
        return "same"
    if diff > same and diff >= 2:
        return "different"
    return "uncertain"


def control(eye: Eye, same: list[tuple[str, str]], diff: list[tuple[str, str]],
            *, workers: int = 2) -> ControlResult:
    """跑負向控制。`same`／`diff` 是 (latexA, latexB) 的清單。

    ⚠ 併發預設壓到 2：眼睛 A 只有一個供應商，開 4 就 429（實測 15/20 失敗）。
    """
    out = ControlResult(eye=eye.name)
    jobs = [("same", i, a, b) for i, (a, b) in enumerate(same)]
    jobs += [("diff", i, a, b) for i, (a, b) in enumerate(diff)]

    def run(job: tuple[str, int, str, str]) -> tuple[str, int, Ruling]:
        kind, idx, a, b = job
        return kind, idx, ask_pair(a, b, eye)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for kind, idx, r in ex.map(run, jobs):
            if r.error:
                out.errors += 1
                out.first_error = out.first_error or r.error
                continue
            if kind == "same":
                out.same_ok += r.says_same
                out.same_wrong += r.says_different
                out.same_abstain += not (r.says_same or r.says_different)
                if r.says_different:
                    out.same_misses.append(idx)
            else:
                out.diff_ok += r.says_different
                out.diff_wrong += r.says_same
                out.diff_abstain += not (r.says_same or r.says_different)
    return out
