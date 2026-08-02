# lightrag-v1

LightRAG 1.5.5 的部署與 MinerU 解析後處理。**這份是唯一真相來源(SSOT)**,
其他文件從這裡連出去。改動任何規則或流程時,這裡要跟著改。

## 文件地圖

| 檔案 | 內容 | 什麼時候看 |
|---|---|---|
| **CLAUDE.md**(本檔) | 現況、鐵則、每條規則的證據基礎 | 每次開工 |
| [.claude/skills/onboard-doc-type/SKILL.md](.claude/skills/onboard-doc-type/SKILL.md) | 接入新文件類型的完整流程與常見誤判 | 要加新 PDF、或 preflight 擋下某份 |
| [docs/judgement-flow.md](docs/judgement-flow.md) | **遇到新問題時的決策程序**：偵測 → 驗偵測器 → 分類 → 叫眼睛 → 判不準怎麼辦 | 發現一個沒見過的問題時 |
| [docs/postprocess-workorder.md](docs/postprocess-workorder.md) | 後處理的完整工單(W0–W14) | 要動 `scripts/pp/` 之前 |
| [README.md](README.md) | 部署、解析選項實測、備份範圍 | 環境有問題時 |
| [tests/canary-baseline.json](tests/canary-baseline.json) | 金絲雀基準數字 | 不要手改,用 `canary --update` |

## 六條鐵則

踩過坑換來的。違反前先讀工單。

1. **`preflight()` 拒絕,不猜。** 遇到未知型別就停整份文件。
   用不適用的規則硬跑會產生「有產出但產出錯誤」—— 這個專案一路在防的就是它。
2. **消音,不刪除。** `.parsed/` 的 `tables.json` 用 `content_list.json#/6` 這種
   **陣列索引**當 `self_ref`。刪一個項目,其後所有引用靜靜指向別的東西。
3. **LightRAG 的行為用 `pp/oracle.py` 問,不要推測。**
   實測踩過:推測 `chart` 的 `img_path` 會污染索引,查 `_coerce_text` 後發現
   它只讀 `("text","content","body","code_body")`,根本不讀 `img_path`。
4. **先查輸入,再查偵測器,最後才查模型。**
   實測踩過:方程式「三方皆異」看起來像模型都讀不出來,實際是裁圖的垂直
   padding 用了表格的 6 點,把上下鄰居框進圖裡 —— 六個模型對共同部分完全
   一致,只是各自決定轉幾條。改成 1 點後「三方皆異」歸零。
   給模型看的東西不對,再多模型、再好的比對邏輯都沒用。
5. **門檻用量的,不要用調的。** 覺得誤判多時先看**差在哪些具體記號**。
   實測有五次「以為要調門檻」其實是偵測器量錯東西(清單見 SKILL.md)。
6. **探針要在沒人問的時候會響。** 只有指定目標才跑的檢查,防的是「你已經
   懷疑的事」—— 而你已經懷疑的事不需要探針。
   實測踩過:A-16「沒有未知的項目型別」本來就抓得到 `chart`,但單篇檢查被
   `if a.doc:` 關著,而你只會對正在處理的那一份指定。184 個 `chart` 分散在
   11 份文件裡,從專案開始到發現為止**一次都沒被喊過**。
   同理:收合輸出時必須報出「幾項通過未列出」,否則「沒印出來」跟「沒檢查」
   在畫面上長得一樣。

## 常用指令

```bash
python3 scripts/parse-only.py                     # 只解析不抽取（規則建立期用這個）
python3 scripts/postprocess.py plan               # 只讀,算出打算改什麼
python3 scripts/postprocess.py plan --details --doc <關鍵字>
python3 scripts/postprocess.py check --doc <關鍵字>   # 兩雙眼睛 + 逐格比對
python3 scripts/postprocess.py canary             # 規則漂移偵測 ← 改規則後必跑
python3 scripts/compat-check.py                   # LightRAG 契約斷言（預設連 20 份文件一起驗）
python3 scripts/compat-check.py --no-docs         # 只驗契約與環境（快）
python3 scripts/compat-check.py --doc <關鍵字>     # 只驗某一份，且逐項列出
python3 scripts/extract-check.py                  # 抽取品質：實體與關係對照原文（三態）
python3 scripts/eq-check.py --n 30                # 方程式：MinerU/qwen/luna 三票多數決
python3 scripts/parse-check.py --details          # 解析品質
```

## 金絲雀:規則漂移偵測

規則是**一份一份文件逼出來的**,每次改動都可能無意間動到別份。手動逐份比對
數字會漏,而漏掉的漂移不會有錯誤訊息。

```bash
python3 scripts/postprocess.py canary            # exit 0 通過 / 2 漂移
python3 scripts/postprocess.py canary --update   # 認可為新基準
```

基準 [tests/canary-baseline.json](tests/canary-baseline.json) **進版控**,
所以規則改動造成的行為變化會直接出現在 `git diff` 裡。

比對這幾個量:`pages` `items` `mute` `held` `ratio` `tables_total`
`repairable` `review`。

**改規則的正確順序:**

1. 改 → 2. `canary`(預期會失敗) → 3. 逐條確認每個漂移都是**想要的**
→ 4. `canary --update` → 5. commit 訊息**說明每個數字為什麼變**

沒說明的數字變動 = 未被察覺的漂移。

實測驗證過金絲雀真的會失敗:門檻 3→20 時它指出 `C: mute 110→101`、
`K: mute 61→48`。(注意 3→5 不會失敗,因為書眉重複次數遠大於 5 ——
**測試本身也要選會咬到的值**。)

## 現況

```
文件      20 份已完成「解析 → 修補 → 重新索引」全流程（processed 20/20、failed 0）
服務      lightrag :9621 查詢　kbapi :9700 圖片與單篇結構（唯讀）
skills    lightrag-search / fetch / images —— 全走 :9700，不需認證，任何機器可用
索引      20 份共 7,211 實體、512 chunk、可疑率 3.2%
圖        image 371（含 chart 轉入的 184）；chunk 裡以 <drawing caption=… path=…/> 出現
解析      pipeline + is_ocr=true + MinerU official
embedding text-embedding-3-large @ 3072 + HNSW_HALFVEC
兩雙眼睛  qwen3.6-35b-a3b(本機) + gpt-5.6-luna(雲端,$0.20/$1.20 per 1M)
```

## 規則分兩類,不能混在一起

混在一起是設計錯誤 —— 兩類的失效方式完全不同。

### 耐久規則:綁文件領域,換模型仍成立

**改動前先看它有多少份文件的證據。** 只有 1 份的很可能是那份文件的巧合。

| 規則 | 證據 | 狀態 |
|---|---|---|
| 消音 header/footer,不刪除 | 7 份 | 穩 |
| 書眉門檻依頁數 `max(2, min(3, ⌈pages×0.5⌉))` | 7 份 | 穩 |
| 兩雙眼睛**必須不同家族**(同模型的系統性誤讀會原樣重現) | 原理 | 穩 |
| 分歧要**逐格**定位,不用整表純量分數 | 原理 + 1 份 | 穩 |
| `aside_text` 先跑重複/樣板規則,`is_gibberish` 只當單次殘骸的後備 | 2 份 | 穩 |
| 書眉/頁尾數**樣板**(數字抹成 `#`),不數字面字串 | 2 份 | 穩 |
| `chart` 只登記不處理 | 3 份（含一份 50 個 chart） | 穩 |
| 接地檢查要**三態**:符號型 chunk 的未接地是「驗不了」不是「錯」 | 5 份 | 穩 |

### 易腐觀察:綁特定模型,換代即失效

記錄在 [tests/model-observations.json](tests/model-observations.json)。

**這些一律不得寫成流程中的自動裁決規則。** 例如「列數不一致優先採信 luna」——
luna 撐不過半年,換代後那條規則不是變舊,是**變成錯的而且錯得很安靜**:
新模型的失誤型態可能完全相反,但規則還在照舊裁決。

`compat-check.py` 的 **A-23** 比對記錄的模型與 `.env` 現行設定,不一致就 hard FAIL,
逼人重新量測。驗證過它抓得到換代。

模型換掉時的正確做法:

1. 重跑 `postprocess.py check`(舊快取以裁圖 sha 為鍵,不會混到)
2. 重新看圖判定,量新模型錯在哪一類
3. 更新 `model-observations.json` 的 `eye_*`、`measured_on`、`observations`
4. `compat-check.py` 應回綠

`domain_facts` 那一節是例外 —— 那些是文件的性質(羅馬數字下標難讀、
跨頁續表詞彙重疊、文字層表示不了數學),換模型仍然成立,可以累積。

## LightRAG 升級時怎麼辦

**我們沒有改過 LightRAG 一行程式碼。** 後處理改的是磁碟上的 `content_list.json`
與 `_manifest.json`，耦合的對象是「LightRAG 如何讀寫 `__parsed__`」這組**未言明的
契約**，不是它的原始碼。所以升級不會有 patch 衝突，但契約可能悄悄改變。

設定全部在**容器外**：

| 在哪 | 內容 | 版控 |
|---|---|---|
| `.env` | 實際值（含金鑰） | ❌ gitignore，chmod 600 |
| `.env.example` | 每個鍵 + **為什麼設這個值** | ✅ |
| `compose.yaml` | 映像以 digest 釘選 | ✅ |

`.env.example` 才是真正的文件 —— 它記的不是「有這個鍵」，而是「為什麼是這個值」，
例如 `MAX_ASYNC=2` 底下寫著 llama.cpp 只有 1 個 slot、4 個並行會排隊撞逾時。
換機器或換人接手時看那個檔就夠。

**升級的步驟：**

```bash
# 1. 先記下現況
python3 scripts/compat-check.py --json > /tmp/before.json
python3 scripts/postprocess.py canary          # 應為綠

# 2. 改 compose.yaml 的 digest，重建

# 3. 契約有沒有變 —— 這是關鍵
python3 scripts/compat-check.py                # 契約 15 項 + 每份文件 6 項
python3 scripts/postprocess.py canary          # 規則行為有沒有漂移
python3 scripts/parse-check.py                 # 解析品質
python3 scripts/extract-check.py               # 抽取品質
```

`compat-check.py` 就是為升級寫的 —— 它把「後處理依賴的假設」變成可執行的斷言。
文件會過期，斷言不會。任何一項 hard 失敗就**不要動工**，先查契約哪裡變了。

已知的契約點（都有對應斷言）：`critical_file` 是 `content_list.json` 且驗
size+sha256、`_coerce_text` 的欄位順序、sidecar 的 `self_ref` 用陣列索引、
`page_number` 被跳過而 `header`/`footer` 走 fallback 進索引。

新增兩點：

- **A-24 走 `_build_ir_drawing` 的型別集合是 `{image, picture, drawing}`,
  而它讀 `image_caption` / `image_footnote`。** `chart→image` 整條規則就
  站在這兩件事上。哪天 LightRAG 把 `chart` 加進集合,規則就該退休（斷言的
  說明會直接這樣寫）；caption 欄位改名的話,現在的搬動會把 caption 搬丟。
- **A-25 `chunk_top_k` 仍然控制回傳的片段數。** kbapi 的 `chunks` 參數就是
  下傳成它。失效時 `/kb/*/search` 會靜靜回到每次 55–60KB —— 不報錯,只是把
  呼叫端的 context 灌爆,所以每次都真的打一次查詢來驗。
  **不要改用 `max_total_tokens` 收**:它先扣圖譜再給原文,設 8000 時
  `available_chunk_tokens` 變負數,chunk 直接回 0 個且不報錯。

## 已知待辦

- **W7 `apply.py`** —— 第一個真的寫檔的步驟(消音 + 表格修補 + 更新 manifest)。
  520 項消音已有 20 份文件證據,比表格修補成熟得多。
- ~~**`chart` → `image`**~~ —— 已完成(2026-08-02)。184 個項目、11 份文件,
  規則在 `pp/rules/chart_type.py`,由 A-24 守著前提。`image` 187 → 371。
  欄位一併改名(`chart_caption` → `image_caption`),否則圖進得去但 caption 掉光。
- **`K Muffler` 對照原文可疑率 12.8%** —— 20 份裡唯一超標,可疑關係大量是
  「概念 → 引用文獻」（`Normalized Partition Impedance → Sullivan 1979`）,待查。
- **實體碎片化 6.1%** —— `k_0` 抽成 5 個節點(`k_0`/`k0`/`K 0`/`K_0`/`K0`)。
  LightRAG 有 `POST /graph/entities/merge`,**不必重跑抽取**。仍未動:合併
  不可逆,而數學裡 `S_n` 與 `S_N` 可能真的是兩回事,要先出候選清單過目。
- **3 條方程式已知錯但未回寫** —— `apply.py` 只寫 `table_body`。
  例:`N Flow` #1005 的 `\hat{o}` 其實是 ∂、`P` 其實是 ρ。門檻比表格高 ——
  表格是「從無到錯」,方程式是「從錯到另一種錯」。
- **接地檢查的 47 個可疑實體** —— `Region I/II/III`、`Mechl`、`S1` 等,
  多數與已記錄的 domain_fact「羅馬數字下標難讀」相關。
- 「qwen 系統性切錯列」需要第二份有空表格的文件才能驗證。15 份裡只有 C 有,
  命中率約 1/15 —— 要湊樣本得再抽十幾份。
- **首頁的期刊/會議資訊**(`Paper ID #8776`、`©American Society...`)只出現一次、
  只在第 0 頁,重複與樣板規則都抓不到,目前留在待查。要處理需要新的訊號
  （限第 0 頁 + 版權/會議標記），但只有 1 份文件的證據,先不動。

## 抽取品質:接地檢查

`extract-check.py` 拿每個實體名字去對它來源的 chunk。原理跟 `pdfcrop` 抽文字層
當 ground truth 一樣:**拿產出對來源,不要相信它**。確定性、不呼叫模型、免費。

必須三態。字串比對只對散文有效 —— 表格裡常常只有符號,實測 C 的 chunk-002 是
`<td>G</td><td>$G=I/\Delta U=1/Z$</td>`,完全沒有 `Conductance` 這個字,但模型
抽出 Conductance 是**正確的**:從符號推論概念名稱正是它該做的事。

二態時未接地率與符號密度高度相關、與幻覺無關(散文 0%、論文 3.4%、C 55%)。
分成「接地 / 符號型無法驗證 / 可疑」之後,C 從 55.1% 降到 3.4%,總計 3.7%。

```
2,084 實體 → 接地 1,238、符號型 799（驗不了）、可疑 47
```

## 兩雙眼睛:為什麼要兩個

實測 C 的 10 張空表格,**沒有哪個模型比較準**,而且錯法互補:

- luna 會**看錯字元**(`S_n`→`S_h`、`p_I`→`p_l`)
- qwen 會**切錯結構**(該分的併、該併的分)
- 兩者都會錯在**羅馬數字下標**(區域 I/II),方向相反

只用其中一個,另一個抓得到的那類錯誤就會靜靜進索引。`pp/eyes.py` 會擋下
「兩雙眼睛是同一個模型」—— 同模型的系統性誤讀會一模一樣地重現,
互相印證等於沒印證。

luna 不接受 `temperature=0`(只允許預設 1),所以**首次轉錄有抽樣變異**;
快取之後才穩定。分歧要重抽一次才知道是真的還是雜訊。
