---
title: 重建檢查表 — 新環境必須保持什麼樣子
date_created: 2026-08-07
date_modified: 2026-08-07
status: accepted
kind: spec
supersedes: "docs/rebuild-2026-08/（整套方案文件，2026-08-07 刪除）"
superseded_by: ""
summary: "從 173 條坑清單裡提煉出唯一在乾淨重建後仍然成立的 13 條。其餘 151 條隨舊結構一起走。"
---

# 重建檢查表

**這份是 173 條坑清單唯一值得帶過來的東西。** 其餘 151 條的成因是舊結構
（雙 workspace、v155 遺跡、`/data/rag`、DeepTutor 共用實例、舊語料體檢表），
結構換掉就不存在，所以隨舊結構一起刪掉了（`git log` 可回溯）。

這 13 條會活下來，因為它們講的是**外部的東西必須保持某個樣子**——換一次環境不會改變。

**8 條的執行者是「沒有人」，而它們全部壞得很安靜。** 那是這份表存在的理由。

---

## A. `.env` 的值（壞掉不報錯，全部沒有人守）

| 鍵 | 必須是 | 壞掉的症狀 |
|---|---|---|
| `MINERU_IS_OCR` | `true` | 文字層路徑靜默吃掉 x-height 字母（a c e g m n o r s u w y），**對文字層完好的非掃描 PDF 最嚴重**。實測 43 個掉字裡 40 個是 x-height |
| `MINERU_MODEL_VERSION` | `pipeline` | 預設的 `vlm` 讓 16/57 表格區域完全空白（同檔同 `is_ocr` 實測），連圖片備份都沒有 |
| `ENTITY_EXTRACTION_USE_JSON` | `true` | 本機 4-bit 模型的關係記錄只吐 4/5 欄位 ⇒ LightRAG **100% 拒收**。症狀是「實體正常、關係 0」 |
| `EMBEDDING_SEND_DIM` | **只有在 `EMBEDDING_DIM` ≠ 模型原生維度時才必要** | 它管的是「要不要把 `dimensions` 參數送給 API」。設了較小的 `EMBEDDING_DIM` 卻沒送，API 仍回原生維度，LightRAG 誤判成雙倍向量數，**索引寫入時才失敗**，錯誤訊息不指向根因。⚠ 2026-08-07 更正：舊版寫成無條件必要，那是錯的——現行 `EMBEDDING_DIM=3072` 就是 `text-embedding-3-large` 的原生維度，不需要截斷，所以這個鍵缺席是對的 |
| `PP_EYE_C_PROVIDER` | 明確指定，不能空 | OpenRouter 同一模型 ID 會被路由到不同供應商 ⇒ 分不清差異是模型錯還是換了後端，交叉驗證的前提被破壞 |
| `KBAPI_PORT` | 在 `.env`（不進版控） | 不能改用 compose `profiles:` 停用 kbapi——那會隨版控進主線，下次 `up -d` 就不起 kbapi，:9700 靜靜消失、三個 skill 一起啞 |

**怎麼驗**：這六個都要在重建後有一條斷言。目前只有 `MINERU_MODEL_VERSION` 被間接守著
（`compat-check` 的 A-11 比對 `options_signature`，而簽章涵蓋 `model_version`）。
其餘五個沒有任何程式讀或斷言。

⚠ `scripts/pp/oracle.py` 的 `mineru_options()` **可以問出容器實際的值，但它是死程式——
全 repo 零呼叫端**。重建時把它接上，那六條就有執行者了。

## A2. 新機器上要先存在的目錄（2026-08-08 加）

| 要什麼 | 誰建 | 不建會怎樣 |
|---|---|---|
| `${DATA_ROOT}/inbox` | **沒有人**——要手動 `mkdir` | intake 的 `source_warnings` 會抱怨、收不到任何候選檔 |
| `${DATA_ROOT}/.lightrag-data-root` | **沒有人**——要手動 `touch` | `compat-check` 的 A-34 會 hard FAIL 說「資料根不是專用磁碟」，動不了工 |

## A3. 資料根是一顆掛載點，而且是 USB 外接的（2026-08-09 加）

2026-08-09 起 `${DATA_ROOT}` 本身就是一顆 1TB SSD 的掛載點。**掛成同一個路徑是
刻意的**：compose、`.env`、`DataPaths` 的預設值、三個 skill 的 URL 全都不必改。

**USB 會掉，而掉了的預設結果是「安靜地寫到別的地方」** —— 沒掛上時 `${DATA_ROOT}`
就是底層磁碟上的一個空目錄，LightRAG 看到空的資料根會建一個新的空知識庫**而且不報錯**。
所以有三道，缺一不可：

| 手段 | 擋哪一種 | 在哪 |
|---|---|---|
| 掛載點目錄設 `root:root` mode `000` | 沒掛上時立刻權限錯誤，而不是看到空目錄 | 手動設，**新機器要記得** |
| fstab 帶 `errors=remount-ro` | 跑到一半掉線 → 檔案系統轉唯讀，不繼續往壞碟寫 | `/etc/fstab` |
| `lightrag-mount-guard.service`（`BindsTo=` 掛載單元） | 掛載點消失 → 停掉**本專案的四個**容器 | systemd |

⚠ **`nofail` 要保留。** 拿掉的話掛不上會掉進 emergency mode，而這台只能 ssh —— 那比
原本要防的問題更糟。
⚠ **不要把 `docker.service` 綁在這個掛載點上。** 那會讓 dockge／backrest／roonserver／
samba／nginx／hbbs 這些**別的專案的容器**也跟著起不來。守衛只停我們自己的。
⚠ `backrest` 把整個 `/data` 綁進它的 mount namespace，所以 `umount ${DATA_ROOT}` 會說
`target is busy`。要卸載得用 `umount -l`，或先停 backrest（**別人的容器，不要碰**）。

執行者是 `compat-check` 的 A-34，**而且它排在「連上容器」之前** —— 硬碟不見時容器也會
連不上，排在後面的話畫面只會說「容器連不上」（症狀），永遠印不出「碟不在」（原因）。

**為什麼不讓 intake 自己建**：`--source` 是**來源白名單**。自動建的話，路徑打錯
（`/data/lightrg/inbox`）會安靜地建出一個空目錄然後「正常運作」——永遠收不到檔，
而畫面上一切正常。**警告比自動修復好**，因為打錯路徑是人的錯，不是缺目錄。

其餘目錄（`library/`、`intake/jobs/`、`work/parsed/`、`inputs/<ws>/`）intake 啟動時
自己建，不必列在這裡。

## B. 部署契約（沒有人守）

| 要保持什麼 | 壞掉的症狀 |
|---|---|
| 映像用 `@sha256:` digest 釘選，不用 tag | compose 一個字沒改卻拉到不同映像，升級變成某次重啟的副作用。**沒有任何檢查斷言它必須是 digest 形式** |
| VLM 轉錄快取的鍵含裁圖 sha256 | 改了裁圖範圍卻讀到舊轉錄，內容與圖不符且不報錯。改 prompt 要手動清快取 |
| 藍桶 9 條工程基線 | repo 內零 lint、零 type-check、零 CI。2026-08-07 已裝 pre-commit（只擋 commit 格式） |

## C. 已經有執行者的（重建時要確認沒斷）

| 要保持什麼 | 誰在守 |
|---|---|
| 每一句 SQL 都帶 `workspace` | `tests/test_rebuild.py` 等三支測試斷言 SQL 字串含 `where workspace =`，走 `run-tests.sh` → `daily-check` |
| 用自己的資料庫實例，不與別的專案共用 | 結構性（沒有別的庫）＋ `A-26` 每日比對 API 與 Postgres 的文件母體 |
| LightRAG 的行為問容器本人，不在容器外重寫一份 | `A-06` 逐字比對 `apply.py` 的 `TEXT_FIELDS` 與容器內的實際欄位。**但「不得新增第二套實作」本身沒有守衛** |
| 某支檢查超標時印出前例，不要求人記得去哪找 | `scripts/pp/findings.py` ＋ `tests/verified-findings.json`，數字偏離查證當時 >50% 時改說「要重查」 |

---

## 這份表自己的執行者

**目前沒有。** 重建時要決定：把 A 那六條變成 `compat-check` 的斷言（那是它存在的目的——
把假設變成可執行的東西），或者接受它們是靠人記得的。

**判準只有一條**：任何規則要進規則區，先回答「違反時誰會發現」。答不出來就不算規則。
