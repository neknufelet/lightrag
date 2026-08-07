"""坑清單的自測 —— 也是 `tests/pits.json` 的消費者。

**這支守的是「規則不准只寫在紙上」這件事。** 沒有消費者的知識資產等於沒寫：
`tests/symbol2-results.json` 進了版控、全 repo grep 不到任何程式讀它，
就是活生生的反例（本清單的 PIT-156）。所以這份清單一落地就要有人讀它。

它做兩件事，缺一不可：

1. **把 backlog 數字印出來。** `pytest -q` 會吃掉 `print`，所以走 `warnings.warn`
   —— warnings summary 在 `-q` 之下仍然會顯示。數字攤在檯面上，它才會往下走。
2. **擋住 backlog 變大。** 想加一條新規則，就得同時交出「哪支探針會在沒人問的
   時候喊它」；交不出來，這裡就會紅。這條規則連本清單自己都適用。

基準放在 `pits.json` 的 `_backlog_baseline`，比照 `tests/canary-baseline.json`
的成功模式：基準進版控，所以每一次變動都會出現在 `git diff` 裡，
而且要在 commit 訊息說明每個數字為什麼變。
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RECORD = ROOT / "tests" / "pits.json"

# 四級守衛品質。順序即強度，**「只在有人主動跑時才響」不算有守衛** ——
# 鐵則 6：探針要在沒人問的時候會響；只有指定目標才跑的檢查，
# 防的是「你已經懷疑的事」，而你已經懷疑的事不需要探針。
GUARD_LEVELS = ("會擋下", "會印警告", "只在有人主動跑時才響", "沒有人")
PRIORITIES = ("high", "medium", "low")


def _load() -> dict[str, object]:
    return json.loads(RECORD.read_text(encoding="utf-8"))


def _rows(data: dict[str, object]) -> list[dict[str, object]]:
    rows = data["pits"]
    assert isinstance(rows, list)
    return rows


def _backlog(rows: list[dict[str, object]]) -> list[str]:
    """探針施工清單：沒有人守、而且重踩代價高的。"""
    return [str(r["id"]) for r in rows
            if r.get("guard_quality") == "沒有人" and r.get("priority") == "high"]


def test_record_is_readable_and_not_empty() -> None:
    """讀得動、而且不是空的。

    空清單會讓下面每一條斷言都「通過」—— 那正是「乾淨的 0」那一族：
    看起來像沒有 backlog，實際是母體不見了。
    """
    data = _load()
    rows = _rows(data)
    assert rows, "pits.json 是空的：backlog 會算成 0，看起來像沒有待補的探針"
    for key in ("_why", "_rule", "_key", "_consumer", "_generated", "_backlog_baseline"):
        assert data.get(key), f"pits.json 缺少 {key} —— 資產要能自己說明為什麼存在、誰讀它"


def test_every_pit_carries_its_audit() -> None:
    """每一條都要回答「誰會發現」與「多重要」。

    缺這兩欄的條目算不進 backlog，於是**漏掉的坑會讓 backlog 看起來比實際小**。
    """
    for row in _rows(_load()):
        pid = row.get("id")
        for key in ("id", "title", "kind", "anchors", "failure_mode",
                    "survives_teardown", "guard_quality", "priority"):
            assert row.get(key), f"{pid} 缺少 {key}"
        assert row["guard_quality"] in GUARD_LEVELS, \
            f"{pid} 的 guard_quality 是 {row['guard_quality']!r}，不在四級之內"
        assert row["priority"] in PRIORITIES, \
            f"{pid} 的 priority 是 {row['priority']!r}，不在 {PRIORITIES}"


def test_baseline_ids_match_the_data() -> None:
    """基準記的 id 集合必須等於算出來的。

    只記數字不記 id 的話，一條被補上、另一條新長出來時總數不變，
    而**換掉的是哪一條沒有人會知道** —— 數字沒有錯誤訊息，它只是靜靜地錯著。
    """
    data = _load()
    baseline = data["_backlog_baseline"]
    assert isinstance(baseline, dict)
    recorded = list(baseline["ids"])  # type: ignore[index]
    actual = _backlog(_rows(data))
    assert sorted(recorded) == sorted(actual), (
        "基準記的 backlog id 與清單算出來的不一致。\n"
        f"  基準有、實際沒有：{sorted(set(recorded) - set(actual))}\n"
        f"  實際有、基準沒有：{sorted(set(actual) - set(recorded))}\n"
        "補了探針就更新基準，並在 commit 訊息說明每一條為什麼變。"
    )
    assert baseline["no_guard_high"] == len(recorded), \
        "_backlog_baseline 的數字與 ids 長度對不上"


def test_backlog_does_not_grow() -> None:
    """**這是最重要的一條：清單只准變短。**

    想往鐵則區加一條新規則，就必須同時交出「哪支探針會在沒人問的時候喊它」。
    交不出來 backlog 就變大，這裡就紅。這條規則連本清單自己都適用 ——
    否則制度會膨脹成一份沒人讀得完的清單，而讀不完的清單等於全部失效。
    """
    data = _load()
    baseline = data["_backlog_baseline"]
    assert isinstance(baseline, dict)
    actual = _backlog(_rows(data))
    assert len(actual) <= int(baseline["no_guard_high"]), (  # type: ignore[call-overload]
        f"沒有人守的 high 優先坑從 {baseline['no_guard_high']} 增加到 {len(actual)} 條。"  # type: ignore[index]
        "\n新增的規則要嘛附一支會響的探針，要嘛先進觀察區 —— 不得直接進清單。"
    )


def test_backlog_number_is_visible() -> None:
    """把數字攤在檯面上。

    `pytest -q` 會吃掉 stdout，所以走 warnings —— warnings summary 在 `-q`
    之下仍然顯示。這一條永遠不會失敗，它的產出就是那行字。
    （同一個手法用在 PIT-012「落點元探針」上：印出「N 條鐵則的落點是靠人記得」，
    數字被看見才會下降。）
    """
    data = _load()
    rows = _rows(data)
    actual = _backlog(rows)
    doc_only = list(data["_backlog_baseline"]["doc_only_subset"])  # type: ignore[index]
    warnings.warn(
        f"坑清單：{len(rows)} 條；沒有人守且 high 優先 {len(actual)} 條"
        f"（其中 {len(doc_only)} 條的錨點不在程式或測試裡，拆文件層前必須先有落點）："
        + ", ".join(actual),
        stacklevel=1,
    )


def test_broken_record_is_a_hard_failure(tmp_path: Path) -> None:
    """壞掉的清單不得被當成「沒有 backlog」。

    與 `pp/findings.py` 刻意相反：那支是**附加**機制，讀不到要降級放行、
    不能擋住檢查；這支是**閘門**，讀不到就是紅的 —— 因為它守的正是
    「規則有沒有落點」，而讀不到清單時的正確結論是「不知道」，不是「都有落點」。
    """
    bad = tmp_path / "壞掉.json"
    bad.write_text("{ this is not json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        json.loads(bad.read_text(encoding="utf-8"))
