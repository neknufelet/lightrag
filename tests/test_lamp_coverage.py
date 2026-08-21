"""每一盞燈都要有「按下去會叫」的測試鈕。

**為什麼需要這支。** 近 30 天有 17 個 commit 修的是同一個病：一盞監控燈說了
假話，而它說的假話是**綠**，所以沒有人發現。前面十七次**每次只修一盞燈**
（`7d4a878` 金絲雀弄丟比對函式、`24d4283` A-22 全部假紅燈、`4fa4f69` A-38
永遠說「沒跑」、`d9c5373` 金絲雀守著 0 份卻天天說通過…）。

這支修的是**類別**：

    一盞燈被寫出來 → 沒有人證明過它會紅 → 它壞掉時預設變綠
    ⇒ 「從來沒證明過」與「好好的」在畫面上長得一模一樣

⇒ 加一盞新燈卻沒附「證明它會紅」的測試，這裡會**當場擋下 commit**。

⚠ **記號不等於證明。** `@pytest.mark.proves_red` 只表示「有人宣稱證明過」，
宣稱是假的仍然要靠 review。但「連宣稱都沒有」從此擋得住，而那正是十七次裡
每一次的起點。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RATCHET = ROOT / "tests" / "lamp-unproven.json"

_spec = importlib.util.spec_from_file_location("lamps", ROOT / "scripts" / "lamps.py")
assert _spec and _spec.loader
lamps = importlib.util.module_from_spec(_spec)
# ⚠ 要先進 sys.modules 再 exec —— `@dataclass` 會回頭查自己的模組，
# 少這行會 AttributeError: 'NoneType' object has no attribute '__dict__'。
sys.modules["lamps"] = lamps
_spec.loader.exec_module(lamps)


def _ratchet() -> list[str]:
    return list(json.loads(RATCHET.read_text(encoding="utf-8"))["lamps"])


def test_a_new_lamp_must_arrive_with_a_way_to_prove_it_goes_red() -> None:
    """**本檔最重要的一條。** 新加的燈沒有測試鈕就擋下來。

    這條紅的時候不是「測試壞了」，是「你加了一盞沒有人證明得了的燈」。
    處置二選一：寫一條真的把它逼紅的測試並標 `@pytest.mark.proves_red("<編號>")`，
    或者說明為什麼證明不了、把它加進 `tests/lamp-unproven.json`
    —— 但後者要連同 `_measured_on` 一起改，而且清單長度**不得增加**（見下一條）。
    """
    unaccounted = sorted({lamp.lamp_id for lamp in lamps.unproven_lamps()} - set(_ratchet()))
    assert not unaccounted, (
        "這幾盞燈沒有人證明過它會紅，也不在待辦清單裡：\n  "
        + "\n  ".join(unaccounted)
        + f"\n\n跑 `./scripts/lamps.py --unproven` 看全部。判準見 {RATCHET.name} 的 _rule。")


def test_the_number_of_proven_lamps_only_ever_goes_up() -> None:
    """棘輪。**守的是「已證明的數量」，不是「待證明清單的長度」。**

    ⚠ 第一版守的是長度，而那量錯了東西：一盞燈改名 → 死條目被
    `test_the_todo_list_has_no_ghosts` 逼著刪掉 → 清單變短，
    但**沒有任何一盞燈因此變得有人守**。母體壞掉時數字會往好看的方向跑，
    同 `49ff127`（`ledger.py summary` 那 151 個「通過」其實是幽靈文件的）。
    """
    recorded = int(json.loads(RATCHET.read_text(encoding="utf-8"))["proven"])
    now = lamps.proven_count()
    assert now >= recorded, (
        f"有人守的燈從 {recorded} 盞掉到 {now} 盞 —— 這個數字只能往上。\n"
        f"（證明被刪掉了？還是那盞燈改名了、標記懸空了？"
        f"跑 `./scripts/lamps.py` 看現況。）")


def test_the_registry_does_not_quietly_lose_lamps() -> None:
    """**名冊自己會說謊，所以要有兩種數法。**

    2026-08-21 這條寫出來當天就抓到真的：`compat-check.py` 有 34 個
    `self.check(…)` 呼叫點，而名冊只抽出 27 條 —— 差的 7 條說明用了 f-string，
    第一版的抽取要求說明必須是字串常數，於是 `A-21`／`A-10`／`A-11`／`A-13`／
    `A-14`／`A-16`／`A-20` **從名冊上無聲消失**，而「待證明」清單看起來少了
    7 盞，那看起來像進步。

    ⇒ 同一件事要有兩種數法，數不一樣就出聲。
    """
    problems = lamps.registry_self_check()
    assert not problems, "名冊漏數了：\n  " + "\n  ".join(problems)


def test_the_todo_list_has_no_ghosts() -> None:
    """清單裡不得有已經不存在的燈。

    死條目會讓數字看起來在進步：燈被刪掉了，待辦也少一筆，但**沒有任何一盞
    燈因此變得有人守**。這與 `ledger.py summary` 在母體脫節時自我停用
    （commit `49ff127`：那 151 個「通過」是幽靈文件的）是同一個形狀。
    """
    real = {lamp.lamp_id for lamp in lamps.all_lamps()}
    ghosts = sorted(set(_ratchet()) - real)
    assert not ghosts, f"待辦清單裡有已經不存在的燈：{ghosts}"


def test_the_registry_reads_all_four_families_from_source() -> None:
    """名冊必須**自動**長出來 —— 手寫的名冊本身就是下一盞會說假話的燈。

    ⚠ 「死人開關」是 2026-08-21 補的第四族，而且它是 P0：排程死掉、結果檔不見、
    結果檔壞掉時**唯一會出聲的就是它**，它壞掉的話其餘 51 盞全部白搭。
    在此之前它不在名冊的任何一個來源裡。
    """
    families = {lamp.family for lamp in lamps.all_lamps()}
    assert families == {"每日檢查", "契約斷言", "體檢表閘門", "死人開關"}, families
    assert "meta:stale" in {lamp.lamp_id for lamp in lamps.all_lamps()}, \
        "過期的綠燈比紅燈危險 —— 那一盞一定要在名冊上"
    ids = [lamp.lamp_id for lamp in lamps.all_lamps()]
    assert len(ids) == len(set(ids)), "名冊裡有重複的編號"
    assert "daily:canary" in ids and "gate:pp.preflight" in ids
    assert any(i.startswith("contract:A-") for i in ids), "契約斷言沒有被撈出來"
