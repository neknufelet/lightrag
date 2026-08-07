# C Equivalent Networks：「bbox 未覆蓋」91 詞的歸因

**這份是材料，不修任何東西。** C waiver 決策前的最後一塊拼圖 ——
逐區塊歸因把 C 的漏詞分到 table 163、image 73、**bbox 未覆蓋區域 93**、
equation 19、text 16，其中「bbox 未覆蓋」是唯一沒被拆開看過的一塊。

產生於 2026-08-02（階段 2.7 收尾，Opus 執行）。方法：`pdftotext -bbox-layout`
取每個詞的座標，換算到 content_list 的 0–1000 正規化空間，扣掉**任何 item 的
bbox 蓋得到的**、再扣掉**該頁所有 item 文字裡本來就有的**，剩下的就是這一類。

## 0. 一頁摘要

| | |
|---|---|
| 詞數 | **91**（不是 93 —— 見 §3） |
| 分佈 | 24 頁，全部在 p26–p66（表格區） |
| 全部是什麼 | **表格／圖片的標題與續頁標籤**。一個正文句子都沒有 |
| 佔 C 殘餘 381 詞 | 24% |
| 可修嗎 | 見 §4：A 類機械可修、B 類要重裁圖、C 類是 MinerU 整塊沒 OCR |

## 1. 三類，加起來就是全部

| 類 | 詞數 | 頁 | 是什麼 |
|---|---:|---:|---|
| **A** 跨頁續表的 `continued` | **19** | 19 | 「Table N **continued**」的續頁標籤 |
| **B** 表格標題行 | **19** | 5 | 「Table N **Medium wide** … **front**／**rear**」等 |
| **C** 整塊只發成 image 的區域 | **53** | 2（p33、p51） | 圖說與表格說明被 MinerU 讀成亂碼 |

### A：`continued` × 19（19 頁各一個）

C 的表格大量跨頁，每一頁頂端或底部有一行 `Table 12 continued`。
MinerU 把表格本體發出來了，但**這一行不在任何 item 的 bbox 裡**。
它是漏詞榜上 `continued(20)` 的來源（榜上 20、這裡 19，差 1 在別的區塊）。

出現位置固定：Y≈128（頁頂）或 Y≈846–854（頁底），與書眉/頁尾同一帶。

### B：表格標題行 × 19（5 頁）

`medium`(5)、`wide`(5)、`front`(3)、`rear`(2)、`field`、`formulation`、
`changes`、`table` 各 1。落在 p31／p34／p49／p62／p64。
這些是「Table 8 Medium wide round neck … front side」這種**表格標題整行**，
與 A 同一個成因：標題行在表格 bbox 之外，而 MinerU 沒有為它開一個 item。

### C：p33 與 p51 —— MinerU 把整塊發成 image（53 詞）

這兩頁是唯一有**實質內容**流失的地方，而且不是「沒發出來」，是**發成了亂碼**：

```
p33  #411 image  bbox=[93,250,512,575]   caption 空
     #412 image  bbox=[93,605,512,932]   caption='-rxa  e - io  e e d  sor b = = = s = = : 00.'
     （整頁只有 2 個 image ＋ header ＋ page_number，沒有任何 text/table item）
p51  #486 table  bbox=[148,114,494,938]  caption=['Tae  r  -b ber', 'Tabnnune c nnued']
     #487 image  bbox=[569,717,883,936]
```

`'-rxa e - io e e d sor b'`、`'Tae r -b ber'`、`'Tabnnune c nnued'` ——
這是 README 記過的 **mangled** 型（同 p64 的 `Ab = = ze = etsosbd) te se`），
不是缺字，是 OCR 把字讀爛了。所以這 53 詞在文字層有、在 content_list 裡
以亂碼的形式「存在」，比對不上。

p33 漏的 18 詞：`example sound pressure axial particle velocity matching
orifice medium wide neck round chamber with absor layer …`
p51 漏的 36 詞：`round neck with diameter ends rectangular chamber with sides
depth with absorber layer thickness adjacent back …`

（`absor` 而不是 `absorber` —— 文字層本身就把它斷在行尾連字號上。）

## 2. 為什麼這一類值得單獨看：它跟 table 那 163 詞的病因不同

`table` 那一塊的 72% 是 **glued/spaced**（詞在 `table_body` 裡，只是黏成一塊或
被逐字母排開），本輪的格內逐字母排版正規化已經處理掉排版那一半。
**這 91 詞不一樣：它們根本不在任何 item 裡**，MinerU 沒有為那些區域開項目
（A、B），或開了但內容是 OCR 亂碼（C）。補格、正規化、重轉錄都碰不到它們 ——
要嘛在**解析階段**解（讓 MinerU 抓到標題行），要嘛按 p64 的辦法逐塊人工裁定。

## 3. 為什麼是 91 不是 93

階段 2.7 的歸因跑在**補格之前**。本輪五筆定點補格（#520／#405／#529／#454／#373）
把 `round`、`neck`、`rectangular` 等詞寫進了 item，歸因的第二道扣除
（「該頁所有 item 文字裡本來就有的」）因此多扣掉 2 個。
**數字會隨修補而動是正常的**，但它也說明一件事：這個歸因不是文件的固有屬性，
是「現在這一版 content_list 與文字層的差」，引用時要連日期一起引。

## 4. 三類各自的可行修法（提案，未執行）

| 類 | 詞數 | 修法 | 代價 | 建議 |
|---|---:|---|---|---|
| A `continued` | 19 | **機械**：續頁標籤位置固定（Y≈128／846–854、字面單一），可在後處理補一個 text item 或併進表格 caption | 低，但**會增加項目數** —— 與「項目數不得改變」的鐵則衝突（sidecar 的 self_ref 是陣列索引），只能併進既有 item 的 caption | 值得做，但要先解決「往哪裡併」 |
| B 標題行 | 19 | 同 A（表格標題行，位置在表格 bbox 正上方） | 同上 | 同 A，合併成一題 |
| C p33／p51 | 53 | 比照 p64 `#540`：裁圖 ＋ 文字層取 ground truth ＋ 人工裁定檔 | 2 塊、需人看圖 | 值得做（唯一有實質內容的一塊） |

**全部修完約可救回 91 詞：381 → 290，10.5% → 8.0%。仍高於 5% 門檻。**

這是 waiver 決策要用的數字：**C 的漏詞不可能靠後處理降到 5% 以下**。
剩下的 290 詞裡最大宗仍是 table 的 glued 型（`ResistorCapacitorCoil` 這種
MinerU 把三列標籤塞進一格且沒有分隔符），那要重排表格結構才救得回，
而重排結構＝整表換掉，與「定點補格、現值一個字不動」互斥。
