r"""改了 `content_list.json` 就必須重蓋 manifest 的指紋。

**2026-08-12 我親手踩了這個坑。** `scan-partial --repair` 直接寫 `content_list.json`
卻沒有更新 `_manifest.json` 的 `critical_file`（size ＋ sha256），於是：

```
LightRAG 的 is_bundle_valid() 回 False
  → 下次 /scan 認為快取壞了 → 重新解析 → 把修補整個覆蓋掉
```

實測：reindex 那 10 份之後 ∂ 探針 0 → 668 處。而 `pp/apply.py` 的檔頭第一段
**一字不差地預告了這件事** —— 我沒讀就自己另開了一條寫入路徑。

⇒ 指紋的維護只能有**一個**擁有者（`apply.py`）。任何改 `content_list.json` 的人
都要透過它，不能各自抄一份 —— 抄一份就是再造第二條會漂移的路。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from pp.apply import ApplyError, restamp_manifest  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "scan_partial", ROOT / "scripts" / "scan-partial.py")
assert _spec and _spec.loader
sp = importlib.util.module_from_spec(_spec)
sys.modules["scan_partial"] = sp
_spec.loader.exec_module(sp)

MISREAD = r"\frac { \hat { o } \mathrm { p } } { \hat { o } \mathrm { n } }"


def _bundle(tmp_path: Path, items: list[dict]) -> Path:
    """一份最小的 mineru_raw：content_list.json ＋ 指紋對得上的 _manifest.json。"""
    raw = tmp_path / "parsed" / "T.pdf.mineru_raw"
    raw.mkdir(parents=True)
    cl = raw / "content_list.json"
    cl.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    (raw / "_manifest.json").write_text(json.dumps({
        "critical_file": {
            "path": "content_list.json",
            "size": cl.stat().st_size,
            "sha256": "sha256:" + hashlib.sha256(cl.read_bytes()).hexdigest(),
        },
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return raw


def _fingerprint_matches(raw: Path) -> bool:
    cf = json.loads((raw / "_manifest.json").read_text())["critical_file"]
    cl = raw / "content_list.json"
    return (cf["size"] == cl.stat().st_size
            and cf["sha256"] == "sha256:" + hashlib.sha256(cl.read_bytes()).hexdigest())


def test_restamp_makes_the_fingerprint_match_again(tmp_path: Path) -> None:
    """改過內容之後重蓋一次，指紋就對得上了。"""
    raw = _bundle(tmp_path, [{"type": "equation", "text": MISREAD}])
    (raw / "content_list.json").write_text(
        json.dumps([{"type": "equation", "text": "改過了，比原本長很多很多很多"}],
                   ensure_ascii=False, indent=1), encoding="utf-8")
    assert not _fingerprint_matches(raw), "前提沒成立：指紋本來就該對不上"

    old, new = restamp_manifest(raw)

    assert old != new
    assert _fingerprint_matches(raw)


def test_restamp_refuses_when_the_contract_changed(tmp_path: Path) -> None:
    """`critical_file` 不是 `content_list.json` 就停下來（照抄 `apply_doc` 的判準）。

    契約變了還照蓋，等於把指紋蓋在一個不知道是什麼的檔案上。
    """
    raw = _bundle(tmp_path, [{"type": "text", "text": "x"}])
    man = json.loads((raw / "_manifest.json").read_text())
    man["critical_file"]["path"] = "middle.json"
    (raw / "_manifest.json").write_text(json.dumps(man), encoding="utf-8")

    with pytest.raises(ApplyError, match="critical_file"):
        restamp_manifest(raw)


def test_repairing_partials_leaves_the_bundle_valid(tmp_path: Path) -> None:
    """**這條是整支的理由。**

    `scan-partial --repair` 改完之後，指紋必須跟著更新 —— 否則下次掃描會重新解析，
    把修補覆蓋掉（2026-08-12 實測：0 → 668 處）。
    """
    raw = _bundle(tmp_path, [{"type": "equation", "text": MISREAD}])
    n_items, n_tokens = sp.repair_bundle(raw.parent, stamp="2026-08-13T00:00:00+08:00")
    assert (n_items, n_tokens) == (1, 2)

    assert _fingerprint_matches(raw), "改了內容卻沒重蓋指紋 —— 下次掃描會把修補洗掉"


def test_a_bundle_nothing_changed_in_is_left_alone(tmp_path: Path) -> None:
    """控制組：沒改到東西就不要碰 manifest。

    每跑一次就重寫一次的話，「這份被改過」這個資訊會被沖掉，而那是查帳的依據。
    """
    raw = _bundle(tmp_path, [{"type": "text", "text": "沒有東西要修"}])
    before = (raw / "_manifest.json").read_bytes()
    assert sp.repair_bundle(raw.parent, stamp="s") == (0, 0)
    assert (raw / "_manifest.json").read_bytes() == before
