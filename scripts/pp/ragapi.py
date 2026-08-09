"""LightRAG HTTP API 的客戶端。**問容器本人，不在容器外重寫第二份。**

鐵則第 3 條：「LightRAG 的行為用 `pp/oracle.py` 問容器本人，不推測、也不在容器外
重寫第二份。」這個檔是同一條原則在「改圖譜」這一側的實作 —— 刪節點、合併實體、
查子圖一律走官方端點，不直接對 Postgres 下 DELETE。直接下 SQL 的話，向量表、
圖節點表、圖邊表三者要自己維持一致，而那個一致性是 LightRAG 自己的內部契約。

**這個類別原本長在 `entity-merge.py` 裡。** 2026-08-09 寫 `graph-clean.py` 時搬出來，
因為第二支要動圖譜的腳本如果自己再寫一份 `_req`，兩份的逾時、標頭、錯誤處理就會
各自漂走 —— 那正是 2026-08-08 審核台六個洞的形狀。行為逐字不變，只補了型別註解
與兩個新方法（`delete_entity`、`entity_exists`）。
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import Final


def _as_list(value: object, what: str) -> list[object]:
    """回傳必須是陣列。不是就當場炸掉，不要回空陣列。

    回空陣列的話「API 換了形狀」與「圖譜真的是空的」在呼叫端長得一模一樣 ——
    而本專案踩過的坑有一半是這種形狀（乾淨的 0 要先當成量錯，鐵則第 7 條）。
    """
    if not isinstance(value, list):
        raise RuntimeError(f"{what} 預期陣列，實際是 {type(value).__name__}")
    return value


def _as_dict(value: object, what: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise RuntimeError(f"{what} 預期物件，實際是 {type(value).__name__}")
    return value


class Rag:
    """對單一 LightRAG 實例的呼叫。位址從 `BIND_ADDR` 來，不寫死 localhost。"""

    # 這個值同時是「回傳上限」與「靜默截斷點」。原本設 60，實測
    # Acoustic Pressure 有 69 條邊，備份只存到 59 條而且不報錯 —— 備份少存邊
    # 這種事，發現的時機通常是「要回復的時候」。呼叫端必須自己比對回傳筆數。
    SUBGRAPH_CAP: Final[int] = 1000

    def __init__(self, env: Mapping[str, str]) -> None:
        self.host = f"http://{env.get('BIND_ADDR', '100.87.88.7')}:{env.get('HOST_PORT', '9621')}"
        self.key = env.get("LIGHTRAG_API_KEY", "")

    def _req(self, path: str, method: str = "GET",
             body: object | None = None, timeout: int = 240) -> object:
        r = urllib.request.Request(
            self.host + path, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"X-API-Key": self.key, "Content-Type": "application/json"})
        with urllib.request.urlopen(r, timeout=timeout) as resp:  # noqa: S310
            return json.loads(resp.read() or "{}")

    def labels(self) -> list[str]:
        return [str(x) for x in _as_list(self._req("/graph/label/list"), "label/list")]

    def popular(self, n: int) -> list[str]:
        return [str(x) for x in _as_list(self._req(f"/graph/label/popular?limit={n}"),
                                         "label/popular")]

    def subgraph(self, label: str) -> dict[str, object]:
        return _as_dict(
            self._req(f"/graphs?label={urllib.parse.quote(label)}"
                      f"&max_depth=1&max_nodes={self.SUBGRAPH_CAP}", timeout=180),
            "graphs")

    def merge(self, sources: list[str], target: str) -> dict[str, object]:
        return _as_dict(
            self._req("/graph/entities/merge", "POST",
                      {"entities_to_change": sources,
                       "entity_to_change_into": target}, timeout=300),
            "entities/merge")

    def delete_entity(self, name: str) -> dict[str, object]:
        """刪一個實體。**LightRAG 沒有 undo，呼叫前必須有備份。**

        端點只吃 `entity_name`，邊由 LightRAG 自己連帶處理 —— 這是 2026-08-09 從
        dker 上跑著的那台的 `openapi.json` 讀到的契約（`DeleteEntityRequest` 只有
        一個必填欄位）。**不要自己再去刪邊**：那等於在容器外重做它的內部一致性。
        """
        return _as_dict(
            self._req("/graph/entity/delete", "DELETE", {"entity_name": name}, timeout=120),
            "entity/delete")

    def entity_exists(self, name: str) -> bool:
        d = _as_dict(self._req(f"/graph/entity/exists?name={urllib.parse.quote(name)}"),
                     "entity/exists")
        return bool(d.get("exists"))

    def pipeline_idle(self) -> bool:
        return not _as_dict(self._req("/health"), "health").get("pipeline_busy")

    def entities_for(self, query: str, top_k: int) -> list[str]:
        # chunk_top_k=1：我們只要實體清單，不需要原文。設 0 會被當成「不限制」，
        # 所以給 1 —— 少搬幾十 KB 的 chunk 過來。
        d = _as_dict(self._req("/query/data", "POST",
                               {"query": query, "mode": "mix", "only_need_context": True,
                                "top_k": top_k, "chunk_top_k": 1}), "query/data")
        data = _as_dict(d.get("data") or {}, "query/data.data")
        out: list[str] = []
        for e in _as_list(data.get("entities") or [], "query/data.entities"):
            name = _as_dict(e, "entity").get("entity_name")
            if name:
                out.append(str(name))
        return out
