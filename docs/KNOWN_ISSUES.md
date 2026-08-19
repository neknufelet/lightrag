---
title: KNOWN ISSUES — lightrag
date_created: 2026-08-07
date_modified: 2026-08-09
status: living
kind: analysis
supersedes: ""
superseded_by: ""
summary: "已知但決定不修（或暫緩）的問題，附各自的理由。從 NEXT.md 的待辦區搬出——它們不是待辦，混在裡面就是雜訊。"
---

# KNOWN ISSUES — lightrag

**這裡放「知道、查過、決定不修或暫緩」的東西。** 它們原本混在 [NEXT.md](NEXT.md) 的
`- [ ]` 裡，讓 799 行的待辦清單裡有一半不是待辦。

判準：真的還要做 → [NEXT.md](NEXT.md)；知道但不做 → 這裡；一次性的裁決與其理由 →
`docs/decisions/`；發生過的事 → `cairn/LOG.md`。

**動任何一條之前先讀它的理由。** 這些不是漏掉的工作，是量過代價之後的決定。

| ID | 嚴重度 | 描述 | 發現 | 相關 |
|---|---|---|---|---|
| KI-001 | 中 | 表格結構黏連：三個詞塞一格沒有分隔符，檢索配不到 | 2026-08-02 | — |
| KI-002 | 中 | backrest 的 `rag-snapshot` 對已不存在的路徑產出空快照 | 2026-08-07 | ADR-0003 |
| KI-003 | 低 | `C` 的羅馬數字下標族（`Region I/II/III`）維持不修 | 2026-08-02 | — |
| KI-004 | 低 | `N Flow` #1410 的 ∂ overbar 誤掛，`pp.equations` 維持 fail | 2026-08-03 | — |
| KI-005 | 低 | `C` 的 `\times` 誤讀還有 6 處未修（在指數裡，錨點外） | 2026-08-03 | — |
| KI-006 | 低 | 實體碎片化的長尾 254 組不合併 | 2026-08-02 | — |
| KI-007 | 低 | 23 處 `\mathsf{P}` 不碰（語料裡多義） | 2026-08-03 | — |
| KI-008 | 低 | `\hat{c}`／`\bar{c}` 不機械套（同式兩義） | 2026-08-03 | — |
| KI-009 | 低 | `C` 的 69 個空 text 項不回填 | 2026-08-02 | — |
| KI-010 | 低 | `N Flow` #1135／#1518 不動（型別判錯，無母體可修） | 2026-08-03 | — |
| KI-011 | 低 | `K Muffler` #277 不改（`eq_similar` 誤報） | 2026-08-03 | — |
| KI-012 | 低 | 首頁期刊／會議資訊抓不到。**2026-08-09 處理了 `text` 型別那一半；`header`／`footer` 型別的仍待查** | 2026-08-02 | — |
| KI-013 | 低 | `100.87.88.7` 的 `nvidia-smi` 壞了（driver/library mismatch） | 2026-08-03 | — |
| KI-014 | 低 | TurboQuant 不適用（查過了） | 2026-08-03 | ADR-0002 |
| KI-015 | 中 | 期刊推薦／封面頁列出**別人的論文**（IOP `You may also like`、AIP `ARTICLES YOU MAY BE INTERESTED IN`） | 2026-08-09 | — |
| ~~KI-016~~ | ~~**高**~~ | ~~外掛：對 PDF 附件那一列按送出會**繞過選片規則**~~ | 2026-08-16 | **2026-08-19 修（外掛 0.3.6）** |
| KI-017 | 中 | 目錄頁已經混進知識庫（2/317）。沒有任何規則管目錄／版權頁 | 2026-08-16 | — |

> 嚴重度：**高** = 功能無法運作 / **中** = 有 workaround / **低** = 不影響主流程

---

## 理由

**KI-001 表格結構黏連。** `<td rowspan=2>ResistorCapacitorCoil</td>`——三個詞塞一格。
**內容沒有掉，掉的是分隔符**，後果是檢索 `Resistor` 配不到。這一類佔 `C` 的
table 漏詞 **72%**，是最大的一族。無法在後處理層修：要救必須重排表格結構＝整表換掉，
與「定點補格、現值一個字不動」互斥。屬 MinerU 上限，該在解析階段解。

**KI-002 空快照。** plan `rag-snapshot` 每 4 小時備份
`/userdata/data/rag/knowledge_bases`，但 PO 已於 2026-08-07 清空 `/data/rag`。
它**回報成功、內容是空的**——本專案記過三次的「備份成功訊號是真的、備份內容是空的」。
那是 DeepTutor 的庫，不歸本專案處置，等 PO 決定。

**KI-003 羅馬數字下標。** `Region I/II/III`、`Mechl` 同一族。對應
`model-observations.json` 的 domain fact「羅馬數字下標難讀」——**兩雙眼睛方向相反地
都會錯**，不是抽取器的問題。v155 有 47 個可疑，v2 的 `C` 只剩 14 個（重驗過）。
列在這裡是因為它會一直出現在可疑清單上，**看到它不必再查一次**。

**KI-004 N Flow #1410。** 式 27，p59，`\mathbf{\overline{\partial}}^{2}`：overbar 被
MinerU 掛到 ∂ 上（應為系綜平均的範圍，Proudman 四階相關），同一式旁邊就有讀對的
`\frac{\partial^2}{\partial t^2}`。**屬整條重轉錄不屬換記號**，所以維持 fail。

**KI-005 `\times` 剩 6 處。** `e^{-\gamma_{n,v}\times}` 型，同一個成因（座標 x 被讀成
乘號），但**位置不同**（在指數裡不是下標），不在已授權的錨點內。
**不一起放寬的理由：規則一次只放寬一條，否則漂移是哪一條造成的分不出來。**

**KI-006 碎片化長尾。** 51 組被檢索到的裡只有 8 組浪費 ≥2 格（已併），另 254 組
**從未出現在任何檢索結果**——254 次不可逆操作換 0 收益。
⚠ 這些數字全來自舊庫 v155，v2 的對應數字一個都沒量（見 [NEXT.md](NEXT.md) 的待辦）。

**KI-007 `\mathsf{P}`。** P 在語料裡多義（ρ₀c₀ 的 ρ、ρ_P 的下標、空間點 P₂、
矩陣 [P]、#1056 壓力波動方程的 p），沒有便宜可靠的訊號能分開。

**KI-008 `\hat{c}`／`\bar{c}`。** #957 同一條式子裡兩義（一處是 ∂、一處是 c̄），
與 KI-007 完全同型。已逐條定案，**不得寫成規則**。同族的 `\hat{c}` 有 3 處是真的 ĉ，
認字元會毀資料——這是「錨點認結構不認字元」那條規則的來源。

**KI-009 69 個空 text 項。** 跨頁段落的續行佔位，正文早被 MinerU 併進前一頁的項目，
**不造成漏字**。（`41598` #41 曾被誤判成「單一空段落」，全母體掃描後才發現是 69 個
同型且都不是洞——歸因只在同區域內比對會看不到被併到上一頁的鄰居。）

**KI-010 N Flow #1135／#1518。** 看圖後確定不是「式子吞散文」，是**符號說明清單被
整片判成 `equation`**——型別判錯、無母體可修。coverage 那半已由偵測器 v2 了結。

**KI-011 K Muffler #277。** `eq_similar` 誤報——`\begin{array}` 的排版結構被算成差異，
MinerU 是對的且多帶著 `\tag{13}`。

**KI-012 首頁期刊資訊。** `Paper ID #8776`、`©American Society…` 只在第 0 頁出現一次，
重複與樣板規則都抓不到。要處理需要新訊號（限第 0 頁 ＋ 版權標記）。

**2026-08-08：第二份證據到了，不再是巧合。** `2019 - Low-frequency sound absorption
of hybrid absorber…`（AIP，與第一份不同期刊）的第 0 頁出現五項同型的東西，全部被
規則標成「待查」而非消音：

```
# 10 p0  'Aps hds prs'                                          OCR 殘骸
# 11 p0  'AIP Publishing'                                       出版社
# 12 p0  'Lake Shore'                                           贊助商
# 13 p0  'Appl. Phys. Lett. 114, 151901 (2019); https://doi.org/…'  期刊引用行
# 14 p0  '114, 151901'                                          卷號／文章號
```

形狀與第一份一致：**第 0 頁、單次出現、期刊／出版社／DOI**。兩份不同期刊都這樣，
所以「限第 0 頁 ＋ 出版資訊標記」這個訊號站得住了。

⚠ **2 份在本專案已經是可動手的門檻**（`aside_text` 那條規則就站在 2 份上），
所以這條不再是「證據不足」，而是**等安全網**：canary 基準還停在舊的 20 篇語料
（2026-08-08 實測報「新增 4 篇、消失 11 篇」）。改規則的正確順序是
「改 → canary 預期失敗 → 逐條確認漂移都是想要的 → `--update`」，
基準壞掉時第二步做不到，改完不會知道有沒有波及其他文件。

**2026-08-09：處理了一半，剩下的一半刻意不動。** canary 基準已補回 27 份，安全網
到位；`pp/rules/title_block.py` 的 `publication` 訊號（錨定在開頭 ＋ 限第 0 頁）
上線，把 `text` 型別的期刊引用行消掉了。同一份 2019 文件實跑：

```
#  1 text        標題頁消音   'Cite as: Appl. Phys. Lett. 114, 151901 (2019); https://doi.org…'
#  2 text        標題頁消音   'Fei Wu, Yong Xiao, Dianlong Yu, Honggang Zhao, Yang Wang, and …'
# 10 aside_text  雜訊待查     'Aps hds prs'
# 11 footer      雜訊待查     'AIP Publishing'
# 12 footer      雜訊待查     'Lake Shore'
# 13 footer      雜訊待查     'Appl. Phys. Lett. 114, 151901 (2019); https://doi.org/…'
# 14 footer      雜訊待查     '114, 151901'
```

**上面舉的那五項一項都沒動，是設計不是漏掉。** 它們的型別是 `header`／`footer`／
`aside_text`，那是 `layout_noise` 的地盤 —— 兩條規則消到同一項時
`_pp_original_text` 會被寫兩次而還原只還原得了一次，所以分工用型別切開
（`apply.py` 有執行者，撞到就整份拒絕）。要消掉它們得改 `layout_noise`
的判準，那是另一條規則的事，不在這一輪。

~~**動它之前**：先讓語料定下來、刷新 canary 基準。~~
**2026-08-09 兩個前提都到位了**（基準 27 份、`canary` 綠），所以剩下那一半的
擋路理由不再是安全網，是「該由哪條規則管」。

**KI-013 nvidia-smi。** `Driver/library version mismatch`，驅動更新但核心模組還是舊的。
不影響現況（llama.cpp 在 `100.71.26.77`），但要在 dker 用 GPU 會踩到。

**KI-014 TurboQuant。** 它是 Google 的 KV cache 量化，實作在 vLLM + Triton 不是
llama.cpp，而且針對長脈絡場景——我們是一次一個 chunk，12 GiB 裡塞滿的是模型權重
不是 KV cache。

**KI-015 期刊推薦區塊列出別人的論文。** 兩種期刊、兩種寫法，同一件事：

```
IOP   2014 - Acoustic coherent perfect absorbers   `You may also like` 下面三篇別人的論文
AIP   2019 - Low-frequency sound absorption …      `ARTICLES YOU MAY BE INTERESTED IN` 下面三篇
```

**它們是真的進了圖譜。** 2026-08-09 從 `lightrag_graph_nodes` 撈到的證據：
`j z song`（IOP 那頁 `To cite this article: J Z Song et al 2014`）與 `jia-hao xu`
（同頁推薦清單裡的作者）都是 `person` 型別的節點。它們既不是本文作者、也不是
聲學史上的人物，純粹是版面帶進來的。

**為什麼這一輪不做**（PO 2026-08-09 裁決）：

- 它的訊號與標題頁那條**不同**。標題頁那條靠「第一項是 `lvl=1` 標題」開火，
  而這兩份的第一項都不是 —— IOP 那份第 0 頁整頁是封面，AIP 那份的推薦區塊
  由 `ARTICLES YOU MAY BE INTERESTED IN`（`lvl=2`）起頭，**正好落在標題頁區塊
  結束的地方之後**。
- 混進同一條規則會讓兩邊都難驗：一條規則兩種開火條件，出事時分不出是哪一種。

**要做的時候**：訊號是「`lvl=2` 標題文字命中推薦清單樣式（`you may also like`／
`articles you may be interested in`／`related articles`），消到下一個同級標題為止」
—— 形狀與 `reference_section` 完全一樣，可以直接抄那條的區段邏輯。
⚠ 抄的時候連「消到下一個同級或更高級標題、不是消到結尾」一起抄，
那一條是被 2017 那篇的補充材料逼出來的。

---

## ~~KI-016~~ 外掛：點 PDF 附件那一列送出會繞過選片規則（2026-08-16 記，**2026-08-19 修**）

> **已修**：`lib/pickpdf.js` 的 `acceptDirect()`，外掛 0.3.6。判準不是「照 `choose()`
> 再挑一次」（那會蓋掉人的明確指定），只擋「點到的那一份本身就是翻譯本」。
> 修之前 6 條新測試全紅，修完 56 條全綠 —— ⚠ 舊判準「50 條測試全綠」在 bug 還在時
> 就已經是綠的，證明不了任何事。以下是當時的紀錄，保留。

**嚴重度高，而且今天才第一次被寫下來。** PO 在 2026-08-15 的交接裡口頭提過，
但 `KNOWN_ISSUES.md` 與 `CHANGELOG.md` 都沒有這一條 —— 這次讀程式碼才確認位置。

`zotero-plugin/bootstrap.js` 的 `sendOne()`（71–105 行）：

```javascript
if (item.isPDFAttachment && item.isPDFAttachment()) {
    attachment = item;                       // ← 直接用，沒過 choose()
    parent = Zotero.Items.get(item.parentItemID) || item;
} else if (item.isRegularItem && item.isRegularItem()) {
    ...
    const verdict = LightRAGPickPDF.choose(...);   // ← 選片規則只在這裡跑
```

⇒ 在 Zotero 條目清單裡**展開文獻、對底下某一份 PDF 附件那一列按送出**，
`choose()` 整段不會執行。過濾中文翻譯本、認 `title === 'PDF'` 那些規則全部跳過，
**你點到哪一份就送哪一份**。

**為什麼還沒修**：0.3.5 那一輪的重點是「選對片、帶 key」，這條路徑當時沒被想到。
修法不難（那一支也走一次 `choose()`，或至少在偵測到翻譯樣式時擋下來問一句），
但要重跑外掛的 50 條測試 —— 而 **dker 沒有 node**，測試只跑得動在 coder 上。

⚠ **這條的代價是不可見的**：送錯了不會報錯，中文翻譯本會安安靜靜進庫，
然後被公式比對當成一個獨立來源。

---

## KI-017 目錄頁會混進知識庫，沒有規則管它（2026-08-16）

`scripts/pp/rules/` 底下真正的消音規則只有三條，**沒有一條的判準提到目錄**：

| 規則 | 管什麼 | 管目錄？ | 管版權頁／前言？ |
|---|---|---|---|
| `layout_noise.py` | 每頁重現的頁眉頁腳 | 否 | 否 |
| `reference_section.py` | References／Bibliography／Acknowledgements | 否 | 否 |
| `title_block.py` | 標題頁的作者／單位／出版資訊 | 否 | 只消單行的出版資訊，不是整頁前言 |

（`title_block.py` 的樣式裡有 `view\s+table\s+of\s+contents`，但那是在認期刊頁上
「View Table of Contents」那一行連結文字，不是整個目錄頁。）

**已經在發生，不是理論風險。** 掃全部 317 份找「三個點以上接頁碼」的樣式，
命中 2 份，而且逐份確認過那些內容**真的在餵進知識庫的 `blocks.jsonl` 裡**：

```
2019 - Comparative Study and Design of Economical Sound Intensity Probe   26 處
   blocks.jsonl 第 6 筆  heading='Table of Contents'
   'List of figures.  List of tables.. . vii  Acknowledgements.. . viii  1 Introduction.. ….1'
2017 - Sound Absorption Structures From Porous Media to Acoustic Metamaterials   1 處
   blocks.jsonl 第 32 筆 heading='Indexes'
   'Cumulative Index of Contributing Authors, Volumes 43–47 .......... 481'
```

**為什麼現在只有 0.6%**：送進來的多半是**已經拆好的單章**或期刊論文，本來就沒有
目錄頁。⚠ **這個比例會隨「整本書送進來」直接跳到接近 100%** —— 見
`docs/whole-book-intake-20260816.md` 的討論。

⚠ 另一個沒人驗過的相依：`title_block.py` 刻意**對教科書章節不開火**
（判準是「第一項必須是 `text_level == 1` 而且在第 0 頁」，拆好的單章第一項通常
是半句話）。**整本書送進來時第一頁是真正的書名頁，這條規則會第一次開火 ——
而沒有人驗過它那時候會消掉什麼。**

---

## 刻意不做的取捨（2026-08-16 從 NEXT.md 搬來）

**又發生一次**：這些不是待辦，是量過代價之後的決定，卻混在待辦清單裡讓它膨脹到 666 行。
判準見本檔開頭。動任何一條之前先讀它的理由。

- **不改 workspace 名稱**（`acoustics_v2` → `acoustic`）。功能上只是字串，但要動
  `backup-cold.sh` 的容器名、`systemd-units.py` 的預設值、三個 skill 的 8 處 URL、
  三個測試檔。波及面大、價值低。（⚠ 新庫是另一回事 —— 它從一開始就用新名字，
  沒有「改名」這個動作，見 [rebuild-v3-design](rebuild-v3-design-20260816.md)。）
- **不擴到 20 篇**。2026-08-08 PO 槓掉，語料就是庫裡現有的那些（份數不寫死，用 psql 量）。
- **不上 Qwen3-Reranker**。已由 `BAAI/bge-reranker-v2-m3` 取代並上線（`8ebdc6b`）。
- **不做符號變體正規化**（`Z_Mi`／`ZMi`／`Z Mi`）。要模型替數學符號自創正規寫法，
  是錯誤代價最高又最難發現的地方 —— 寫錯成「看起來合理但不是論文用的」符號，
  沒有人看得出來。那類留給重抽後的審查表用原文逐組判斷。
- **不做單複數正規形**。實際候選清單裡根本沒有這種案例。
- **`.env` 不要用 `source` 讀**。`LIGHTRAG_PARSER` 的值含 `;`，shell 會把分號後面
  當指令。取值用 `grep -E '^KEY=' … | cut -d= -f2-`。（執行者：`guard-command.py`）
- **llama 的金鑰不換、也不從命令列移走**。2026-08-08 PO 裁決：「不擔心，本地端而且
  只有我用」。事實記著以免重新爭一輪：`--api-key <值>` 在容器的 `Cmd` 上，
  `docker inspect` 與 `ps aux` 都看得到。形狀與 `oracle.py` 當初修掉的
  `-e KEY=VALUE` 相同，但**風險面不同**：那台在 Tailscale 內、單人使用。
  ⇒ 判準不是「有沒有洩漏路徑」，是**誰在那條路徑上**。
- **`:9621` 暫時不對外關掉**（2026-08-07 決定暫留，LightRAG 的 WebUI 有圖譜瀏覽器）。
- **`:9700` 沒有認證是刻意的**。實測不帶金鑰回 200，唯一的保護是只綁 Tailscale 位址
  （綁 `0.0.0.0` 等於知識庫在區網上裸奔）。⇒ 代價：**任何進得了 Tailscale 的東西，
  都讀得到整個知識庫。**
