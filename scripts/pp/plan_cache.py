"""算過的處理計畫記起來，檔案沒變就不重算。

**為什麼需要它**：2026-08-18 把「還有幾份要確認」加進審核台首頁之後，PO 當場
感覺到變慢 ——「為什麼覺得登入網路的反應變好慢」。因為那個數字每次都要重算
全部 317 份的計畫，dker 實測 **4.71 秒**，跟頁面變慢的秒數一模一樣。

⚠ **之前的碼裡刻意寫著「不做快取，因為快取要處理失效」。** 那個判斷在
「只有確認清單那一頁會用到」的前提下是對的；一旦它上了首頁，前提就變了。
**判斷會過期，理由要跟著重看，不要只看結論。**

失效只認一件事：**檔案的改動時間 ＋ 大小**。兩個一起看，因為有些檔案系統的
時間戳解析度很粗，同一秒內改兩次只靠時間戳看不出來。
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Container
from pathlib import Path

logger = logging.getLogger(__name__)

#: 檔案指紋：``(改動時間, 大小)``。**不是內容雜湊** —— 算雜湊要把整份讀進來，
#: 那正是這個快取想省掉的成本。
Stamp = tuple[int, int]


class PlanCache:
    """一份文件一格。**執行緒安全** —— 審核台是 `ThreadingHTTPServer`。"""

    def __init__(self) -> None:
        self._entries: dict[Path, tuple[Stamp, dict]] = {}
        self._lock = threading.Lock()

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._entries)

    def get(self, path: Path, stamp: Stamp, compute: Callable[[], dict]) -> dict:
        """拿這份文件的計畫。指紋一樣就用記著的，不一樣就重算。

        ⚠ **`compute` 刻意在鎖外面跑。** 算一份要十幾毫秒，抱著鎖算的話
        多執行緒會排隊排成單執行緒，等於沒有多開。代價是同一份可能被兩個
        請求同時算 —— 算兩次的結果一樣，浪費一次，比全部排隊便宜。
        """
        with self._lock:
            hit = self._entries.get(path)
            if hit is not None and hit[0] == stamp:
                return hit[1]

        plan = compute()

        with self._lock:
            self._entries[path] = (stamp, plan)
        logger.debug("重算 %s 的計畫（指紋 %s）", path.name, stamp)
        return plan

    def keep_only(self, alive: Container[Path]) -> None:
        """把已經不存在的文件從快取清掉。

        ⚠ 這一條是為了**整顆碟被清空**那天：舊庫刪掉之後，快取如果還抱著
        317 份的計畫，畫面會繼續顯示已經不存在的文件，而且不會報錯。
        """
        with self._lock:
            gone = [p for p in self._entries if p not in alive]
            for path in gone:
                del self._entries[path]
        if gone:
            logger.info("有 %d 份文件不見了，從計畫快取清掉", len(gone))
