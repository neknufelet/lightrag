"""標題頁的作者、單位與出版資訊消音：它們生出人名機構節點，卻回答不了任何問題。

**為什麼需要這條**：抽取規則第 1 條的措辭已經涵蓋 `author/affiliation block`，
**是模型沒遵守**。2026-08-09 量到正式庫有 188 個 person／organization 節點，
裡面是 `mohan d. rao`、`aip publishing`、`american institute of physics` 這種東西。
跟參考清單一樣，兩種浪費要在兩個地方解決：抽取規則管「不要變成節點」，這條管
「那段文字根本不要進到模型面前」。

⚠ **位置只用來圈範圍，絕不單獨當判準。** 2026-08-09 逐份看過 27 份解析結果，
「從標題消到第一個小標題為止」這個直覺做法被真實資料證偽了三次：

    01701_8.1 General remarks       lvl=1 標題後接的是正文第一段
    C Equivalent Networks           同上
    2016 - 3D Acoustic Field        span 第 11 項是**摘要**，第 12 項是關鍵詞

這三份照位置消，會把真內容整段吃掉**而且不報錯** —— 正是鐵則第 1 條在防的
「有產出但產出錯誤」。所以每一項還要自己通過正面測試才消音，通不過的一律進
`held` 列出來給人看。

⚠ **這條規則救不了的**（先寫清楚，免得事後以為它壞了）：
  - 正文裡的引用（`Almeida et al.`、`Jia et al.`）—— 那不在標題頁
  - 期刊封面頁（IOP 那種「You may also like」列別人論文的版面）—— 它的第一項
    不是 `lvl=1` 標題，本規則不開火。那是另一種版面，另一條規則的事
  - `Helmholtz`、`Cremer`、`Maa`、`Mechel` —— 那些是聲學史上的真人，本來就不該刪
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pp.rules import layout_noise

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from mineru_common import BODY_TYPES  # noqa: E402

# 只看這兩種型別。header／footer／aside_text 是 `layout_noise` 的地盤 ——
# 兩條規則消到同一項的話，`_pp_original_text` 會被寫兩次，計數各算一次而
# 還原只還原得了一次。分工用型別切開，不靠「記得不要重疊」。
CONSIDERED_TYPES: Final[frozenset[str]] = frozenset({"text", "page_footnote"})

# 標題頁區塊最多幾項。實測 17 份有 lvl=1 標題的文件，最長的是 DTU 那份的 15 項
# （含著作權聲明）。設 25 是留餘裕，不是判準 —— 判準是下面的逐項測試。
MAX_SPAN = 25

# 標題不在第 0 項時，往下找 lvl=1 標題的上限。
#
# **為什麼需要**：很多期刊在論文標題**上方**加一行分類標籤（`PAPER`、
# `ACCEPTED MANUSCRIPT`、`Full length article`、`PAPERS • OPEN ACCESS`），
# 標題因此被擠到第 1～3 項，整條規則就不開火了。2026-08-16 逐份掃 317 個解析包
# 量到 52 份單篇論文長這樣，它們的作者、單位、出版社原封不動進了知識庫。
#
# 5 是量出來的：實測需要救的文件裡，標題最深出現在第 3 項。
TITLE_LOOKAHEAD: Final[int] = 5

# 放寬找標題的位置之後的**保險絲**：只有頁上出現這兩種訊號才准放寬。
#
# ⚠ **不能只放寬位置。** 教科書章節的第 0 頁也常常在前幾項出現 lvl=1 標題，
# 2026-08-16 實測只放寬位置會讓 7 份從**章節標題**往下消音 —— 其中
# `01901_10.1 Acoustical scale models` 抓到的還是**上一章**的標題，
# 消掉的會是正文開頭。
#
# 這兩種是**明確字串**（`Citation:`、`doi:`、`corresponding author`、email），
# 不是靠形狀猜的。分界線量得很乾淨：21 份誤判的拆章文件**零份**有這種訊號，
# 而該救的論文都有。合起來實測 **+25 份、零誤傷**。
ANCHOR_SIGNALS: Final[frozenset[str]] = frozenset({"publication", "correspondence"})

# ── 訊號一：單位 ───────────────────────────────────────────────────────────
# 字彙表是 2026-08-09 從 17 份文件的標題頁**實際抄下來的**，不是憑印象列的。
#
# ⚠ 開頭用 `(?<![A-Za-z])` 而不是 `\b`。單位列前面常常黏著上標的編號
# （`1Department of Physics`、`2Institute for Advanced Study`、`3Acoustic Metamaterials`），
# 而 `1` 與 `D` 都是 word character，中間**沒有** `\b`。用 `\b` 的話這些列
# 一個都認不出來，然後掉進「作者列」那條 —— 實測就是這樣，訊號標成 author
# 但仍然被消音，所以**症狀是統計數字錯，不是漏消**。那種錯最難發現。
AFFILIATION = re.compile(
    r"(?<![A-Za-z])(department|dept\.|institute|institut|university|universit[ée]|"
    r"college|school\s+of|"
    r"faculty|laborator(y|ies)|laboratoire|academy|academia|research\s+cent(er|re)|"
    r"cent(er|re)\s+for|ministry|division|hospital|cnrs|affiliations?|"
    r"co\.,?\s*ltd|company|inc\.|gmbh|corporation|\bltd\b)\b", re.I)

# ── 訊號二：通訊方式 ──────────────────────────────────────────────────────
CORRESPONDENCE = re.compile(
    r"[\w.+-]+\s*@\s*[\w.-]+\.\w+"                     # email
    r"|corresponding\s+author"
    r"|author\s+to\s+whom\s+correspondence"
    r"|\be-?mail\s*:"
    r"|\btel\.?\s*:", re.I)

# ── 訊號三：出版資訊 ──────────────────────────────────────────────────────
# **一律錨定在開頭**。不錨定的話「本文引用了……」這種正文句子也會中。
# 這一族是 `aip publishing`、`american institute of physics`、
# `acoustical society of america` 那些機構節點的來源。
PUBLICATION = re.compile(
    r"^\s*[\\*°••\-]*\s*("
    r"citation\b|cite\s+as\b|published\s+(by|in)\b|publication\s+date\b|"
    r"view\s+(online|table\s+of\s+contents)\b|link\s+(to|back)\b|"
    r"downloaded\s+from\b|document\s+version\b|copyright\b|©|"
    r"doi\s*:|https?://(dx\.)?doi\.org|submitted\s*:|received\s*:|accepted\s*:"
    r")", re.I)

# ── 訊號四：作者列 ────────────────────────────────────────────────────────
# 作者列沒有關鍵字可認，只能認**形狀**：一串以大寫開頭的名字，用逗號／分號／
# and 串起來，而且不是句子。
AUTHOR_SEPARATORS = re.compile(r"[,;]|\band\b", re.I)
_ALPHA_TOKEN = re.compile(r"[A-Za-zÀ-ɏ]{2,}")

# 散文的判準：夠長而且大寫開頭的字佔比低。**兩個條件是 AND**。
#
# 大寫比例那半的實測值：`01701` 第一段 0.13、`C Equivalent Networks` 第一段 0.10、
# `2016` 的摘要 0.16；而單位列 `a School of Aerospace Engineering …` 是 0.83、
# 作者列 `Houyou Long, Shuxiang Gao, …` 是 1.00。0.5 落在中間很寬的空隙裡。
#
# **字數那半 2026-08-16 才補上實測**（原本只有「夠長」兩個字，12 沒有來源）。
# 全庫 317 份、還原消音後掃第 0 頁的 text/page_footnote：
#
#     有訊號（作者／單位／出版）n=828 　中位  9 字　75% 15　90% 22
#     沒訊號且大寫比例低（像正文）n=1771　中位 53 字　75% 117　90% 185
#
# ⇒ 兩堆的中位數是 **9 對 53**，中間是一個很大的空隙，12 落在裡面。
#
# ⚠ 但字數這半**不是主要防線**：828 個有訊號的項目裡有 325 個（39%）字數 ≥12，
# 它們是靠大寫比例才被擋下來的。**兩個條件缺一不可，不要以為拿掉字數沒差。**
PROSE_MIN_WORDS = 12
PROSE_MAX_CAPS_RATIO = 0.5

# 作者列要求的大寫比例。比散文門檻高，因為認錯作者列的代價是消掉真內容。
AUTHOR_MIN_CAPS_RATIO = 0.7
AUTHOR_MAX_CHARS = 220

# 消音佔比超過此值就標記待查。標題頁在論文裡佔比很小（實測 0.3–2.4%），
# 所以門檻比參考清單（30%）緊得多 —— 超過就表示圈錯範圍了。
SUSPICIOUS_RATIO = 0.08


@dataclass
class TitleMute:
    index: int
    item_type: str
    page: object
    text: str
    signal: str         # "affiliation" | "correspondence" | "publication" | "author"


@dataclass
class TitleHeld:
    index: int
    item_type: str
    page: object
    text: str
    why: str


@dataclass
class TitlePlan:
    mutes: list[TitleMute]
    held: list[TitleHeld]
    fired: bool                 # 規則有沒有開火（沒有標題頁時是 False）
    reason: str                 # 沒開火的話，為什麼
    body_chars_before: int
    body_chars_after: int

    @property
    def ratio(self) -> float:
        b = self.body_chars_before
        return (b - self.body_chars_after) / b if b else 0.0

    @property
    def suspicious(self) -> bool:
        return self.ratio > SUSPICIOUS_RATIO

    def summary(self) -> str:
        """**永遠報出消音項數，即使區塊沒開火。**

        第 0 頁的 page_footnote 那一掃不看區塊 —— 沒有標題頁的文件照樣可能消掉
        通訊作者與 DOI。原本這裡看到 `fired=False` 就只印「未開火」，於是
        `2025 - Design and optimization` 消了 5 項而畫面上一個字都沒有。
        金絲雀 2026-08-09 用 `title_fired=False, title_mute=5` 這組矛盾的數字
        把它照出來 —— 那正是把 fired 單獨記一格的理由。
        """
        span = "有標題頁區塊" if self.fired else f"無標題頁區塊（{self.reason}）"
        by: dict[str, int] = {}
        for m in self.mutes:
            by[m.signal] = by.get(m.signal, 0) + 1
        detail = "、".join(f"{k} {n}" for k, n in sorted(by.items())) or "無"
        return (f"標題頁消音：{len(self.mutes)} 項（{detail}）、保留待查 {len(self.held)} 項；"
                f"{span}；"
                f"正文 {self.body_chars_before:,} → {self.body_chars_after:,} "
                f"（{self.ratio * 100:.2f}%）"
                + ("　⚠ 比例異常，請人工確認" if self.suspicious else ""))


def caps_ratio(text: str) -> float:
    """以大寫開頭的字佔所有字的比例。單字母的字（`a`、`b` 那種單位標記）不算。"""
    tokens = _ALPHA_TOKEN.findall(text)
    if not tokens:
        return 0.0
    return sum(1 for t in tokens if t[0].isupper()) / len(tokens)


def looks_like_prose(text: str) -> bool:
    """這是不是一段散文（＝可能是真內容）。

    **這個判斷是本規則唯一的安全網**：標題頁區塊裡混著真正的摘要與正文第一段，
    而它們沒有任何「我是正文」的標記可認。只能反過來認散文的形狀。
    """
    if len(text.split()) < PROSE_MIN_WORDS:
        return False
    return caps_ratio(text) < PROSE_MAX_CAPS_RATIO


def looks_like_author_line(text: str) -> bool:
    """這是不是一列作者名。

    判準三條同時成立：夠短、有分隔符、幾乎全是大寫開頭的字。
    實測 12 份文件的作者列全部通過，而摘要與正文第一段全部不通過。
    """
    t = text.strip()
    if not t or len(t) > AUTHOR_MAX_CHARS:
        return False
    if not AUTHOR_SEPARATORS.search(t):
        return False
    return caps_ratio(t) >= AUTHOR_MIN_CAPS_RATIO


# 投稿／修訂／接受日期。期刊流程的紀錄，回答不了任何聲學問題。
# PO 2026-08-18 在 19 份真資料裡丟過 12 次，一次都沒留。
# ⚠ 用 `match`（從頭比對）不是 `search`：正文裡「The microphone received the
# signal…」也有 received，從頭比對才不會咬到正文。
SUBMISSION_DATES: Final[re.Pattern[str]] = re.compile(
    r"^\s*\(?\s*(received|revised|accepted|submitted|manuscript\s+received)\b", re.I)

# 期刊的分類碼。PACS 是聲學期刊最常見的，MSC/CCS/AMS 是別的領域的同類。
CLASSIFICATION_CODES: Final[re.Pattern[str]] = re.compile(
    r"^\s*(PACS|MSC|CCS|AMS)\b", re.I)

# 作者自己標的主題詞。**留著**（PO 2026-08-18 裁）——那正是內容圖譜要連的東西，
# 比參考書目的名字字串有用得多。
KEYWORDS: Final[re.Pattern[str]] = re.compile(
    r"^\s*(index\s+terms|key\s?words?)\b", re.I)


# 封面上單獨一行的人名。期刊把作者排成一行一個，所以每個都自成一段。
#
# ⚠ **這條規則唯一會出事的方向是咬到正文。** PO 2026-08-18 自己問到重點：
# 「單獨人名不會錯嗎？在文章裡面的好像不容易單獨拆開來」—— 他是對的，
# 而且量得出來：把這個樣式套到 1827 段正文上，**命中 0 段**。
# 正文裡的人名總是夾在句子裡（"Toole reported…"），不會自成一段。
#
# 四道關一起才擋得住：
#   ① 整段完全比對（不是 search）—— 正文段落更長
#   ② 至少兩個詞 —— 'Rayleigh'、'Frequency' 這種章節標題只有一個詞
#   ③ 長度上限
#   ④ **必須有縮寫點**（`R.`、`E.`、`A.`）
#
# ⚠ 第 ④ 條是被自己的測試逼出來的：前三條讓 'Sound Absorption' 通過了 ——
# 兩個大寫字，跟人名長得一模一樣。實測庫裡那 62 個真人名**每一個都有縮寫點**
# （FLOYD **E.** TOOLE、Michael **R.** Stinson、**A.** CRAGGS…），
# 而章節標題沒有。
# 代價是漏掉沒有縮寫的名字（"Michael Stinson"）—— **那是安全的方向**：
# 漏抓只是多問人一次，誤抓是丟掉真內容而且不報錯。
STANDALONE_NAME: Final[re.Pattern[str]] = re.compile(
    r"[A-Z][A-Za-z'\-]*\.?(\s+[A-Z][A-Za-z'\-]*\.?){1,3}")

#: 縮寫：單一個大寫字母加一個點。人名一行必須至少有一個。
INITIAL: Final[re.Pattern[str]] = re.compile(r"\b[A-Z]\.")

#: 人名一行的長度上限。實測庫裡最長的是 'Julio Cesar B. Torres'（21 字）；
#: 給到 34 留餘裕，但擋得住整串大寫的標題。
NAME_MAX_CHARS: Final[int] = 34


def is_standalone_name(text: str) -> bool:
    """這一段是不是「整段就只有一個人名」。

    ⚠ **只該用在封面那一區。** 實測 62 個命中裡 56 個在第 0 頁；不在封面的
    那 6 個是期刊標章與掃壞的字（'AUDIO A ES'、'AC IPT'），不是內容 ——
    但既然位置給得起保險，就收緊到封面，一個都不多碰。
    """
    t = (text or "").strip().rstrip(",;")
    if not t or len(t) > NAME_MAX_CHARS:
        return False
    if not INITIAL.search(t):
        return False
    return STANDALONE_NAME.fullmatch(t) is not None


def _signal(text: str) -> str | None:
    """這一項該不該消音，以及是憑哪個訊號。不該消就回 None。

    順序有意義：`publication` 與 `correspondence` 是錨定／明確的字串，即使
    整段是散文也照消（DTU 那份的著作權聲明就是散文）。`affiliation` 只是關鍵字，
    **遇到散文就不算數** —— 不然正文裡一句「…… at Tongji University ……」
    就會把整段真內容消掉。
    """
    t = text.strip()
    if not t:
        return None
    if PUBLICATION.match(t):
        return "publication"
    if SUBMISSION_DATES.match(t):
        return "submission"
    if CLASSIFICATION_CODES.match(t):
        return "classification"
    # ⚠ 判準跟 `layout_noise` 共用同一支 —— **同一件事不要有兩個定義**，
    # 不然兩邊會慢慢漂開，而漂開不會有錯誤訊息。
    # PO 2026-08-18 對 'Check for updates' 的原話：「我以為那是你寫的字」。
    # 一個使用者把語料裡的字當成介面文字，那它就不是內容。
    if layout_noise.is_publisher_boilerplate(t):
        return "publisher"
    if CORRESPONDENCE.search(t):
        return "correspondence"
    if looks_like_prose(t):
        return None
    if AFFILIATION.search(t):
        return "affiliation"
    if looks_like_author_line(t):
        return "author"
    # 單獨一行的人名。放在最後 —— 前面每一條都比它明確，先讓它們認領。
    if is_standalone_name(t):
        return "name_line"
    return None


def _has_anchor(items: list[dict]) -> bool:
    """第 0 頁上有沒有**明確字串**（出版資訊或通訊方式）。

    只認 :data:`ANCHOR_SIGNALS` 那兩種 —— 它們是關鍵字比對，不是形狀猜測。
    作者列與單位列**刻意不算**：教科書章節的章名（`6.2 SOUND ABSORPTION BY
    MEMBRANES AND PERFORATED SHEETS`）會被大寫比例猜成作者列，拿它當保險絲
    等於沒有保險絲。
    """
    for it in items:
        if (it.get("page_idx") or 0) != 0:
            continue
        if it.get("type") not in CONSIDERED_TYPES:
            continue
        if _signal(str(it.get("text") or "")) in ANCHOR_SIGNALS:
            return True
    return False


def _title_index(items: list[dict]) -> tuple[int | None, str]:
    """文件標題在第幾項。回傳 (索引, 沒找到的理由)。

    兩條路，**寬鬆程度刻意不同**：

    1. 第 0 項就是 `text_level == 1` 的標題 —— 直接採用，不附加條件（現行行為）。
    2. 標題被期刊分類標籤擠到後面 —— 往下最多找 :data:`TITLE_LOOKAHEAD` 項，
       **而且第 0 頁必須有錨定字串**（見 :data:`ANCHOR_SIGNALS`）。

    第二條沒有保險絲的話會咬到教科書章節，實測 7 份。
    """
    first = items[0]
    if first.get("text_level") == 1:
        if (first.get("page_idx") or 0) != 0:
            return None, "第一項不在第 0 頁"
        return 0, ""

    for i, it in enumerate(items[:TITLE_LOOKAHEAD]):
        if (it.get("page_idx") or 0) != 0:
            break                       # 翻頁了，後面不算「被標籤擋住」
        if it.get("text_level") == 1:
            if not _has_anchor(items):
                return None, (f"標題在第 {i} 項而不是第一項，但第 0 頁沒有錨定字串 —— "
                              "教科書章節長這樣，放行會從章節標題往下消掉正文")
            return i, ""
    return None, "第一項不是 lvl=1 標題（教科書章節、期刊封面頁都長這樣）"


def _span(items: list[dict]) -> tuple[list[int], str]:
    """圈出標題頁區塊的候選索引。回傳 (索引清單, 沒開火的理由)。

    開火條件刻意嚴格，理由見 :func:`_title_index`。找到標題之後，從它的下一項
    往後圈到「碰到下一個標題」或「翻頁」為止。

    ⚠ **圈出來的範圍不等於要消的東西。** 每一項還要自己通過 :func:`_signal`，
    2026-08-09 逐份看過 27 份證實：有三份文件的標題後面直接接正文或摘要。
    """
    if not items:
        return [], "文件沒有項目"
    start, why = _title_index(items)
    if start is None:
        return [], why

    span: list[int] = []
    for i, it in enumerate(items[start + 1:], start=start + 1):
        if it.get("text_level"):
            break                       # 碰到 Abstract／Introduction，區塊結束
        if (it.get("page_idx") or 0) != 0:
            break                       # 翻頁了
        if len(span) >= MAX_SPAN:
            break
        span.append(i)
    if not span:
        return [], "標題後面直接就是下一個標題"
    return span, ""


def plan(items: list[dict]) -> TitlePlan:
    """算出標題頁區塊要消音哪些項目。只讀不寫。"""
    span, reason = _span(items)
    mutes: list[TitleMute] = []
    held: list[TitleHeld] = []

    for i in span:
        it = items[i]
        itype = it.get("type", "")
        text = it.get("text") or ""
        if itype not in CONSIDERED_TYPES:
            # 圖片沒有文字；header／footer 歸 layout_noise。都不列入待查，
            # 不然每份文件都會多出幾項雜訊把真正該看的蓋掉。
            continue
        sig = _signal(text)
        if sig:
            mutes.append(TitleMute(index=i, item_type=itype, page=it.get("page_idx"),
                                   text=text, signal=sig))
        elif text.strip():
            held.append(TitleHeld(
                index=i, item_type=itype, page=it.get("page_idx"), text=text,
                # 關鍵字要留著（PO 2026-08-18 裁），但**留著的方式是標明判準、
                # 不是憑空消失** —— 規則要報得出自己看到什麼。要不要拿來問人
                # 是確認清單那一層的事（`pp/confirm.py` 的 `_NOT_WORTH_ASKING`）。
                why=("關鍵字" if KEYWORDS.match(text.strip())
                     else "散文" if looks_like_prose(text) else "沒有訊號")))

    # 第 0 頁的 page_footnote 另外掃一次：通訊作者的 email 常常掛在頁腳，
    # 而頁腳在 Abstract 之後 —— 不在上面圈的區塊裡。實測 2017 Optimal 就是
    # `\*Corresponding author. Email: sheng @ust.hk`。
    # **只認通訊與出版兩個明確訊號**，不用單位關鍵字 —— 頁腳裡什麼都有。
    seen = {m.index for m in mutes}
    for i, it in enumerate(items):
        if i in seen or it.get("type") != "page_footnote":
            continue
        if (it.get("page_idx") or 0) != 0:
            continue
        text = it.get("text") or ""
        t = text.strip()
        if not t:
            continue
        if PUBLICATION.match(t):
            mutes.append(TitleMute(i, it.get("type", ""), it.get("page_idx"), text,
                                   "publication"))
        elif CORRESPONDENCE.search(t):
            mutes.append(TitleMute(i, it.get("type", ""), it.get("page_idx"), text,
                                   "correspondence"))

    def body_chars(skip: set[int]) -> int:
        return sum(len(it.get("text") or "")
                   for j, it in enumerate(items)
                   if it.get("type") in BODY_TYPES and j not in skip)

    before = body_chars(set())
    after = body_chars({m.index for m in mutes})
    return TitlePlan(mutes=sorted(mutes, key=lambda m: m.index), held=held,
                     fired=bool(span), reason=reason,
                     body_chars_before=before, body_chars_after=after)


def apply_to_items(items: list[dict], plan_: TitlePlan) -> int:
    """就地消音。原文存進 `_pp_original_text` —— 還原時讀它，查帳時比對它。

    沿用 `layout_noise` 的鍵，所以 `layout_noise.revert_items` 還原得了它。
    本規則不碰 `list_items`（標題頁沒有清單型別），所以不需要自己的 revert。
    """
    n = 0
    for m in plan_.mutes:
        it = items[m.index]
        if it.get("text"):
            it["_pp_original_text"] = it["text"]
            it["text"] = ""
            n += 1
    return n
