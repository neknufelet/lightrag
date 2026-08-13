r"""走圖譜卻沒帶關鍵詞 → 擋下來，**不要安靜地變成不確定**。

PO 要的是「外部 agent 查詢時吐回去的 context 是確定的」。2026-08-13 走 `:9700`
實測（同一題各三次、比對回傳位元組的 sha256）：

```
mode      不帶關鍵詞     帶關鍵詞
naive     三次相同       三次相同
mix       **三次不同**   三次相同
local     **三次不同**   三次相同
global    **三次不同**   三次相同
```

原因 `kbapi.py` 裡早就寫著：走圖譜會先用後端 LLM 把問題變成關鍵詞，那一步沒有
快取也不確定。`lightrag-search` 的說明第一行也叫人自己帶 ——
**但說明不是執行者**，在此之前沒有任何東西擋著。

⚠ 這條守的是一個**安靜失敗**：忘了帶不會報錯，只是每次拿到不同段落。
沒有測試的話，重構時它會無聲消失而沒有人發現。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# `kbapi` 一 import 就讀 `.env`，而 **coder 刻意沒有 .env**（現役那份只在 dker）。
# 直接 import 會在收集階段就爆掉，改成 skip 又等於這條守衛永遠沒被測到 ——
# 而 pre-commit 跑在 coder 上，那正是最需要它跑的地方。
# 所以把環境先擋掉再載入。⚠ 擋的是 `.env` 的讀取，**不是被測的判準**。
import mineru_common  # noqa: E402
import pp.paths  # noqa: E402

_real_load_env, _real_root = mineru_common.load_env, pp.paths.configured_data_root
mineru_common.load_env = lambda *_a, **_k: {"WORKSPACE": "test_ws"}
pp.paths.configured_data_root = lambda *_a, **_k: ROOT
try:
    _spec = importlib.util.spec_from_file_location("kbapi", ROOT / "scripts" / "kbapi.py")
    assert _spec and _spec.loader
    kbapi = importlib.util.module_from_spec(_spec)
    sys.modules["kbapi"] = kbapi
    _spec.loader.exec_module(kbapi)
finally:
    mineru_common.load_env, pp.paths.configured_data_root = _real_load_env, _real_root

GRAPH_MODES = ("mix", "local", "global")


@pytest.mark.parametrize("mode", GRAPH_MODES)
def test_graph_mode_without_keywords_is_blocked(mode: str) -> None:
    """**本檔的理由。** 三種走圖譜的模式，沒帶關鍵詞一律擋。"""
    assert kbapi.needs_keywords(mode, [], [], "0")


def test_naive_never_needs_keywords() -> None:
    """`naive` 不走圖譜，本來就確定 —— 擋它只會擋掉一條好路。"""
    assert not kbapi.needs_keywords("naive", [], [], "0")


@pytest.mark.parametrize("hl,ll", [(["a"], []), ([], ["b"]), (["a"], ["b"])])
def test_one_side_of_keywords_is_enough(hl: list[str], ll: list[str]) -> None:
    """有一邊就放行。兩邊都要求會逼人硬湊，**硬湊的關鍵詞比沒有更糟**。"""
    assert not kbapi.needs_keywords("mix", hl, ll, "0")


@pytest.mark.parametrize("allow", ["1", "true", "TRUE", "yes"])
def test_the_escape_hatch_works(allow: str) -> None:
    """逃生門要真的打得開 —— 擋下的東西沒有辦法明確要求的話，
    遲早有人繞過整個這一層。"""
    assert not kbapi.needs_keywords("mix", [], [], allow)


@pytest.mark.parametrize("allow", ["0", "", "no", "false", "maybe"])
def test_the_escape_hatch_is_not_opened_by_accident(allow: str) -> None:
    """**控制組。** 隨便一個值都能打開的逃生門等於沒有守衛。"""
    assert kbapi.needs_keywords("mix", [], [], allow)


def test_empty_strings_count_as_not_supplied() -> None:
    """`hl_keywords=` 這種要算「沒帶」。

    送空陣列下去，LightRAG 會當成「關鍵詞就是空的」而不是「請你自己抽」，
    於是圖譜那一段等於沒查 —— **而且不報錯**。那比不帶更糟。
    （`_kw()` 會把空字串濾成空 list，這裡驗的是收到空 list 之後的判定。）
    """
    assert kbapi.needs_keywords("mix", [], [], "0")
