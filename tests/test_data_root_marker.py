"""記號檔的檔名只有一份定義。

`pp/paths.py` 的 `DATA_ROOT_MARKER` 是唯一的來源，但 `compose.yaml` 的 healthcheck
是一行 YAML 字串，**沒辦法 import 常數**，只能把檔名抄進去。抄過去的東西會漂 ——
改了一邊而另一邊沒改時，症狀是「健康檢查永遠紅」或更糟的「健康檢查永遠綠」，
兩種都不會有錯誤訊息。所以在這裡把兩邊釘在一起。

同一個形狀在本專案出現過好幾次（量測與清除各算一次、判準與 CLI 各寫一份），
處置一律是「共用一份」；共用不了的時候，就用測試把抄本釘住。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from pp.paths import DATA_ROOT_MARKER  # noqa: E402

COMPOSE = ROOT / "compose.yaml"


def test_compose_healthcheck_uses_the_same_marker_name() -> None:
    """compose 的 healthcheck 抄的檔名要跟 `DATA_ROOT_MARKER` 一致。"""
    text = COMPOSE.read_text(encoding="utf-8")
    assert DATA_ROOT_MARKER in text, (
        f"compose.yaml 裡找不到 {DATA_ROOT_MARKER!r} —— "
        "改了 pp/paths.py 的 DATA_ROOT_MARKER 卻沒改 compose 的 healthcheck，"
        "kbapi 會一直讀不到那個檔而永遠是 unhealthy")


def test_the_marker_is_actually_checked_not_just_mentioned() -> None:
    """光是出現在檔案裡不夠，要真的在 healthcheck 那一行被讀。

    沒有這一條的話，把檔名寫在註解裡也會讓上面那條通過 —— 而註解不會偵測任何東西。
    """
    lines = [ln for ln in COMPOSE.read_text(encoding="utf-8").splitlines()
             if DATA_ROOT_MARKER in ln and not ln.lstrip().startswith("#")]
    assert lines, f"{DATA_ROOT_MARKER} 只出現在註解裡 —— 註解偵測不了任何東西"
    assert any("read_bytes" in ln for ln in lines), (
        "記號檔沒有被真的讀取。用 read_bytes() 而不是 exists()／stat："
        "碟壞掉時只有真的開檔才會回 I/O 錯誤，stat 可能被 dentry 快取擋掉")


def test_compose_is_valid_yaml() -> None:
    """compose.yaml 至少要解析得動。

    **這條是踩出來的**：2026-08-09 把 healthcheck 寫成
    `["CMD", "python", "-c",\\n "a" \\n "b"]` —— Python 會把相鄰字串串起來，
    YAML 的 flow sequence 不會，那是語法錯誤。而 `deploy-stack.py install`
    照樣把它複製到 stack 目錄並印「已寫入」，要到有人跑 `docker compose up`
    才會爆。現在 install 自己也擋（`_assert_parses`），這條是第二道。
    """
    import yaml
    yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def test_marker_name_does_not_name_a_specific_disk() -> None:
    """名字不要綁硬碟型號或容量 —— 換碟是合法操作，寫死的那版撐不過第一次換碟。

    2026-08-09 第一版叫 `.on-1tb-ssd`，當天就改掉了。
    """
    lowered = DATA_ROOT_MARKER.lower()
    for bad in ("1tb", "ssd", "usb", "wdc", "sda", "nvme"):
        assert bad not in lowered, (
            f"記號檔名 {DATA_ROOT_MARKER!r} 提到了 {bad!r} —— "
            "那是這一顆碟的性質，不是這個檔的用途")
