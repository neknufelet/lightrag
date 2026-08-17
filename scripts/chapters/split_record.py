"""拆章勾選紀錄的存檔與讀回。

**這個檔案守的是「檔名不要變」，不是省下切的力氣。** 切章本身純本機、免費、
幾秒鐘；痛的是後面兩步 —— 檔名一變，MinerU 要重解析、DeepSeek 要重抽，
而且庫裡會長出同一本書的兩套章，還不會報錯。

格式與四條裁決在 `docs/chapter-selection-record-20260817.md`：

======================================  ==================================
規則之後改了，同一本書再切一次？        照舊的切，檔名不變
紀錄放哪裡？                            跟程式碼一起（repo，進版控）
書的檔案被換掉、頁碼可能對不上？        停下來問人，不照舊頁碼硬切
改勾選要不要寫一句為什麼？              不強迫，可留空白
======================================  ==================================

第一條是其他三條的上游：因為要「照舊的切」，所以**存整份清單**（不是只存改了
哪幾列）並且**存最後的檔名**（不是只存標題）—— 砍 80 字也是規則，規則一改
檔名會安靜地跟著變。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from chapters.selection import DECIDED_BY_RULE, SelectionRow

logger = logging.getLogger(__name__)

#: 紀錄落在這裡。跟 `verdicts/records/ledger/` 同一層 —— 那裡放的都是
#: 「重跑不出來的人工判定」，而人手改的勾選正是那種東西。
RECORD_SUBDIR = Path("verdicts") / "records" / "chapter-splits"

#: 格式版本。欄位形狀變了就要 +1，讀舊檔的人才知道自己在讀什麼。
FORMAT_VERSION = 1


class PdfChangedError(RuntimeError):
    """PDF 的指紋與紀錄裡的對不上 —— 舊頁碼可能指到完全不同的內容。"""


@dataclass(frozen=True)
class SplitRecord:
    """一本書的拆章勾選紀錄。

    Attributes:
        doc: 原 PDF 檔名。
        pdf_sha256: 原 PDF 的指紋（含 ``sha256:`` 前綴，與體檢表同形）。
        key: 這本書的 8 碼 Zotero item key。
        chosen_level: 當初選的層次。
        rows: 整份清單，**含沒勾的列**。
        at: 存檔時間。
        rules_commit: 當時 `scripts/chapters/` 的 commit。**只拿來對照，不拿來重算。**
    """

    doc: str
    pdf_sha256: str
    key: str
    chosen_level: int
    rows: list[SelectionRow]
    at: str
    rules_commit: str


def record_path(root: Path, doc: str) -> Path:
    """這本書的紀錄該放哪。一本書一個檔，檔名跟體檢表同作法。"""
    return root / RECORD_SUBDIR / f"{doc}.json"


def write_record(root: Path, *, doc: str, pdf_sha256: str, key: str, chosen_level: int,
                 rows: list[SelectionRow], at: str, rules_commit: str) -> Path:
    """把勾選結果寫成一個檔，回傳寫到哪裡。

    ⚠ **整份清單都寫，沒勾的列照樣寫進去**（藍桶第 2 條）。只寫勾好的話，
    重來時那幾章會被當成「規則沒偵測到」而重新勾上 —— 人當初取消勾選的決定
    就被安靜地推翻了。
    """
    path = record_path(root, doc)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": FORMAT_VERSION,
        "_": (
            f"{at} 由人在勾選畫面確認的拆章決定。"
            "重來時**照這份切、不重跑規則**（PO 2026-08-17 裁）。"
            "`decided_by=human` 的那幾列是人改的，重跑規則產不出來，"
            "所以這個檔進版控。`rules_commit` 只拿來對照，不拿來重算。"
            "格式說明在 docs/chapter-selection-record-20260817.md。"
        ),
        "doc": doc,
        "pdf_sha256": pdf_sha256,
        "key": key,
        "chosen_level": chosen_level,
        "at": at,
        "rules_commit": rules_commit,
        "rows": [
            {
                "serial": r.serial,
                "title": r.title,
                "level": r.level,
                "page_range": list(r.page_range),
                "filename": r.filename,
                "selected": r.selected,
                "decided_by": r.decided_by,
                "note": r.note,
            }
            for r in rows
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    logger.info("拆章紀錄已寫入 %s（%d 列，勾好 %d 列）",
                path, len(rows), sum(1 for r in rows if r.selected))
    return path


def read_record(path: Path) -> SplitRecord:
    """讀回一份拆章紀錄。

    Raises:
        FileNotFoundError: 檔案不存在。
        KeyError / ValueError: 欄位缺漏或形狀不對 —— **不補預設值**。
            補了等於拿猜測冒充當初的決定，而這個檔存在的意義就是不猜。
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = [
        SelectionRow(
            title=row["title"],
            level=row["level"],
            page_range=(row["page_range"][0], row["page_range"][1]),
            serial=row["serial"],
            filename=row["filename"],
            selected=row["selected"],
            decided_by=row.get("decided_by", DECIDED_BY_RULE),
            note=row.get("note", ""),
        )
        for row in payload["rows"]
    ]
    return SplitRecord(
        doc=payload["doc"], pdf_sha256=payload["pdf_sha256"], key=payload["key"],
        chosen_level=payload["chosen_level"], rows=rows,
        at=payload["at"], rules_commit=payload["rules_commit"],
    )


def require_same_pdf(record: SplitRecord, actual_sha256: str) -> None:
    """指紋對不上就擋下來（PO 2026-08-17 裁：停下來問人）。

    PDF 被換掉（重新下載、換版本）時，紀錄裡的頁碼可能指到完全不同的內容。
    照舊頁碼硬切會切錯**而且不報錯**，要很久之後才會發現 —— 所以寧可吵人。

    Raises:
        PdfChangedError: 指紋不同。訊息裡帶書名，否則人不知道是哪一本。
    """
    if record.pdf_sha256 != actual_sha256:
        raise PdfChangedError(
            f"「{record.doc}」的內容跟當初勾選時不一樣了"
            f"（紀錄 {record.pdf_sha256[:19]}…、現在 {actual_sha256[:19]}…）。"
            "舊的頁碼可能指到別的地方，要重新勾一次才能切。"
        )
