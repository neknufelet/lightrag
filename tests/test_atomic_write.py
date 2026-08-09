"""寫 bundle 的檔案時，中間態不可觀測。

`content_list.json` 是 LightRAG 掃描時會讀的東西，而 `Path.write_text` 是
「先清空再寫」—— 清空到寫完之間讀到的是空檔或半個檔，**而且不會有錯誤訊息**，
只會是一份內容不對的索引。

這件事跟併行無關也該做：單條寫入時窗口比較小，但不是零（斷電、OOM、掃描剛好
撞上都會踩到）。2026-08-09 查併行放行時發現這條路一直沒有保護。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from pp.apply import write_json_atomic  # noqa: E402


def _tmp_siblings(path: Path) -> list[Path]:
    """同目錄下殘留的暫存檔。留下來的話下一次的人得猜那是什麼。"""
    return [p for p in path.parent.iterdir() if p.name.startswith(".") and p.suffix == ".tmp"]


def test_writes_the_payload_and_leaves_no_temp_file(tmp_path: Path) -> None:
    target = tmp_path / "content_list.json"
    write_json_atomic(target, [{"type": "text", "text": "甲"}])
    assert json.loads(target.read_text(encoding="utf-8")) == [{"type": "text", "text": "甲"}]
    assert _tmp_siblings(target) == []


def test_overwrite_replaces_completely(tmp_path: Path) -> None:
    """新內容比舊的短時，不能留下舊檔的尾巴。

    改名的語義本來就保證這件事（整個檔換掉），但值得釘住 —— 如果哪天有人
    改回「開檔覆寫」，短內容會留下舊尾巴而且是合法 JSON 之外的垃圾。
    """
    target = tmp_path / "_manifest.json"
    write_json_atomic(target, {"critical_file": {"sha256": "x" * 64}, "extra": "很長的舊內容" * 20})
    write_json_atomic(target, {"critical_file": {"sha256": "y" * 64}})
    assert json.loads(target.read_text(encoding="utf-8")) == {"critical_file": {"sha256": "y" * 64}}
    assert _tmp_siblings(target) == []


def test_a_failed_write_leaves_the_original_intact(tmp_path: Path) -> None:
    """**這條才是這道保護的意義。**

    序列化失敗（或寫到一半掛掉）時，舊檔必須一個位元組都沒動 —— 而
    `write_text` 在同樣的情況下會留下一個已經被清空、或寫了一半的檔案。
    """
    target = tmp_path / "content_list.json"
    good = [{"type": "text", "text": "原本的內容"}]
    write_json_atomic(target, good)
    before = target.read_bytes()

    class NotSerializable:
        pass

    with pytest.raises(TypeError):
        write_json_atomic(target, [{"bad": NotSerializable()}])

    assert target.read_bytes() == before, "寫失敗卻動到了舊檔"
    assert _tmp_siblings(target) == [], "失敗之後留下暫存檔"


def test_temp_file_sits_in_the_same_directory(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """暫存檔必須跟目標**同目錄**。

    跨檔案系統的改名不是原子的（會退化成複製＋刪除，窗口又回來了），而同目錄是
    唯一能保證同檔案系統的做法。寫進 `/tmp` 再搬過去看起來一樣，實際上就退化了
    —— 而退化不會有任何訊號。

    攔改名那一步來看它到底從哪裡搬：比事後翻目錄可靠，因為成功路徑上暫存檔
    存在的時間只有一瞬間。
    """
    target = tmp_path / "sub" / "content_list.json"
    target.parent.mkdir()
    seen: list[Path] = []
    real = Path.replace

    def spy(self: Path, other: Path) -> Path:
        seen.append(self)
        return real(self, other)

    monkeypatch.setattr(Path, "replace", spy)
    write_json_atomic(target, {"a": 1})

    assert seen, "沒有走改名這條路 —— 判準本身失效了"
    assert seen[0].parent == target.parent, f"暫存檔不在目標目錄：{seen[0]}"
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}
