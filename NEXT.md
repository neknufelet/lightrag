# NEXT — 待辦與進行中

規則與契約在 [CLAUDE.md](CLAUDE.md)（SSOT），重建的階段、閘門與各階段的
驗收紀錄在 [docs/rebuild-plan.md](docs/rebuild-plan.md)。這裡只放「接下來
要做什麼」。**做完就刪**——教訓沉澱回 CLAUDE.md 或 rebuild-plan，不留屍體；
新增時寫清楚證據在哪。

---

## 開新對話直接貼這段

```
專案 lightrag（聲學知識庫）。我在 florian-coder，透過 ssh 操作 florian-dker。

座標
  repo      ~/ghq/github.com/neknufelet/lightrag-v1（coder，工作台）
            ~/ghq/github.com/neknufelet/lightrag（dker，部署，唯讀只 pull）
  GitHub    neknufelet/lightrag-v1（尚未改名，計畫改成 lightrag，卡在 gh 未登入）
  服務      dker: lightrag-acoustics_v2 :9621、kbapi-acoustics_v2 :9700
            自己的 lightrag-postgres 與 lightrag-neo4j（2026-08-03 從 DeepTutor 搬出）
  資料      /data/lightrag（DB）＋ /data/rag/lightrag（解析快取與裁決紀錄）

先讀 CLAUDE.md 與 NEXT.md，兩份都是 2026-08-03 大改過的。
CLAUDE.md 前半是治理層（座標、藍桶 9 條、雙軌溝通、提交紀律、驗收路由、命名規則），
後半是原本的六條鐵則與現況。

規矩重點：
  - 改在 coder、驗在 dker。**驗證輸出沒拿到就還沒 done。**
  - coder 上沒有 .env、沒有 docker，碰 DB 的腳本在那裡跑不起來——這是刻意的。
  - 重票觸發清單見 CLAUDE.md「執行方針與驗收路由」，有疑義＝重票。

下一步照 NEXT.md 的狀態總表。**2026-08-03 收完一大批，目前只剩一條主線：**
  SCALEUP-1  擴量到 390 份。前置都已收斂（見下），開跑前先讀「擴量到 390 份」那節

當天收掉的（都有實測，別重做）：
  BACKUP 全線 —— 還原演練通過、排程已接、還原點 1→3
  SPEEDUP-2  —— MAX_ASYNC 2→4（+28% 吞吐，已生效）
  SPEEDUP-1  —— MTP 不做（GPU 在 c=4 已飽和，換不到東西）；vLLM 同理
  SPEEDUP-4  —— gleaning 不能盲砍（它撈到的 93% 是新東西）
  SYMBOL 全線 —— -2 不掃、-4 不修（OCR 污染僅 0.3%）、-5 第一版反效果暫緩、
               -3.1 量測工具停在未過審（數字只當線索）

**這批多數是「查完決定不做」。動它們之前先讀理由，那些理由都是實測換來的。**
```

## 狀態總表

label 格式與字母語意見 [CLAUDE.md](CLAUDE.md)「工作項目命名規則」。
legend：`✅完成 / 🔵進行中 / ⬜未起 / ⏸暫停 / ⚠️卡住`

| 線 | 當前 item | 狀態 |
|---|---|---|
| `REBUILD` | `REBUILD-5`（驗收與切換） | ✅ |
| `CUTOVER` | `CUTOVER-4`（v155 退役） | ✅ |
| `BACKUP` | — | ✅ **全線完成 2026-08-03**：`-1` 檔案備份／`-2` 索引冷備份／`-3` 還原演練通過（數字逐項對上）／`-4` 排程已接（每日 03:00，無新抽取成果則跳過）。還原點 1 → **3** |
| `SCANNER` | `SCANNER-1`（∂ 誤讀探針接進 daily-check） | ✅ 完成 2026-08-03（commit `f637aea`，基準 `tests/scan-partial-baseline.json` 進版控） |
| `SYMBOL` | — | ⏸ **全線無在跑項目**：`-1`／`-2`（不掃）／`-3`／`-4`（不修）✅ 已定案；`-5`（改 prompt）第一版實測反效果**暫緩**；`-3.1`（量測工具）**停在未過審**，數字只當線索 |
| `VERIFY` | `VERIFY-1`（`compat-check` 加 `suite` 欄） | ⬜ 常態線，只在有待辦時列 |
| `PPWORK` | `PPWORK-12` 之後無新項 | ✅ 大部分完成，殘項見「其他待辦」 |
| `SPEEDUP` | `SPEEDUP-2`（`MAX_ASYNC` 2→4） | ✅ **已改並實測驗證**（PO 2026-08-03 拍板降檔為一般票）。`SPEEDUP-2.1`／`SPEEDUP-3` ✅；`SPEEDUP-1`（MTP）⏸ **PO 判不划算，不做**——理由見下 |
| `SCALEUP` | `SCALEUP-1`（390 份） | ⬜ 等上面收斂 |

---

## 現況（2026-08-03）

**acoustics_v2 已接手上線，acoustics_v155 已完全退役。** 重建的階段 0–5 全部
完成：0–3 經主線獨立驗收，切換與退役於 2026-08-03 執行完畢並實測驗證。

```
唯一的庫  acoustics_v2
checkout  ~/ghq/github.com/neknufelet/lightrag（單一，無 worktree、無 v1/v2 分身）
服務      lightrag :9621（容器 lightrag-acoustics_v2）
          kbapi    :9700（容器 kbapi-acoustics_v2）—— 三個 skill 全走這裡
儲存      lightrag-postgres（database `lightrag`）＋ lightrag-neo4j，2026-08-03 從
          DeepTutor 共用實例搬出，資料在 /data/lightrag（postgres 622 MB、neo4j 2.1 GB）。
          lightrag-neo4j 只有 neo4j／system 兩個 database ＝ 專用實例，不再跨專案共用
內容      20 份 processed / 0 failed、7,211 實體、10,500 關係、510 chunk、可疑率 4.5%
排程      lightrag-daily-check.timer   每天 08:30 跑 compat-check + canary
          lightrag-cold-backup.timer   每天 03:00 冷備份（沒有新抽取成果就跳過不停機）
          兩者紅燈都打自架 ntfy（/opt/stacks/ntfy :9800），腳本自己掛掉各有 OnFailure 備援
v155      已不存在。Neo4j label、Postgres 列、磁碟目錄、容器全部移除，數字見 CLAUDE.md
```

> **備份**：兩條都已接上（2026-08-03）。① `/data/rag/lightrag`（含 `__parsed__`
> 與 `records/`）走 backrest plan `lightrag-snapshot`，每 6 小時，**並驗過能還原**。
> ② 索引本體（`/data/lightrag` 的 Postgres＋Neo4j）走 `scripts/backup-cold.sh`
> 冷備份。在此之前 ① 一直沒有備份而文件宣稱有——詳見下方「接上備份」。
> **還原演練 `BACKUP-3` 已於 2026-08-03 通過**（拉回雲端快照、起臨時 DB、數字逐項對上）。
> **仍缺的是冷備份的排程**——實測發現索引本體目前只有**一個**還原點，同節有處置。

> **今天的裁決材料**：`SPEEDUP` 與 `SYMBOL-3` 兩條線的工單與終審判定全文
> （15 份，含 fable 的設計單、sol 的五份判定）存在
> `$RECORDS/review/20260803-speedup-symbol3/`——**在 `/data`、已在備份範圍內**。
> 本檔引用它們一律用 `$RECORDS/…`，不要寫成 `/tmp` 的 session 路徑（一清就死）。

> **路徑約定**：本檔寫 `$RECORDS/…` 一律指
> `/data/rag/lightrag/acoustics_v2/records/`——**在 `/data`，不在 git**
> （已在 backrest 範圍內）。寫成相對路徑會被誤讀成 repo 內的檔案。

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

### `SYMBOL-1` — 50 題考卷：判「驗不了」那桶健不健康　✅ 完成 2026-08-03

**結論：這桶子不是幻覺問題，是【檢索價值】問題。**

母體 1,482 個「符號型／驗不了」實體，seed=20260803 取排列前 50，由主線逐題
讀來源 chunk 原文親手標。答案卷進版控：[tests/symbol1-answer-key.json](tests/symbol1-answer-key.json)。

| 判定 | 50 題 | 外推到 1,482（Wilson 95%，含有限母體修正） |
|---|---:|---|
| `correct` 從符號推論出真概念 | 19（38%）| 386–765 個 |
| **`restated` 名字實質就是符號本身** | **27（54%）** | **601–990 個** |
| `wrong` 與來源不符 | 4（8%）| 48–277 個 |
| `unjudgeable` 讀了也判不出 | 0 | — |

**NEXT.md 原本把問題設成二選一（正確推論 vs 垃圾），實際上主要族群是第三種。**
`restated` 不是錯、不會給出錯誤答案——它們的名字實質就是符號本身。
例：`Nn,v, (II)`（同一格的列標題就寫著「Mode norms in (II)」，真概念名就在旁邊
沒被用）、`S Sub 0 N Squared`（把 S_{0,n}² 唸出來）、`Variable X`、`Gamma Constants`
（命名的是希臘字母，而 Γ 在該處是傳播常數、隨頻率變，叫 constant 還輕微誤導）。

> ~~它們只是**永遠不會被檢索命中**。~~
> **⚠ 這句在 2026-08-03 被 `SYMBOL-3` 實測推翻，原文保留以免下次又寫回來**：
> 27 個已標註 `restated` 在 59 個成功的熱門標籤探針中**有 6 個被命中**
> （且經查沒有任何一個本身是查詢種子，不是自撞）。全稱命題一個可信命中即推翻。
> 正確的說法見下方 `SYMBOL-3` 那節。

**四個 `wrong` 的性質不同，處置也不同：**

- `Density Fluctuation`（N Flow）：整個 chunk 對 density/rho/ρ 命中 **0 次**，
  原文用的是 `Π'=ln(p'/p₀)`，是**壓力**擾動。模型靠領域先驗補的。
- `Mechanical Resistance`（C）：該段講的是互易網路（Z→Z_r=r²/Z*），沒有機械阻。
- `Impedance Mismatch Matrix`（2017 Metadiffusers）：原文是 transfer matrix，
  「阻抗失配矩陣」是不存在的物件。
- **`Brota Parameters`（G Porous）：根因不在模型。** 原文寫 `BroT's parameters`
  ——那是 **`Biot` 被 OCR 弄壞**（P/Q/R 是 Biot 多孔彈性理論的標準參數）。
  模型忠實抄了壞掉的專有名詞。**這一類要往上游修，不是修抽取。**

**同族的上游污染在 `restated` 裡也很多**：`Z0 V11x`（`v_{I|x}` 的 `I|` 被讀成 `11`）、
`P11 Function`（`p_{II}` 的羅馬數字 II 被讀成 11）、`Axial Wavenumber L A`
（`Γ_a` 的 Γ 被讀成 L）。**這些與已記載的 domain_fact「羅馬數字下標難讀」同源。**

**這 50 題不能說的話**：樣本涵蓋 6 份文件，另外 9 份（共 30 筆、佔母體 2%）
未抽到，本結論不涉及它們。逐文件數字（C n=27、K n=9、N n=7、G n=5、其餘 n=1）
樣本太小，只看形狀不看比例——但 **N Flow 的 7 題有 6 題 correct、0 題 restated**，
與 C 的 27 題有 18 題 restated 形成明顯對比，值得後續查是「散文密度高的文件
抽得比較好」還是抽樣巧合。

**抽樣可延伸**：用固定種子的排列取前綴，日後擴到 100 題時**前 50 題不必重標**。

### 由 `SYMBOL-1` 長出來的：`SYMBOL-3` — restated 怎麼處置　✅ 已量 ＋ PO 2026-08-03 拍板選 ②

**量法**：`scripts/symbol-hits.py`（`SYMBOL-3.1`），判準刻意與
`entity-merge.py cmd_plan` 逐項相同（熱門標籤當種子、`mode=mix`、
`chunk_top_k=1`、同查詢同名兩次算兩格），因為 `rebuild-plan` 階段 4
就是用那把尺得出「254 組從未被檢索到 → 254 次不可逆操作換 0 收益」。
報告在 `$RECORDS/bench/symbol3-hits{,-60}.json`。

**⚠ 這些數字的 estimand 要講清楚，否則會被誤讀**（終審逐條糾正過主線的初稿）：

| 量到的 | 30 種子 | 60 種子 | **它到底是什麼** |
|---|---:|---:|---|
| 總實體格位 | 1,795 | 3,218 | 探針下 API 回傳的 entity entries 總數 |
| 符號桶佔格位 | 438（24.4%）| 744（23.1%）| **entity entries 的佔比，不是脈絡佔比**——沒計描述長度、關係、chunk 或 token |
| 符號桶被命中過 | 356/1,482 | 498/1,482 | 固定探針下的**普查**，是確值。~~Wilson CI~~ **用錯了**（普查不是抽樣）|
| 從未被命中 | 1,126 | **984** | 可與階段 4 的「254 組」對比 |

**成立的結論**：「`restated` 永遠不會被檢索命中」**被推翻**（27 個中 6 個被命中，
且沒有一個本身是查詢種子）。全稱命題一個可信命中即推翻，與 CI 寬窄無關。

**不成立的說法**（主線初稿講錯、終審糾正）：
- ❌「符號型吃掉四分之一的檢索脈絡」——那是 entity entries 佔比，且熱門標籤
  種子不是真實查詢流量（`rebuild-plan.md:258` 記載這類種子會被少數大文件壟斷，
  曾有 12 份文件一次都沒被命中）。
- ❌「restated 與 correct 沒有差異」——Fisher `p≈1.00`、差值 −2.5 pp、
  **差值 95% 區間橫跨 −27 pp 到 +20 pp**。正確說法是「小樣本沒有偵測到差異，
  也沒有能力排除很大的差異」。**加查詢數解不了**（答案卷的 n 永遠是 27／19）；
  要判等價需每組約 275 個標註（±10 pp），換算約 725 題人工標註。**不值得。**

**PO 2026-08-03 拍板：選 ② 改抽取 prompt**（「若同格／鄰近有概念名，優先用它」）。
理由是這個選擇**不依賴那個量不準的數字**：只影響未來的 390 份、不動既有資料、
可逆、成本低。① 不動的原本理由（反正永遠不被命中）今天被推翻了；
③ 事後合併既有實體不可逆，而且現有數據**證明不了**它有收益——階段 4 的前車之鑑。

- [ ] **`SYMBOL-5`：把 ② 落成抽取 prompt 的改動 —— ⚠️ 第一版實測「反效果」，暫緩。**

      **好消息**：改得動，而且**不必動 LightRAG 的程式碼**。它有官方注入點
      `ENTITY_TYPE_PROMPT_FILE`（env）／`addon_params["entity_types_guidance"]`，
      內容會落在抽取 prompt 的 `---Entity Types---` 段。
      ⚠ **那是整段取代**——自訂檔案必須把原本 11 種型別的清單一起帶上，否則分類法會掉。

      **壞消息**：探針實測（2026-08-03，6 個真實 chunk × 加/不加規則，唯讀不寫 DB，
      材料在 `$RECORDS/review/20260803-speedup-symbol3/naming-probe-*.json`）
      顯示第一版規則**把無害問題換成有害問題**：

      - chunk-142 原文對「mode norm」「norm」「propagation constant」「impedance」
        **各出現 0 次**，加規則後模型卻抽出 `Mode Norm`、`Propagation Constant`、
        `Impedance Function`。**`Mode Norm` 正是我寫在規則裡的舉例**——模型把例子當資料抄。
      - chunk-049 加規則後抽出 `Z 0 V 11 X`、`K 0`、`D N`、`P`、`R`、`X`、`T`
        ——符號拼音**加了空格**，比原本更爛，還冒出單字母實體。
      - 總實體數 61 → 86（+41%），多出來的不少是這類。

      ⇒ **拿 `restated`（無害）換 `wrong`（有害）。**

      **實驗本身的缺陷（必須一起記，否則下次會誤讀）**：控制組**沒有重現**當初的
      爛名字（0/7）——原樣重跑那些名字本來就不見了（輸出跨批次非決定性，見
      `SPEEDUP-2` 副產物②）。所以「加規則後爛名字消失」證明不了任何事；
      **站得住的只有另一半**：加規則後出現了原文裡沒有的名字——那個不受重跑變異影響。

      要再試的話，下一版必須：① **不放具體例子**（會被抄）；② 明文禁止輸出原文中
      不存在的名稱；③ 判準改成「**有沒有編造**」而不是「爛名字有沒有消失」。
      也可能該收手：`restated` 無害，而每次嘗試都在冒「換成有害」的風險。
**⏹ `SYMBOL-3.1`（量測工具）：PO 2026-08-03 拍板停在此處，不走完重票流程。**

工具已產出它該產出的數字，`SYMBOL-3` 的決策也據此下完。但它**本身未過終審**：

- 第一輪（code）終審 BLOCK：健全性檢查只是報告不是擋板、JSON 缺逐查詢
  provenance（無法稽核哪個實體被哪個查詢命中）、判準一致性測試部分假綠
  （只用 AST 讀 3 個常數）、統計呈現會誤導。
- **票級也判錯**：實際 diff 416 行命中觸發清單 #7（>200 行），本來就該是重票。
- 補走重票後：fable 出設計單 → sol 單審 **BLOCK**（T12 自相矛盾、零成功查詢仍會
  假綠、`known_short_seed` 會誤放行、抽樣契約沒被閘門證明）→ fable 已修訂 →
  **停在「等第二次單審」**。

**停的理由**：它唯一的未來用途是當「`SYMBOL-5` 改 prompt 前後的對照器」，
而 `SYMBOL-5` 第一版實測反效果、已暫緩——**沒有消費者了還在磨，是為不存在的
用途付成本**。

⚠ **因此 `symbol-hits.py` 的數字一律當「線索」不當「證據」**，
引用時必須帶上 `SYMBOL-3` 那節列的五個弱點。日後若重啟命名那條線，
**重做工具而不是接續這輪**——修訂版設計單留在
`$RECORDS/review/20260803-speedup-symbol3/ticket-symbol3-r2.md`（含 sol 的兩份判定）。### `SYMBOL-4` — OCR 污染要不要回頭修　✅ 已量，**不修**（2026-08-03）

`Brota`／`V11x`／`P11`／`L A` 都是上游解析錯誤被忠實抄進索引。

**先講一個讓這一族至今沒被抓到的性質**：**它對接地檢查是隱形的。**
`Brota Parameters` 能對上原文——因為**原文本身就被污染了**（`BroT's parameters`
真的在裡面）。所以它永遠不會進「可疑」清單。偵測器必須看**原文**，
不能看「實體 vs 原文」的比對。

**規模（`$RECORDS/review/20260803-speedup-symbol3/ocr_sizing.py`，母體 7,211 個實體名）**：

```
數字 11/111（羅馬 II/III 誤讀）   17 個　例全為真：Z0 V11x、Pressure Field p11、Acoustic Pressure P11
字母數字黏連（V11x 型）            4 個　其中 T33s/T13s 是應力張量分量，正常寫法
詞中大寫（BroT 型）               27 個　多半是符號音譯不是 OCR 壞字
孤立單字母（Γ→L 型）             695 個　**幾乎全是雜訊**：Maximum Distance R Max、Epsilon I 都是正常命名
```

⇒ **真正的 OCR 污染約 17–30 個，佔 0.3%。**

**不修的理由**：修既有的要「改上游解析 → 重建索引 → 重抽 4 小時 → 不可逆操作」，
換回約 30 個實體的名字；而且**沒有便宜的上游修法**——`Γ`→`L`、`II`→`11` 是
MinerU 的極限，`model-observations.json` 的 domain_fact 已記載「兩雙眼睛方向
相反地都會錯」。符合停損原則：**有問題 ≠ 值得修，先量代價再排序**。
按比例外推 390 份約 330–580 個，仍是小數目。

**若日後真要做偵測器，別走枚舉那條路。** `scan-partial.py` 的三代演進已經證明：
①枚舉符號→族一直長；②加白名單→**白名單是枚舉換了個方向**；③結構性規則才成。
列一張「已知錯法清單」（II→11、Γ→L、Biot→BroT）就是重犯第一代。

### `SYMBOL-2` — 用模型判那 1,482 個　✅ 實驗完成 2026-08-03（決策未下）

拿 `SYMBOL-1` 的 50 題當考卷，`gpt-5.6-luna` 跑三組。結果進版控：
[tests/symbol2-results.json](tests/symbol2-results.json)。

| 組 | 脈絡 | 推理 | 與人工一致 | 95% CI | `wrong` 召回 | `wrong` 誤報 |
|---|---|---|---:|---|---|---:|
| A | 截斷 700 字元 | low | 32/50 (64%) | [50, 76] | 3/4 | 6 |
| B | 完整 chunk | low | 36/50 (72%) | [58, 83] | 1/4 | 6 |
| C | 完整 chunk | **xhigh** | **41/50 (82%)** | [69, 90] | 2/4 | **0** |

**主線原本的預測被推翻。** NEXT.md 寫「主線的預測是『普通＋加大脈絡』會贏……
多給脈絡通常比多給推理有效，而且便宜得多」。實測：加脈絡 +8pp（A→B，
McNemar p=0.34 不顯著），**在脈絡之上再加推理又 +10pp**（B→C，p=0.23 不顯著；
但 A→C p=0.012 顯著）。**推理的貢獻不小於脈絡。** 那個前例（`X a` 拉長脈絡就
解決）不能外推到這個任務。

**但一致率不是該用的指標。** 真正要問的是「能不能撈出該人工看的那些」：

- **C 組零誤報**，但只召回 2/4。
- **A∪B 的聯集召回 4/4**，代價是撈出 12/50（24%）、誤報 8。
- **多數決反而更差**（召回 2/4、誤報 4）——因為三組抓到的是**不相交的子集**，
  投票把各自的獨門命中投掉了。這條要記住：**這個任務不能用多數決做 ensemble。**

**模型最擅長的是 `restated`**：C 組 27 題判對 24。那是母體的最大宗（54%），
而且是**結構性**判斷（名字是不是就是符號本身），不太需要領域推理——
這也暗示 `SYMBOL-3` 也許用便宜得多的手段就能量。

**部分分歧是題目的問題不是模型的問題。** `J0 Function`、`Transmission Component Ta`、
`Integral Operation` 三題模型判 `correct` 我判 `restated`——`correct`/`restated`
的界線是我畫的，這幾題本來就在線上（我在答案卷裡對 #22 就寫了「介於兩者之間，取嚴」）。
要把這條線變成可自動化的判準，**得先把 rubric 寫得比現在硬**。

**NEXT.md 警告的陷阱沒有出現**：三組都完整作答 50/50，沒有空字串、沒有預算耗盡。

**成本**：A 的 log 53 KB、B 159 KB、C 163 KB；C 約 4–5 分鐘，B 約 1 分鐘。

**✅ `SYMBOL-2` 的決策已下（PO 2026-08-03）：不掃全部 1,482。**

**理由不是「掃不準」，是「掃出來也不會拿去做任何事」**：

1. A∪B 會撈出約 350 個要人看（24%），**其中約七成是誤報**；
2. `SYMBOL-3` 已拍板**不動既有資料**（只改未來抽取），所以那份清單**沒有消費者**；
3. 模型最擅長判的是 `restated`——**正好是無害那一族**；它對 `wrong`（有害那族）
   推理拉滿也只召回 2/4。**工具的強項與問題的所在錯開。**

實驗本身的價值仍在（`tests/symbol2-results.json` 進版控）：它量出了
「加脈絡 +8pp、在脈絡之上再加推理又 +10pp」與「**這個任務不能用多數決做
ensemble**」（三組抓到不相交的子集，投票把獨門命中投掉）。那兩條是耐久的。

## `BACKUP` — 接上備份

**兩條都接上了（`BACKUP-1`／`BACKUP-2` ✅），缺的是還原演練與排程。**
2026-08-03 查證：文件宣稱 `/data/rag` 在 restic 備份範圍，
**那是假的**——backrest 當時只涵蓋 `/data/rag/knowledge_bases`（DeepTutor 的庫）。
假的安全宣稱比沒有宣稱更危險，因為你會照著它做決定。

- [x] **`/data/rag/lightrag` 已接上**（plan `lightrag-snapshot` → repo `rag-db`，
      cron `30 */6 * * *`，保留 14 日／8 週／3 月）。backrest 容器早就把 `/data`
      唯讀掛成 `/userdata/data`，所以不用改掛載、不用重建容器。
      **已驗過能還原**：首份快照 `f2d40c9f`（203.198 MiB／3,118 檔），
      `restic restore` 取回 `records/` 的 73 個檔，**sha256 逐位元與現役相同**。
- [x] 修掉 `.env.example` 與 README 裡「restic 備份範圍」的假宣稱

### `BACKUP-2` — 索引本體　✅ 完成 2026-08-03

**搬家把這題變簡單了。** DB 從 DeepTutor 的共用實例搬進自己的 `lightrag-postgres`／
`lightrag-neo4j` 之後，「只備我們的」不再需要 `pg_dump`／`neo4j-admin dump`——
整個 `/data/lightrag` 就是我們的，停機抄目錄即可。**pg_dump 路線為什麼被取代、
為什麼要停機、為什麼先抄本地再上傳**，理由都寫在 `scripts/backup-cold.sh` 檔頭
（commit `c6d07da`、`54f86f7`），這裡不重抄。

| 路徑 | 大小 | 備份 |
|---|---|---|
| `/data/rag/lightrag`（解析快取＋裁決紀錄） | 215 MB | ✅ backrest plan `lightrag-snapshot`，每 6 小時 |
| `/data/lightrag/postgres`（**7,211 實體／10,500 關係／向量都在這**） | 622 MB | ✅ `backup-cold.sh` 冷備份 |
| `/data/lightrag/neo4j`（圖） | 2.1 GB | ✅ 同上 |

實測 2026-08-03（restic repo `rag-db`）：`--tag lightrag-db` 兩份
`e8af6a5b`（12:59）、`25a3048a`（13:54），各 2.633 GiB；
`--tag plan:lightrag-snapshot` 兩份 `f2d40c9f`（10:45／203.198 MiB）、
`07289a88`（12:30／207.263 MiB）——**後者是 cron 自己跑出來的，排程確實在動。**

- [x] **`BACKUP-4`：冷備份的排程　✅ 完成 2026-08-03。** ⚠️ 起因是 `BACKUP-3` 演練查出的事：
      restic 的兩份 `lightrag-db` 快照（`e8af6a5b` 12:59、`25a3048a` 13:54）
      **逐位元相同**——`restic diff` 回 `0 new, 0 removed, 0 changed`。
      13:54 那份不是新的停機複製（若是，`pg_control` 的關機時戳一定會變），
      是同一份 stage 被重複上傳。⇒ 當時索引本體**只有一個還原點**。

      **已完成的一半（commit `3fee838`，2026-08-03 實測三種情境）**：
      腳本加了「沒有新的抽取成果就不停機」的判斷。判準是資料庫內容指紋
      （`doc_status`／`doc_chunks`／`entity_chunks`／`relation_chunks` 的計數
      ＋ `max(updated_at)`），不是時鐘。

      ```
      第一次（無指紋檔）  真的備份 → 快照 522c330a，停機 21:30:03–21:31:19（75 秒）
                          2.633 GiB 的資料，**實際只存進 1.448 MiB**（restic 內容去重）
                          本地複製只花 1 秒 —— 停機幾乎全在容器優雅關機與健康檢查
      第二次（指紋未變）  跳過、不停機、exit 0；服務 Up 時間未被重置
      第三次（--force）   照跑
      ```

      ⇒ **現在有兩個還原點**（12:59、21:30）。

      **✅ systemd timer 已接（2026-08-03）**：`lightrag-cold-backup.timer`
      每日 `03:00`（與 08:30 的 daily-check 錯開，也避開白天查詢時段）、
      `Persistent=true`（關機錯過會補跑）、`TimeoutStartSec=3600`（上傳走 Google Drive
      要留餘裕，但不能無上限否則掛住沒人知道）。失敗走
      `lightrag-cold-backup-crashed.service` 獨立備援通知——**刻意不走 `notify.sh`**，
      照既有慣例：備援不能依賴可能正是故障原因的主路徑。該通知的內容特別提醒
      **「服務可能停著」**，因為冷備份失敗與 daily-check 失敗的後果不同。
      實測：`systemctl start` 觸發 → `Result=success`、輸出在 journal 看得到、
      正確跳過、四個容器 Up 時間未被重置。
      - [ ] **擴量期間改成每批跑一次**：390 份分批索引，每批完是自然停頓點，
            那時停 75 秒不影響任何事。不必改排程，手動跑即可。

### `BACKUP-3` — 還原演練　✅ 完成 2026-08-03，**通過**

**從雲端整份拉回來、起臨時資料庫、逐項對數字，全部對上。** 現役未被觸碰。

實測（dker，主線親跑，臨時容器 `-restoretest` 後綴、不綁埠、拆乾淨）：

```
restic restore 25a3048a → /data/backups/restoretest
  Restored 1724 files/dirs (2.633 GiB) in 3:12        ← 下載方向首次被走過

臨時 PG（pgvector/pgvector:pg16，掛還原目錄）
  log: database system was shut down at 12:59:37      ← 乾淨關機，非崩潰復原
  chunks|entities|relations|docs = 510|7211|10500|20  ← 與現役逐項相同
  向量表 7211|10500|510                                ← 檢索本體也完整

臨時 Neo4j（neo4j:5，掛還原目錄）
  15 秒 Started.
  7211 節點 / 10500 關係                               ← 與現役相同
  抽樣實體帶得到 description，不是空殼
```

**三件實測換來的事：**

1. **「權限會擋住 PG」這個擔心是錯的。** 還原出來的 `postgres/` 是 `755`（`backup-cold.sh`
   的 `chmod -R a+rX` 造成），現役是 `700`——但官方映像的 entrypoint 會自己修正，PG 正常啟動。
   **不必為此改備份腳本**（記在這裡，免得下次有人又擔心一次）。
2. **冷備份真的抓到一致狀態**：PG 開機 log 是乾淨關機，沒有崩潰復原。停機再抄這個做法成立。
3. **還原只能落在 `/data/backups`**：backrest 容器把 `/data` 唯讀掛成 `/userdata/data`，
   只有 `/data/backups` 是可寫的。下次還原時直接用那裡，別浪費時間試別的路徑。

- [ ] **算一次「全毀要多久重建」**再決定要做到什麼程度。目前已知：
      `__parsed__` 重解析 6–10 小時（已有備份，不必重跑）、抽取 3 小時 58 分、
      嵌入 4.56M 字元 ≈ US$0.15。**人工裁決那部分重跑也回不來**，但它在
      `records/` 裡，已經備份到了。

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
      **2026-08-03 起真的有備份了**（在那之前這句是空話），但仍**不在 git**——
      三個月後問「為什麼 `\mathfrak{O}` 在白名單上」，答案存在但不在版控裡、
      不會出現在任何 diff。
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

- [ ] **`SPEEDUP-1` MTP 加速評估 —— 三關已查兩關，`SPEEDUP-1` 原本的兩個前提都被實測推翻**
      （2026-08-03 在 coder 上實查；**這台就是 `100.71.26.77`**，llama.cpp 跑在這裡）：

      **關卡① GGUF 有沒有 MTP 權重 —— ❌ 沒有，定案。** 直接解析 GGUF 表頭
      （不是 `strings` 猜的：`strings` 掃到的 `mtp`／`draft` 全是 tokenizer 詞表）：
      `Qwen3.6-35B-A3B-UD-IQ4_XS.gguf` 有 **733 個張量、`blk.0`–`blk.39`、
      `nextn`／MTP 相關 0 個**（arch `qwen35moe`、`block_count 40`）。
      MTP 頭應該在 `blk.40.nextn.*`。**要用 MTP 就得換檔**——HF 上有保住 MTP 頭的
      同階量化（`unsloth/Qwen3.6-35B-A3B-MTP-GGUF`、
      `localweights/Qwen3.6-35B-A3B-MTP-IQ4_XS-GGUF` 等），不是重新轉檔才有。

      **關卡② 顯存 —— 很緊，未驗。** 2× RTX 3060 共 24 GiB，目前已用 21.4 GiB
      （free：GPU0 805 MiB、GPU1 1,601 MiB）。MTP 頭是 Q8_0 約 0.5–1 GiB 量級
      `(未驗,推測)`，換檔後塞不塞得下要實測。

      **關卡③ 驗證不是相信 —— 原本的判準已被實測推翻，要改寫。**
      原文寫「同一個 chunk 開關各跑一次，比對輸出是否逐字相同」當無損判準。
      **2026-08-03 實測：不開 MTP、`temperature=0`、固定 seed，輸出在不同併發度
      下就已經 `0/8` 逐字相同**（連續批次改變批次組成 ⇒ 浮點累加順序變）。
      所以「逐字相同」在併發環境**結構性不成立**。可行的替代：
      **固定 `--concurrency 1` 比對**（實測 c=1 是決定性的，兩輪 `completion_tokens`
      都是 14,266），或改用非逐字的判準。tok/s 那半不變，且**要看
      `decode_tok_s`**——MTP 只加速生成段，用牆鐘 `tok_s_aggregate` 會被 prefill 稀釋。

      **前提壞掉之一：「強制 `n_parallel=1` 對我們免費」不成立。**
      伺服器現在跑 `--parallel 4`（啟動 log `n_slots = 4`、`n_ctx_slot = 32768`），
      不是文件寫的單 slot。開 MTP＝把 4 個 slot 降成 1 個，而 390 份抽取正是
      併發批次負載。上游對 `n_parallel=1` 的強制我們**尚未在 build 10200 親驗**
      `(未驗,推測，來源＝下方參考連結)`。

      **前提壞掉之二：旗標名稱已改。** build 10200（`5f55650a7`）的列舉是
      `--spec-type none,draft-simple,draft-eagle3,draft-mtp,draft-dflash,…`
      ——是 **`draft-mtp`** 不是 `mtp`。`--spec-draft-n-max` 預設就是 3。

      **旁證（不是我們的實測）**：同為 Ampere＋同一顆 A3B MoE 的公開 benchmark
      （RTX 3090、`UD-Q4_K_XL`）在 llama.cpp 上**所有非 MTP 的投機變體都是負收益**：
      baseline 135.7 tok/s、ngram-mod −4%、ngram-cache −13%、classic draft −11%、
      DFlash −44.6%；作者明說是單流結果、**不能外推到併發批次**。
      ⇒ 不需要換檔的 `ngram-*` 那條便宜路線，先驗期望值就偏低。
      https://github.com/thc1006/qwen3.6-speculative-decoding-rtx3090

      **我們自己的基準（從現役 server log 撿的，非受控）**：4 slot 併發下
      tg 約 50–62 tok/s／slot、prompt eval 600–1,130 tok/s。
      **受控基準還沒建**——沒有它，任何 A/B 都沒有尺。

      參考：https://ai-coding.wiselychen.com/llama-cpp-mtp-merged-local-llm-2x-speedup/

      **⏸ PO 2026-08-03 拍板：MTP 與 vLLM 都不做。理由是 `SPEEDUP-2` 量出來的
      新事實 —— GPU 在 c=4 已接近飽和**（c=4→c=8 只 +4.6%，曲線壓平）。
      投機解碼的收益來自「單流解碼時算力閒著」，而**批次吃的是同一塊 headroom**，
      我們已經用併發吃掉了。用實測的 server 端 decode 速率估：

      | 情境 | 單題 decode | 併發 | 等效總 decode |
      |---|---:|---:|---:|
      | c=1（現況） | 77 tok/s | 1 | 77 |
      | **c=4（現況）** | 35 tok/s | 4 | **≈140** |
      | MTP ＋ 強制 c=1（樂觀 1.7×） | ≈131 tok/s | 1 | **≈131** |

      ⇒ **MTP 單流跑到最好，大約就是四路併發已經有的水準**，代價是 19.4 GB
      下載、換模型檔、顯存只剩 2.4 GB、還要照 `A-23` 重新量測模型觀察。
      **唯一的翻盤條件**：若 build 10200 的 `draft-mtp` 其實**沒有**強制
      `n_parallel=1`（旗標從 `mtp` 改名成 `draft-mtp` 說明實作動過），
      疊在 4 路併發上才可能真贏。驗法很便宜（起測試伺服器讀 log 的 `n_slots`），
      但要先下載 19.4 GB 且顯存不夠同時跑兩個伺服器。
      **vLLM 不做**：MTP 實作確實較好（同硬體 +27.5% decode），但 24 GB 顯存
      吃緊、GGUF 支援是實驗性的、兩張 3060 無 NVLink 走 PCIe 的 tensor parallel
      對 MoE 常是負收益，而且整條契約要重驗——**基礎設施搬遷換個位數百分比**。

### `SPEEDUP-4` — gleaning 佔比　🔵 已量一輪，**不足以下永久裁決**（2026-08-03）

每個 chunk 被 LLM 讀兩次：① 初次抽取 ②「補抓遺漏或描述錯誤」。
原假設是「補抓多半重工或撈渣，砍掉可省一半」。**實測推翻了這個假設**，
但第二意見（luna）指出證據撐不起「不要砍」這個永久結論。

**量到的**（dker，母體＝`lightrag_llm_cache` 的 1,019 筆 `extract`）：

```
            呼叫數  輸出字元佔比  抽出實體  每次實體   符號型佔比
initial      510      60.3%      6,372     12.5      14.8%
gleaning     509      39.7%      3,912      7.7      24.9%   ← 1.69 倍
邊際（458 個兩輪都可解析的 chunk）：
  補抓抽出 3,439 個名字 → 第一輪已有 227（6.6%）、真正新增 3,212（93.4%）
  新增裡符號型 878、非符號型 2,334
```

**⚠ 這些數字有五個已知弱點（luna 逐條指出，主線接受）**：

1. **「非符號型＝有用」只是弱代理。** 專案自己定義符號型是「驗不了」不是失敗；
   50 題樣本裡符號型有 38% 是正確概念推論，且 `restated` 實測會被檢索命中。
2. **分類母體對不上。** `--dump-symbolic` 是從**最終 VDB** 分類（已過解析、去重、
   跨 chunk 合併），卻被拿來標**原始 cache 輸出**。
3. **完全沒量關係。** gleaning 同時補 entities 與 relationships，可能補的是
   「兩個已存在實體之間的邊」——只數名字會漏掉它真正的價值。
4. **「同 chunk 內是新名字」≠「最終索引多一個節點」。** 2,334 很可能高估
   （跨 chunk 合併會吃掉一部分；大小寫不敏感比對可能把別名／下標變體算成新的）。
5. **字元佔比不是時間佔比。** 該用 completion tokens；gleaning 把第一輪內容放進
   歷史，prefill 成本不同（且本庫 prompt 前綴分岔、快取幾乎命不中）。
   可能超過 40% 也可能就是 40%，**沒量就不能斷言**。

**現階段的結論（採 luna 的措辭）**：原始快取顯示 gleaning 產生大量新候選，
**足以擋掉盲砍**，但尚未完成 parser-aware／merge-aware／relation-aware／
query-aware 的 A/B，**不足以永久封殺 selective gleaning**。

- [ ] 真要定案，缺的量測是：用實際 parser 重播、比對**最終 unique 節點與邊**的增量、
      量 `prompt_tokens`／`completion_tokens` 與 prefill/decode 時間、
      以及固定查詢集下的檢索品質 A/B。
- [ ] **獨立問題：63 筆（6%）`return_value` 不是合法 JSON**（initial 41、gleaning 22）。
      我的 `json.loads` 失敗**不等於** LightRAG 的 parser 也失敗——要用實際 parser
      重播那 63 筆才知道內容有沒有整批掉。這條與 gleaning 無關，但同樣沒人在看。

- [x] **`SPEEDUP-2.1`：受控吞吐基準工具**（`scripts/llm-bench.py`，commit `580a6f1`
      ＋ `3299ee9`）。四輪終審才過，每輪擋掉一個會產生錯數字的缺陷；判定原文四份。
      題本走 `$RECORDS/bench/`（含論文原文，不進 git）。

- [x] **`SPEEDUP-2`：`MAX_ASYNC` 2 → 4 —— ✅ 已改並驗證（2026-08-03）。**

      dker `.env` 改 `MAX_ASYNC=2` → `4`（備份 `.env.bak-20260803-maxasync`），
      `docker compose up -d lightrag` recreate（**`restart` 不會重讀環境變數**）。
      驗證輸出：健康檢查 5 秒轉 healthy、容器內 `printenv MAX_ASYNC` → `4`、
      `/health` `status=healthy pipeline_busy=False core_version=1.5.5`、
      kbapi :9700 HTTP 200、索引完整 510 chunk／7,211 實體／10,500 關係。
      **PO 拍板降檔為一般票**（單一數值、可逆、已有實測支撐）。
      ⚠ **真正的 4 路併發要到下一次抽取才會被實際行使**——目前只驗到
      「設定已生效、服務健在」，吞吐改善本身 `(未驗,推測)` 直到 `SCALEUP-1`。

      **量測結果**（2026-08-03，coder 實跑；報告在 `$RECORDS/bench/`，
      題本 `fixture-8.json` sha `7bfaf16d…`，伺服器 `b10200-5f55650a7`、
      `total_slots=4`、`cache_prompt=false`、`max_tokens=4096`、`trunc=0`、
      兩輪反序）：

      | 併發 | tok/s（R1／R2） | 相對 c=2 | p50 延遲 |
      |---:|---|---:|---:|
      | 1 | 67.83／68.01 | 0.82× | 25 s |
      | **2（現況）** | 84.01／81.82 | — | 32／40 s |
      | **4** | 107.47／105.44 | **+28%** | 60／64 s |
      | 8 | 110.03／112.85 | +34% | 97／110 s |

      **結論：2 → 4 買到約 +28% 吞吐；4 → 8 只再多 4.6%，但 p50 延遲從 62 s
      漲到 104 s。建議調到 4，不要調到 8。** `LLM_TIMEOUT=600` 對 c=4 有餘裕。

      **票別＝重票**（觸發清單 #4「動 `.env` 的鍵」）。改動本身可逆，
      但要走五站。順帶修 `.env.example`（寫 4）與 live `.env`（是 2）的不一致。

      **粗估效益**：現有 20 份抽取花 3 小時 58 分（`MAX_ASYNC=2`）。若照 +28%
      線性外推，390 份的抽取段從約 77 小時降到約 60 小時 `(未驗,推測——
      chunk 組成不同、且抽取不是唯一成本)`。

- [ ] **`SPEEDUP-2` 的三個副產物**（實測換來的，動它們之前先讀）：

      1. **`--repeat 2` 四個併發度全部是第 2 輪較慢**（c=2 達 6.2%，超過 5% 門檻）。
         方向一致而非隨機，像熱漂移或累積負載。**兩輪分不出漂移與雜訊**，
         要下結論得加輪數。
      2. **輸出在不同併發度下不逐字相同（`0/8`）**，即使 `temperature=0` ＋ 固定 seed。
         連續批次會改變批次組成 ⇒ 浮點累加順序變 ⇒ token 選擇分岔。
         **但 `--concurrency 1` 是決定性的**（兩輪 `completion_tokens` 都是 14,266）。
      3. **prompt cache 在真實負載幾乎吃不到**：拿伺服器沒見過的 8 題（`fixture-8b`，
         與舊題本 0 重疊）開快取跑，`cache_tokens_total = 0`、命中率 **0.0%**。
         原因是這批 prompt 的**全域共同前綴只有 11 個字元**（`---Task---\n`）——
         LightRAG 的抽取 prompt 有多種型別（初次抽取／gleaning），型別不同時
         前綴立刻分岔；同型別的兩兩共同前綴約 1,812 字元，佔平均 prompt 的 ~11%。
         ⇒ **冷測（關快取）就是這個負載的代表性量法**，不必另外做溫測校正。
         ⚠ 但**基準工具自己的前一輪會污染快取**：同一批題目重跑並開快取時
         量到 99.9% 命中，那是殘影不是真實。**A/B 一定要用沒跑過的題本。**

- [ ] **`SPEEDUP-3`：llama-server 的啟動設定沒有落檔。** 它是 `docker run` 起來的
      （`restart: unless-stopped`、掛 `~/ghq/models:/models`），**沒有 compose、
      沒有 systemd unit、repo 裡 grep 不到任何呼叫者**——參數只活在容器的 config 裡。
      任何 A/B 都要重啟它，容器一旦被 `docker rm` 掉，現行參數就沒了。
      **做實驗之前先把現況固化成檔**（含 image digest），否則回不去。
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
