r"""圖片別名撞名 —— **給錯的圖比給不了圖糟得多**。

2026-08-14 查文獻時被另一個 agent 發現、當天查證屬實並且範圍更大：`slug()` 把
文件名截到 48 字，全庫 **8 組共 30 份文件**產生同一個 slug。最嚴重的是章節切片：

```
2021 - Room acoustic modeling  with the TD_DG method_CH1 … _CH7   七章共用一個
2007 - Hybrid method … part 1 / part 2                            兩篇共用一個
2020 - … Absorbing Panels / … Supplementary Material              正文與附件共用一個
```

撞名之後 `/images/<別名>` 拿到哪一篇的圖沒有保證，而**它不會報錯**：
圖出得來、掛進卡片、來源是錯的。

兩道修法，缺一不可：

1. 新別名帶文件指紋（sha1 前 6 碼）→ 不再撞
2. 舊別名撞到多份就回 409 並列出是哪幾篇 → **不要挑第一個給他**
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import mineru_common  # noqa: E402
import pp.paths  # noqa: E402

# `kbapi` 一 import 就讀 `.env`，而 coder 刻意沒有。擋掉環境再載入 ——
# 擋的是 `.env` 的讀取，**不是被測的判準**（同 test_kbapi_keywords.py）。
_real = mineru_common.load_env, pp.paths.configured_data_root
mineru_common.load_env = lambda *a, **k: {"WORKSPACE": "test_ws"}
pp.paths.configured_data_root = lambda *a, **k: ROOT
try:
    from _scripts import load  # noqa: E402

    kbapi = load("kbapi", "kbapi.py")
finally:
    mineru_common.load_env, pp.paths.configured_data_root = _real

# 取自 dker 的真實檔名（2026-08-14 實查撞名的那一組）。
PART1 = ("2007 - Hybrid method for numerical simulation of room acoustics "
         "with auralization part 1 - theoretical and.pdf")
PART2 = ("2007 - Hybrid method for numerical simulation of room acoustics "
         "part 2 - validation of the computational c.pdf")


def _bundle(root: Path, doc: str, image: str) -> None:
    """做一份最小的解析成果：一張圖 ＋ 指到它的 content_list。"""
    raw = root / f"{doc}.mineru_raw"
    (raw / "images").mkdir(parents=True, exist_ok=True)
    (raw / "images" / image).write_bytes(b"\xff\xd8\xff")          # 假的 JPEG 開頭
    (raw / "content_list.json").write_text(json.dumps(
        [{"type": "image", "img_path": f"images/{image}", "page_idx": 2,
          "image_caption": ["圖說"]}]), encoding="utf-8")


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """兩份 slug 相同的文件，各有一張圖。

    ⚠ `parsed_dir()` 與 `_index()` **各自推路徑**（前者走函式、後者走模組層的
    `DATA_ROOT`），所以兩個都要換掉 —— 只換一個的話 `_index` 會去讀真的資料根，
    測試變成看那台機器有什麼。
    """
    parsed = tmp_path / "work" / "parsed"
    parsed.mkdir(parents=True)
    _bundle(parsed, PART1, "aaaa.jpg")
    _bundle(parsed, PART2, "bbbb.jpg")
    monkeypatch.setattr(kbapi, "parsed_dir", lambda _ws: parsed)
    monkeypatch.setattr(kbapi, "DATA_ROOT", tmp_path)
    kbapi._index.cache_clear()
    return parsed


def test_the_slug_really_does_collide() -> None:
    """先證明前提成立 —— 這條紅了表示 `slug()` 改過，整份測試要重寫。"""
    assert kbapi.slug(PART1) == kbapi.slug(PART2)


def test_colliding_documents_get_different_aliases(corpus: Path) -> None:
    """**本檔的理由。** slug 撞名，別名不准跟著撞。"""
    a = next(iter(kbapi._index("ws", PART1)["by_alias"]))
    b = next(iter(kbapi._index("ws", PART2)["by_alias"]))
    assert a != b, (a, b)


def test_the_alias_still_says_which_paper_it_is(corpus: Path) -> None:
    """指紋不能把可讀性吃掉 —— 別名前面仍然看得出是哪一篇。

    這條是上一條的配套：只要唯一不要可讀的話，直接用雜湊就好，
    而那正是這支當初做別名要取代的東西。
    """
    alias = next(iter(kbapi._index("ws", PART1)["by_alias"]))
    assert alias.startswith(kbapi.slug(PART1))
    assert hashlib.sha1(PART1.encode()).hexdigest()[:6] in alias  # noqa: S324


def test_a_new_alias_resolves_to_its_own_document(corpus: Path) -> None:
    """帶指紋的別名要取得**自己那一篇**的圖，不是掃描順序上的第一篇。"""
    alias1 = next(iter(kbapi._index("ws", PART1)["by_alias"]))
    alias2 = next(iter(kbapi._index("ws", PART2)["by_alias"]))
    assert kbapi.find_image("ws", alias1).name == "aaaa.jpg"
    assert kbapi.find_image("ws", alias2).name == "bbbb.jpg"


def test_an_ambiguous_old_alias_is_refused_not_guessed(corpus: Path) -> None:
    """**這條是最重要的。** 舊別名對到兩篇時要拒絕，而且說得出是哪兩篇。

    舊版一找到就回傳，於是拿到「掃描順序上第一個」—— 圖出得來、來源是錯的、
    而且沒有任何訊號。
    """
    old_alias = f"{kbapi.slug(PART1)}-p03-01.jpg"
    for doc, img in ((PART1, "aaaa.jpg"), (PART2, "bbbb.jpg")):
        (corpus / f"{doc}.mineru_raw" / "images" / old_alias).write_bytes(b"\xff\xd8\xff")
        assert (corpus / f"{doc}.mineru_raw" / "images" / img).is_file()
    with pytest.raises(kbapi.AmbiguousImage) as got:
        kbapi.find_image("ws", old_alias)
    assert len(got.value.docs) == 2


def test_a_unique_old_alias_still_works(corpus: Path) -> None:
    """**控制組。** 沒有歧義的舊引用不准被一起判死 ——
    直接把舊別名判死會讓已經寫進卡片的引用整批失效，而大多數本來就不歧義。"""
    only = f"{kbapi.slug(PART1)}-p09-09.jpg"
    (corpus / f"{PART1}.mineru_raw" / "images" / only).write_bytes(b"\xff\xd8\xff")
    assert kbapi.find_image("ws", only) is not None


def test_path_traversal_is_still_rejected(corpus: Path) -> None:
    """既有的防線不能被我改壞。"""
    assert kbapi.find_image("ws", "../../etc/passwd") is None
