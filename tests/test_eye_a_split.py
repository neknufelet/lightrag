"""眼睛 A 與抽取 LLM 的拆分：不填新鍵時，行為必須一個位元都沒變。

**為什麼要拆**：在此之前眼睛 A 直接讀 `LLM_BINDING_*`／`LLM_MODEL`，所以改抽取模型
會連帶改掉看圖的那一隻。而 `pp/judge.py` 實測過「deepseek-v4 不吃 image_url，純文字」
—— 把抽取換成 DeepSeek 的那一刻，眼睛 A 會靜靜變成看不見圖的模型，表格轉錄整條壞掉
而且沒有錯誤訊息。

**為什麼這支測試比拆分本身重要**：拆分的驗收條件是「今天什麼都不會變」。這種
「應該沒差」的改動最危險 —— 沒有人會去看，出事時也不會聯想到它。所以把「沒差」
寫成可執行的斷言，而不是寫在 commit 訊息裡。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from pp import eyes  # noqa: E402

# 拆分前 `eyes_from_env` 讀的就是這三個鍵。測資刻意用非預設值，
# 這樣「有沒有真的讀到」才看得出來 —— 全用預設值的話，讀錯鍵也會過。
LEGACY_ENV = {
    "LLM_BINDING_HOST": "http://100.71.26.77:8080/v1",
    "LLM_BINDING_API_KEY": "local-key-not-a-real-secret",
    "LLM_MODEL": "qwen3.6-35b-a3b",
    "PP_EYE_B_HOST": "https://api.openai.com/v1",
    "PP_EYE_B_API_KEY": "eye-b-key-not-a-real-secret",
    "PP_EYE_B_MODEL": "gpt-5.6-luna",
}


def test_without_new_keys_eye_a_is_unchanged() -> None:
    """不填 `PP_EYE_A_*` 時，眼睛 A 逐欄位等於拆分前。"""
    a, _ = eyes.eyes_from_env(dict(LEGACY_ENV))
    assert a.name == "qwen"
    assert a.host == LEGACY_ENV["LLM_BINDING_HOST"]
    assert a.api_key == LEGACY_ENV["LLM_BINDING_API_KEY"]
    assert a.model == LEGACY_ENV["LLM_MODEL"]
    assert a.family == "qwen"
    assert a.provider == ""


def test_cache_filename_is_unchanged(tmp_path: Path) -> None:
    """轉錄快取的檔名不能變 —— 變了就是既有快取全部 miss、重新付一次錢。

    這裡不是比對字串，是**真的放一個舊檔名的快取進去，看它撈不撈得到**。
    比對字串的測試會跟著實作一起改，撈不撈得到不會。
    """
    a, _ = eyes.eyes_from_env(dict(LEGACY_ENV))
    sha = "0123456789abcdef"
    legacy_name = f"{sha}.qwen.qwen3.6-35b-a3b.json"
    (tmp_path / legacy_name).write_text(
        '{"model": "qwen3.6-35b-a3b", "html": "<table></table>", "raw": "", "finish": "stop"}',
        encoding="utf-8")
    assert eyes._cached(tmp_path, a, sha) is not None, "舊快取撈不到了 —— 檔名規則被改動"


def test_new_keys_override() -> None:
    """填了就要生效，而且三個欄位各自獨立 —— 只換模型不換位址是合法的用法
    （本機那台同時服務多個模型時就會這樣）。"""
    env = dict(LEGACY_ENV) | {"PP_EYE_A_MODEL": "qwen/qwen3-vl-235b-a22b-instruct"}
    a, _ = eyes.eyes_from_env(env)
    assert a.model == "qwen/qwen3-vl-235b-a22b-instruct"
    assert a.host == LEGACY_ENV["LLM_BINDING_HOST"], "只換模型不該連位址一起換"

    env = dict(LEGACY_ENV) | {
        "PP_EYE_A_HOST": "https://openrouter.ai/api/v1",
        "PP_EYE_A_API_KEY": "or-key-not-a-real-secret",
        "PP_EYE_A_MODEL": "qwen/qwen3-vl-32b-instruct",
    }
    a, _ = eyes.eyes_from_env(env)
    assert (a.host, a.api_key, a.model) == (
        "https://openrouter.ai/api/v1", "or-key-not-a-real-secret", "qwen/qwen3-vl-32b-instruct")


def test_empty_new_key_falls_back_instead_of_blanking() -> None:
    """空字串要當成「沒設」，不是「設成空的」。

    `.env` 裡留一行 `PP_EYE_A_MODEL=` 是很常見的寫法（先佔位、之後再填）。
    若把空字串當成有效值，眼睛 A 會拿著空的 model 去打 API —— 那會失敗，
    但失敗訊息會指向 API 而不是設定檔，找起來很久。
    """
    env = dict(LEGACY_ENV) | {"PP_EYE_A_MODEL": "", "PP_EYE_A_HOST": ""}
    a, _ = eyes.eyes_from_env(env)
    assert a.model == LEGACY_ENV["LLM_MODEL"]
    assert a.host == LEGACY_ENV["LLM_BINDING_HOST"]


def test_family_guard_still_fires_after_the_split() -> None:
    """拆分不能把守門拆掉。眼睛 A 換成 openai 家族時仍要擋下來。"""
    env = dict(LEGACY_ENV) | {"PP_EYE_A_MODEL": "gpt-4o"}
    try:
        eyes.eyes_from_env(env)
    except RuntimeError as e:
        assert "家族" in str(e)
    else:
        raise AssertionError("兩隻眼睛同屬 openai 家族卻沒有被擋下")


def test_split_lets_extraction_model_change_without_touching_the_eye() -> None:
    """這條就是拆分要防的那顆地雷。

    抽取換成 DeepSeek（`judge.py` 實測：不吃 image_url，純文字）時，
    眼睛 A 必須**還是本機那顆看得見圖的模型**。
    """
    env = dict(LEGACY_ENV) | {
        "LLM_BINDING_HOST": "https://api.deepseek.com",
        "LLM_BINDING_API_KEY": "deepseek-key-not-a-real-secret",
        "LLM_MODEL": "deepseek-v4-flash",
        "PP_EYE_A_HOST": "http://100.71.26.77:8080/v1",
        "PP_EYE_A_API_KEY": "local-key-not-a-real-secret",
        "PP_EYE_A_MODEL": "qwen3.6-35b-a3b",
    }
    a, _ = eyes.eyes_from_env(env)
    assert a.model == "qwen3.6-35b-a3b", "抽取換了模型，眼睛 A 跟著被換掉了"
    assert a.family == "qwen"
