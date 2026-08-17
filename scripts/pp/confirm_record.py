"""確認清單的存檔與讀回。

**這個檔案守的是「人當初的決定不會被規則悄悄推翻」，不是省下勾選的力氣。**
算清單本身很便宜（`postprocess.py plan --json` 全母體 6.27 秒）；痛的是後面那一步
—— 消音會改變送去抽取的文字（`pp/apply.py` 的註解：消音會讓 `is_bundle_valid`
變假、快取失效），抽完再改消音就得**重抽一次**，而抽取是整條線最貴的一步。

PO 2026-08-17 裁的三條（全文在 `docs/confirm-list-design-20260817.md`）：

======================================  ====================================
存在哪裡？                              兩份：資料區一份（實際在用）、repo 一份
存整份清單還是只存改動？                **整份**，含人看過但決定留著的
什麼時候存？                            **每確認一份存一次**
======================================  ====================================

第二條是其餘兩條的上游：只存改動的話，規則之後一改、項目數與順序都會變，
`section:index` 這種號碼就會指到別的段落，人的決定被搬到錯的地方去。

⚠ **形狀刻意抄 `scripts/chapters/split_record.py`。** 那支解的是同一個題目
（人手改過的勾選要能原封不動拿回來），而且已經踩過「直接寫進 dker 的 repo
會永遠上不了 GitHub」那個坑。同一件事不要有兩種做法。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from pp.confirm import DECIDED_BY_RULE, ConfirmItem

logger = logging.getLogger(__name__)

#: **live 紀錄**在資料區，跟 `records/ledger/` 同一層。backrest 備份得到。
#:
#: ⚠ **不要直接寫進 repo。** 服務跑在 dker，而 dker 的 repo 是唯讀只 `git pull`
#: —— 直接寫進去的檔會躺在那裡永遠上不了 GitHub。體檢表踩過同一個坑，一度
#: dker 318 份而 git 只有 20 份，備份只做到 6%。
LIVE_SUBDIR = Path("records") / "confirm-lists"

#: **版控副本**在 repo，跟 `verdicts/records/ledger/` 同一層 —— 那裡放的都是
#: 「重跑不出來的人工判定」，而人手改的勾選正是那種東西。
#: 由 `scripts/pull-verdicts.py` 從 dker 拉回 coder，再由人提交。
REPO_SUBDIR = Path("verdicts") / "records" / "confirm-lists"

#: 格式版本。欄位形狀變了就要 +1，讀舊檔的人才知道自己在讀什麼。
FORMAT_VERSION = 1

#: 寫進檔案裡的自述。**半年後打開的人不會記得為什麼不能事後改。**
_PREAMBLE = (
    "由人在確認清單畫面做的決定：打勾＝這段不要進知識庫。"
    "**整份清單都在這裡，含人看過但決定留著的那些**（PO 2026-08-17 裁）—— "
    "只存改動的話，規則一改、項目數與順序就變了，`section:index` 會指到別的段落。"
    "`decided_by=human` 的那幾列是人改的，重跑規則產不出來，所以這個檔進版控。"
    "⚠ **不要事後改**：消音會改變送去抽取的文字，改了那一份就得重抽一次，"
    "而抽取是整條線最貴的一步。"
    "`rules_commit` 只拿來對照，不拿來重算。"
    "格式說明在 docs/confirm-list-design-20260817.md。"
)


class SourceChangedError(RuntimeError):
    """PDF 的指紋與紀錄裡的對不上 —— 舊的項目編號可能指到完全不同的內容。"""


@dataclass(frozen=True)
class ConfirmRecord:
    """一份文件的確認清單紀錄。

    Attributes:
        doc: 原 PDF 檔名。
        pdf_sha256: 原 PDF 的指紋（含 ``sha256:`` 前綴，與體檢表同形）。
        items: 整份清單，**含人看過但決定留著的**。
        at: 存檔時間。呼叫端給，這裡不取現在時間 —— 測試才驗得到。
        rules_commit: 當時的 commit。**只拿來對照，不拿來重算。**
    """

    doc: str
    pdf_sha256: str
    items: list[ConfirmItem]
    at: str
    rules_commit: str

    def require_same_source(self, actual_sha256: str) -> None:
        """指紋對不上就擋下來（比照拆章那條裁決：停下來問人）。

        ``ConfirmItem.index`` 是「解析結果裡第幾項」。PDF 被換掉（重新下載、
        換版本）時，同一個號碼可能指到完全不同的段落，照舊決定套下去會
        **消錯東西而且不報錯**，要很久之後才會發現 —— 所以寧可吵人。

        ⚠ 指紋用的是 **PDF**，不是解析結果。解析結果會被消音改寫，拿它當指紋
        會在 apply 之後天天假警報。2026-08-17 實測支持這個選擇：同一份 PDF
        隔一週重新解析，165 項的型別、頁碼、文字逐項相同。

        Raises:
            SourceChangedError: 指紋不同。訊息帶檔名，否則人不知道是哪一份。
        """
        if self.pdf_sha256 != actual_sha256:
            raise SourceChangedError(
                f"「{self.doc}」的內容跟當初確認時不一樣了"
                f"（紀錄 {self.pdf_sha256[:19]}…、現在 {actual_sha256[:19]}…）。"
                "舊的項目編號可能指到別的段落，要重新確認一次。"
            )


def record_path(data_root: Path, doc: str) -> Path:
    """這份文件的 live 紀錄該放哪（資料區）。一份文件一個檔，檔名跟體檢表同作法。"""
    return data_root / LIVE_SUBDIR / f"{doc}.json"


def repo_record_path(repo: Path, doc: str) -> Path:
    """這份文件的版控副本該放哪（repo）。由 `pull-verdicts.py` 寫入。"""
    return repo / REPO_SUBDIR / f"{doc}.json"


def write_record(root: Path, *, doc: str, pdf_sha256: str, items: list[ConfirmItem],
                 at: str, rules_commit: str) -> Path:
    """把確認結果寫成一個檔，回傳寫到哪裡。

    ⚠ **整份清單都寫，人決定留著的那些照樣寫進去**（藍桶第 2 條）。只寫勾掉的
    那些的話，「看過、決定留著」會被當成「還沒看過」而下次再問一次；更糟的是
    規則一改、那幾項可能變成預設勾掉，**人當初決定留著的東西就被安靜地丟了**。
    """
    path = record_path(root, doc)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": FORMAT_VERSION,
        "_": f"{at} {_PREAMBLE}",
        "doc": doc,
        "pdf_sha256": pdf_sha256,
        "at": at,
        "rules_commit": rules_commit,
        "items": [
            {
                "section": i.section,
                "index": i.index,
                "category": i.category,
                "reason": i.reason,
                "text": i.text,
                "page": i.page,
                "suppress": i.suppress,
                "decided_by": i.decided_by,
                "note": i.note,
            }
            for i in items
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")
    logger.info("確認紀錄已寫入 %s（%d 項，其中丟掉 %d 項）",
                path, len(items), sum(1 for i in items if i.suppress))
    return path


def read_record(path: Path) -> ConfirmRecord:
    """讀回一份確認紀錄。

    Raises:
        FileNotFoundError: 檔案不存在。
        KeyError / ValueError: 欄位缺漏或形狀不對 —— **不補預設值**（`note` 除外，
            PO 裁「改勾選不強迫寫為什麼」）。補了等於拿猜測冒充當初的決定，
            而這個檔存在的意義就是不猜。這個碼庫記過同型事故：`pp.tables`
            因為缺鍵而回 `{}`，一路走到「共 None 張，沒有待修的」，
            在 dker 上產生 4 個假通過。
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    items = [
        ConfirmItem(
            section=row["section"],
            index=row["index"],
            category=row["category"],
            reason=row["reason"],
            text=row["text"],
            page=row["page"],
            suppress=row["suppress"],
            decided_by=row.get("decided_by", DECIDED_BY_RULE),
            note=row.get("note", ""),
        )
        for row in payload["items"]
    ]
    return ConfirmRecord(
        doc=payload["doc"], pdf_sha256=payload["pdf_sha256"], items=items,
        at=payload["at"], rules_commit=payload["rules_commit"],
    )
