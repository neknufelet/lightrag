r"""「骨架逐字相同」不等於「同一條公式」。

2026-08-13：三隻不同家族的模型獨立打槍了同一批 Tier A 組，人工複核確認
**模型是對的**：

```
A_a = P_abs / I_0     吸收面積        骨架 #={\frac{#}{#}}
κ   = ε_p / ε_v       一個比值        骨架 #={\frac{#}{#}}
```

「X 等於 Y 除以 Z」不帶任何資訊，而 `TRIVIAL` 那條正規表達式抓不到它
（它排除的是 `#=#` 那種，`\frac` 會活下來）。62 組裡 8 組是這種形狀。

⚠ **試過用尺寸型的數字切，不行。** 「結構命令 ≤1 且變數槽 ≤3」8 組全中，
但誤殺 4 組真的，其中一組是 `\nabla^2#+#^2#=N`（亥姆霍茲方程式）——
`\frac` 到處都是而 `\nabla` 很罕見，數量分不出這件事。
所以判定凍結成資料（`verdicts/eq-tier-a-audit.json`），跟來源登記同一個做法。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

_spec = importlib.util.spec_from_file_location("eq_dup", ROOT / "scripts" / "eq-dup.py")
assert _spec and _spec.loader
eqdup = importlib.util.module_from_spec(_spec)
sys.modules["eq_dup"] = eqdup
_spec.loader.exec_module(eqdup)

AUDIT = ROOT / "verdicts" / "eq-tier-a-audit.json"
# 全票判異的實例，取自 2026-08-13 的審計。
FAKE = r"#=\frac{#}{#}"
# 判同、而且**會被尺寸型規則誤殺**的實例：亥姆霍茲方程式。
REAL_BUT_SMALL = r"\nabla^2#+#^2#=N,"


def _groups(*skeletons: str) -> list[dict]:
    return [{"skeleton": s} for s in skeletons]


def test_the_frozen_audit_still_contains_the_two_anchor_cases() -> None:
    """素材沒被改掉 —— 這兩組是本檔其餘斷言的地基。"""
    data = json.loads(AUDIT.read_text(encoding="utf-8"))["groups"]
    assert data[FAKE]["verdict"] == "different", data.get(FAKE)
    assert data[REAL_BUT_SMALL]["verdict"] == "same", data.get(REAL_BUT_SMALL)


def test_a_contentless_skeleton_is_dropped() -> None:
    """`X = Y/Z` 不是證據。**這條是本檔的理由。**"""
    kept, tally = eqdup.audited(_groups(FAKE), eqdup.load_audit(AUDIT))
    assert kept == [] and tally["different"] == 1


def test_a_small_but_real_equation_survives() -> None:
    """亥姆霍茲方程式很短，但它是一條**具體**的方程式，不能跟著被殺。

    這條是上一條的控制組：只會刪不會留的規則，跟「整個 Tier A 關掉」沒有差別。
    """
    kept, _ = eqdup.audited(_groups(REAL_BUT_SMALL), eqdup.load_audit(AUDIT))
    assert [g["skeleton"] for g in kept] == [REAL_BUT_SMALL]


def test_never_audited_is_excluded_and_counted_separately() -> None:
    """沒審過的排除、而且**要分開報數**。

    安靜跳過就是這個專案七個 bug 的共同形狀。排除是對的（少報不假報），
    不報數才是 bug —— 語料一長，Tier A 會安靜地縮水。
    """
    kept, tally = eqdup.audited(_groups("從沒見過的骨架"), eqdup.load_audit(AUDIT))
    assert kept == [] and tally["unaudited"] == 1


def test_model_disagreement_is_not_treated_as_pass() -> None:
    """模型自己就分歧的留 `uncertain`，**不當成通過**。

    把「沒有共識」算成「是同一條」，就是把不知道講成知道。
    """
    data = json.loads(AUDIT.read_text(encoding="utf-8"))["groups"]
    split = [k for k, v in data.items() if v["verdict"] == "uncertain"]
    assert split, "審計檔裡一組分歧都沒有 —— 素材不對，換一份"
    kept, tally = eqdup.audited(_groups(*split), eqdup.load_audit(AUDIT))
    assert kept == [] and tally["uncertain"] == len(split)


def test_a_missing_audit_file_does_not_silently_pass_everything() -> None:
    """審計檔不見時**全部排除**，不是全部放行。"""
    kept, tally = eqdup.audited(_groups(FAKE, REAL_BUT_SMALL),
                                eqdup.load_audit(ROOT / "does-not-exist.json"))
    assert kept == [] and tally["unaudited"] == 2
