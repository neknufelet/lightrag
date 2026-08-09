"""截斷偵測（V1／V2）真的被呼叫了。

**這支測試守的是「有沒有接上」，不是「判準對不對」。** `vlm.py` 的十二道閘門
2026-08-09 查到整包零呼叫點 —— 寫好的檢查沒被呼叫等於沒寫，而且當時它在生產
路徑上。所以這裡的斷言全部走 `eyes.look()`（真正跑著的那條路），不去直接戳
`judge()`；只有最後一條例外，那條專門證明兩邊共用同一份實作、沒有第二份抄本。

**真正會靜靜通過的是哪一種截斷**（三種形狀實測，見 `t_the_silent_hole`）：
    單表截斷        `gate_table_html` 會擋，但訊息說「不是單一完整的 table」，
                    看不出成因是截斷，而且擋法是整批 sys.exit
    表後截斷        表本身完整，多出來的閒聊被切斷
    兩表、第二表截斷 ← **這個才是洞**。`extract_html` 的非貪婪正則只取第一個完整
                    的 `<table>`，半張表會被當成整張表採用，閘門看到的是結構完整
                    的表，放行。

不碰網路也不碰實機資料：所有案例都預先塞一個快取檔，走快取命中那條路。
"""
from __future__ import annotations

import importlib.util
import json
import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from pp import eyes, vlm  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "postprocess", ROOT / "scripts" / "postprocess.py")
_pp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_pp)

# 完整的一張表，以及模型常見的 ``` 圍籬收尾。dker 上 21 筆真實快取全部長這樣，
# 而且 V1／V2 實跑 21/21 通過 —— 接上這道閘門不會改變今天的任何行為。
GOOD = '<table><tr><td>Z_M</td><td>$Z_{\\mathrm{Mi}}$</td></tr></table>'
GOOD_FENCED = f"```html\n{GOOD}\n```"

# 三種截斷形狀
CUT_MID = '<table><tr><td>Z_M</td><td>$Z_{\\mathrm{Mi}}$</td></tr><tr><td>partial'
CUT_AFTER = f"{GOOD}\n\nNote: the second column of this table sh"
CUT_SECOND_TABLE = f"{GOOD}\n<table><tr><td>continued</td><td>$B_0"

# 方程式那條路的輸出：裸 LaTeX，沒有任何收尾標記。
EQ = r"Z_{\mathrm{Mi}} = \frac{1}{1 - C_0/B_0}"


def _eye() -> eyes.Eye:
    return eyes.Eye("qwen", "http://localhost:8080/v1", "k-not-a-real-secret",
                    "qwen3.6-35b-a3b", max_out=3072, max_out_key="PP_EYE_A_MAX_OUT")


def _seed(tmp_path: Path, raw: str | None, fin: str | None) -> tuple[Path, Path, Path]:
    """塞一個快取檔，回傳 (裁圖, 快取目錄, 快取檔)。

    `raw`／`fin` 傳 None 代表那個欄位**不存在**（不是空字串）—— 缺欄位與
    「有欄位但值是空的」是兩件事，測試要分得開。
    """
    png = tmp_path / "t0.png"
    png.write_bytes(b"not-a-real-png-but-hashable")
    cache = tmp_path / "cache"
    cache.mkdir()
    eye = _eye()
    f = eyes._cache_file(cache, eye, eyes._sha(png))
    body: dict[str, str] = {"model": eye.model,
                            "html": vlm.extract_html(raw if raw is not None else "")}
    if raw is not None:
        body["raw"] = raw
    if fin is not None:
        body["finish_reason"] = fin
    f.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return png, cache, f


def test_complete_transcription_still_passes(tmp_path: Path) -> None:
    """今天的行為不能變。dker 上 21 筆真實快取全部是這一類。"""
    png, cache, _ = _seed(tmp_path, GOOD, "stop")
    html, err = eyes.look(_eye(), png, cache)
    assert err is None, err
    assert html == GOOD


def test_code_fence_is_not_truncation(tmp_path: Path) -> None:
    """收尾的 ``` 圍籬不算截斷 —— 21 筆真實快取裡有 9 筆長這樣。

    這條是誤殺的防線：判準若寫成「原始輸出必須剛好以 </table> 結束」，
    那 9 筆會全部被判失敗，而它們是好的。
    """
    png, cache, _ = _seed(tmp_path, GOOD_FENCED, "stop")
    _, err = eyes.look(_eye(), png, cache)
    assert err is None, err


@pytest.mark.parametrize(("name", "raw"), [
    ("單表截斷", CUT_MID),
    ("表後截斷", CUT_AFTER),
    ("兩表、第二表截斷", CUT_SECOND_TABLE),
])
def test_truncated_transcriptions_are_rejected(tmp_path: Path, name: str, raw: str) -> None:
    """三種形狀都不得靜靜通過，而且回的是錯誤不是例外。

    不拋例外是刻意的：`look()` 的契約是「一張表看不了不該中斷整份文件」，
    被截斷的那張退回 review.md 給人看，其餘照跑。
    """
    png, cache, _ = _seed(tmp_path, raw, "length")
    html, err = eyes.look(_eye(), png, cache)
    assert err is not None, f"{name} 沒有被擋下"
    assert html == "", "被擋下時不該還回傳內容"
    assert "截斷" in err


def test_the_silent_hole_two_tables_second_one_cut(tmp_path: Path) -> None:
    """**這條是這次改動存在的理由。**

    模型把一張表拆成兩塊、寫到第二塊被切斷時，舊路徑會採用第一塊並且一路綠燈：
    `extract_html` 取到一個結構完整的 `<table>`，`gate_table_html` 放行。
    先證明那個洞是真的，再證明現在補起來了 —— 只斷言後者的話，哪天判準被改回去
    也看不出來損失了什麼。
    """
    extracted = vlm.extract_html(CUT_SECOND_TABLE)
    assert extracted == GOOD, "前提變了：extract_html 不再只取第一個完整的表"
    # 舊路徑：閘門看到的是結構完整的表，放行 —— 半張表就這樣進了索引
    assert _pp.gate_table_html(extracted, "測試") == GOOD

    # 新路徑：同一份原始輸出，擋下
    png, cache, _ = _seed(tmp_path, CUT_SECOND_TABLE, "length")
    _, err = eyes.look(_eye(), png, cache)
    assert err is not None, "半張表被當成整張表採用了"


def test_v2_fires_even_when_the_server_says_stop(tmp_path: Path) -> None:
    """V1 與 V2 抓的不是同一件事，缺一不可。

    伺服器回 `stop`（或快取沿用時根本沒有這個欄位）而輸出仍然是斷的，
    只有 V2 看得出來 —— 它看的是輸出自己的形狀。
    """
    png, cache, _ = _seed(tmp_path, CUT_MID, "stop")
    _, err = eyes.look(_eye(), png, cache)
    assert err is not None and "V2" in err and "V1" not in err, err


def test_error_message_names_the_file_to_delete_and_the_key(tmp_path: Path) -> None:
    """訊息要能直接動作。

    快取的鍵是「裁圖 sha ＋ 眼睛 ＋ 模型」，**不含 max_out** —— 所以調大額度不會
    讓壞掉的那筆自動失效。不講的話，人會調完額度、重跑、看到一模一樣的失敗。
    """
    png, cache, f = _seed(tmp_path, CUT_MID, "length")
    _, err = eyes.look(_eye(), png, cache)
    assert err is not None
    assert str(f) in err, "沒有講要刪哪個檔"
    assert "PP_EYE_A_MAX_OUT" in err, "沒有講要調哪個鍵"


def test_missing_fields_are_unverified_not_failure(
        tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """缺欄位＝驗不了，放行但要出聲。

    `_store` 一定會寫 `raw` 與 `finish_reason`（實測 dker 上 21 筆全都有），
    走到這條路代表快取檔來自沒見過的格式。當成失敗會無端重付一輪轉錄費，
    當成通過而不吭聲則讓「沒檢查」跟「檢查通過」在畫面上長得一樣（鐵則 6）。
    """
    png, cache, _ = _seed(tmp_path, None, None)
    with caplog.at_level(logging.WARNING, logger="pp.eyes"):
        _, err = eyes.look(_eye(), png, cache)
    assert err is None, "缺欄位被當成截斷了 —— 那會重付一輪轉錄費"
    assert any("驗不了" in r.message for r in caplog.records), "驗不了的時候沒有出聲"


def test_equation_output_is_not_judged_by_the_table_closing(tmp_path: Path) -> None:
    """`eq-check.py` 轉的是裸 LaTeX，V2 對它不成立。

    這條擋的是「順手把 V2 無條件掛在 look() 上」—— 那會把方程式檢查整條打死
    （每一條都判截斷），而且症狀會長得像模型壞了。
    """
    png, cache, _ = _seed(tmp_path, EQ, "stop")
    _, err = eyes.look(_eye(), png, cache, closing=None)
    assert err is None, err

    # 同一份輸出，用表格的判準就會被誤殺 —— 證明這個參數真的有在作用，
    # 不是預設值剛好通過
    _, err_table = eyes.look(_eye(), png, cache)
    assert err_table is not None, "closing 參數沒有生效"


def test_judge_and_look_share_one_implementation() -> None:
    """十二道的 V1／V2 與 look() 走同一份實作，沒有第二份抄本。

    抄一份過去就是再造一條「寫了沒人叫」的路 —— 那正是這個坑本身的成因，
    修的時候不能重蹈。
    """
    v = vlm.judge(vlm.extract_html(CUT_MID), CUT_MID, "length",
                  gt_text="impedance orifice partition chamber resonator absorber "
                          "perforated cavity network",
                  neighbour_gts=[], caption="")
    shared = vlm.truncation_failures(CUT_MID, "length")
    assert shared, "測資本身沒有觸發 V1／V2"
    assert set(shared) <= set(v.failed), f"judge() 沒有用共用的那份：{v.failed}"
