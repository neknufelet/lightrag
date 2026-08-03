# NEXT — 待辦與進行中

規則與契約在 [CLAUDE.md](CLAUDE.md)（SSOT），重建的階段、閘門與各階段的
驗收紀錄在 [docs/rebuild-plan.md](docs/rebuild-plan.md)。這裡只放「接下來
要做什麼」。**做完就刪**——教訓沉澱回 CLAUDE.md 或 rebuild-plan，不留屍體；
新增時寫清楚證據在哪。

---

## 現況（2026-08-03）

**acoustics_v2 已接手上線，acoustics_v155 已完全退役。** 重建的階段 0–5 全部
完成：0–3 經主線獨立驗收，切換與退役於 2026-08-03 執行完畢並實測驗證。

```
唯一的庫  acoustics_v2
checkout  ~/ghq/github.com/neknufelet/lightrag（單一，無 worktree、無 v1/v2 分身）
服務      lightrag :9621（容器 lightrag-acoustics_v2）
          kbapi    :9700（容器 kbapi-acoustics_v2）—— 三個 skill 全走這裡
內容      20 份 processed / 0 failed、7,211 實體、10,500 關係、510 chunk、可疑率 4.5%
排程      lightrag-daily-check.timer 每天 08:30 跑 compat-check + canary，
          紅燈打自架 ntfy（/opt/stacks/ntfy :9800），腳本自己掛掉走 systemd OnFailure 備援
v155      已不存在。Neo4j label、Postgres 列、磁碟目錄、容器全部移除，數字見 CLAUDE.md
```

> ⚠️ **`/data/rag/lightrag` 沒有備份。** 本檔與 `.env.example` 曾寫它在
> 「restic 備份範圍」——**那是假的**。backrest 的 `rag-snapshot` plan 備的是
> `/userdata/data/rag/knowledge_bases`（DeepTutor 的庫），不是我們這個。
> 現在 v2 是唯一的庫，`__parsed__` 重解析要 6–10 小時，`records/` 那套人工
> 裁決重跑也回不來。**處置見下方「接上備份」。**

> **路徑約定**：本檔寫 `$RECORDS/…` 一律指
> `/data/rag/lightrag/acoustics_v2/records/`——**在 `/data`，不在 git，
> 且目前沒有備份**（見上）。寫成相對路徑會被誤讀成 repo 內的檔案。

**體檢表**（`$RECORDS/ledger/`，工具 `scripts/ledger.py summary`）：
160 格全滿，通過 151、fail 9、驗不了 0。
9 個 fail 全部已查明並記錄，**沒有一個是未知問題**：

| fail | 份數 | 已查明的性質 |
|---|---:|---|
| `parse.coverage` | 2 | **waiver 放行**：41598 7.0% 全為 chart 圖例軸標（政策性遺失）；C 10.5% 主要是黏字假訊號與圖說標籤，全修也只到 8.0%，是 MinerU 上限 |
| `pp.equations` | 1 | N Flow：#1410 單處已知缺陷（見下） |
| `extract.grounding` | 6 | **全部查過不是幻覺**，分兩族：符號→概念命名、概念→引用文獻（見下） |

**waiver 的 provenance**：三份 waiver（41598／C 的 `parse.coverage`、N Flow 的
`pp.equations`）由**主線於 2026-08-02 裁決「准進階段 3」**，原文追加在體檢表的
note 欄（`$RECORDS/ledger/`），不是口頭放行。要翻案先讀那三則 note。

---

## 立刻要做的（新對話從這裡接）

### 1. 50 題考卷：判「驗不了」那桶健不健康　← **尚未開始**

v2 有 **1,482 個實體**落在接地檢查的「符號型／驗不了」格（v155 是 1,547，
所以這不是 v2 帶來的問題，兩邊都有且舊的更多）。這是全專案最大的未驗證區域：
它們不是錯的，但也**從來沒被檢查過**，20 份時可接受，390 份時會變成一萬五千個。

**做法**：抽 50 個由主線（大模型）**親手標答案**，看這桶子的健康度。
成本極低（讀原文即可，不呼叫模型不花錢），資訊量高：

- 絕大多數是**正確的符號推論**（例如來源 chunk 是
  `<td>G</td><td>$G=I/\Delta U=1/Z$</td>`，抽出「Conductance」是對的——
  從符號推論概念名稱正是抽取器該做的事）→ 桶子健康，切換上線無疑慮
- 有相當比例是垃圾 → **上線前必須知道**，停下來重新評估

這 50 題標好之後**不是一次性的**，它同時是第 2 項的標準答案。

### 2. 接 DeepSeek 判那 1,482 個

判準來自實測：**問「這個判斷需要的資訊，在我給模型看的東西裡嗎」。**
符號辨識（∂ 還是 σ̂）的答案在像素裡，純文字判官實測只有 51%／48%
（flash／pro，換更強的模型不會改善，缺的是資訊不是推理）；但**接地檢查
不一樣，資訊完全在文字裡**，這才是文字模型的主場。

拿第 1 項的 50 題當考卷，跑三組比正確率與成本：
**普通模式／普通模式＋加大脈絡／推理模式**。

- 主線的預測是「普通＋加大脈絡」會贏——專案有前例：`X a`／`X_a`／`Xa`
  原本標「分不出來」，脈絡從 90 字元拉到 300 字元後定義式就出現了。
  **多給脈絡通常比多給推理有效，而且便宜得多。** 但預測不算數，實測才算。
- 已知陷阱：推理模型會把額度吃光，回空字串但 `finish_reason=stop`——
  看起來像「模型判不出來」其實是預算耗盡。**兩者必須分開回報。**

跑完之後常見的推論型態可以歸納成確定性規則（例如「表格首欄符號 → 該列
概念名」），那時這桶子才真的變成養分。

### 3. 封閉掃描器進版控，變成會自己響的探針　← **最優先的工程項**

**這是「新符號誤讀」唯一的偵測手段。** 漏字檢查抓不到它（誤讀不刪字，
覆蓋率永遠 100%）、preflight 也抓不到（型別沒變）——它可以完全安靜地進索引。

現況：它是 scratchpad 裡的**拋棄式腳本**，兩輪都是如此，而**上一輪的盲點
因此活過一整輪、下一輪又找到第三個**。這正是「拋棄式腳本會漂移、沒人維護」
的活例子。

規格：

- 以**位置**為錨（accent 類 ∪ 裸花體 token，站在 frac 首位或行內除法的
  算子位置而不是 `\partial`），**不以符號枚舉**——族的清單這輪從 4 個
  長到 9 個再到 14 個，枚舉永遠追不上
- 殘留清單**白名單化**：c̄、c̄_p、D̄、ρ̃、ρ̄、Ψ̄、`\mathfrak{O}`（C 的孔隙率）、
  大 O 記號等已定案真符號。**冒出白名單外的 token 就報**
- 三個已知盲點要補：裸 token 沒有 accent 配不到、連續兩個誤讀算子只抓得到
  第一個、`\frac` 後面不是 `{` 的截斷式剖析不了
- 進 `compat-check.py` 或獨立閘門，納入 `daily-check.sh`
- **校準教訓**：錨點放太寬會炸出 2,803 處合法符號——
  **永遠很長的殘留清單就不是殘留清單**（鐵則 6 同源）

---

## 接上備份　← **最優先，因為 v2 現在是唯一的一份**

`/data/rag/lightrag` 不在任何備份計畫裡。文件曾宣稱它在 restic 範圍，
**那句話是假的**——假的安全宣稱比沒有宣稱更危險，因為你會照著它做決定。

實測（2026-08-03，`docker exec backrest` 讀 config.json）：

```
plan project-daily   /data/project_source
plan lih-obsidian    /data/learning_source/obsidian
plan lih-zotero      /data/learning_source/zotero
plan lih-calibre     /data/learning_source/Calibre
plan rag-snapshot    /userdata/data/rag/knowledge_bases   ← DeepTutor 的，不是我們的
我們的               /data/rag/lightrag  210 MB           ← 不在任何 plan
systemd timer        只有 lightrag-daily-check.timer，沒有備份 timer；crontab 空
```

- [ ] **加一條 backrest plan 指向 `/userdata/data/rag/lightrag`**。backrest 容器
      已經把 `/data` 以唯讀掛成 `/userdata/data`，所以**不用改掛載、不用重建容器**，
      加 plan 就行。
- [ ] 跑一次完整備份並**驗證取得回來**（不是看到「成功」就算——restic 要
      `restore` 一份出來比對）。沒驗過的備份等於沒有備份。
- [ ] 修掉 `.env.example` 與各文件裡「restic 備份範圍」的假宣稱

優先序理由：`__parsed__` 重解析要 6–10 小時（花時間但做得到），
`records/` 那套人工裁決**重跑也回不來**（那是人的判斷）。

---

## 其他待辦

### 資料層（v2）

- [ ] **六份接地 >5% 的處置**。已查明**不是幻覺**，分兩族：
      **符號→概念命名**（K Muffler 15.1%、00712 11.9%、G Porous 6.4%）——
      K Muffler 的 92 個可疑裡**只有 1 個**是引用文獻型，其餘是傳遞矩陣的
      裸符號被命名（`Coefficient Ta`、`Matrix GA`、`H12 Parameter`）。
      **這推翻了 v155 時代「大量概念→引用文獻」的歸因**，根因是
      `SYMBOLIC_RATIO=0.35` 把同一族切成兩半，一半進「驗不了」一半進「可疑」。
      **調門檻前先照鐵則 5「看差在哪些具體記號」。**
      G Porous 6.4% 是**同一件事的 Bessel 版**（`Modified Bessel Function I0`
      這類裸符號被取描述性名字），不是另一個病因。
      **材料＝那 120 個名字，全在體檢表的 note 欄**（`$RECORDS/ledger/`）——
      要重量 `is_symbolic` 直接讀那份，不必重跑。
      **概念→引用文獻**（01200_6 6.1%、2025 5.7%、2023 FEM 5.0%）——
      作者縮寫名、期刊全名 vs 原文縮寫。
- [ ] **C 的羅馬數字下標族維持不修**（v155 47 個可疑 → v2 C 剩 14 個，重驗過）：
      `Region I/II/III`、`Mechl` 同一族，對應 `model-observations.json` 的
      domain_fact「羅馬數字下標難讀」——**兩雙眼睛方向相反地都會錯**，
      不是抽取器的問題。列在這裡是因為它會一直出現在可疑清單上，
      **看到它不必再查一次**。
- [ ] **N Flow #1410**（式 27，p59）`\mathbf{\overline{\partial}}^{2}`：
      overbar 被 MinerU 掛到 ∂ 上（應為系綜平均的範圍，Proudman 四階相關），
      同一式旁邊就有讀對的 `\frac{\partial^2}{\partial t^2}`。
      **屬整條重轉錄不屬換記號**，所以 `pp.equations` 對 N Flow 維持 fail。
- [ ] `eq-check` 三票多數決還沒對 v2 跑過（∂ 族已用裁圖定案了結，
      這項現在的用途是方程式的一般性品質，不急）
- [ ] C 的 `\times` 誤讀還有 6 處未修：`e^{-\gamma_{n,v}\times}` 型。
      同一個成因——座標 x 被讀成乘號，裁圖 `t373` 上寫的是 `e^{-γ_n x}`——
      但**位置不同**（在指數裡，不是下標），不在已授權的錨點內。
      **不一起放寬的理由：規則一次只放寬一條，否則漂移是哪一條造成的分不出來。**
- [ ] **C 的 91 個「bbox 未覆蓋」詞往哪裡併，尚未裁決**（歸因見
      `$RECORDS/review/c-uncovered-words.md`）：19 個 `continued` 續表標籤、
      19 個表格標題行、53 個在 p33／p51 兩頁（MinerU 整塊發成 image、
      caption 是 OCR 亂碼）。前兩類位置固定、字面單一，機械可修，但
      **會增加項目數**，與鐵則 2「項目數不得改變」衝突（sidecar 的 `self_ref`
      是陣列索引），只能併進既有 item 的 caption——**併到哪個 item 要先裁決**。
      第三類比照 p64 `#540` 逐塊人工裁定。全修 → 10.5% 降到 8.0%，**仍高於 5%**，
      所以這項不影響 waiver 成立與否，但未決的裁決本身不該消失。
- [ ] 首頁的期刊／會議資訊（`Paper ID #8776`、`©American Society…`）
      只在第 0 頁出現一次，重複與樣板規則都抓不到。要處理需要新訊號
      （限第 0 頁 ＋ 版權標記），但只有 1 份文件的證據，先不動

### 工具層

- [ ] `retrieval-check.py` 的框架對 v2 已過期：docstring 還寫著
      「目前索引裡 19 份是未經處理的」，而且**頭條數字是假訊號**——
      它報 0.57%／55% chunk 含雜訊，實際命中集中在單字元消音字串
      （`d` 9,059 次、`C` 385）與同時是真標題的書眉。
      真正該看的量是**相異雜訊字串數 670（v155）→ 13（v2）**，
      按這個量**消音確實生效**。
      **兩條出路，擇一**：① 給它一個新問題（現在這個已經被消音解掉了）；
      ② 讓它改報相異字串數而不是命中率。不動它就等於留一個永遠亮紅的假訊號。
- [ ] **裁決材料進版控**。今天的定案（∂ 族白名單、C 補格、為什麼某些東西
      刻意不碰）寫在 `$RECORDS/review/` 底下，
      有 restic 備份但**不在 git**——三個月後問「為什麼 `\mathfrak{O}` 在
      白名單上」，答案存在但不在版控裡、不會出現在任何 diff。
      建議把各檔的**「定案」節**抽出來進 git，龐大的原始材料與裁圖留在 `/data`
- [ ] `cmd_apply` 的批次原子性已實作並用注入失敗測過，但**新的機械規則對
      canary 是隱形的**（它的計數不在被追蹤的八個量裡）——內容變動型的規則
      需要自己的漂移偵測
- [ ] **實體碎片化在 v2 還沒量**（rebuild-plan 階段 4「量了才修」的殘留）。
      下面「刻意不做」那條的 388／254／51／8 全是**舊庫 v155 的數字**，
      v2 的對應數字一個都沒有。不合併的結論目前**借的是舊母體**——
      要嘛在 v2 重量一次確認結論仍成立，要嘛把那條改寫成「依 v155 證據暫緩」。
- [ ] **「qwen 系統性切錯列」還缺第二份樣本**：命中率約 1/15，目前只有一份
      有空表格的文件當證據。**一份證據的觀察是那份文件的巧合**（CLAUDE.md
      「規則分兩類」的判準），所以它現在只能留在 `model-observations.json`
      的易腐觀察，不得升格成裁決規則。要升格得先找到第二份。

### 效能（擴量前）

- [ ] **MTP 加速評估**：`--spec-type mtp --spec-draft-n-max 3`。
      `Qwen3.6-35B-A3B`（就是我們跑的那顆）**原生支援**，實測 1.7–2.5×。
      它「強制 `n_parallel=1`」的限制**對我們免費**——llama.cpp 本來就只有
      1 個 slot（所以 `.env` 的 `MAX_ASYNC=2`，再高只會排隊撞逾時）。
      抽取吐的是結構化 JSON，格式可預測，草稿接受率應該偏高。
      三關按順序：①那顆 GGUF（`Qwen3.6-35B-A3B-UD-IQ4_XS`）**有沒有帶
      MTP 權重**——很多量化轉檔會把 MTP 頭丟掉；②顯存，GPU0 只剩 0.67 GiB；
      ③**驗證不是相信**——同一個 chunk 開關各跑一次，比對輸出是否逐字相同
      （貪婪解碼下應該無損，但要驗）＋實際 tok/s。輸出若有差就不只是加速，
      是換了模型行為，要照 A-23 那套重新量測模型觀察。
      **價值在 390 份擴量時**，抽取是那時的時間大宗。
      參考：https://ai-coding.wiselychen.com/llama-cpp-mtp-merged-local-llm-2x-speedup/
- [ ] **TurboQuant 不適用**（查過了）：它是 Google 的 KV cache 量化，
      實作在 vLLM + Triton 不是 llama.cpp，而且針對長脈絡場景——
      我們是一次一個 chunk，12 GiB 裡塞滿的是模型權重不是 KV cache
- [ ] 這台主機（100.87.88.7）的 `nvidia-smi` 壞了：
      `Driver/library version mismatch`，驅動更新但核心模組還是舊的。
      不影響現況（llama.cpp 在 100.71.26.77），但要在這台用 GPU 會踩到

### 擴量到 390 份（等上面收斂）

- [ ] 新期刊／新版面預期會冒出新型態，照
      `.claude/skills/onboard-doc-type/SKILL.md` 走，預期幾輪介入後穩定
- [ ] **解析階段議題**：表格結構黏連（`<td rowspan=2>ResistorCapacitorCoil</td>`
      ——三個詞塞一格沒有分隔符）。**內容沒有掉，掉的是分隔符**，後果是
      檢索 `Resistor` 配不到。**這一類佔 C 的 table 漏詞 72%**，是最大的一族。
      無法在後處理層修：要救必須重排表格結構＝整表換掉，與「定點補格、
      現值一個字不動」互斥。屬 MinerU 上限，該在解析階段解（MinerU 選項／版面規則）。
      同輪的另一半 `\mathsf{t a n h}` 逐字母排版**已了結**，走機械正規化
      2,399 段（commit `32276f9`，20 份／679 項）

---

## 刻意不做（決策記錄，動它之前先讀理由）

- **實體碎片化的長尾不合併**：51 組被檢索到的裡只有 8 組浪費 ≥2 格（已併），
  另 254 組從未出現在任何檢索結果——254 次不可逆操作換 0 收益。
- **23 處 `\mathsf{P}` 不碰**：P 在語料裡多義（ρ₀c₀ 的 ρ、ρ_P 的下標、
  空間點 P₂、矩陣 [P]、#1056 壓力波動方程的 p），沒有便宜可靠的訊號能分開。
- **`\hat{c}`／`\bar{c}` 不機械套**：#957 同一條式子裡兩義（一處是 ∂、
  一處是 c̄），與 `\mathsf{P}` 完全同型。已逐條定案，不得寫成規則。
- **C 的 69 個空 text 項不回填**：它們是跨頁段落的續行佔位，正文早被 MinerU
  併進前一頁的項目，**不造成漏字**。（41598 #41 曾被誤判成「單一空段落」，
  全母體掃描後才發現是 69 個同型且都不是洞——歸因只在同區域內比對會看不到
  被併到上一頁的鄰居。）
- **N Flow #1135／#1518 不動**：看圖後確定不是「式子吞散文」，是**符號說明
  清單被整片判成 `equation`**——型別判錯、無母體可修。coverage 那半已由
  偵測器 v2 了結。
- **K Muffler #277 不改**：`eq_similar` 誤報——`\begin{array}` 的排版結構被
  算成差異，MinerU 是對的且多帶著 `\tag{13}`。

---

## 工作方式（交接用）

- **分工**：主線（大模型）只做規劃、文檔、裁決與**獨立驗收**；執行類工作
  （部署、改程式、跑流程）一律開 Opus 子代理，附精確工單（要讀哪些文檔、
  約束、驗收條件）。**執行者的「自稱完成」不算數**——每一輪都由主線親自
  重跑關鍵指令驗收，這一路抓到過執行者漏報與歸因錯誤。
- **停損**：這次階段 2 的後半花了三小時追兩份文件的最後 1%，換回 39 個詞而
  閘門仍然不翻。**有問題 ≠ 值得修，先量代價再排序**（judgement-flow 第 8 節）。
- **審計軌跡**在 `$RECORDS/`：
  `ledger/`（每份文件的三態體檢表）、`review/`（裁決材料，每份都有
  「建議／依據／信心」與主線的「定案」節）、`review/crops/`（裁圖）。
- **常用驗收指令**（在 v2 worktree 跑）：
  ```bash
  python3 scripts/compat-check.py          # 契約 + 資料層，135 項
  python3 scripts/postprocess.py canary    # 規則漂移
  python3 scripts/ledger.py summary        # 體檢表總表
  python3 scripts/coverage-check.py        # 解析漏詞（--doc 篩單份）
  python3 scripts/extract-check.py         # 接地三態（--workspace 可指舊庫）
  python3 scripts/compare-ws.py <關鍵字> acoustics_v155 acoustics_v2
  ```
