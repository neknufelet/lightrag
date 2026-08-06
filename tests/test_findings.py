"""已查證紀錄的自測。

**這支守的是「不要重複查證」這件事本身。** 機制壞掉時的症狀不是報錯，是
檢查工具安靜地不再附上前例——然後某個人再查一次 K Muffler，得到跟
2026-08-03 一樣的結論。沒有訊號，只有浪費。

最重要的是「過期要說要重查」那一條：**過期的結論比沒有結論更危險**，
因為它會讓人跳過本來該做的查證。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from pp import findings  # noqa: E402

RECORD = ROOT / "tests" / "verified-findings.json"


def test_shipped_record_is_valid_and_not_empty() -> None:
    """出貨的紀錄檔要讀得動、而且不是空的。

    空的紀錄檔會讓 lookup 一律回 None —— 那正是「乾淨的 0」那一族：
    看起來像「沒有前例」，實際是母體不見了。
    """
    data = json.loads(RECORD.read_text(encoding="utf-8"))
    rows = data["findings"]
    assert rows, "verified-findings.json 是空的，lookup 會一律回 None 而看起來像沒有前例"
    for row in rows:
        for key in ("check", "metric", "doc", "verified_on", "summary", "source"):
            assert row.get(key), f"{row.get('doc')} 缺少 {key}"
        # 沒有 at_verification 就無法偵測過期，等於這筆永遠不會說「要重查」
        assert row.get("at_verification"), f"{row['doc']} 沒有 at_verification，偵測不到過期"


def test_lookup_matches_by_keyword_not_exact_name() -> None:
    """紀錄寫 `K Muffler Acoustics`，實際 file_path 帶 .pdf —— 要配得到。"""
    hit = findings.lookup("extract-check", "grounding_suspect_rate",
                          "K Muffler Acoustics.pdf")
    assert hit is not None
    assert hit.verdict == "not_hallucination"
    assert "傳遞矩陣" in hit.summary


def test_lookup_misses_are_none_not_crashes() -> None:
    """沒查證過的文件回 None，不是丟例外 —— 這個機制是附加的，不能擋住檢查。"""
    assert findings.lookup("extract-check", "grounding_suspect_rate", "Z 不存在.pdf") is None
    assert findings.lookup("別支檢查", "grounding_suspect_rate", "K Muffler Acoustics.pdf") is None
    assert findings.lookup("extract-check", "別的指標", "K Muffler Acoustics.pdf") is None


def test_current_numbers_matching_gives_the_conclusion() -> None:
    hit = findings.lookup("extract-check", "grounding_suspect_rate",
                          "L Capsules and Cabins.pdf",
                          current={"suspect": 22, "rate": 0.147})
    assert hit is not None and not hit.stale_reason
    body = "\n".join(hit.lines())
    assert "已查證 2026-08-05" in body
    assert "根因" in body and "例：" in body


def test_drifted_numbers_demand_a_recheck(capsys: pytest.CaptureFixture[str]) -> None:
    """**這是最重要的一條。**

    數字大幅變動時不得再回報原結論——那會讓人拿著 2026-08-05 的「不是幻覺」
    去解釋一個完全不同的現況，然後跳過該做的查證。
    """
    hit = findings.lookup("extract-check", "grounding_suspect_rate",
                          "L Capsules and Cabins.pdf",
                          current={"suspect": 80, "rate": 0.53})
    assert hit is not None
    assert hit.stale_reason, "數字翻了 3 倍還回報原結論"
    body = "\n".join(hit.lines())
    assert "要重查" in body
    # 過期時**不得**再印原結論與例子，否則讀者還是會被舊結論帶走
    assert "符號→概念命名" not in body
    assert "Velocity Variable" not in body


def test_missing_record_file_warns_and_degrades(tmp_path: Path,
                                                caplog: pytest.LogCaptureFixture) -> None:
    """紀錄檔不見時：檢查照跑，但要留痕。

    安靜地回 None 會讓「沒有前例」與「紀錄檔不見了」在畫面上長得一樣。
    """
    with caplog.at_level("WARNING"):
        assert findings.lookup("extract-check", "grounding_suspect_rate",
                               "K Muffler Acoustics.pdf",
                               path=tmp_path / "不存在.json") is None
    assert any("找不到已查證紀錄" in r.message for r in caplog.records)


def test_broken_record_file_warns_and_degrades(tmp_path: Path,
                                               caplog: pytest.LogCaptureFixture) -> None:
    bad = tmp_path / "壞掉.json"
    bad.write_text("{ this is not json", encoding="utf-8")
    with caplog.at_level("WARNING"):
        assert findings.lookup("extract-check", "grounding_suspect_rate",
                               "K Muffler Acoustics.pdf", path=bad) is None
    assert any("讀不了" in r.message for r in caplog.records)
