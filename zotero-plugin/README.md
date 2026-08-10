# LightRAG 收件匣（Zotero 外掛）

在 Zotero 裡選文獻 → 右鍵「送進 lightrag 收件匣」→ 打上標籤。

**取代的是「自己拖檔案 + 自己打標」這兩個手動動作**，不多做別的判斷。

## 裝法

```bash
./make-xpi.sh                       # 產生 lightrag-inbox-0.1.0.xpi
```

Zotero → 工具 → 附加元件 → 齒輪 → Install Add-on From File → 選那個 `.xpi`。

⚠ **要 Zotero 8 以上。** Zotero 8 起選單走 `Zotero.MenuManager`，7 以前的
自己塞 DOM 那套沒有寫在這裡。

⚠⚠ **裝不上的第一個要看的地方是 `manifest.json` 的 `strict_max_version`。**
Zotero 比對這個值，比執行中的版本小就**直接拒裝**，而且訊息不會告訴你是哪一行。
2026-08-10 就是這樣：寫 `9.*` 而 PO 跑的是 10 beta。升級到 11 之後把那個數字
改掉再 `./make-xpi.sh` 就好 —— 這是升級後唯一要動的地方。

## 設定

沒設過就用預設值。要改：Zotero → 設定 → 進階 → 設定編輯器，搜 `lightrag`。

| 鍵 | 預設 | 是什麼 |
|---|---|---|
| `extensions.zotero.lightrag.server` | `http://100.87.88.7:9710` | 審核台的網址（Tailscale 內網） |
| `extensions.zotero.lightrag.tag` | `_toRaged` | 送成功之後打的標籤 |

## 標籤的意思是「送出去了」，不是「已經進知識庫」

送進收件匣之後還要解析、過規格、抽取，而且**可能被擋下來等你看**。
Zotero 這邊看不出來 —— 要對帳的話，審核台上「失敗／等你看」那兩格就是差集。

## 一次送很多份會怎樣

| 伺服器回什麼 | 外掛做什麼 |
|---|---|
| 201 進了收件匣 | 打標籤 |
| 409 已經在收件匣／已經進知識庫了 | **還是打標籤**（不打的話看起來像沒送成功，你會一直重按） |
| 其他 | 不打標籤，列在結果視窗上 |
| 沒有 PDF 附件、檔案不在本機 | 算「跳過」，列出來 |

**一份出事不會擋住其餘的。** 結束時跳一個視窗說「送進去 n／已經在裡面 n／
跳過 n／失敗 n」，有問題就逐條列出來 —— 只給數字看不出來要去修哪一筆。

去重不在這裡做：伺服器用**內容雜湊**比對，同一份改名再傳一樣會被擋。

## 驗過什麼、沒驗什麼

```
✅ 檔名怎麼組出來的        node --test zotero-plugin/tests/*.test.js（10 條）
✅ 上傳端點的行為          tests/test_intake.py 那一族（伺服器側）
❌ 外掛本身                沒驗 —— 這裡沒有 Zotero 跑得起來
```

⚠ **第一次按下去很可能要修一兩個地方**（API 名稱、選單位置、fetch 的行為）。
出事先看 Zotero 的偵錯輸出：說明 → 偵錯輸出記錄 → 檢視輸出，搜 `lightrag-inbox`。

## 檔案

```
manifest.json               外掛身分與相容版本
bootstrap.js                生命週期、選單、送出流程
lib/filename.js             檔名怎麼組（純函式，唯一測得到的部分）
locale/en-US/*.ftl          選單標籤（Zotero 8 起只能走語言檔）
tests/filename.test.js      node 測試
```
