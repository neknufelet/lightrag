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


def _stack_dir() -> Path:
    """這台機器的 stack 目錄，跟受測程式走同一條解析路徑。

    ⚠ **不要寫死。** 這裡本來寫死 `/opt/stacks/lightrag`，2026-08-19 改名之後那個
    目錄不存在了，於是下面那條 skipif **在 dker 上也成立** —— 唯一真正守著
    「stack 那份與 repo 一致」的測試從此靜靜跳過，而跳過看起來跟通過一樣。
    """
    return _module().default_stack_dir()


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


@pytest.mark.skipif(not _stack_dir().is_dir(),
                    reason="沒有 stack 目錄（coder 上就是這樣）⇒ 驗不了")
def test_stack_matches_repo() -> None:
    """真正的守衛：dker 上跑時，stack 那份必須與 repo 一致。"""
    mod = _module()
    assert mod.cmd_verify(_args(mod, _stack_dir())) == 0, (
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

    依據是 compose.yaml:132 的掛載，不是猜的。多列一個服務就是為它製造一條永遠
    紅的假警報；少列一個，它跑舊碼時沒有人會知道。
    """
    mod = _module()
    assert mod._mounted_code_for("kbapi"), "kbapi 掛了 scripts/，必須被檢查"
    for service in ("lightrag", "postgres", "infinity"):
        assert mod._mounted_code_for(service) == (), service


def test_import_closure_is_narrower_than_the_whole_scripts_dir() -> None:
    """要看的是**服務真的會載入的檔**，不是整個 `scripts/`。

    **為什麼**：拿整個 scripts/ 當基準的話，改一支 kbapi 根本不 import 的腳本
    （compat-check、deploy-stack…）也會把它判成跑舊碼。每天都紅、而且每次都不必
    理，正是訓練人無視紅燈的形狀。
    """
    mod = _module()
    closure = mod._mounted_code_for("kbapi")
    assert "scripts/kbapi.py" in closure, "自己一定要在裡面"
    assert "scripts/mineru_common.py" in closure, "它 import 的本地模組要跟進去"
    assert "scripts/compat-check.py" not in closure, (
        "kbapi 不 import compat-check —— 跟進去就會製造假紅燈")
    assert "scripts/deploy-stack.py" not in closure


def test_import_closure_follows_packages_and_stops_at_third_party() -> None:
    """跟到 `scripts/` 底下的模組就停，不追標準庫與第三方。

    追下去會把整個 site-packages 拖進來，而那些東西變動也不是靠重啟服務解決的。
    """
    mod = _module()
    closure = mod._local_import_closure("scripts/intake.py")
    assert "scripts/pp/paths.py" in closure, "套件內的模組要跟得到"
    assert not [p for p in closure if not p.startswith("scripts/")], closure


def test_every_long_running_unit_has_a_registered_entry_point() -> None:
    """常駐服務一定要登記進入點，否則它跑舊碼沒有人會知道。

    這條守的是「新增一個常駐服務卻忘了登記」——那種漏會安靜地少檢查一個服務，
    而 freshness 仍然全綠。
    """
    mod = _module()
    missing = [u for u in mod._long_running_units()
               if u not in mod.SYSTEMD_ENTRY_POINTS]
    assert not missing, f"這些常駐單元沒登記進入點：{missing}"


def test_dry_run_output_is_parsed_into_stale_containers() -> None:
    """`compose up -d --dry-run` 的輸出解析：只有 Recreate／Create 算漂移。

    **為什麼判準是問 compose 而不是自己算雜湊**（走過兩個錯的版本）：

    1. 「容器啟動時間 vs compose.yaml 最後 commit」——時間戳只是代理指標，
       四台答錯兩台，其中一個是**漏報**。
    2. 「比對 config-hash 標籤與 `compose config --hash`」——看起來精確，但
       `config --hash` **不把 env_file 的內容算進去**，而 `up` 會。2026-08-08
       實測：四個服務裡只有 lightrag 有 `env_file: .env`，也只有它誤報。

    ⇒ 自己重算一份「應該是什麼」永遠會跟真正的決策者漂移。
    """
    mod = _module()
    sample = (
        " Container lightrag-infinity Running \n"
        " Container lightrag-acoustics_v2 Recreate \n"
        " Container lightrag-acoustics_v2 Recreated \n"
        " Container kbapi-acoustics_v2 Running \n"
        " Container new-thing Create \n"
    )

    class _P:
        returncode, stdout, stderr = 0, sample, ""

    original = mod._run
    mod._run = lambda *a, **k: _P()
    try:
        got = mod._containers_needing_recreate(Path("/nonexistent"))
    finally:
        mod._run = original
    assert got == ["lightrag-acoustics_v2", "new-thing"], got


def test_recreated_and_starting_lines_do_not_count_as_drift() -> None:
    """`Recreated`／`Starting` 是同一次動作的後續回報，不是另一台要動。

    漏掉這個區分會讓一台漂移的容器被數成三台，而數字錯了就沒有人會相信這份報告。
    """
    mod = _module()
    sample = (
        " Container lightrag-postgres Recreated \n"
        " Container 3f9ef5ffe58f_lightrag-postgres Starting \n"
        " Container 3f9ef5ffe58f_lightrag-postgres Started \n"
    )

    class _P:
        returncode, stdout, stderr = 0, sample, ""

    original = mod._run
    mod._run = lambda *a, **k: _P()
    try:
        assert mod._containers_needing_recreate(Path("/nonexistent")) == []
    finally:
        mod._run = original


def test_last_commit_epoch_reads_real_history() -> None:
    """對真的 repo 問「compose.yaml 最後何時被改」，要拿得到數字。

    這條同時守住「路徑名寫錯」——寫錯的路徑會回 None，而 None 在 freshness 裡
    是紅燈而不是靜默跳過。
    """
    mod = _module()
    assert mod._last_commit_epoch(("compose.yaml",)) is not None
    assert mod._last_commit_epoch(("this-path-does-not-exist",)) is None


def test_only_long_running_units_are_checked() -> None:
    """`Type=oneshot` 的單元不必檢查新鮮度 —— 它們每次執行都重新讀檔。

    只有常駐（`Type=simple`）的會把程式碼留在記憶體裡。清單從單元檔推導而不是
    寫死，所以新增一個常駐服務時會自動被涵蓋。

    **為什麼需要這支**：第一版 freshness 只看 compose 容器，而審核台 :9710 是
    systemd service（刻意不在 compose 裡）。2026-08-08 實測它跑著 7 小時前的
    intake.py，**完全在檢查範圍之外**。
    """
    mod = _module()
    units = mod._long_running_units()
    assert "lightrag-intake.service" in units, "審核台是常駐服務，必須被檢查"
    for oneshot in ("lightrag-daily-check.service", "lightrag-cold-backup.service",
                    "lightrag-stack.service"):
        assert oneshot not in units, f"{oneshot} 是 oneshot，不該被當成會變舊的服務"


def test_unit_start_epoch_returns_none_for_a_unit_that_is_not_running() -> None:
    """問一個不存在的單元要回 None，不能丟例外也不能瞎猜一個時間。

    回 None 在 freshness 裡是紅燈（「常駐服務但沒在跑」），那是對的——
    服務掛了跟服務是舊的都要有人知道。
    """
    mod = _module()
    assert mod._unit_start_epoch("this-unit-does-not-exist-drill.service") is None


# ── stack 目錄從哪裡來 ─────────────────────────────────────────────────────
#
# 2026-08-19 workspace 從 `lightrag` 改名成 `rag_acoustic`，Dockge 的 stack 目錄
# 跟著變成 `/opt/stacks/rag_acoustic`。`.env` 有 `STACK_DIR`，`systemd-units.py`
# 讀它，**這支沒讀**——於是它去看一個不存在的目錄，報「stack 還沒部署」：
#
#     stack 還沒部署：/opt/stacks/lightrag/compose.yaml 不存在
#     修法：deploy-stack.py install --commit
#
# 而照那句去做會把 stack 裝到舊路徑，變成真的有兩份。**寫死的名字跟寫死的數字
# 是同一種病**——同日 CLAUDE.md 兩處、`deploy/` 的容器名都踩過同一個形狀。

def test_the_stack_dir_comes_from_the_env_file(tmp_path: Path) -> None:
    """`.env` 說了算 —— `systemd-units.py` 讀同一個鍵，兩邊不能各講各的。"""
    (tmp_path / ".env").write_text("WORKSPACE=rag_acoustic\nSTACK_DIR=/opt/stacks/somewhere\n")
    mod = _module()

    assert mod.default_stack_dir(tmp_path) == Path("/opt/stacks/somewhere")


def test_without_stack_dir_it_is_derived_from_the_workspace(tmp_path: Path) -> None:
    """沒設 `STACK_DIR` 就從 `WORKSPACE` 算 —— Dockge 的目錄名就是專案名。

    這是不寫死名字的那一半：改 workspace 時這裡自動跟上，不必記得改第二個地方。
    """
    (tmp_path / ".env").write_text("WORKSPACE=rag_acoustic\n")
    mod = _module()

    assert mod.default_stack_dir(tmp_path) == Path("/opt/stacks/rag_acoustic")


def test_no_env_file_does_not_explode(tmp_path: Path) -> None:
    """coder 上刻意沒有 `.env`，而 argparse 的預設值在 import 時就要算得出來。

    丟例外的話這支在 coder 上連 `--help` 都跑不起來。
    """
    mod = _module()

    assert mod.default_stack_dir(tmp_path).parent == Path("/opt/stacks")
