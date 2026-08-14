#!/usr/bin/env python3
r"""Zotero 狀態標籤對帳：讓標籤反映**量到的事實**，不是記憶。

## 這支在解什麼問題

文獻庫裡兩個狀態標籤各自對應一座知識庫：

```
_Raged      這篇在 LightRAG 知識庫裡        權威：kbapi 的 /kb/<ws>/docs
_INGESTED   深讀過、寫成 Obsidian 筆記      權威：10_Research 底下的 .md
```

兩邊都會長大，而**標籤過期不會有任何訊號** —— 2026-08-14 實測：對帳當下知識庫
276 份，同一個下午變成 312 份，於是剛進去的 36 份在 Zotero 上還是沒有標籤。
靠人記得對帳，代價是每隔一陣子整批失真一次。

## 為什麼不是「照舊標籤搬」

2026-08-14 對帳前的實況：238 筆 `_Raged` 裡有 **70 筆掛在子筆記或附件上**，
10 筆標著 `_NOT_IN_KB` 其實已經在庫裡，還有一組大小寫分岔（`_RAGED` vs
`_Raged`）是外掛與手打各寫各的。舊標籤沒有一個是可信的輸入，所以這支
**只讀兩座知識庫，不讀舊標籤**。

## ⚠ 六條血淚，改這支之前先讀

1. **絕不用 `DELETE /tags?tag=X`。** Zotero 這個端點**不分大小寫**，刪 `_RAGED`
   會把 `_Raged` 一起帶走 —— 2026-08-14 因此誤刪 163 筆，靠事先存的備份逐筆
   PATCH 才救回來。要移除標籤只能逐筆改寫該項目的 tags 陣列。
2. **寫入是整欄覆蓋。** PATCH／POST 送出的 `tags` 會取代原本整個陣列，所以一定
   先讀現值、保留使用者其他標籤，再加上狀態標籤。
3. **標籤要寫成手動（type 0）。** type 1 是自動標籤，會被 Zotero 的「刪除本館
   所有自動標籤」一次清光，而且介面可以整批隱藏。同名的 type 0 與 type 1 在
   Zotero 眼中是**兩個不同的標籤**。這支省略 `type` 欄位，那就是 0。
4. **標籤只掛父層文獻。** 掛在筆記上看起來一樣（子項目也會顯示圓點），但篩選、
   匯出、統計全部會錯。
5. **比對用「詞」不用「字元前綴」。** 前綴太短會把 `Low-frequency broadband
   absorber…` 開頭的三篇不同論文配成同一篇；太長則 `Review of FEM **in** Room
   Acoustics` 配不上 `**A** Review of FEM **for** …`。
6. **預設只補不刪。** 「找不到證據」不等於「沒有那件事」——比對失敗、筆記改名、
   WebDAV 掉線都會製造假的「沒有」。要移除得明講 `--prune`。

## 秘密從哪來

`ZOTERO_API_KEY`、`OBSIDIAN_DAV`（`帳號:密碼`）從環境變數讀，**不進版控**。
LightRAG 的 `.env` 只在 dker，而這支跑在 coder（它打得到 kbapi 與 NAS），
所以刻意不走那條路。

用法：
    zotero-sync.py check              # 唯讀，印出「會改什麼」
    zotero-sync.py check --json OUT   # 同上，差異另存成 JSON
    zotero-sync.py apply              # 寫入（只補不刪），先自動備份
    zotero-sync.py apply --prune      # 連「證據消失的」也一併移除
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

REPO: Final[Path] = Path(__file__).resolve().parent.parent

ZOTERO_USER: Final[str] = "13417799"
ZOTERO_BASE: Final[str] = f"https://api.zotero.org/users/{ZOTERO_USER}"
KBAPI: Final[str] = "http://100.87.88.7:9700"
DAV_BASE: Final[str] = "http://florian-nas.pleco-acoustic.ts.net:5005"
DAV_NOTES: Final[str] = "/Learning_DB/obsidian/Florian/10_Research/"

IN_KB: Final[str] = "_Raged"
DEEP_READ: Final[str] = "_INGESTED"
STATUS_TAGS: Final[frozenset[str]] = frozenset({IN_KB, DEEP_READ})

# 退休的標籤。留在這裡是為了**認得出並清掉它們**，不是為了繼續寫。
#   `_toRaged`    外掛送出時打的暫時記號，不是狀態
#   `_NOT_IN_KB`  「不在庫裡」＝沒有 `_Raged`，不需要第二個名字
#   `_RAGED`      外掛 0.2.0 的大寫版，0.2.1 起與手打對齊
RETIRED: Final[frozenset[str]] = frozenset({"_toRaged", "_NOT_IN_KB", "_RAGED"})
KNOWN: Final[frozenset[str]] = STATUS_TAGS | RETIRED

# 比對時丟掉的虛詞。留著它們會讓「兩篇都用了 of/the」被算成相似。
#
# ⚠ `part` **刻意不在裡面**，單字元的數字也刻意留著（見 `significant_words`）。
#    `… Preferences: Part 1` 與 `… Part 2` 只差這兩個 token；把它們丟掉，
#    兩篇就完全一樣、分數並列，於是**兩篇都不給** —— 而庫裡其實只有 Part 2。
STOPWORDS: Final[frozenset[str]] = frozenset({
    "a", "an", "the", "of", "for", "in", "on", "and", "with", "to", "by",
    "at", "from", "using", "via", "its", "into", "based",
})
MIN_WORDS: Final[int] = 3
MIN_OVERLAP: Final[float] = 0.85

# 光看涵蓋率不夠：分母是短的一方，所以**兩個字的書章名很容易被 100% 涵蓋**。
# 2026-08-14 實測的誤判：
#
#     Z: A Geometrical Acoustics Approach Linking Surface Scattering …
#     K: M Room Acoustics.pdf          ← 只因為兩邊都有 room 與 acoustics
#     Z: Binaural room simulation based on an image source model …
#     K: E Scattering of Sound.pdf     ← 只因為兩邊都有 scattering 與 sound
#
# 所以再要求「共同的詞夠多」。書章名短，湊不到；真正同一篇的隨便都超過。
MIN_SHARED: Final[int] = 4

# 入庫時檔名會被截斷。實測（2026-08-14、312 份）最長的停在 105 字元，
# 而被截到的那些最後一個字是半個 —— 到這個長度就當它可能被切過。
TRUNCATED_AT: Final[int] = 95

# 筆記檔名常是 `作者 年份 - 標題`；標題那段才拿去比對。
NOTE_TITLE: Final[re.Pattern[str]] = re.compile(
    r"^(?:draft_)?[A-Za-zÀ-ɏ&\-']+\s+\d{4}\s*[-–]\s*(?P<title>.+)$")


# ── 比對 ──────────────────────────────────────────────────────────────────

def _keep(word: str) -> bool:
    """單字母丟掉（`a`、`A` 那種切碎的），**單一數字留著**。

    `Part 1` 與 `Part 2` 的差別就只有那個數字。丟掉它，同一篇論文的上下集
    在比對眼中完全相同 —— 而知識庫裡可能只有其中一集。
    """
    return word not in STOPWORDS and (len(word) > 1 or word.isdigit())


def significant_words(text: str) -> frozenset[str]:
    """標題拆成有意義的詞。大小寫、標點、語序、虛詞都不影響結果。"""
    normalised = unicodedata.normalize("NFKD", text).lower()
    return frozenset(w for w in re.findall(r"[a-z0-9]+", normalised) if _keep(w))


def kb_words(filename: str) -> frozenset[str]:
    """知識庫檔名拆詞 —— 先去掉**檔名才有、標題沒有**的東西。

    ```
    2025 - Labyrinthine type acoustic metamaterial with micro-slit ….pdf
    ^^^^^^^                                                        ^^^^   去掉
    01405_5.5 The influence of unequal path lengths.pdf
    ^^^^^^                                                                去掉
    ```

    年份與書章編號留著會被當成「標題的詞」，兩篇同年的論文因此互相加分。

    ⚠ 檔名長到接近上限時**丟掉最後一個詞**：入庫時會截斷，最後一個字常是半個
       （`… part 1 - theoretical and`），而半個字永遠對不上任何標題。
    """
    stem = re.sub(r"\.pdf$", "", filename, flags=re.IGNORECASE)
    stem = re.sub(r"^\d{4}\s*-\s*", "", stem)
    stem = re.sub(r"^\d{5}_", "", stem)
    words = [w for w in re.findall(r"[a-z0-9]+",
                                   unicodedata.normalize("NFKD", stem).lower())
             if _keep(w)]
    if len(stem) >= TRUNCATED_AT and len(words) > MIN_WORDS:
        words = words[:-1]
    return frozenset(words)


def overlap(left: frozenset[str], right: frozenset[str]) -> float:
    """短的一方有多少比例被長的一方涵蓋。

    用「涵蓋率」而不是 Jaccard，因為兩邊長度本來就會差很多：知識庫的檔名被
    截到 48 字，Obsidian 的筆記標題常是縮寫。Jaccard 會把這種正確配對壓到很低。
    """
    shorter = left if len(left) <= len(right) else right
    return len(left & right) / len(shorter) if shorter else 0.0


def score(left: frozenset[str], right: frozenset[str]) -> float:
    """兩邊有多像；不夠格的一律 0。

    三道閘缺一不可 —— 各自擋掉一種實際發生過的誤判：
      詞數不足   `M Room Acoustics`（兩個字）不該去配任何長標題
      共同詞太少 同上，但擋的是「短的那邊剛好全中」
      涵蓋率不足 `Low-frequency broadband absorber…` 開頭相同的三篇
    """
    if min(len(left), len(right)) < MIN_WORDS or len(left & right) < MIN_SHARED:
        return 0.0
    ratio = overlap(left, right)
    return ratio if ratio >= MIN_OVERLAP else 0.0


def best_match[T](needle: str, haystack: list[tuple[frozenset[str], T]]) -> T | None:
    """找最像的一個。**並列就回 None** —— 分不出來時不要猜。"""
    words = significant_words(needle)
    ranked = sorted(((s, value) for other, value in haystack
                     if (s := score(words, other)) > 0),
                    key=lambda pair: -pair[0])
    if not ranked or (len(ranked) > 1 and ranked[0][0] == ranked[1][0]):
        return None
    return ranked[0][1]


def recorded_filename(item: dict[str, Any]) -> str | None:
    """外掛送檔案時寫進「其他」欄位的檔名 —— **有這個就不必猜標題**。

    ```
    lightrag: 2026 - Nonlinear Dynamics and Vibration Suppression ….pdf
    ```

    ⚠ 2026-08-14 實測只有 84/1083 筆有，所以它是**優先**訊號不是唯一訊號；
       沒有的還是得靠比對。要提高覆蓋率是外掛那邊的事，不是把書目標題改成
       跟檔名一樣 —— 標題是出版社的正式名稱，遷就檔名等於把對的改成錯的。
    """
    for line in (item["data"].get("extra") or "").splitlines():
        if line.strip().lower().startswith("lightrag:"):
            return line.split(":", 1)[1].strip() or None
    return None


def note_candidates(name: str, body: str) -> list[str]:
    """一篇筆記裡可能指向論文的字串。

    檔名不夠：`Li 2024 - HTTP Multifunctional Hybrid Lattice` 對應的論文全名
    完全不同。`## Sources` 段落裡寫的才是全名，所以那裡也要撈。

    ⚠ 不掃 `## Links`：那是概念之間的連結，掃進去會把「提到過」算成「深讀過」。
    """
    head = body.split("## Links")[0]
    match = NOTE_TITLE.match(name)
    found = [match.group("title") if match else name]
    sources = head.split("## Sources", 1)
    if len(sources) > 1:
        found += re.findall(r"`([^`]{20,})`", sources[1])
        found += re.findall(r"[-*]\s+(.{20,})", sources[1])
    return found


# ── 抓資料 ────────────────────────────────────────────────────────────────

def _get(url: str, headers: dict[str, str], *, method: str = "GET",
         body: object = None, timeout: int = 30) -> tuple[Any, dict[str, str]]:
    """送一個請求，回 (解析好的 JSON, 回應標頭)。

    `body` 收 `object`：能被 `json.dumps` 吃掉的都算數，這裡不需要更窄的型別。
    """
    data = json.dumps(body).encode() if body is not None else None
    if data:
        headers = {**headers, "Content-Type": "application/json"}
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
        return (json.loads(raw) if raw else None), dict(response.headers)


def zotero_items(api_key: str) -> list[dict[str, Any]]:
    """全庫的**文獻層**項目。子項目另外處理，見 `zotero_tagged_children`。"""
    headers = {"Zotero-API-Key": api_key, "Zotero-API-Version": "3"}
    rows: list[dict[str, Any]] = []
    while True:
        page, _ = _get(f"{ZOTERO_BASE}/items/top?"
                       + urllib.parse.urlencode({"format": "json", "limit": 100,
                                                 "start": len(rows)}), headers)
        if not page:
            return rows
        rows.extend(page)
        time.sleep(0.15)


def zotero_tagged_children(api_key: str) -> list[dict[str, Any]]:
    """身上帶著狀態標籤的筆記／附件 —— 這些標籤要清掉（血淚 4）。

    ⚠ `tag=` 查詢**不分大小寫**，所以退休的大寫版也會一起被撈到，這正是想要的；
       但**數量不能拿它當準**，要逐筆讀 tags 欄位。
    """
    headers = {"Zotero-API-Key": api_key, "Zotero-API-Version": "3"}
    query = " || ".join(sorted(KNOWN))
    rows: list[dict[str, Any]] = []
    while True:
        page, _ = _get(f"{ZOTERO_BASE}/items?"
                       + urllib.parse.urlencode({"format": "json", "limit": 100,
                                                 "start": len(rows), "tag": query}),
                       headers)
        if not page:
            return [r for r in rows if r["data"].get("parentItem")]
        rows.extend(page)
        time.sleep(0.15)


def kb_documents(workspace: str) -> list[str]:
    """LightRAG 知識庫裡的檔名清單。"""
    payload, _ = _get(f"{KBAPI}/kb/{workspace}/docs", {})
    return [doc["doc"] for doc in payload["documents"]]


def _dav(path: str, credential: str, *, method: str = "GET",
         depth: str = "1") -> str:
    auth = base64.b64encode(credential.encode()).decode()
    headers = {"Authorization": f"Basic {auth}", "Depth": depth}
    request = urllib.request.Request(DAV_BASE + urllib.parse.quote(path),
                                     headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", "replace")


def dav_walk(path: str, credential: str) -> list[str]:
    """遞迴列出 `.md`。跳過 `.` 開頭的目錄（`.obsidian`、`#recycle`）。"""
    import html

    body = _dav(path, credential, method="PROPFIND")
    hrefs = [html.unescape(urllib.parse.unquote(h))       # PROPFIND 回的是 XML
             for h in re.findall(r"<[Dd]?:?href>(.*?)</[Dd]?:?href>", body)]
    found: list[str] = []
    for href in hrefs:
        if href.rstrip("/") == path.rstrip("/"):
            continue
        if href.endswith("/"):
            if not Path(href).name.startswith((".", "#")):
                found += dav_walk(href, credential)
        elif href.endswith(".md"):
            found.append(href)
    return found


def obsidian_notes(credential: str) -> dict[str, str]:
    """10_Research 底下每一篇筆記的全文，鍵是不含副檔名的檔名。

    ⚠ **不先用檔名篩掉「不像論文」的。** `NIRO Composite Cost Function
       (Petrolli).md` 這種概念式命名一樣是深讀一篇論文寫出來的；用檔名篩，
       2026-08-14 實測會少算 12 篇。
    """
    notes: dict[str, str] = {}
    for path in dav_walk(DAV_NOTES, credential):
        for attempt in range(3):                      # NAS 偶爾把連線掐掉
            try:
                notes[Path(path).stem] = _dav(path, credential)
                break
            except urllib.error.HTTPError:
                break                                  # 檔案不見了，跳過
            except OSError:
                if attempt == 2:
                    raise
                time.sleep(1.5 * (attempt + 1))
    return notes


# ── 算差異 ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Change:
    """一筆要改的項目。`tags` 已經是完整陣列（血淚 2）。"""

    key: str
    title: str
    had: tuple[str, ...]
    now: tuple[str, ...]
    reason: str
    tags: list[dict[str, str]] = field(compare=False, default_factory=list)


def _rewrite(item: dict[str, Any], want: set[str], reason: str) -> Change | None:
    """算出這一筆的新 tags 陣列；沒變化就回 None。"""
    data = item["data"]
    current = {tag["tag"] for tag in data.get("tags", [])}
    keep = [tag for tag in data.get("tags", []) if tag["tag"] not in KNOWN]
    tags = keep + [{"tag": name} for name in sorted(want)]   # 省略 type ＝ 手動
    if {tag["tag"] for tag in tags} == current:
        return None
    return Change(key=data["key"], title=data.get("title", ""),
                  had=tuple(sorted(current & KNOWN)), now=tuple(sorted(want)),
                  reason=reason, tags=tags)


def documents_in_kb(items: list[dict[str, Any]], kb_docs: list[str]) -> set[str]:
    """哪些 Zotero 文獻真的在知識庫裡，回傳它們的 key。

    ⚠ **一份知識庫檔案最多屬於一筆文獻。** 兩筆同時配到同一份，至少有一筆是錯的
       —— 2026-08-14 實測 `Loudspeaker … Part 1` 與 `Part 2` 撞在一起，而庫裡
       只有 Part 2。搶同一份時取分數高的；同分就兩邊都不給（不猜）。
    """
    stored = set(kb_docs)
    index = [(kb_words(doc), doc) for doc in kb_docs]
    claims: dict[str, list[tuple[float, str]]] = {}
    for item in items:
        key, title = item["data"]["key"], item["data"].get("title", "")
        if (exact := recorded_filename(item)) and exact in stored:
            claims.setdefault(exact, []).append((2.0, key))   # 精確連結永遠贏
        elif (doc := best_match(title, index)) is not None:
            claims.setdefault(doc, []).append(
                (max(score(significant_words(title), words)
                     for words, name in index if name == doc), key))

    winners: set[str] = set()
    for holders in claims.values():
        holders.sort(key=lambda pair: -pair[0])
        if len(holders) == 1 or holders[0][0] > holders[1][0]:
            winners.add(holders[0][1])
    return winners


def plan_changes(items: list[dict[str, Any]], children: list[dict[str, Any]],
                 kb_docs: list[str], notes: dict[str, str],
                 *, prune: bool) -> list[Change]:
    """比對兩座知識庫，算出每一筆文獻該有哪些狀態標籤。

    `prune=False`（預設）時只補不刪：證據消失只可能是比對失敗或來源掉線，
    而把使用者手標的東西判掉，比少標一個嚴重得多（血淚 6）。
    """
    title_index = [(significant_words(item["data"].get("title", "")), item)
                   for item in items if item["data"].get("title")]

    read: set[str] = set()
    for name, body in notes.items():
        for candidate in note_candidates(name, body):
            if (hit := best_match(candidate, title_index)) is not None:
                read.add(hit["data"]["key"])
    in_kb = documents_in_kb(items, kb_docs)

    changes: list[Change] = []
    for item in items:
        current = {tag["tag"] for tag in item["data"].get("tags", [])} & KNOWN
        want = set()
        if item["data"]["key"] in in_kb:
            want.add(IN_KB)
        if item["data"]["key"] in read:
            want.add(DEEP_READ)
        if not prune:
            want |= current & STATUS_TAGS
        if (change := _rewrite(item, want, "依兩座知識庫重算")) is not None:
            changes.append(change)

    changes += [c for child in children
                if (c := _rewrite(child, set(), "子項目：狀態標籤不掛這裡")) is not None]
    return changes


# ── 寫入 ──────────────────────────────────────────────────────────────────

def write_backup(items: list[dict[str, Any]], children: list[dict[str, Any]],
                 destination: Path) -> int:
    """動手前的還原點。**這不是可有可無的** —— 2026-08-14 就是靠它救回 163 筆。"""
    snapshot = [{"key": row["data"]["key"], "version": row["version"],
                 "itemType": row["data"]["itemType"],
                 "title": row["data"].get("title", ""),
                 "tags": row["data"].get("tags", [])}
                for row in [*items, *children]]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1),
                           encoding="utf-8")
    return len(snapshot)


def apply_changes(changes: list[Change], by_key: dict[str, dict[str, Any]],
                  api_key: str) -> tuple[int, list[dict[str, Any]]]:
    """批次寫回 Zotero（一次最多 50 個物件）。

    ⚠ 送的是**完整的 data 物件**、只換掉 tags —— 多物件寫入是整份取代，
       自己拼一個精簡版會把其他欄位清掉。
    """
    headers = {"Zotero-API-Key": api_key, "Zotero-API-Version": "3"}
    payload = [dict(by_key[c.key]["data"], tags=c.tags) for c in changes]
    written, failed = 0, []
    for start in range(0, len(payload), 50):
        chunk = payload[start:start + 50]
        try:
            result, _ = _get(f"{ZOTERO_BASE}/items", headers,
                             method="POST", body=chunk)
            written += len(result.get("success", {}))
            failed += [{"key": chunk[int(i)]["key"], **err}
                       for i, err in result.get("failed", {}).items()]
        except urllib.error.HTTPError as error:
            failed.append({"batch": start, "code": error.code,
                           "body": error.read().decode()[:300]})
    return written, failed


# ── CLI ───────────────────────────────────────────────────────────────────

def _report(changes: list[Change], items: list[dict[str, Any]]) -> None:
    tally: dict[tuple[str, str], int] = {}
    for change in changes:
        slot = (",".join(change.had) or "（無）", ",".join(change.now) or "（無）")
        tally[slot] = tally.get(slot, 0) + 1
    print(f"\n要改 {len(changes)} 筆：")
    for (had, now), count in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"  {count:5d}  {had:<28} → {now}")
    current = {tag["tag"] for item in items
               for tag in item["data"].get("tags", [])} & RETIRED
    if current:
        print(f"\n⚠ 還有退休標籤在用：{sorted(current)}")


def _secret(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"缺少環境變數 {name}（見本檔開頭「秘密從哪來」）")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("check", "apply"))
    parser.add_argument("--workspace", default="acoustics_v2")
    parser.add_argument("--prune", action="store_true",
                        help="連「找不到證據的」也一併移除（預設只補不刪）")
    parser.add_argument("--json", type=Path, help="差異另存成 JSON")
    parser.add_argument("--backup", type=Path,
                        default=REPO / "verdicts" / "zotero-tags-backup.json")
    args = parser.parse_args()

    api_key = _secret("ZOTERO_API_KEY")
    credential = _secret("OBSIDIAN_DAV")

    print("讀取中……", file=sys.stderr)
    items = zotero_items(api_key)
    children = zotero_tagged_children(api_key)
    kb_docs = kb_documents(args.workspace)
    notes = obsidian_notes(credential)
    print(f"Zotero 文獻 {len(items)} 筆（另有 {len(children)} 個子項目帶著標籤）；"
          f"知識庫 {len(kb_docs)} 份；Obsidian 筆記 {len(notes)} 篇")

    changes = plan_changes(items, children, kb_docs, notes, prune=args.prune)
    _report(changes, items)
    if args.json:
        args.json.write_text(json.dumps(
            [{"key": c.key, "title": c.title, "had": list(c.had),
              "now": list(c.now), "reason": c.reason} for c in changes],
            ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"差異寫進 {args.json}")

    if args.command == "check":
        return 0
    if not changes:
        print("沒有要改的。")
        return 0

    print(f"\n備份 {write_backup(items, children, args.backup)} 筆 → {args.backup}")
    by_key = {row["data"]["key"]: row for row in [*items, *children]}
    written, failed = apply_changes(changes, by_key, api_key)
    print(f"寫入成功 {written} 筆，失敗 {len(failed)} 筆")
    for entry in failed[:10]:
        print(f"  {entry}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
