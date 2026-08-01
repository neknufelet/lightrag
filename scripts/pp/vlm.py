"""用視覺模型把裁下來的表格轉錄成 HTML，並用十二道閘門驗證轉錄是否可信。

為什麼需要十二道：原本打算用「召回率」判斷轉錄正確與否，實測沒有鑑別力 ——
拿 B 表的正確轉錄去頂 A 表，240 組錯配有 45% 通過；門檻放寬到 0.40 則 97% 通過。
原因是這些表是同一張跨頁續表的片段，詞彙都是 impedance / orifice / mode / norms
那組；而召回率只管「真文字有沒有出現」，**完全不管 HTML 多出來什麼** —— 幻覺加行、
複製上一張表、行列轉置、數值抄到隔壁欄，全部放行。

其中兩道是關鍵：
  V8 負向控制 —— 同時對鄰近表算召回，自己贏鄰居不到 0.15 就不算數。這道補上面那個洞。
  V12 分母下限 —— 純數字表在空的詞集合上召回率恆為 1.0，那叫真空通過。

為什麼不用「雙取樣一致性」：同一模型、同 prompt、temperature 0，系統性錯誤（漏一欄、
吃掉符號格、對某字型一貫誤讀）會在兩次取樣中一模一樣地重現，判定通過。它只抓得到
隨機抖動，抓不到系統性省略 —— 而系統性省略正是本專案踩過的型態。
"""
from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from mineru_common import LEAK, TAG

PROMPT = (
    "Transcribe this table into HTML. Use <table><tr><td>. "
    "Render every mathematical expression as inline LaTeX delimited by $...$. "
    "Preserve subscripts, superscripts, integrals, fractions and Greek letters exactly. "
    "If a cell contains a figure or diagram rather than text, write [FIGURE] in that cell. "
    "Do not invent rows or columns that are not visible. "
    "Output only the HTML, no commentary."
)

# 閘門門檻。來源見工單 §5.2 的實測。
T_ALPHA_RECALL = 0.70
T_NUM_PRECISION = 0.95
T_LCS_RATIO = 0.60
T_NEG_MARGIN = 0.15      # V8：自己的召回要贏鄰居這麼多才算數
T_ROW_DELTA = 0.30
MIN_ALPHA_GT = 8         # V12：分母低於此值宣告 unverified，不假裝驗過
MIN_NUM_GT = 6


@dataclass
class Verdict:
    """三態，不是二態。

    「驗證出錯誤」與「無法驗證」必須分開：前者代表轉錄確實壞了，該丟棄；後者代表
    我們的指標對這張表沒有鑑別力，轉錄可能完全正確，只是自動化擔保不了 —— 該交人工，
    不該丟棄。混為一談會讓正確的修補被誤殺，或讓「大部分都失敗」看起來像品質問題，
    實際上是驗證方法的侷限。
    """
    ok: bool
    unverified: bool = False          # 無法驗證 → 人工佇列
    failed: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    def line(self) -> str:
        if self.unverified:
            return f"無法驗證（{'、'.join(self.failed)}）→ 人工"
        if self.ok:
            m = self.metrics
            np = m.get('num_precision')
            return (f"通過  alpha={m.get('alpha_recall',0):.2f} "
                    f"num_prec={'n/a' if np is None else f'{np:.2f}'} "
                    f"lcs={m.get('lcs',0):.2f} margin={m.get('neg_margin',0):+.2f}")
        return f"未通過：{'、'.join(self.failed)}"


# LaTeX 指令名不是內容。不剝掉的話 \int \frac \eta \underset \longrightarrow 這些
# 會被當成單字混進詞序，把 LCS 對齊整個打亂（實測讓 7/10 張誤判成順序錯亂）。
LATEX_CMD = re.compile(r"\\[a-zA-Z]+")


# 文字層把數學壓平成 zmi / zsh / hpi / vix / pii 這種殘骸（分別是 Z_Mi、Z_sh、
# ⟨p_I⟩、v_Ix、π）。VLM 永遠不會產出它們 —— 它正確地寫成 $Z_{\mathrm{Mi}}$。
# 拿這些當比對基準等於要求 VLM 重現文字層的壞掉方式，召回率必然趨近 0。
# 判準：至少 4 個字元且含母音。這會一併排掉 cos / sin / cot 這些數學函式名
#（VLM 寫成 \cos，已被 LATEX_CMD 剝掉），它們同樣不可比對。
_VOWEL = re.compile(r"[aeiou]")


def _words(t: str) -> list[str]:
    out = []
    for w in re.findall(r"[A-Za-z]{4,}", LATEX_CMD.sub(" ", t or "")):
        lw = w.lower()
        if _VOWEL.search(lw):
            out.append(lw)
    return out


def _nums(t: str) -> list[str]:
    return re.findall(r"\d+(?:\.\d+)?", t or "")


def _lcs_len(a: list[str], b: list[str]) -> int:
    """最長共同子序列長度。用來抓「順序全亂」與「只轉了前三列」。"""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b):
            cur.append(prev[j] + 1 if x == y else max(cur[j], prev[j + 1]))
        prev = cur
    return prev[-1]


def transcribe(png: Path, host: str, api_key: str, model: str,
               timeout: int = 300) -> tuple[str, str]:
    """回傳 (原始輸出, finish_reason)。不做任何清理 —— V2 要檢查結尾。"""
    img = base64.b64encode(png.read_bytes()).decode()
    body = json.dumps({
        "model": model, "temperature": 0, "max_tokens": 3072,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": PROMPT},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img}"}},
        ]}],
    }).encode()
    req = urllib.request.Request(
        f"{host.rstrip('/')}/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"VLM HTTP {e.code}: {e.read().decode(errors='replace')[:200]}") from e
    ch = d["choices"][0]
    return ch["message"]["content"], ch.get("finish_reason", "")


def extract_html(raw: str) -> str:
    """把模型可能包上的 ```html 圍籬剝掉。找不到 <table> 就原樣回傳，讓 V2 去擋。"""
    m = re.search(r"<table\b.*?</table>", raw, re.S | re.I)
    return m.group(0) if m else raw.strip()


def judge(html: str, raw: str, finish_reason: str, gt_text: str,
          neighbour_gts: list[str], caption: str,
          layout_rows: int | None = None) -> Verdict:
    """十二道閘門。任何 hard 失敗即不採用；分母不足則標 unverified 交人工。"""
    failed: list[str] = []
    m: dict = {}

    # V1 / V2：截斷
    if finish_reason and finish_reason != "stop":
        failed.append(f"V1 finish_reason={finish_reason}")
    if not raw.rstrip().rstrip("`").rstrip().lower().endswith("</table>"):
        failed.append("V2 輸出未以 </table> 結尾")

    # V3：數學被換成圖片
    if "<img" in html.lower():
        failed.append("V3 輸出含 <img>")

    # V4：prompt 洩漏
    if LEAK.search(html):
        failed.append("V4 prompt 洩漏")

    out_text = TAG.sub(" ", html)
    gt_w, out_w = _words(gt_text), _words(out_text)
    gt_set, out_set = set(gt_w), set(out_w)

    # V12：分母下限。純數字／純符號表在空集合上召回率恆為 1.0 —— 真空通過。
    #
    # 門檻只看 alpha：那是主要的鑑別訊號（V5 召回、V7 順序、V8 負向控制都建立在它上面）。
    # 數字不足時只是讓 V6 不適用，不該否定整個判斷 —— 工單原本要求「唯一數字 >= 6」，
    # 實測這類數學表的數字幾乎都是下標的 0/1/2，唯一數字只有 4–5 個，10 張裡 9 張會被
    # 判 unverified，等於整組閘門作廢、全部退回人工。那是安全但無用。
    gt_nums = set(_nums(gt_text))
    m.update(gt_alpha=len(gt_set), gt_num=len(gt_nums))
    if len(gt_set) < MIN_ALPHA_GT:
        return Verdict(ok=False, unverified=True,
                       failed=[f"V12 英文詞分母不足（{len(gt_set)} < {MIN_ALPHA_GT}）"]
                              + failed, metrics=m)

    # V5：alpha 召回。
    #
    # 不做 IDF 過濾 —— 那道與 V8 負向控制重複，而且在這類文件上正好反向：它會剔除
    # impedance / orifice / partition 這些「在多數鄰近表都出現」的詞，而那正是唯一
    # 可比對的散文；留下的全是文字層的數學殘骸，召回率必然掉到 0。
    # 「共用詞彙讓分數虛高」由 V8 處理，那才是它存在的理由。
    scoring = gt_set
    recall = len(scoring & out_set) / len(scoring)
    m["alpha_recall"] = recall
    if recall < T_ALPHA_RECALL:
        failed.append(f"V5 召回 {recall:.2f} < {T_ALPHA_RECALL}")

    # V6：數值 precision —— 輸出裡的每個數字都該在原文找得到。擋幻覺與抄錯欄。
    out_nums = _nums(out_text)
    if len(gt_nums) < MIN_NUM_GT:
        # 原文的數字太少，precision 沒有鑑別力。記錄不適用，不假裝驗過。
        m["num_precision"] = None
    elif out_nums:
        prec = sum(1 for n in out_nums if n in gt_nums) / len(out_nums)
        m["num_precision"] = prec
        if prec < T_NUM_PRECISION:
            failed.append(f"V6 數值 precision {prec:.2f} < {T_NUM_PRECISION}")
    else:
        m["num_precision"] = 1.0

    # V7：順序
    lcs = _lcs_len(gt_w, out_w) / max(len(gt_w), 1)
    m["lcs"] = lcs
    if lcs < T_LCS_RATIO:
        failed.append(f"V7 LCS 比例 {lcs:.2f} < {T_LCS_RATIO}")

    # V8：負向控制 —— 這道就是補「拿別張表也能通過」的洞
    nb = [len(set(_words(g)) & out_set) / max(len(set(_words(g))), 1) for g in neighbour_gts]
    margin = recall - (max(nb) if nb else 0.0)
    m["neg_margin"] = margin
    m["neighbour_best"] = max(nb) if nb else 0.0
    if nb and margin < T_NEG_MARGIN:
        failed.append(f"V8 負向控制 margin {margin:+.2f} < {T_NEG_MARGIN} —— "
                      "對鄰近表的召回幾乎一樣高，這個分數沒有鑑別力")

    # V9：caption
    if caption.strip():
        cap_w = set(_words(caption))
        if cap_w and len(cap_w & (out_set | set(_words(gt_text)))) / len(cap_w) < 0.5:
            failed.append("V9 caption 未出現在輸出或原文，rect 可能錯位")

    # V10：列數對帳
    if layout_rows:
        rows = len(re.findall(r"<tr\b", html, re.I))
        delta = abs(rows - layout_rows) / max(layout_rows, 1)
        m["rows"], m["layout_rows"], m["row_delta"] = rows, layout_rows, delta
        if delta > T_ROW_DELTA:
            failed.append(f"V10 列數 {rows} vs layout {layout_rows}（差 {delta:.0%}）")

    # V11：覆蓋率，只記錄不擋 —— 誠實揭露自動化擔保了多少
    all_tok = [t for t in re.findall(r"\S+", gt_text)]
    m["token_coverage"] = (
        sum(1 for t in all_tok if t.lower() in out_text.lower()) / len(all_tok)
        if all_tok else 0.0)

    # 分流：hard 失敗代表轉錄確實壞了；鑑別力不足代表指標無效，交人工而非丟棄。
    HARD = ("V1", "V2", "V3", "V4", "V6", "V9", "V10")
    hard = [f for f in failed if f.split()[0] in HARD]
    if hard:
        return Verdict(ok=False, failed=hard + [f for f in failed if f not in hard], metrics=m)
    if failed:
        return Verdict(ok=False, unverified=True, failed=failed, metrics=m)
    return Verdict(ok=True, metrics=m)
