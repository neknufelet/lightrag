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
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import pytest  # noqa: E402
from intake import (  # noqa: E402
    Job,
    OperationResult,
    SubprocessRunner,
    hard_failing_documents,
)


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


# ── 名單什麼時候記下來 ──────────────────────────────────────────────────────
#
# 上面四支釘的是「怎麼歸屬」，這一段釘的是「拿什麼名單去歸屬」。判準對、名單過期，
# 結果一樣錯。

def _runner(monkeypatch: pytest.MonkeyPatch, compat_json: str,
            on_compat_check: Callable[[], None]) -> SubprocessRunner:
    """真的 `SubprocessRunner`，只把兩個會碰外面的動作換掉。

    換掉 `_wait_pipeline_idle`（要打 LightRAG）與 `_run`（要跑 compat-check）。
    `verify_batch` 本身、以及它決定「何時去問名單」的那段，都是真的在跑。
    """
    runner = SubprocessRunner(Path("/nonexistent"), {})
    monkeypatch.setattr(runner, "_wait_pipeline_idle", lambda: None)

    def fake_run(command: list[str], timeout: float,
                 *, merge_stderr: bool = True) -> OperationResult:
        on_compat_check()
        assert not merge_stderr, "compat-check 的 stdout 要拿去解析，不能併 stderr"
        return OperationResult(True, compat_json, code=0)

    monkeypatch.setattr(runner, "_run", fake_run)
    return runner


def _one_job(filename: str) -> Job:
    return Job(
        job_id="j1", candidate_id="c1", source_root="/src", source_path=f"/src/{filename}",
        source_name="inbox", source_key="inbox-1", filename=filename,
        source_sha256="sha256:x", status="extracting", decision="clean", reasons=[],
        details=[], plan=None, created_at="2026-08-20T00:00:00+00:00",
        created_epoch=0.0, updated_at="2026-08-20T00:00:00+00:00",
    )


def test_a_job_created_during_the_check_is_still_attributable(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """**檢查跑到一半才進來的新檔，不准把整批判死。**

    2026-08-20 實測踩過：00:46:00 這一批進入契約驗證並記下名單，00:46:57 PO 丟了
    4 個新 PDF 進收件匣，00:49:28 整批判失敗。那 4 份當時解析到一半（`content_list.json`
    還沒寫出來）所以 A-10 紅，而它們不在 57 秒前記的名單裡 —— 於是有主的紅燈被
    當成整庫層級，`XVD6N97J` 陪葬。它其實已經 `processed` 進庫了，壞掉的只有簿記。

    名單要在**量測之後**才問，那時候新來的已經有 job 了。
    """
    late = "遲到.pdf"
    payload = json.dumps([_row("A-10", "hard", f"{late}：content_list.json 只在 critical_file", False)])
    known = {"這一批.pdf"}
    runner = _runner(monkeypatch, payload, on_compat_check=lambda: known.add(late))

    verdicts = runner.verify_batch([_one_job("這一批.pdf")], lambda: set(known))

    assert verdicts["j1"].ok, f"被別人的紅燈判死了：{verdicts['j1'].error}"


def test_a_genuinely_ownerless_hard_failure_still_stops_the_batch(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """**控制組。** 晚一點問名單不等於把整庫層級的紅燈放掉。

    A-19（pipeline 閒置）講的是整個系統，沒有任何檔名認領得了它。沒有這一條的話，
    「名單永遠當成認領得了」也會讓上面那支通過。
    """
    payload = json.dumps([_row("A-19", "hard", "pipeline 目前 idle", False)])
    runner = _runner(monkeypatch, payload, on_compat_check=lambda: None)

    verdicts = runner.verify_batch([_one_job("這一批.pdf")], lambda: {"這一批.pdf"})

    assert not verdicts["j1"].ok
    assert "A-19" in (verdicts["j1"].error or "")


# ── stdout 要能餵給 json.loads ──────────────────────────────────────────────

def test_a_parsed_command_keeps_stderr_out_of_stdout() -> None:
    """**要解析的輸出不准被 stderr 污染。**

    2026-08-30 實測踩過：`compat-check --json` 刻意把 `#scope N` 走 stderr 以
    保持 stdout 整份是 JSON，而 `_run` 預設 `stderr=STDOUT` 把它併了回去 ——
    那一行就黏在收尾的 `]` 後面，`json.loads` 回
    `Extra data: line 11206 column 2`，一批 11 份全部倒在「輸出讀不出來」，
    而契約檢查本身其實跑完了。
    """
    runner = SubprocessRunner(ROOT, {})
    script = "import sys; print('[1, 2]', end=''); sys.stderr.write('#scope 1132')"

    result = runner._run([sys.executable, "-c", script], 30.0, merge_stderr=False)

    assert json.loads(result.output) == [1, 2]
    assert result.stderr == "#scope 1132", "stderr 不能就這樣消失，它是診斷"


def test_merged_output_is_still_the_default_for_human_facing_commands() -> None:
    """**控制組。** 併流本身沒有錯，錯的是拿併過的東西去解析。

    給人看的命令（解析、放行、備份）只有一份輸出比較好讀，而失敗原因常常只在
    stderr。沒有這一條的話，「一律分流」也會通過上面那支，而那會讓 run.log 裡
    的失敗原因安靜地少一半。
    """
    runner = SubprocessRunner(ROOT, {})
    script = "import sys; print('out'); sys.stderr.write('err\\n')"

    result = runner._run([sys.executable, "-c", script], 30.0)

    assert "out" in result.output and "err" in result.output
