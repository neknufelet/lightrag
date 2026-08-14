r"""Zotero 標籤對帳 —— **每一條都對應 2026-08-14 真的踩過的坑。**

那天的實況：238 筆 `_Raged` 裡 70 筆掛在子筆記上、10 筆標著「不在庫」其實在庫、
外掛與手打的大小寫分岔，而收拾的時候用 `DELETE /tags` 又誤刪了 163 筆。
這支測試守的就是「同樣的事不要再發生一次」。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))

from _scripts import load  # noqa: E402

zsync = load("zotero_sync", "zotero-sync.py")


def _item(key: str, title: str, tags: list[str] | None = None,
          parent: str | None = None) -> dict:
    data = {"key": key, "title": title, "itemType": "journalArticle",
            "tags": [{"tag": t} for t in (tags or [])]}
    if parent:
        data["parentItem"] = parent
    return {"key": key, "version": 1, "data": data}


# ── 比對 ──────────────────────────────────────────────────────────────────

def test_the_year_prefix_on_a_filename_is_not_a_word_of_the_title() -> None:
    """檔名前面的 `2025 - ` 與書章的 `01405_` 是檔名才有的，不是標題的詞。

    留著它們，同年的兩篇論文會因為都有 `2025` 而互相加分。
    """
    assert "2025" not in zsync.kb_words("2025 - Recent advancements.pdf")
    assert "01405" not in zsync.kb_words("01405_5.5 The influence of path lengths.pdf")


def test_a_truncated_filename_still_matches_its_paper() -> None:
    """入庫時檔名被截斷，最後一個字是半個 —— 比對不能因此失手。

    這是真實檔名（2026-08-14 取自 dker），結尾 `theoretical and` 就是被切的地方。
    """
    full = ("Hybrid method for numerical simulation of room acoustics with "
            "auralization: part 1 - theoretical and numerical aspects")
    stored = ("2007 - Hybrid method for numerical simulation of room acoustics "
              "with auralization part 1 - theoretical and.pdf")
    assert zsync.overlap(zsync.significant_words(full),
                         zsync.kb_words(stored)) >= zsync.MIN_OVERLAP


def test_leading_articles_and_prepositions_do_not_break_a_match() -> None:
    """`A Review of FEM **for** Room Acoustics` ↔ `Review of FEM **in** …`。

    字元前綴比對會從第一個字就失手（多一個 `A `），所以才改成比詞。
    """
    assert zsync.overlap(
        zsync.significant_words("A Review of Finite Element Methods for Room Acoustics"),
        zsync.significant_words("Review of Finite Element Methods in Room Acoustics"),
    ) >= zsync.MIN_OVERLAP


def test_three_papers_sharing_an_opening_are_kept_apart() -> None:
    """**這條是本檔的理由。** 前綴比對 25 字時，這三篇被配成同一篇。

    它們開頭一模一樣、講的是三個不同的東西。配錯的後果是「標籤說進去了，
    其實那是另一篇」—— 而且不會有任何訊號。
    """
    index = [(zsync.significant_words(t), t) for t in (
        "Low-frequency broadband absorbers based on coupling micro-perforated panels",
        "Low-frequency broadband acoustic absorption characteristics of honeycomb cores",
        "Low-frequency broadband acoustic metamaterial absorber based on coiled channels",
    )]
    got = zsync.best_match(
        "Low-frequency broadband absorber with porous material-coupled cavity", index)
    assert got is None, got


def test_a_tie_is_refused_rather_than_guessed() -> None:
    """兩個一樣好的候選 → 回 None。猜一個等於製造假事實。"""
    index = [(zsync.significant_words(t), t) for t in (
        "Broadband impedance modulation via non-local acoustic metamaterials",
        "Broadband impedance modulation via non-local acoustic metamaterials",
    )]
    assert zsync.best_match(
        "Broadband impedance modulation via non-local acoustic metamaterials",
        index) is None


def test_a_title_too_short_to_be_distinctive_is_refused() -> None:
    """兩三個字的標題會偶然命中，寧可漏掉也不要配錯。"""
    index = [(zsync.significant_words("Sound Absorption Structures: From Porous Media"),
              "x")]
    assert zsync.best_match("Sound", index) is None


# ── 筆記 ──────────────────────────────────────────────────────────────────

def test_the_sources_section_is_read_but_links_are_not() -> None:
    """`## Links` 是概念連結，掃進去會把「提到過」算成「深讀過」。"""
    body = ("# n\n## Sources\n- `Hybrid method for numerical simulation of room "
            "acoustics`\n## Links\n- [[Acoustic Diffusion Equation (DE)]]\n")
    found = " ".join(zsync.note_candidates("Tenenbaum 2007 - Hybrid method", body))
    assert "Hybrid method for numerical simulation" in found
    assert "Acoustic Diffusion Equation" not in found


def test_a_concept_named_note_still_offers_its_own_name() -> None:
    """`NIRO Composite Cost Function (Petrolli).md` 這種命名沒有「作者 年份 -」，
    但它一樣是深讀一篇論文寫出來的 —— 用檔名格式篩會少算 12 篇（實測）。"""
    assert zsync.note_candidates("NIRO Composite Cost Function (Petrolli)", "") == [
        "NIRO Composite Cost Function (Petrolli)"]


# ── 改寫規則 ──────────────────────────────────────────────────────────────

def test_other_tags_of_the_user_are_never_touched() -> None:
    """寫入是整欄覆蓋，忘了保留就會把使用者其他標籤清光。"""
    change = zsync._rewrite(_item("K", "t", ["/unread", "Absorption", "_toRaged"]),
                            {zsync.IN_KB}, "x")
    assert {t["tag"] for t in change.tags} == {"/unread", "Absorption", zsync.IN_KB}


def test_tags_are_written_as_manual_not_automatic() -> None:
    """type=1（自動）會被 Zotero 的「刪除本館所有自動標籤」一次清光，
    而且同名的 type 0 與 type 1 在 Zotero 眼中是**兩個不同的標籤**。
    省略 `type` 欄位就是 0。"""
    change = zsync._rewrite(_item("K", "t", []), {zsync.IN_KB}, "x")
    assert all("type" not in tag for tag in change.tags), change.tags


def test_an_item_already_correct_produces_no_change() -> None:
    """已經對的不要重寫 —— 每一次寫入都會推進 version 並觸發一次同步。"""
    assert zsync._rewrite(_item("K", "t", [zsync.IN_KB]), {zsync.IN_KB}, "x") is None


# ── 整體計畫 ──────────────────────────────────────────────────────────────

KB = ["2019 - Broadband ultra-thin acoustic metasurface absorber.pdf"]
IN = _item("A", "Broadband ultra-thin acoustic metasurface absorber")
OUT = _item("B", "Something entirely unrelated to acoustics whatsoever here")


def test_a_document_in_the_knowledge_base_gets_the_tag() -> None:
    (change,) = zsync.plan_changes([IN], [], KB, {}, prune=False)
    assert change.now == (zsync.IN_KB,)


def test_a_child_item_is_stripped_of_status_tags() -> None:
    """**血淚 4。** 2026-08-14 有 70 筆掛在筆記與附件上。

    掛在筆記上畫面看起來一樣（子項目也顯示圓點），但篩選、匯出、統計全部會錯。
    """
    child = _item("C", "總結 - 某篇", [zsync.IN_KB], parent="A")
    changes = zsync.plan_changes([IN], [child], KB, {}, prune=False)
    stripped = [c for c in changes if c.key == "C"]
    assert stripped and stripped[0].now == ()


def test_a_retired_tag_is_removed_even_without_prune() -> None:
    """`_toRaged`／`_NOT_IN_KB`／大寫 `_RAGED` 一律清掉 —— 它們不是狀態，
    留著就是讓同一件事有兩個名字（大小寫分岔正是這樣來的）。"""
    item = _item("A", IN["data"]["title"], ["_toRaged", "_NOT_IN_KB", "_RAGED"])
    (change,) = zsync.plan_changes([item], [], KB, {}, prune=False)
    assert set(change.now) == {zsync.IN_KB}


def test_by_default_evidence_that_vanished_does_not_remove_a_tag() -> None:
    """**血淚 6。** 比對失敗、筆記改名、WebDAV 掉線都會製造假的「沒有」。

    預設只補不刪：少標一個，使用者看得出來；把手標的判掉，使用者不會發現。
    """
    item = _item("B", OUT["data"]["title"], [zsync.IN_KB, zsync.DEEP_READ])
    assert zsync.plan_changes([item], [], KB, {}, prune=False) == []


def test_prune_is_what_actually_removes_it() -> None:
    """要移除得明講 —— 這條是上一條的控制組，證明不是「永遠刪不掉」。"""
    item = _item("B", OUT["data"]["title"], [zsync.IN_KB, zsync.DEEP_READ])
    (change,) = zsync.plan_changes([item], [], KB, {}, prune=True)
    assert change.now == ()


def test_a_note_marks_its_paper_as_deeply_read() -> None:
    notes = {"Zhu 2019 - Broadband ultra-thin acoustic metasurface absorber": ""}
    (change,) = zsync.plan_changes([IN], [], [], notes, prune=False)
    assert change.now == (zsync.DEEP_READ,)


def test_the_two_tags_are_independent_not_exclusive() -> None:
    """一篇可以同時「在 LightRAG 裡」和「深讀寫成筆記」——那是兩件事。

    2026-08-14 實測 70 筆同時有兩個。做成互斥會逼人在兩個真話裡二選一。
    """
    notes = {"Zhu 2019 - Broadband ultra-thin acoustic metasurface absorber": ""}
    (change,) = zsync.plan_changes([IN], [], KB, notes, prune=False)
    assert set(change.now) == {zsync.IN_KB, zsync.DEEP_READ}


# ── 防線 ──────────────────────────────────────────────────────────────────

def test_the_module_never_calls_the_tag_delete_endpoint() -> None:
    """**最重要的一條。** `DELETE /tags?tag=X` 不分大小寫：刪 `_RAGED` 會把
    `_Raged` 一起帶走。2026-08-14 因此誤刪 163 筆。

    移除標籤只能逐筆改寫該項目的 tags 陣列，所以這個端點在本檔應該
    **完全不存在**（只出現在說明為什麼不用它的註解裡）。
    """
    source = (ROOT / "scripts" / "zotero-sync.py").read_text(encoding="utf-8")
    code = "\n".join(line for line in source.splitlines()
                     if not line.lstrip().startswith("#"))
    body = code.split('"""', 2)[-1]                   # 去掉模組 docstring
    assert "/tags?" not in body and '"DELETE"' not in body


@pytest.mark.parametrize("name", ["ZOTERO_API_KEY", "OBSIDIAN_DAV"])
def test_a_missing_secret_stops_instead_of_running_half_way(
        name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """秘密沒設就停 —— 半套跑起來會寫出一份「什麼都不在庫」的計畫。"""
    monkeypatch.delenv(name, raising=False)
    with pytest.raises(SystemExit):
        zsync._secret(name)


# ── 外掛記下的檔名 ────────────────────────────────────────────────────────

def _with_extra(extra: str) -> dict:
    item = _item("A", "完全對不上的標題", [])
    item["data"]["extra"] = extra
    return item


def test_the_plugin_recorded_filename_is_read_out_of_extra() -> None:
    """外掛把送出去的檔名寫進「其他」欄位，那是唯一一條精確連結。"""
    got = zsync.recorded_filename(_with_extra(
        "Citations: 9 (Crossref)\nlightrag: 2022 - An Equation for the Bulk Modulus.pdf"))
    assert got == "2022 - An Equation for the Bulk Modulus.pdf"


def test_no_such_line_is_not_an_error() -> None:
    """只有 84/1083 筆有這條 —— 沒有是常態，不是異常。"""
    assert zsync.recorded_filename(_with_extra("Citations: 9 (Crossref)")) is None
    assert zsync.recorded_filename(_item("A", "t", [])) is None


def test_an_exact_filename_beats_a_title_that_would_never_match() -> None:
    """標題完全對不上也沒關係 —— 有精確連結就用精確連結。"""
    docs = ["2022 - An Equation for the Bulk Modulus.pdf"]
    (change,) = zsync.plan_changes(
        [_with_extra("lightrag: 2022 - An Equation for the Bulk Modulus.pdf")],
        [], docs, {}, prune=False)
    assert change.now == (zsync.IN_KB,)


def test_a_stale_recorded_filename_falls_back_to_matching() -> None:
    """**這條最重要。** 檔案改過名、重新解析過，那條記錄就過期了。

    過期的記錄不該推翻實況 —— 對不上要退回比對，不是直接判「不在庫」。
    """
    item = _item("A", "Broadband ultra-thin acoustic metasurface absorber", [])
    item["data"]["extra"] = "lightrag: 這個檔名已經不存在了.pdf"
    (change,) = zsync.plan_changes([item], [], KB, {}, prune=False)
    assert change.now == (zsync.IN_KB,)


# ── 短檔名與撞檔 ──────────────────────────────────────────────────────────

def test_a_two_word_chapter_title_does_not_swallow_a_long_paper() -> None:
    """**2026-08-14 實測的誤判。** 涵蓋率的分母是短的一方，所以
    `M Room Acoustics`（兩個字）會被任何含 room 與 acoustics 的長標題 100% 涵蓋。

    共同詞門檻擋的就是這個 —— 書章名短，湊不到 4 個共同詞。
    """
    index = [(zsync.kb_words("M Room Acoustics.pdf"), "chapter"),
             (zsync.kb_words("E Scattering of Sound.pdf"), "chapter2")]
    assert zsync.best_match(
        "A Geometrical Acoustics Approach Linking Surface Scattering and "
        "Reverberation in Room Acoustics", index) is None


def test_two_papers_cannot_both_claim_the_same_stored_file() -> None:
    """**血淚：Loudspeaker Part 1／Part 2。** 庫裡只有 Part 2，兩篇卻都配上去。

    一份檔案最多屬於一筆文獻；搶同一份而分不出高下時，兩邊都不給。
    """
    docs = ["1986 - LoudspeakerMeasurements and Their Relationship to "
            "Listener Preferences Part 2.pdf"]
    both = [_item("A", "LoudspeakerMeasurements and Their Relationship to "
                       "Listener Preferences: Part 1"),
            _item("B", "LoudspeakerMeasurements and Their Relationship to "
                       "Listener Preferences: Part 2")]
    got = zsync.documents_in_kb(both, docs)
    assert got == {"B"}, got


def test_the_exact_link_wins_over_a_merely_similar_title() -> None:
    """外掛記下的檔名是精確的，不該被一個「看起來也很像」的標題搶走。"""
    docs = ["2021 - Broadband low-frequency sound absorbing metastructures "
            "based on impedance matching.pdf"]
    similar = _item("A", "Broadband low-frequency sound absorbing "
                         "metastructures composed of impedance layers")
    exact = _item("B", "毫不相干的標題")
    exact["data"]["extra"] = f"lightrag: {docs[0]}"
    assert zsync.documents_in_kb([similar, exact], docs) == {"B"}


def test_an_exact_title_beats_a_longer_one_that_merely_contains_it() -> None:
    """**涵蓋率分不出的那一種。** 短標題被兩份 100% 涵蓋，其中一份是它本人。

    只看涵蓋率會並列、於是兩個都不要（那篇因此被標成「不在庫」）。
    交集比聯集分得出來：4/4 對 4/12。
    """
    index = [(zsync.kb_words("2014 - Acoustic coherent perfect absorbers.pdf"), "exact"),
             (zsync.kb_words("2023 - Ultra-broadband symmetrical acoustic coherent "
                             "perfect absorbers designed by the causality principle.pdf"),
              "longer")]
    assert zsync.best_match("Acoustic coherent perfect absorbers", index) == "exact"


def test_part_two_wins_the_file_that_says_part_two() -> None:
    """庫裡只有 Part 2。Part 1 也很像，但 Part 2 才是精確的那個。"""
    docs = ["1986 - LoudspeakerMeasurements and Their Relationship to "
            "Listener Preferences Part 2.pdf"]
    both = [_item("A", "LoudspeakerMeasurements and Their Relationship to "
                       "Listener Preferences: Part 1"),
            _item("B", "LoudspeakerMeasurements and Their Relationship to "
                       "Listener Preferences: Part 2")]
    assert zsync.documents_in_kb(both, docs) == {"B"}


def test_a_stale_lightrag_line_does_not_mask_a_working_one() -> None:
    """**2026-08-14 實測。** 一筆文獻的「其他」欄位有兩行 `lightrag:`：

        lightrag: n.d. - Perception of room modes ….pdf   ← 外掛早期寫的，檔案已不存在
        lightrag: 2023 - Perception-of-room-modes_CH1.pdf  ← 拆成九章之後補的

    只讀第一行的話，過期的那行把有效的擋住，整部論文被判成不在庫。
    """
    item = _item("A", "毫不相干的標題", [])
    item["data"]["extra"] = ("lightrag: 已經不存在的舊檔名.pdf\n"
                             "lightrag: 2023 - Perception-of-room-modes_CH1.pdf")
    assert zsync.recorded_filenames(item) == [
        "已經不存在的舊檔名.pdf", "2023 - Perception-of-room-modes_CH1.pdf"]
    got = zsync.documents_in_kb([item], ["2023 - Perception-of-room-modes_CH1.pdf"])
    assert got == {"A"}
