"""確認清單的存檔與讀回。

**這個檔案守的是「人當初的決定不會被規則悄悄推翻」。** 確認清單本身很便宜
（`postprocess.py plan --json` 全母體 6.27 秒），痛的是後面那一步 —— 消音會改變
送去抽取的文字，抽完再改消音就得**重抽一次**，而抽取是整條線最貴的一步。

三條裁決（PO 2026-08-17，寫在 `docs/confirm-list-design-20260817.md`）：

    存兩份：資料區一份（實際在用）、repo 一份（備份）
    存整份清單，不是只存改了哪幾格
    每確認一份存一次

第二條是這裡最容易寫錯的：只存改動的話，規則之後一改、項目數與順序都會變，
`section:index` 這種號碼就會指到別的段落上，人的決定被搬到錯的地方去。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from pp.confirm import DECIDED_BY_HUMAN, DECIDED_BY_RULE, ConfirmItem  # noqa: E402
from pp.confirm_record import (  # noqa: E402
    FORMAT_VERSION,
    ConfirmRecord,
    SourceChangedError,
    read_record,
    record_path,
    repo_record_path,
    write_record,
)

DOC = "2019 - Compact Acoustic Rainbow Trapping.pdf"
SHA = "sha256:" + "a" * 64

ITEMS = [
    # 人勾掉的（＝不要）
    ConfirmItem(section="noise", index=41, category="頁首頁尾",
                reason="重複 5 次，像頁首頁尾，但次數不夠多、不敢確定",
                text="GRADED LOCALLY RESONANT METAMATERIALS", page=3,
                suppress=True, decided_by=DECIDED_BY_HUMAN, note="這是頁眉"),
    # 人看過、決定留著的 —— **這一列最重要，它不能消失**
    ConfirmItem(section="title", index=1, category="標題區塊",
                reason="沒看到單位、通訊作者、期刊那些封面訊號，不敢確定",
                text="Received 14 January 2019", page=0,
                suppress=False, decided_by=DECIDED_BY_HUMAN),
    # 人沒動、維持規則預設的
    ConfirmItem(section="title", index=2, category="標題區塊",
                reason="讀起來像正文，不像封面資訊，所以不敢消",
                text="We measured the absorption coefficient…", page=0,
                suppress=False),
]


def _write(tmp_path: Path) -> Path:
    return write_record(tmp_path, doc=DOC, pdf_sha256=SHA, items=ITEMS,
                        at="2026-08-18T01:20:00+08:00", rules_commit="eaabb4f")


def test_one_document_one_file_next_to_the_other_verdicts(tmp_path: Path) -> None:
    """一份文件一個檔，檔名就是文件名 —— 跟體檢表、拆章紀錄同一個作法。

    ⚠ **live 檔寫資料區，不寫 repo。** 服務跑在 dker，而 dker 的 repo 是唯讀
    只 `git pull`：直接寫進去的檔會躺在那裡永遠上不了 GitHub。體檢表踩過，
    一度 dker 318 份而 git 只有 20 份，備份只做到 6%。
    """
    assert record_path(Path("/data/lightrag"), DOC) == Path(
        "/data/lightrag/records/confirm-lists") / f"{DOC}.json"
    assert repo_record_path(Path("/repo"), DOC) == Path(
        "/repo/verdicts/records/confirm-lists") / f"{DOC}.json"

    written = _write(tmp_path)
    assert written.parent == tmp_path / "records" / "confirm-lists"
    assert written.is_file()


def test_the_whole_list_is_stored_including_what_was_left_alone(tmp_path: Path) -> None:
    """**整份清單都寫，沒勾的照樣寫進去**（PO 第二條、藍桶第 2 條）。

    只寫勾掉的那些的話，人「看過、決定留著」的那些會被當成「還沒看過」，
    下次重來又被問一次 —— 更糟的是規則一改，那幾項可能變成預設勾掉，
    **人當初決定留著的東西就被安靜地丟了**。
    """
    payload = json.loads(_write(tmp_path).read_text(encoding="utf-8"))

    assert len(payload["items"]) == len(ITEMS) == 3
    kept = [i for i in payload["items"] if not i["suppress"]]
    assert len(kept) == 2, "決定留著的兩列必須在檔案裡"


def test_it_reads_back_exactly_what_went_in(tmp_path: Path) -> None:
    """寫進去什麼就讀得回什麼 —— 一個欄位都不能掉。

    掉了 `text` 的話下一輪對不回原文，掉了 `decided_by` 的話分不出
    「人改的」與「規則勾的」，而只有前者是重跑產不出來的。
    """
    record = read_record(_write(tmp_path))

    assert isinstance(record, ConfirmRecord)
    assert record.doc == DOC
    assert record.pdf_sha256 == SHA
    assert record.at == "2026-08-18T01:20:00+08:00"
    assert record.rules_commit == "eaabb4f"
    assert record.items == ITEMS


def test_the_file_says_what_it_is_and_which_format(tmp_path: Path) -> None:
    """檔案要自己講清楚它是什麼 —— 半年後打開的人不會記得。

    版本號是給「欄位形狀改過」的未來看的：沒有它，讀舊檔的人不知道自己在讀什麼。
    """
    payload = json.loads(_write(tmp_path).read_text(encoding="utf-8"))

    assert payload["version"] == FORMAT_VERSION
    assert "重抽" in payload["_"], "要講清楚為什麼不能事後改"
    assert "confirm-list-design" in payload["_"], "要指得到設計文件"


def test_a_changed_source_stops_instead_of_guessing(tmp_path: Path) -> None:
    """PDF 換了就擋下來，不要照舊號碼硬套（比照拆章那條裁決）。

    `index` 是「解析結果裡第幾項」。PDF 一換，同一個號碼可能指到完全不同的段落，
    照舊決定套下去會**消錯東西而且不報錯**。寧可吵人。
    """
    record = read_record(_write(tmp_path))

    with pytest.raises(SourceChangedError) as exc:
        record.require_same_source("sha256:" + "b" * 64)

    assert DOC in str(exc.value), "訊息要帶檔名，否則人不知道是哪一份"
    record.require_same_source(SHA)          # 一樣就安靜通過


def test_a_broken_file_does_not_get_papered_over(tmp_path: Path) -> None:
    """欄位缺漏就丟例外，**不補預設值**。

    補了等於拿猜測冒充當初的決定，而這個檔存在的意義就是不猜。
    這個碼庫記過同型事故：`pp.tables` 因為缺鍵而回 `{}`，一路走到
    「共 None 張，沒有待修的」，在 dker 上產生 4 個假通過。
    """
    path = _write(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    del payload["items"][0]["suppress"]                  # 最關鍵的那一格不見了
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(KeyError):
        read_record(path)


def test_only_the_note_is_optional(tmp_path: Path) -> None:
    """`note`（人改的理由）可以留白，其餘不行 —— PO 裁「不強迫寫為什麼」。"""
    path = _write(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    for item in payload["items"]:
        item.pop("note", None)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    assert all(i.note == "" for i in read_record(path).items)


def test_pull_verdicts_knows_about_this_folder() -> None:
    """`pull-verdicts.py` 要認得這個目錄，不然 repo 那份備份永遠不會出現。

    ⚠ 這正是「存兩份」的第二份。少了這一條，live 檔會安靜地只留在 dker 上，
    而 dker 的 repo 推不出去 —— 備份等於沒做。
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _scripts import load

    pull = load("pull_verdicts", "pull-verdicts.py")

    assert "confirm-lists" in pull.KINDS
    live, repo = pull.KINDS["confirm-lists"]
    assert live == "records/confirm-lists"
    assert repo == "verdicts/records/confirm-lists"


def test_a_rule_decision_that_nobody_touched_is_still_recorded(tmp_path: Path) -> None:
    """規則勾的、人沒動的那些也要標明是誰決定的。

    分不出來的話，下一輪就不知道哪些可以照新規則重算、哪些必須照舊 ——
    而只有人改過的那些是重跑產不出來的。
    """
    by_index = {i.index: i for i in read_record(_write(tmp_path)).items}

    assert by_index[41].decided_by == DECIDED_BY_HUMAN
    assert by_index[2].decided_by == DECIDED_BY_RULE
