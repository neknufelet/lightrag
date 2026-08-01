"""Mathpix 當第三隻眼睛。

為什麼需要第三隻：兩眼一致時判定很可靠，但實測 30 條裡有 11 條兩眼不一致
（37%）—— 那時候誰對誰錯沒有依據。qwen 會誤讀羅馬數字、luna 會看錯字元，
兩個都可能錯。需要一個**失誤型態不同**的第三方來打破僵局。

Mathpix 是專為數學訓練的，失誤型態跟通用 VLM 不相關 —— 那正是交叉驗證要的。

不是 OpenAI 相容 API，所以不能沿用 Eye：認證走 app_id/app_key 兩個 header，
回應在 `latex_styled` 或 `text` 欄位。

免費方案額度很小（10 snips），所以呼叫前一定要先確認這一條值得問。
`pick_worth_asking()` 挑的是「兩眼分歧最大」與「已知 MinerU 可疑」的，
不要均勻亂抽 —— 額度花在沒有爭議的式子上等於浪費。
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

ENDPOINT = "https://api.mathpix.com/v3/text"


class MathpixError(RuntimeError):
    pass


def _creds(env: dict) -> tuple[str, str]:
    aid = env.get("MATHPIX_APP_ID") or os.environ.get("MATHPIX_APP_ID")
    key = env.get("MATHPIX_APP_KEY") or os.environ.get("MATHPIX_APP_KEY")
    if not aid or not key:
        raise MathpixError(
            "缺少 MATHPIX_APP_ID / MATHPIX_APP_KEY。到 mathpix.com 的 Console → "
            "API Keys 取得，填進 .env（那個檔已 gitignore）")
    return aid, key


def transcribe(png: Path, env: dict, timeout: int = 120) -> tuple[str, dict]:
    """回傳 (LaTeX, 原始回應)。失敗丟例外 —— 額度有限，錯誤要當場看到。"""
    aid, key = _creds(env)
    img = base64.b64encode(png.read_bytes()).decode()
    body = json.dumps({
        "src": f"data:image/png;base64,{img}",
        # 只要 LaTeX，不要 mmd 包裝；include_line_data 會多花額度但不多要
        "formats": ["latex_styled", "text"],
        "ocr": ["math", "text"],
        "format_options": {"latex_styled": {"transforms": ["rm_spaces"]}},
    }).encode()
    req = urllib.request.Request(
        ENDPOINT, data=body,
        headers={"app_id": aid, "app_key": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise MathpixError(f"HTTP {e.code}: {e.read()[:300].decode(errors='replace')}") from e

    if d.get("error"):
        raise MathpixError(f"{d.get('error_info') or d['error']}")
    latex = (d.get("latex_styled") or d.get("text") or "").strip()
    if not latex:
        raise MathpixError(f"回應沒有 LaTeX：{json.dumps(d, ensure_ascii=False)[:200]}")
    return latex, d
