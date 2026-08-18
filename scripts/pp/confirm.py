"""確認清單的純算層：從處理計畫挑出「要人看的段落」。

**規則只做確定的，其餘進清單**（PO 2026-08-16 裁決）。這一層不開畫面、不寫檔，
只回答三件事：這份文件有哪幾項要人確認、規則預設怎麼勾、**為什麼**。

設計與四條裁決在 `docs/confirm-list-design-20260817.md`：

1. 打勾 ＝ 不要
2. 一份一份，確認一份放行一份（沒確認的不會被抽取 —— 先抽再改要重抽，花兩次錢）
3. 不確定的預設不勾（＝留著）：寧可多留垃圾，不要誤刪正文
4. **每一項都要有一句白話理由** —— 少了它，人得自己重新判斷每一項，
   「規則先幫你勾好」就白幫了

**這裡刻意不寫「有幾項」。** 同一個量在四個地方出現過四個不同的值
（631／1015／1232／1342），因為量的時機不同 —— `pp.apply` 動手之後再算，
消音早就執行完了，`noise.mute` 會是 0。要數字就自己跑，六秒鐘的事：

    scripts/postprocess.py plan --json   # 只讀不寫，dker 全母體實測 6.27 秒

再把每份計畫餵給 :func:`items_from_plan` 與 :func:`muted_count`。
**四格要一起報**：母體幾份、要人看幾項、散在幾份、規則直接丟幾項，
並註明是在 apply 之前還是之後量的 —— 少了最後這項，兩次的數字不能比。
理由寫在 `docs/confirm-list-design-20260817.md` 的「量」那一節。
"""
from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DECIDED_BY_RULE = "rule"
DECIDED_BY_HUMAN = "human"


@dataclass(frozen=True)
class ConfirmItem:
    """確認清單的一列。

    Attributes:
        section: 來自計畫的哪一段（``noise`` / ``title``）。與 ``index`` 合起來
            才是穩定的識別 —— 兩段的 index 各自從 0 起算，會撞。
        index: 這一項在解析結果裡是第幾項。
        category: 給人看的分類（「頁首頁尾」「標題區塊」）。
        reason: **白話理由**，說「機器憑什麼這樣勾」，不是只說分類。
        text: 原文片段。不給原文，人沒辦法判斷。
        page: 第幾頁。不給頁碼，人回不去查。
        suppress: 要不要丟掉。**沒把握的一律 False（留著）。**
        decided_by: :data:`DECIDED_BY_RULE` 或 :data:`DECIDED_BY_HUMAN`。
        note: 人改這一項的理由。選填。
    """

    section: str
    index: int
    category: str
    reason: str
    text: str
    page: int
    suppress: bool
    decided_by: str = DECIDED_BY_RULE
    note: str = ""

    @property
    def key(self) -> str:
        """穩定識別。存檔與回填都用它。"""
        return f"{self.section}:{self.index}"


def _require(plan: Mapping[str, object], name: str) -> Mapping[str, object]:
    """計畫裡必須有這一段。**缺了就丟，不要回空的假裝乾淨。**

    這個碼庫記過同型事故：`pp.tables` 因為缺鍵而回 `{}`，一路走到
    「共 None 張，沒有待修的」，在 dker 上產生 4 個假通過。

    ⚠ **不要猜原因。** 缺一段有兩種可能，而且處置一樣（都要重跑一次計畫）：

    * 這份是**舊版程式跑的**，那時候還沒有這條規則
      （2026-08-17 實測：50 份缺 `title` 與 `refs`，全部是早就 `indexed` 的舊文件）
    * 這份的計畫**半路失敗**

    第一版的訊息寫死「多半是計畫半路失敗」—— 實測 50 份裡一份都不是。
    寫死的因果跟寫死的數字一樣會過期（今天 `ledger.py` 才因為同一個病錯了六百倍）。

    ⚠ **那 50 份不是從 `postprocess.py plan --json` 來的。** 2026-08-17 稍晚拿
    `plan --json` 對 dker 全母體 317 份重跑，缺段的是 **0 份** —— 因為 `plan`
    每次都現算，四段一定齊全。缺段只會出現在**讀存下來的舊計畫**時。
    引用「50」這個數字之前先確認自己餵的是哪一種輸入。
    """
    section = plan.get(name)
    if not isinstance(section, Mapping):
        raise KeyError(
            f"處理計畫沒有 `{name}` 這一段 —— 可能是舊版程式跑的（那時還沒有這條規則），"
            "也可能是計畫半路失敗。兩種都表示「不知道有沒有要確認的項目」，"
            "不能當成沒有；處置一樣：重跑一次計畫")
    return section


def _rows(section: Mapping[str, object], key: str) -> Sequence[Mapping[str, object]]:
    value = section.get(key) or []
    return value if isinstance(value, list) else []


#: 標題區塊那條規則自己分出來的判準（`TitleHeld.why`）→ 給人看的白話理由。
#:
#: ⚠ **規則的用詞是分類，不能直接印給人看。**「散文」是分類，
#: 「讀起來像正文，不像封面資訊」才是理由 —— PO 2026-08-17 第四條：
#: 人要判斷的是「機器憑什麼這樣勾」。
#:
#: ⚠ **不要退回一句通用句。** 之前 292 項全部共用「可能是期刊封面資訊，也可能是
#: 正文開頭」，等於沒講理由。認不得的判準寧可**照原文吐出來**，讓人看到
#: 一個沒見過的詞，也不要用一句漂亮話把它蓋掉。
_TITLE_REASONS: Mapping[str, str] = {
    "散文": "讀起來像正文，不像封面資訊，所以不敢消",
    "沒有訊號": "沒看到單位、通訊作者、期刊那些封面訊號，不敢確定",
}


def _title_reason(why: str) -> str:
    known = _TITLE_REASONS.get(why)
    if known:
        return known
    logger.warning("標題區塊出現沒見過的判準 %r —— 理由照原文吐出", why)
    return f"規則的判準是「{why}」，這個判準還沒有白話說明" if why else "規則沒有給判準"


#: 規則自己就答得出來的判準，不要拿來問人。
#:
#: ⚠ 只影響**清單問不問**，不影響規則做什麼 —— 那些項目仍然在
#: `title_block` 的 `held` 裡，`plan --details` 照樣印得出來。
#: 兩件事分開：規則負責不要無聲消失，清單負責不要浪費人的時間。
_NOT_WORTH_ASKING: frozenset[str] = frozenset({"散文"})


def items_from_plan(plan: Mapping[str, object]) -> list[ConfirmItem]:
    """挑出要人確認的項目。**規則有把握的不進來**（那些走 :func:`muted_count`）。

    有把握的也塞進來的話，列數會變成「要人看的 ＋ 規則直接丟的」—— 人看不完，
    而「規則先幫你勾好」這個設計就失去意義。（**不寫死倍數**：那個比例隨語料
    與量的時機浮動，模組開頭那段說明了為什麼。）

    Raises:
        KeyError: 計畫缺段（見 :func:`_require`）。
    """
    noise = _require(plan, "noise")
    title = _require(plan, "title")

    items: list[ConfirmItem] = []
    for row in _rows(noise, "held"):
        repeat = row.get("repeat")
        items.append(ConfirmItem(
            section="noise", index=int(row["index"]), category="頁首頁尾",
            reason=_noise_reason(repeat),
            text=str(row.get("text") or ""), page=int(row.get("page") or 0),
            suppress=False,
        ))
    for row in _rows(title, "held"):
        if str(row.get("why") or "") in _NOT_WORTH_ASKING:
            # **規則自己已經知道答案的，不要佔用人的時間。**
            # 「散文」＝這一段讀起來像正文，規則的預設就是留著，而人看了
            # 幾乎一定也是留著。2026-08-18 全庫實測 138 項判成散文、
            # 中位 602 字，那是摘要或正文開頭。
            #
            # ⚠ **只從清單裡拿掉，不從規則裡拿掉。** `title_block` 的 `held`
            # 是那條規則自己的安全網（`plan --details` 會印出來），
            # 拆掉它等於讓「留著沒消」與「根本沒看到」再也分不出來。
            continue
        items.append(ConfirmItem(
            section="title", index=int(row["index"]), category="標題區塊",
            reason=_title_reason(str(row.get("why") or "")),
            text=str(row.get("text") or ""), page=int(row.get("page") or 0),
            suppress=False,
        ))

    logger.debug("%s：要確認 %d 項", plan.get("doc"), len(items))
    return items


#: 參考文獻那條規則的判準 → 白話。同 :data:`_TITLE_REASONS`：認不得的照原文吐。
_REF_REASONS: Mapping[str, str] = {
    "reference": "參考書目，機器有把握。消掉是決定不是損失 —— 文獻之間的關聯"
                 "靠內容圖譜連，不靠這些名字字串",
    "acknowledgement": "致謝／經費，機器有把握。它不回答問題",
}

#: 標題區塊那條規則丟掉時看到的訊號 → 白話。
_TITLE_SIGNALS: Mapping[str, str] = {
    "publication": "看到期刊名與卷期，是封面資訊",
    "affiliation": "看到作者單位，是封面資訊",
    "correspondence": "看到通訊作者，是封面資訊",
    "author": "看到作者列，是封面資訊",
}


def _lookup(table: Mapping[str, str], key: str, what: str) -> str:
    """查白話理由。**認不得就照原文吐出來，不要用一句漂亮話蓋掉。**

    蓋掉的話，規則多了一種判準而畫面照樣說得頭頭是道，沒有人會發現。
    """
    known = table.get(key)
    if known:
        return known
    logger.warning("%s出現沒見過的判準 %r —— 理由照原文吐出", what, key)
    return f"規則的判準是「{key}」，這個判準還沒有白話說明" if key else "規則沒有給判準"


def _noise_reason(repeat: object) -> str:
    """頁首頁尾那條規則沒把握時，用人話說它在猶豫什麼。

    ⚠ 第一版寫「重複 N 次，像頁首頁尾，但次數不夠多、不敢確定」。PO 2026-08-18
    看著畫面說「只出現一行字就要我確認這是什麼，我有點搞不太清楚」——
    **「重複 1 次」對人沒有意義**，它其實是「整份只出現過一次」。
    而全庫 82%（867／1053）的問題都是這一種。

    真正該講的是機器的推理：解析器說它是頁眉，但真的頁眉會一頁一頁重複出現。
    """
    if repeat is None:
        return "解析器把它標成頁首頁尾，但機器看不出這是版面還是內容"
    if repeat == 1:
        # ⚠ 這句會被跳脫後直接印在網頁上，**不要寫 Markdown 星號** ——
        # 會原樣印出來。同一個錯 2026-08-18 已經在 _dropped() 犯過一次。
        return ("解析器把它標成頁首頁尾，但整份只出現這一次 —— "
                "真的頁眉會每頁重複，所以它比較像章節標題或內文")
    return (f"解析器把它標成頁首頁尾，整份出現 {repeat} 次 —— "
            "次數不夠多，不確定是頁眉還是內容")


def muted_items(plan: Mapping[str, object]) -> list[ConfirmItem]:
    """規則有把握、**已經丟掉**的那些，攤開成跟確認清單同樣的形狀。

    PO 2026-08-18 問「確定的沒露出？」—— 在此之前沒有，只有 :func:`muted_count`
    的一個數字。**只給數字是死路**：看到「丟了 12 段」覺得不對勁，卻沒有任何
    辦法看是哪 12 段。PO 原話：「如果有問題還是要寫看全部吧」。

    回傳的每一項 ``suppress`` 都是真的 —— 它們已經被丟了，不是待決定。
    ⚠ 這個函式**只負責攤開來看**，不參與勾選；要覆核就是重跑規則的事。
    """
    items: list[ConfirmItem] = []
    for row in _rows(_section(plan, "noise"), "mute"):
        repeat = row.get("repeat")
        items.append(ConfirmItem(
            section="noise", index=int(row["index"]), category="頁首頁尾",
            reason=(f"重複 {repeat} 次，確定是頁首頁尾" if repeat is not None
                    else "確定是頁首頁尾"),
            text=str(row.get("text") or ""), page=int(row.get("page") or 0),
            suppress=True,
        ))
    for row in _rows(_section(plan, "refs"), "mute"):
        items.append(ConfirmItem(
            section="refs", index=int(row["index"]), category="參考書目",
            reason=_lookup(_REF_REASONS, str(row.get("kind") or ""), "參考文獻"),
            text=str(row.get("text") or ""), page=int(row.get("page") or 0),
            suppress=True,
        ))
    for row in _rows(_section(plan, "title"), "mute"):
        items.append(ConfirmItem(
            section="title", index=int(row["index"]), category="標題區塊",
            reason=_lookup(_TITLE_SIGNALS, str(row.get("signal") or ""), "標題區塊"),
            text=str(row.get("text") or ""), page=int(row.get("page") or 0),
            suppress=True,
        ))
    return items


def _section(plan: Mapping[str, object], name: str) -> Mapping[str, object]:
    """有這一段就回它，沒有就回空的。

    ⚠ 跟 :func:`_require` **刻意不同**：那支是「不知道有沒有要確認的，不能當成
    沒有」，所以缺段就丟；這支攤開的是**已經丟掉**的東西，缺段時報少一點
    不會讓人誤刪正文。兩種嚴格度對應兩種後果，不要統一。
    """
    section = plan.get(name)
    return section if isinstance(section, Mapping) else {}


def muted_count(plan: Mapping[str, object]) -> int:
    """規則有把握、直接丟掉的項數。

    **要報個數，不能安靜消失**（藍桶第 2 條）。數字不見的話，人分不出
    「這份很乾淨」與「規則把半份文件丟了」。
    """
    total = 0
    for name in ("noise", "refs", "title"):
        section = plan.get(name)
        if isinstance(section, Mapping):
            total += len(_rows(section, "mute"))
    return total
