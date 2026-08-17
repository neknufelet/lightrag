"""`ledger.py summary` 在體檢表與現役母體脫節時必須拒絕輸出總表。

**這支守的是一個實測到的假訊號**（2026-08-07，dker）：語料在 08-04 整批換掉，
舊的 20 張體檢表還留著，於是總表印出「264 格：通過 151、fail 9、未設定 104」——
那 151 個通過與 9 個 fail **全部屬於已經不在庫裡的文件**，而現役 18 份幾乎一格都沒驗。

**比印出 0 更危險**：0 會讓人懷疑，漂亮的高通過數不會。所以處置是拒絕輸出，
不是「照印但加個註記」——人只看最後那一行總計。

三態，不是兩態：
    現役母體讀不到（0 份） → 「驗不了」，不是「所有體檢表都是幽靈」
    有幽靈體檢表           → 停用，印出處置
    乾淨                   → 正常輸出總表
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "ledger.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ledger_summary_gate", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _args(root: Path) -> argparse.Namespace:
    return argparse.Namespace(root=root, workspace="test", problems=False)


def _make(root: Path, *, ledger_docs: tuple[str, ...], live_pdfs: tuple[str, ...],
          gates: dict[str, str] | None = None) -> None:
    """建出「體檢表目錄」與「現役 PDF」兩邊，讓兩者可以刻意對不上。"""
    ledger = root / "records" / "ledger"
    ledger.mkdir(parents=True, exist_ok=True)
    parsed = root / "work" / "parsed"
    parsed.mkdir(parents=True, exist_ok=True)
    for name in ledger_docs:
        rec = {"doc": name, "pdf_sha256": None,
               "gates": {g: {"state": s} for g, s in (gates or {"parse.coverage": "pass"}).items()}}
        (ledger / f"{name}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    for name in live_pdfs:
        (parsed / name).write_bytes(b"%PDF-1.4\n")


def test_ghost_ledgers_disable_the_summary(tmp_path: Path,
                                          capsys: pytest.CaptureFixture[str]) -> None:
    """有幽靈體檢表 ⇒ rc=3，而且**不得印出總計那一行**。

    這是本測試的核心：如果只是「印了警告又照樣印總表」，那個漂亮的通過數還在，
    問題完全沒解決。
    """
    module = _module()
    _make(tmp_path, ledger_docs=("已經換掉的舊語料.pdf", "現役的.pdf"),
          live_pdfs=("現役的.pdf",))

    rc = module.cmd_summary(_args(tmp_path))
    out = capsys.readouterr().out

    assert rc == 3, "脫節時必須回非零，否則排程與人都會以為這張表可信"
    assert "已停用" in out
    assert "已經換掉的舊語料" in out, "要指名道姓說哪幾張是幽靈"
    assert "archive-ledger.py" in out, "要給可以直接跑的處置"
    assert "共 " not in out and "格：通過" not in out, \
        "拒絕輸出時不得印出總計 —— 那一行就是假訊號本身"


def test_ghost_severity_is_measured_not_hardcoded(tmp_path: Path,
                                                 capsys: pytest.CaptureFixture[str]) -> None:
    """停用訊息裡的「幽靈佔幾格」必須是**數出來的**，不得寫死。

    這一條守的是 2026-08-17 抓到的病：原訊息寫死「幽靈貢獻了總表上絕大部分的
    『通過』」，dker 實測卻是 1218 格通過裡幽靈只佔 2 格 —— 錯了六百倍。
    **而它讀起來像結論，所以沒有人會想到要去數。** 這比沒寫更糟。

    兩組刻意給不同的格數，輸出必須跟著變；只要有一組對不上，就是又寫死了。
    """
    module = _module()
    _make(tmp_path, ledger_docs=("幽靈.pdf", "現役的.pdf"), live_pdfs=("現役的.pdf",),
          gates={"parse.coverage": "pass", "pp.tables": "fail"})

    rc = module.cmd_summary(_args(tmp_path))
    out = capsys.readouterr().out

    assert rc == 3
    assert "2 格判定" in out, "幽靈只帶 2 格判定，訊息就得說 2"
    assert "pass 1" in out and "fail 1" in out, "三態分佈要照實拆開，不能只給總數"
    assert "絕大部分" not in out, "嚴重程度是量測值，不得用形容詞寫死"


def test_ghost_cell_count_tracks_the_actual_data(tmp_path: Path,
                                                 capsys: pytest.CaptureFixture[str]) -> None:
    """同一段程式碼、不同的資料 ⇒ 不同的格數。這是「有量」的唯一證據。"""
    module = _module()
    _make(tmp_path, ledger_docs=("幽靈甲.pdf", "幽靈乙.pdf", "現役的.pdf"),
          live_pdfs=("現役的.pdf",),
          gates={"parse.coverage": "pass", "pp.tables": "pass", "extract.grounding": "pass"})

    rc = module.cmd_summary(_args(tmp_path))
    out = capsys.readouterr().out

    assert rc == 3
    assert "6 格判定" in out, "兩張幽靈 × 三格 = 6，寫死成上一條的 2 就會在這裡爆"
    assert "pass 6" in out


def test_missing_population_is_unverifiable_not_all_ghosts(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """現役母體讀不到 ⇒ 「驗不了」，不能把全部體檢表當成幽靈。

    在 coder 上跑就是這個情況（沒有 /data）。把它講成「文件都不見了」
    等於把「不知道」講成「知道」—— 三態存在的理由。
    """
    module = _module()
    _make(tmp_path, ledger_docs=("某份.pdf",), live_pdfs=())

    rc = module.cmd_summary(_args(tmp_path))
    out = capsys.readouterr().out

    assert rc == 3
    assert "驗不了" in out
    assert "已停用" not in out, "母體讀不到與有幽靈是兩種狀態，訊息不得混用"
    assert "某份" not in out, "母體讀不到時不得把體檢表指控成幽靈"


def test_clean_ledger_still_prints_the_summary(tmp_path: Path,
                                              capsys: pytest.CaptureFixture[str]) -> None:
    """沒有幽靈 ⇒ 照原本輸出。

    沒有這一條，「永遠拒絕」也會讓上面兩條通過 —— 那是把工具停成廢鐵，
    而且同樣不報錯。
    """
    module = _module()
    _make(tmp_path, ledger_docs=("現役的.pdf",), live_pdfs=("現役的.pdf",))

    rc = module.cmd_summary(_args(tmp_path))
    out = capsys.readouterr().out

    assert rc == 0
    assert "格：通過" in out, "乾淨時必須照印總表"
    assert "已停用" not in out


def test_fail_still_returns_one_when_clean(tmp_path: Path,
                                          capsys: pytest.CaptureFixture[str]) -> None:
    """乾淨但有 fail ⇒ 維持原本的 rc=1，停用閘門不得吃掉它。"""
    module = _module()
    _make(tmp_path, ledger_docs=("現役的.pdf",), live_pdfs=("現役的.pdf",),
          gates={"parse.coverage": "fail"})

    rc = module.cmd_summary(_args(tmp_path))
    out = capsys.readouterr().out

    assert rc == 1, "fail 的退出碼是 1，與停用的 3 必須分得開"
    assert "fail 的文件不得進下一段" in out
