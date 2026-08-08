"""`deploy-stack.py`：repo 的 compose 與 Dockge stack 那份不得漂移。

**為什麼需要這支**：2026-08-07 決定用 Dockge 管理之後，`compose.yaml` 有兩份，
而當天那份副本是手動 `cp` 過去的、沒有任何東西守它們一致。Dockge 的 UI 可以直接
編輯 compose——改完不會有人知道 repo 那份已經不是真的了。

同一類東西兩個地方，而漂移不報錯：本專案已踩過三次（文件地圖、版本史、commit type）。

⚠ **`test_stack_matches_repo` 在沒有 stack 目錄時 skip**（coder 上就是這樣），
所以它只在 dker 上真正生效。那是三態的正確用法——「驗不了」不是「通過」。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STACK_DIR = Path("/opt/stacks/lightrag")


def _module():
    spec = importlib.util.spec_from_file_location(
        "deploy_stack", ROOT / "scripts" / "deploy-stack.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["deploy_stack"] = mod
    spec.loader.exec_module(mod)
    return mod


def _args(mod, stack_dir: Path, **kw):
    import argparse
    return argparse.Namespace(stack_dir=str(stack_dir), commit=False, **kw)


def test_identical_copy_verifies(tmp_path: Path) -> None:
    mod = _module()
    (tmp_path / "compose.yaml").write_text(
        (ROOT / "compose.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    assert mod.cmd_verify(_args(mod, tmp_path)) == 0


def test_drift_is_detected(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """差一個字就要紅 —— 這正是 Dockge UI 改過之後的樣子。"""
    mod = _module()
    (tmp_path / "compose.yaml").write_text(
        (ROOT / "compose.yaml").read_text(encoding="utf-8") + "\n# 有人在 UI 改了\n",
        encoding="utf-8")
    assert mod.cmd_verify(_args(mod, tmp_path)) == 2
    out = capsys.readouterr().out
    assert "不一致" in out
    assert "不要直接覆蓋" in out, "要提醒別把別人在 UI 的修改蓋掉"


def test_missing_stack_copy_is_not_a_pass(tmp_path: Path) -> None:
    """還沒部署 ⇒ 回非零並給修法。回 0 會讓「沒部署」看起來像「一致」。"""
    mod = _module()
    assert mod.cmd_verify(_args(mod, tmp_path)) == 2


def test_symlinked_stack_dir_is_refused(tmp_path: Path) -> None:
    """stack 目錄是 symlink ⇒ 停下來。

    Dockge UI 的刪除會沿著 symlink 刪到目標，而目標最可能是 repo ——
    那正是 2026-08-07 拆掉的那條掛載造成的事故形狀。
    """
    mod = _module()
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    with pytest.raises(mod.StackError) as e:
        mod.cmd_verify(_args(mod, link))
    assert "symlink" in str(e.value)


def test_install_without_commit_writes_nothing(tmp_path: Path) -> None:
    mod = _module()
    assert mod.cmd_install(_args(mod, tmp_path)) == 0
    assert not (tmp_path / "compose.yaml").exists(), "預設是 dry-run，不得寫檔"


@pytest.mark.skipif(not STACK_DIR.is_dir(), reason="沒有 stack 目錄（coder 上就是這樣）⇒ 驗不了")
def test_stack_matches_repo() -> None:
    """真正的守衛：dker 上跑時，stack 那份必須與 repo 一致。"""
    mod = _module()
    assert mod.cmd_verify(_args(mod, STACK_DIR)) == 0, (
        "stack 的 compose.yaml 與 repo 不一致。"
        "repo 是 SSOT——若 stack 那份是在 Dockge UI 改的，先把改動搬回 repo。")


# ── freshness：檔案放對了不代表跑著的是它 ──────────────────────────────


def test_nanosecond_timestamp_is_parsed() -> None:
    """docker 的 `StartedAt` 是奈秒精度，`fromisoformat` 只吃到微秒。

    不截掉會丟 ValueError，而那個例外看起來像「docker 壞了」而不是「多了三位
    小數」—— 探針自己壞掉卻報成被探測的東西壞掉，是最難查的一種。
    """
    mod = _module()
    epoch = mod._rfc3339_to_epoch("2026-08-08T09:15:12.123456789Z")
    assert abs(epoch - mod._rfc3339_to_epoch("2026-08-08T09:15:12.123456Z")) < 1e-6


def test_second_precision_timestamp_is_parsed() -> None:
    """沒有小數部分也要能解析 —— 不是每個 runtime 都吐奈秒。"""
    mod = _module()
    assert mod._rfc3339_to_epoch("2026-08-08T09:15:12Z") > 0


def test_only_kbapi_mounts_repo_code() -> None:
    """`scripts/` 只掛進 kbapi，其餘服務跑 baked image。

    這張表決定「哪些容器要用時間戳判斷」。多列一個服務，就會為它製造一條
    永遠紅的假警報；少列一個，它跑舊碼時沒有人會知道。
    依據是 compose.yaml:132 的掛載，不是猜的。
    """
    mod = _module()
    assert mod._mounted_code_for("kbapi") == ("scripts",)
    for service in ("lightrag", "postgres", "infinity"):
        assert mod._mounted_code_for(service) == (), service


def test_mounted_code_is_keyed_by_service_not_container() -> None:
    """用服務名當鍵，不用容器名。

    容器名含 workspace（`kbapi-acoustics_v2`），改 workspace 就會對不上；
    compose 的服務名不會變。
    """
    mod = _module()
    assert mod._mounted_code_for("kbapi-acoustics_v2") == (), \
        "傳容器名應該查不到 —— 這張表的鍵是服務名"


def test_compose_hashes_parse_service_and_digest() -> None:
    """`docker compose config --hash` 的輸出是「服務名 空白 雜湊」逐行。

    解析壞掉的話會回空 dict，而空 dict 會讓每個容器都被判成「compose 裡沒有
    這個服務」—— 一次噴四條假紅燈。
    """
    mod = _module()
    sample = "infinity d2ba48a8\nkbapi e4164711\n"

    class _P:
        returncode, stdout, stderr = 0, sample, ""

    original = mod._run
    mod._run = lambda *a, **k: _P()
    try:
        got = mod._compose_config_hashes(Path("/nonexistent"))
    finally:
        mod._run = original
    assert got == {"infinity": "d2ba48a8", "kbapi": "e4164711"}


def test_last_commit_epoch_reads_real_history() -> None:
    """對真的 repo 問「compose.yaml 最後何時被改」，要拿得到數字。

    這條同時守住「路徑名寫錯」——寫錯的路徑會回 None，而 None 在 freshness 裡
    是紅燈而不是靜默跳過。
    """
    mod = _module()
    assert mod._last_commit_epoch(("compose.yaml",)) is not None
    assert mod._last_commit_epoch(("this-path-does-not-exist",)) is None
