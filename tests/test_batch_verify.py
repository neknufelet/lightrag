"""一批的契約驗證：跑一次全庫，不是逐份跑 N 次。

2026-08-10 實測：86 份一批，抽取做完之後的尾巴逐份跑 `compat-check`，
**約 20 秒／份、總共約 28 分鐘**，而且每次都打一輪 Postgres。整批 66 分鐘裡
有四成花在這裡。那 N 次問的是同一個母體，一次就答得完。

`intake-reconcile.py` 先前踩過同一個形狀並改成「跑一次全庫」，所以解析
`compat-check --json` 的那段邏輯收進 `intake.py` 由兩邊共用 ——
**同一件事兩份實作是本專案踩過五次的形狀。**
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from intake import hard_failing_documents  # noqa: E402


def _row(check_id: str, level: str, what: str, ok: bool | None) -> dict:
    return {"id": check_id, "level": level, "what": what, "ok": ok, "detail": "", "data": {}}


def test_a_hard_failure_is_attributed_to_the_document_it_names() -> None:
    """逐份檢查的 `what` 以檔名開頭，靠它把紅燈歸到那一份。"""
    payload = json.dumps([
        _row("A-14", "hard", "甲.pdf：layout.json 頁序未位移", False),
        _row("A-16", "hard", "乙.pdf：沒有未知的項目型別", True),
    ])
    bad, fatal = hard_failing_documents(payload, {"甲.pdf", "乙.pdf"})
    assert bad == {"甲.pdf"}
    assert fatal == []


def test_a_hard_failure_with_no_owner_is_reported_separately() -> None:
    """**整庫層級的紅燈不能算在任何一份頭上。**

    A-19（pipeline 閒置）、A-26（母體一致）那種講的是整個系統，把它算成某一份
    文件的問題會讓那一份被誤殺 —— 而那正是 2026-08-10 一批 89 份誤殺 84 份的
    成因。呼叫端看到 `fatal` 非空就該停下來，而不是繼續判每一份。
    """
    payload = json.dumps([
        _row("A-19", "hard", "pipeline 目前 idle", False),
        _row("A-14", "hard", "甲.pdf：layout.json 頁序未位移", False),
    ])
    bad, fatal = hard_failing_documents(payload, {"甲.pdf"})
    assert bad == {"甲.pdf"}
    assert len(fatal) == 1 and "A-19" in fatal[0]


def test_soft_failures_never_block() -> None:
    """**控制組。** soft 的定義就是「值得知道但不該擋」。

    2026-08-08 踩過：A-32 第一次在這條路上回 soft 失敗，整批放行當場被自己的
    紅燈擋死。沒有這一條的話，「所有非 ok 都算失敗」也會通過上面兩支。
    """
    payload = json.dumps([
        _row("A-33", "soft", "甲.pdf：圖譜裡沒有確定該刪的位置標記節點", False),
        _row("A-25", "soft", "chunk_top_k 仍然控制回傳的片段數", False),
    ])
    bad, fatal = hard_failing_documents(payload, {"甲.pdf"})
    assert bad == set()
    assert fatal == []


def test_a_document_not_in_the_batch_is_ignored_but_still_has_an_owner() -> None:
    """歸屬要比對**全部**文件，不是只比對這一批。

    2026-08-10 實測踩過：比對母體只給了「待處置的那幾筆」，於是別份文件的
    A-14 被算成無主的整庫紅燈，把整支工具擋下來。
    """
    payload = json.dumps([
        _row("A-14", "hard", "丙.pdf：layout.json 頁序未位移", False),
    ])
    bad, fatal = hard_failing_documents(payload, {"甲.pdf", "乙.pdf", "丙.pdf"})
    assert bad == {"丙.pdf"}
    assert fatal == [], "有主的紅燈被當成整庫層級了"
