"""拖曳上傳失敗時必須說話。

**2026-08-17 實測踩到的：** PO 說「拖一本書的 PDF 進去沒反應」，而伺服器紀錄裡
**一次連線都沒有**。原因是這一行：

    if (e.dataTransfer && e.dataTransfer.files.length) send(e.dataTransfer.files);

拖進來的東西沒有 File 物件時（從另一個瀏覽器分頁拖、從雲端硬碟網頁拖），
`files.length` 是 0 —— 整個 drop **靜靜地什麼也不做**：不送請求、不顯示訊息。
使用者只看得到「沒反應」，而且無從得知為什麼。

⚠ 這裡只能做字串層級的檢查（瀏覽器 JS 跑不起來），所以它證明的是
「那段程式碼在」，不是「它在瀏覽器裡真的會動」。真正的驗證是部署後實拖一次。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from intake import JS  # noqa: E402


def test_a_drop_with_no_files_is_not_a_silent_no_op() -> None:
    """沒有檔案的 drop 要講話，不能靜靜地什麼都不做。

    這是 PO 實際踩到的那一格：從瀏覽器分頁或雲端硬碟拖過來的東西沒有 File 物件，
    舊版直接跳過整個分支 —— 沒有請求、沒有訊息、沒有任何痕跡。
    """
    assert "files.length" in JS
    assert "else" in JS, "沒有檔案時要有一條路，不能只有 if"
    assert "拖不進來" in JS, "要講人話說明發生什麼事"


def test_the_message_tells_the_user_what_to_do_instead() -> None:
    """訊息要給出路 —— 只說「失敗」等於把人丟在原地。

    可行的替代路徑是頁面上本來就有的「選擇檔案」挑選器（`#picker`），
    它拿到的一定是真的 File。
    """
    assert "選擇檔案" in JS


def test_the_upload_says_it_started_before_it_finishes() -> None:
    """按下去要**立刻**有話說，不能等傳完才出聲。

    2026-08-17 實測：PO 拖一本 20 MB 的教科書，傳輸要好幾秒，而這幾秒之內畫面
    完全安靜 —— 使用者只能解讀成「沒反應」，然後去重新整理或再拖一次，
    而**重新整理會把正在傳的上傳掐斷**（實測就是這樣斷在 2.1 MB / 20.5 MB）。

    所以「開始傳了」這句話不只是禮貌，它直接防止使用者做出弄壞它的動作。
    """
    assert "傳送中" in JS


def test_a_cancelled_upload_says_so_in_plain_words() -> None:
    """傳到一半被中斷要講清楚是怎麼回事，並叫人不要在傳的時候換頁。

    伺服器那邊已驗證 20 MB 收得下（curl 實測 201），所以這一格是瀏覽器端被打斷，
    訊息必須指向正確的原因，不然使用者會一直重試同一個會失敗的動作。
    """
    assert "不要重新整理" in JS
