"""把 dker 資料區的人工裁定拉回 coder 的 repo，好進版控。

**為什麼需要這支**：服務跑在 dker，人工裁定生在那裡；而 dker 的 repo 唯讀只
`git pull`，coder 才有提交權。中間沒有東西搬的話，裁定就躺在 dker 上永遠上不了
GitHub —— 體檢表踩過這個坑，一度 dker 318 份而 git 只有 20 份，備份只做到 6%。

**只准變多。** 這支永不刪除 repo 裡的副本：dker 上不見了可能是被歸檔、被誤刪、
或路徑打錯，而三種的處置完全不同。刪掉等於用一個猜測毀掉唯一的備份。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "pull_verdicts", ROOT / "scripts" / "pull-verdicts.py")
assert _spec is not None and _spec.loader is not None
pull_verdicts = importlib.util.module_from_spec(_spec)
sys.modules["pull_verdicts"] = pull_verdicts
_spec.loader.exec_module(pull_verdicts)

sync_records = pull_verdicts.sync_records


def _put(directory: Path, name: str, body: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(body, encoding="utf-8")


def test_a_directory_that_does_not_exist_yet_is_not_an_error() -> None:
    """遠端還沒有那個目錄 ≠ 連不上。兩者必須分得開。

    第一次還沒有人按過確認時，`records/chapter-splits/` 本來就不存在。把它報成
    錯誤的話**每次跑都會紅一次**，而天天都在的紅會讓人不再看它 —— 這個專案
    2026-08-17 才因為同一個形狀，讓真的紅燈埋在假紅裡一整天。
    """
    missing = ('rsync: [sender] change_dir "/data/lightrag/records/chapter-splits" '
               "failed: No such file or directory (2)")
    assert pull_verdicts.is_missing_remote_dir(missing)


def test_a_real_failure_is_still_an_error() -> None:
    """連不上、沒權限這些要照樣紅。全部當成「還沒有東西」就等於把警報拆掉。"""
    assert not pull_verdicts.is_missing_remote_dir("ssh: Could not resolve hostname florian-dker")
    assert not pull_verdicts.is_missing_remote_dir("rsync: [sender] failed: Permission denied (13)")


def test_new_records_are_copied_in(tmp_path: Path) -> None:
    """dker 上有、repo 沒有的，複製過去。"""
    src, dst = tmp_path / "src", tmp_path / "dst"
    _put(src, "a.pdf.json", '{"v":1}')
    dst.mkdir()

    result = sync_records(src, dst)

    assert (dst / "a.pdf.json").read_text(encoding="utf-8") == '{"v":1}'
    assert result.added == ["a.pdf.json"]


def test_changed_records_are_updated(tmp_path: Path) -> None:
    """兩邊都有但內容不一樣的，以 dker 為準覆蓋過去。

    dker 是人真的按下確認的地方 —— repo 那份只是副本。反過來以 repo 為準的話，
    今天勾的東西會被上一次的副本蓋掉。
    """
    src, dst = tmp_path / "src", tmp_path / "dst"
    _put(src, "a.pdf.json", '{"v":2}')
    _put(dst, "a.pdf.json", '{"v":1}')

    result = sync_records(src, dst)

    assert (dst / "a.pdf.json").read_text(encoding="utf-8") == '{"v":2}'
    assert result.updated == ["a.pdf.json"]


def test_untouched_records_are_not_reported_as_work(tmp_path: Path) -> None:
    """內容一樣的不算搬過。全部都報成「更新」的話，人看不出這次真的變了什麼。"""
    src, dst = tmp_path / "src", tmp_path / "dst"
    _put(src, "a.pdf.json", '{"v":1}')
    _put(dst, "a.pdf.json", '{"v":1}')

    result = sync_records(src, dst)

    assert result.added == [] and result.updated == []
    assert result.unchanged == 1


def test_a_copy_missing_upstream_is_kept_and_reported(tmp_path: Path) -> None:
    """repo 有、dker 沒有的 —— **留著**，只報出來。

    dker 上不見了可能是被歸檔、被誤刪、或路徑打錯，三種的處置完全不同。
    刪掉等於用一個猜測毀掉唯一的備份（`verdicts/README.md` 的整個前提）。
    """
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    _put(dst, "old.pdf.json", '{"v":1}')

    result = sync_records(src, dst)

    assert (dst / "old.pdf.json").is_file(), "不得刪除 repo 裡的副本"
    assert result.only_local == ["old.pdf.json"]


def test_a_missing_source_directory_is_refused_not_treated_as_empty(tmp_path: Path) -> None:
    """來源目錄不存在 ⇒ 明講，**不要當成「那邊沒有東西」**。

    當成空的話，這支會安靜地報「沒有新的」，而真正的原因是路徑打錯或沒掛上 ——
    那正是「乾淨的 0」最會騙人的地方。
    """
    dst = tmp_path / "dst"
    dst.mkdir()

    try:
        sync_records(tmp_path / "nope", dst)
    except FileNotFoundError as exc:
        assert "nope" in str(exc)
    else:
        raise AssertionError("來源不存在時必須丟例外，不得回一個空結果")
