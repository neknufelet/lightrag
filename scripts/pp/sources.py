r"""讀來源登記檔：這份文件屬於哪個來源，以及登記本身可不可信。

## 為什麼有這支

`eq-dup` 原本**從檔名推論**來源，五類全錯（理由與逐類證據在 `scripts/source-map.py`
的檔頭）。改成讀一份人核過的資料，而**這支是唯一的讀取者** —— 不要在別處再解析
一次那個 JSON，本專案已經被「同一件事兩個地方」咬過五次。

## fail-safe 的方向：寧可少報，不要假報

查不到登記的文件回 `None`（unknown），而 **unknown 永遠不計入「跨了幾個來源」**。
少報只是漏掉一條線索；假報會讓人去查一個不存在的分歧，那更貴。

⚠ **登記檔不存在時不是「全部通過」，是全部 unknown。** 整份報告會安靜地變空 ——
所以 `reconcile()` 一定要被呼叫、數字一定要印出來。這個專案七個 bug 都是同一形狀：
工具報「N 筆」而 N 的母體根本不是真的母體。

## 雜湊是守衛不是鍵

鍵是檔名（重建時檔名留著、雜湊會變，拿雜湊當鍵會整份失聯）。雜湊用來抓
「登記在、但檔案被換過」—— 對不上就降成 unknown 並報出來，不自動接受。
⚠ 雜湊**不在這裡算**，讀體檢表的 `pdf_sha256`（有權威來源時不得自己重算）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .paths import DataPaths

DEFAULT_MAP_PATH = Path(__file__).resolve().parent.parent.parent / "verdicts" / "source-map.json"


def ledger_hashes(root: Path) -> dict[str, str]:
    """體檢表記的 `檔名 → pdf_sha256`。**權威來源，這裡只讀不算。**"""
    out: dict[str, str] = {}
    led = DataPaths(root).ledger_dir
    if not led.is_dir():
        return out
    for rec in sorted(led.glob("*.json")):
        data = json.loads(rec.read_text(encoding="utf-8"))
        doc = str(data.get("doc") or rec.name).removesuffix(".json").removesuffix(".pdf")
        if digest := data.get("pdf_sha256"):
            out[doc] = str(digest)
    return out


@dataclass(frozen=True)
class Reconciliation:
    """母體對帳的結果。**每一格都要印出來**，不然少掉的那些沒有人會發現。"""

    corpus: int
    registered: int
    hash_ok: int
    hash_changed: list[str] = field(default_factory=list)
    unregistered: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)
    no_ledger: list[str] = field(default_factory=list)

    @property
    def usable(self) -> int:
        """真正算得進「跨來源」的份數。**這才是報告該印的母體。**"""
        return self.hash_ok

    def line(self) -> str:
        return (f"語料 {self.corpus} 份／已登記 {self.registered}／雜湊對得上 {self.hash_ok}"
                f"　⚠ 檔案換過 {len(self.hash_changed)}、未登記 {len(self.unregistered)}、"
                f"體檢表沒有 {len(self.no_ledger)}（這些都不計入跨來源）")


class SourceMap:
    """人核過的來源登記。**沒有推論，只有查表。**"""

    def __init__(self, sources: dict[str, dict], documents: dict[str, dict]) -> None:
        self._sources = sources
        self._documents = documents
        self._root = self._build_merges(sources)
        self._trusted: set[str] | None = None

    @staticmethod
    def _build_merges(sources: dict[str, dict]) -> dict[str, str]:
        """`same_work_as` 併成等價類。

        ⚠ 這裡**確實做傳遞閉包**，而 `eq-dup` 的 Tier B 刻意不做 —— 差別在於
        這些是**人明講的**「這兩個是同一部作品」，不是相似度算出來的。
        相似度的傳遞會造出讀不了的假等價類，人工宣告不會。
        """
        root: dict[str, str] = {s: s for s in sources}

        def find(x: str) -> str:
            while root.setdefault(x, x) != x:
                root[x] = root[root[x]]
                x = root[x]
            return x

        for sid, meta in sources.items():
            for other in meta.get("same_work_as") or []:
                a, b = find(sid), find(str(other))
                if a != b:
                    root[a] = b
        return {s: find(s) for s in root}

    @classmethod
    def load(cls, path: Path = DEFAULT_MAP_PATH) -> SourceMap:
        """檔案不在就回空的 —— **全部 unknown，不是全部通過。**"""
        if not path.is_file():
            return cls({}, {})
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(dict(data.get("sources") or {}), dict(data.get("documents") or {}))

    def reconcile(self, corpus: list[str], hashes: dict[str, str]) -> Reconciliation:
        """對帳：語料、登記檔、體檢表三邊。**先跑這個，再信任何來源分組。**"""
        changed, unreg, no_led = [], [], []
        ok = 0
        for doc in corpus:
            entry = self._documents.get(doc)
            if entry is None:
                unreg.append(doc)
                continue
            digest = hashes.get(doc)
            if digest is None:
                no_led.append(doc)
            elif entry.get("pdf_sha256") and entry["pdf_sha256"] != digest:
                changed.append(doc)
            else:
                ok += 1
        self._trusted = {d for d in corpus if d not in set(changed) | set(unreg) | set(no_led)}
        return Reconciliation(
            corpus=len(corpus),
            registered=sum(1 for d in corpus if d in self._documents),
            hash_ok=ok, hash_changed=sorted(changed), unregistered=sorted(unreg),
            stale=sorted(set(self._documents) - set(corpus)), no_ledger=sorted(no_led))

    def source_of(self, doc: str) -> str | None:
        """來源 id；沒登記、或對帳沒過關的，回 `None`（unknown）。

        ⚠ **沒跑過 `reconcile()` 就查，一律回 None。** 「沒對帳」與「對過帳且乾淨」
        必須長得不一樣，否則忘了對帳會安靜地變成「全部可信」。
        """
        if self._trusted is None or doc not in self._trusted:
            return None
        entry = self._documents.get(doc) or {}
        sid = entry.get("source")
        return self._root.get(str(sid), str(sid)) if sid else None

    def label(self, source_id: str) -> str:
        return str((self._sources.get(source_id) or {}).get("label") or source_id)
