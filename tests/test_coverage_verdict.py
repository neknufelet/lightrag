r"""漏字檢查的紅綠判準：**證人讀不全時是「驗不了」，不是「超標」**。

**為什麼有這一檔。** `coverage-check.py` 拿 `pdftotext` 讀出來的文字層當對照源
（下稱「證人」），數抽取結果少了哪些詞。當證人自己讀不全時，它讀出來的詞數會
**少於**抽取結果 —— 這時候「漏了多少」在數學上量不出來，而舊版把它算成超標。

2026-08-21 全庫實測（dker，172 份）：

    11 份超標裡有 5 份是「抽取詞數 > 證人詞數」
    其中 3 份早在 2026-08-10 就被逐份查證為假訊號，結論寫在 verified-findings.json
        J8TSCA5Z   證人   397 vs 抽取 2500   （直式浮水印被讀成逐字母碎片）
        C8ST3USB   證人 2,359 vs 抽取 2,748  （1979 掃描件沒有詞邊界）
        HKP7TKW6   證人   903 vs 抽取 1,429  （數學字型讀成重複字母）

**一份一份記結論沒有盡頭。** 那三次查證每次都花掉人工，而判準一直沒動，於是
第四份、第五份出現時又要再查一次。這一檔守的是**類別**：
`ledger.py` 檔頭寫著「把 unverifiable 併進 fail，等於宣稱壞了」——
漏字檢查之前對這一族做的正是那件事。

⚠ **只驗「壞的會紅」等於沒驗。** 所以下面三條是一組，缺一不可：

    1. 真的掉字            → 紅   （弄壞看它叫）
    2. 同一份降到門檻以下  → 綠   （改回來看它閉嘴）
    3. 證人讀不全          → 不紅 （相似但不該觸發）

⚠ **逼的是發訊號的那一支。** 測試呼叫 `main()` 走 `--json` 分支 —— 那正是
`daily-check.sh` 用的路徑。只驗 `report()` 證明不了它，因為 `--json` 會在
呼叫 `report()` 之前就 return（2026-08-21 的 `#scope` 就是這樣漏掉的）。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

_spec = importlib.util.spec_from_file_location(
    "coverage_check_verdict", ROOT / "scripts" / "coverage-check.py")
assert _spec and _spec.loader
cc = importlib.util.module_from_spec(_spec)
sys.modules["coverage_check_verdict"] = cc
_spec.loader.exec_module(cc)

THRESHOLD = cc.DEFAULT_THRESHOLD


def _doc(name: str, pdf_words: int, content_words: int, missing: int) -> dict:
    """一份文件的量測結果，欄位與 `check_doc()` 的回傳一致。

    `rate` 照 `check_doc` 的定義算（漏掉的 ÷ 證人詞數），不另外給值 ——
    測試自己算一個數字塞進去的話，判準改了測試也不會知道。
    """
    out = {
        "doc": name, "pdf": f"/tmp/{name}.pdf", "items": 10,
        "pdf_words": pdf_words, "content_words": content_words,
        "missing": missing, "rate": missing / pdf_words, "top": [("slit", missing)],
    }
    if cc.witness_short(pdf_words, content_words):
        out["unverifiable"] = True
        out["unverifiable_reason"] = "測試夾具：證人讀不全"
    return out


# 真的掉字：證人讀得比抽取多（比對成立），而且缺了 20%。
REALLY_LOST = _doc("真的掉字", pdf_words=1000, content_words=800, missing=200)
# 同一份修好之後：只差 2%，在 5% 門檻以下。
FIXED = _doc("修好了", pdf_words=1000, content_words=995, missing=20)
# 證人讀不全：J8TSCA5Z 2026-08-21 的真實數字。
SHORT_WITNESS = _doc("證人讀不全", pdf_words=397, content_words=2500, missing=314)


def _run_json(results: list[dict], monkeypatch: pytest.MonkeyPatch) -> int:
    """跑真正的入口，走 `--json` 那條路（＝ daily-check 走的那條），回離開碼。"""
    monkeypatch.setattr(cc, "load_env", lambda *a, **k: {"WORKSPACE": "t"})
    monkeypatch.setattr(cc, "scan", lambda *a, **k: results)
    monkeypatch.setattr(sys, "argv", ["coverage-check.py", "--json"])
    return cc.main()


@pytest.mark.proves_red("daily:coverage")
def test_a_document_that_really_lost_words_makes_the_check_exit_red(
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    """**測試鈕：按下去要叫。** 真的掉了 20% 的詞 → `--json` 回 1。

    這條紅的時候不是「測試壞了」，是漏字檢查**不會叫了** —— 從此任何一份
    真的掉字的文件都會安靜地通過每日體檢。
    """
    assert _run_json([REALLY_LOST], monkeypatch) == 1, (
        "掉了 20% 的詞卻沒有亮紅燈")
    # 分母也要在：rc=0 沒分母會被 check-levels.py 拒發綠燈，但 rc=1 時
    # 少了分母一樣看不出「比對了幾份」。
    assert "#scope 1" in capsys.readouterr().err


def test_the_same_document_below_the_threshold_goes_green(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """**改回來要變綠。** 只驗「壞的會紅」等於沒驗 —— 一支永遠回 1 的檢查
    也能通過上面那條。"""
    assert _run_json([FIXED], monkeypatch) == 0


def test_a_short_witness_does_not_turn_it_red(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """**相似但不該觸發。** 漏詞率 79%（比上面那條的 20% 高得多），但證人
    只讀出 397 詞而抽取有 2500 —— 比對不成立，這是驗不了不是超標。"""
    assert _run_json([SHORT_WITNESS], monkeypatch) == 0, (
        "證人讀不全被算成超標了 —— 這正是 2026-08-10 那三次人工查證的成因")


def test_the_unverifiable_document_is_still_reported_not_dropped(
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    """**不紅不等於消失**（藍桶 2：不得無聲消失）。

    它照樣要出現在輸出裡、照樣帶著自己的數字與理由，只是不算紅燈。
    「驗不了」與「通過」在畫面上長得一樣的話，這個改動就只是換一種說謊法。
    """
    _run_json([SHORT_WITNESS], monkeypatch)
    out = capsys.readouterr().out
    assert "證人讀不全" in out and "unverifiable" in out


def test_both_code_paths_agree_on_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """人看的報表與 `--json` 必須給同一個答案。

    ⚠ 改之前**它們已經漂開了**：解析失敗（`error` 但不是 unverifiable）在
    `report()` 裡算紅、在 `--json` 裡不算 —— 而 daily-check 走的正是 `--json`。
    於是「有一份解析失敗」在每日體檢上是綠的，在人工跑的報表上是紅的，
    中間沒有任何錯誤訊息。
    """
    broken = {"doc": "解析失敗", "error": "缺少 content_list.json（解析未完成或失敗）"}
    for case in ([REALLY_LOST], [FIXED], [SHORT_WITNESS], [broken],
                 [SHORT_WITNESS, FIXED], [SHORT_WITNESS, REALLY_LOST]):
        via_json = _run_json(case, monkeypatch)
        via_report = cc.report(list(case), THRESHOLD, False)
        assert via_json == via_report, (
            f"兩條路對同一批資料給出不同答案：--json={via_json}、"
            f"report={via_report}，資料={[r['doc'] for r in case]}")


def test_a_witness_exactly_as_large_as_the_extraction_is_still_measured() -> None:
    """邊界：證人與抽取一樣大時**比對仍然成立**，不該被判驗不了。

    判準是「證人比抽取**少**」。寫成 `>=` 的話，`HMJ6IDEG_04`（今天實測
    469 vs 469）會從此永遠不受檢。
    """
    assert cc.witness_short(469, 469) is False, "一樣大被判成證人讀不全"
    assert cc.witness_short(397, 2500) is True, "397 vs 2500 沒有被判成證人讀不全"
    tie = _doc("一樣大", pdf_words=469, content_words=469, missing=30)
    assert not tie.get("unverifiable")
    assert cc.is_red(tie, THRESHOLD) is True
