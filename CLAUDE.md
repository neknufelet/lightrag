# lightrag-v1

LightRAG 1.5.5 的部署與 MinerU 解析後處理。**這份是唯一真相來源(SSOT)**,
其他文件從這裡連出去。改動任何規則或流程時,這裡要跟著改。

## 文件地圖

| 檔案 | 內容 | 什麼時候看 |
|---|---|---|
| **CLAUDE.md**(本檔) | 現況、鐵則、每條規則的證據基礎 | 每次開工 |
| [NEXT.md](NEXT.md) | **待辦與進行中**(含 v155 凍結遺留、刻意不做的決策) | 每次開工 |
| [.claude/skills/onboard-doc-type/SKILL.md](.claude/skills/onboard-doc-type/SKILL.md) | 接入新文件類型的完整流程與常見誤判 | 要加新 PDF、或 preflight 擋下某份 |
| [docs/judgement-flow.md](docs/judgement-flow.md) | **遇到新問題時的決策程序**：偵測 → 驗偵測器 → 分類 → 叫眼睛 → 判不準怎麼辦 | 發現一個沒見過的問題時 |
| [docs/rebuild-plan.md](docs/rebuild-plan.md) | **acoustics_v2 乾淨重建**：階段與閘門、體檢表格式、分工（Opus 執行／主線驗收） | 動任何重建相關工作之前 |
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

**兩個 workspace 並存,`WORKSPACE` 由各 checkout 自己的 `.env` 決定
(不進版控)。下面的數字說的是 `acoustics_v2`;`acoustics_v155` 是現役服務中
的那個,兩者的分工見「服務」與「對照」兩列。**

```
文件      20 份已完成「解析 → 修補 → 抽取」全流程(processed 20/20、failed 0)
          分 4 批索引,每批 5 份;總耗時 3 小時 58 分(61.1/70.1/46.1/61.1 分)
服務      v155(現役) lightrag :9621 查詢(容器 lightrag-acoustics_v155)
                     kbapi :9700 圖片與單篇結構,唯讀(容器 kbapi-acoustics_v155)
          v2(候補)   lightrag :9622 查詢(容器 lightrag-acoustics_v2)
                     kbapi 未起(容器名 kbapi-acoustics_v2,埠走 ${KBAPI_PORT} 錯開 9700)
skills    lightrag-search / fetch / images —— 全走 :9700,不需認證,任何機器可用
          **目前打的是 v155**;CUTOVER 時才換位址,見 NEXT.md
索引      7,211 實體、10,500 關係、510 chunk;圖 7,211 節點 / 10,500 邊
          ↑ 來源＝**vdb 列數**(extract-check.py)。與下面「對照」列的
          8,010／10,535 **不衝突,是兩把不同的尺**:那邊來源是 LightRAG 自己的
          逐文件計數欄 `lightrag_full_entities.count`(compare-ws.py),同一個實體
          出現在兩份文件會被數兩次。差值 799 實體／35 關係就是跨文件重複。
          **引用數字前先看它是哪一把尺量的。**
接地      可疑率 4.5%(260/5,729 個可判定實體);符號型 1,482 個「驗不了」
          6 份 >5% 標黃(K Muffler 15.1%、00712 11.9%、G Porous 6.4%、01200_6 6.1%、
          2025 5.7%、2023 FEM 5.0%),形狀逐份記在體檢表 —— 全部不是幻覺
格式      Empty entity name 共 1,669 次(第 1 批 477 = 基線),全部帶得到 chunk key
圖        image 371(含 chart 轉入的 184);chunk 裡以 <drawing caption=… path=…/> 出現
          項目數 5,448:text 2,731、equation 1,273、header 514、page_number 353、table 82
解析      pipeline + is_ocr=true + MinerU official
embedding text-embedding-3-large @ 3072 + HNSW_HALFVEC;本輪實際嵌入 4.56M 字元 ≈ US$0.15
兩雙眼睛  qwen3.6-35b-a3b(本機) + gpt-5.6-luna(雲端,$0.20/$1.20 per 1M)
體檢表    20 份 × 8 閘門 = 160 格:通過 151、fail 9、驗不了 0、未設定 0
          fail 9 = 3 份 waiver(41598/C 的 coverage、N Flow 的 equations)
                 + 6 份 extract.grounding >5%
對照      acoustics_v155 凍結中(:9621/:9700),同 DB 靠 workspace 欄位隔離
          v155 → v2:chunk 512→510、實體 7,968→8,010、關係 10,407→10,535、
          含掉字 chunk 86→27(-69%) ← 來源＝逐文件計數欄,見「索引」列的說明
          2026-08-03 重跑 `compare-ws.py '' acoustics_v155 acoustics_v2` 逐位元重現
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
  注意:**空 workspace 上它結構性驗不了**(chunk 數恆 0,`b > a` 不可能成立),
  該讀成「驗不了」而非紅燈 —— 2026-08-02 建 v2 時發現,已三態化。
  **三態化的最終驗證在 2026-08-03 拿到**:v2 索引完 20 份後,同一條斷言
  **自動從「驗不了」轉回真實判斷**(`chunk_top_k=2 → 2 個、=8 → 8 個,
  母體 20 份已索引`),不必改任何一行程式。「母體不足」與「契約壞了」
  被分開之後,兩種狀態各自都會在該響的時候響。
  **不要改用 `max_total_tokens` 收**:它先扣圖譜再給原文,設 8000 時
  `available_chunk_tokens` 變負數,chunk 直接回 0 個且不報錯。
- **同一組 Postgres 裡多個 workspace 共存時,每一句 SQL 都要帶 `workspace`。**
  儲存層靠這個欄位隔離,而兩個 workspace 的 `file_path` 是同一批 PDF 檔名 ——
  漏掉條件時逐份報表會把兩邊的同一份文件**併成一列**,數字看起來完全正常
  (大約兩倍)、不報錯、不會有任何訊號。實測踩過(2026-08-03,extract-check.py
  三句 SQL 全漏):合計實體 14,402 = v155 7,191 + v2 7,211,而且**翻轉了三份
  文件的閘門判定**。單一 checkout 時代這個 bug 不可觀測 —— 與階段 0 的
  「容器名寫死」同一族,開第二個 workspace 的那一刻才引爆。
  修完的驗證方式:**拿舊 workspace 重跑,要重現歷史數字**(v155 回 3.2%,
  與本檔記載逐位元相同)。

## 待辦

在 [NEXT.md](NEXT.md) —— 本檔只放規則與契約,待辦與進行中的狀態不放這裡。
待辦做完就從 NEXT 刪;過程學到的教訓沉澱回本檔或對應文件,不留屍體。
「刻意不做」的決策記錄也在那裡,動它們之前先讀理由。

排程檢查已存在(2026-08-02 起):`lightrag-daily-check.timer` 每天 08:30 跑
compat-check + canary,紅燈打自架 ntfy(`/opt/stacks/ntfy`,:9800),腳本本身
掛掉走 systemd `OnFailure=` 獨立備援。狀態落地 `/data/rag/lightrag/checks/`。
**「誰會報錯」的答案從「沒有人」改成它。**

## 抽取品質:接地檢查

`extract-check.py` 拿每個實體名字去對它來源的 chunk。原理跟 `pdfcrop` 抽文字層
當 ground truth 一樣:**拿產出對來源,不要相信它**。確定性、不呼叫模型、免費。

必須三態。字串比對只對散文有效 —— 表格裡常常只有符號,實測 C 的 chunk-002 是
`<td>G</td><td>$G=I/\Delta U=1/Z$</td>`,完全沒有 `Conductance` 這個字,但模型
抽出 Conductance 是**正確的**:從符號推論概念名稱正是它該做的事。

二態時未接地率與符號密度高度相關、與幻覺無關(散文 0%、論文 3.4%、C 55%)。
分成「接地 / 符號型無法驗證 / 可疑」之後,C 從 55.1% 降到 3.4%,總計 3.7%。

```
acoustics_v2（2026-08-03 重跑，全 20 份；來源＝entity/relation vdb 的列數）
 7,211 實體 → 接地 5,469、符號型 1,482（驗不了）、可疑 260 　可疑率 4.5%
10,500 關係 → 兩端接地 6,780、符號型 3,261、只有一端 349（4.8%）、兩端皆無 110（1.5%）
```

**關係那一列曾經是錯的,而且錯法就是它自己修的那個 bug。** 舊版寫
`20,873 關係 → 12,459 / 7,491 / 689 / 234`,每一項都約是實際的 **2 倍** ——
那是 `extract-check.py` 補上 `workspace` 條件（commit `9ef8026`）**之前**的
雙重計數。那個 commit 更新了實體那一列,漏了關係那一列,於是「兩個 workspace
被併成一列」的症狀留在文件裡活了下來。**2026-08-03 重跑 `extract-check.py`
定案為上表數值。**

教訓與該 commit 自己寫的契約點同一條:多 workspace 共存時,**修完 SQL 還要
把所有引用舊數字的地方一起重算**——數字沒有錯誤訊息,它只是靜靜地錯著。

**「可疑」不等於「幻覺」——形狀要逐份看過才算量到。** v2 的 260 個可疑
分成兩族,兩族都不是捏造:

| 形狀 | 長相 | 例 |
|---|---|---|
| 符號→概念命名 | 模型替裸符號取描述性名字 | K Muffler `Coefficient Ta`、G Porous `Modified Bessel Function I0` |
| 概念→引用文獻 | 參考文獻條目被拆成實體 | 01200_6 `Journal Of The Acoustical Society Of America`、2025 的作者縮寫名 |

前者是**三態判準的邊界效應**:同一族的東西,散文比例低於
`SYMBOLIC_RATIO=0.35` 的落進「驗不了」,高於的落進「可疑」。所以
K Muffler 15.1%(全庫最高)的分子裡 92 個只有 1 個是引用文獻 ——
**NEXT 記載的 v155 結論「K Muffler 大量概念→引用文獻型」在 v2 母體被推翻**。
要真的降下來得重量 `is_symbolic` 的判準(門檻用量的不要用調的)。

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

**一致不等於沒有多餘的東西。** 實測(2026-08-02,C #525):qwen 對示意圖格
**捏造外部圖片網址**(`<img src="https://i.imgur.com/…">`)。crosscheck 只回答
「兩眼一不一致」,不回答「多出了什麼」——兩眼剛好都幻覺時會全綠通過。
所以**內容閘門掛在寫入點**(`postprocess.py` 的 `gate_table_html`:單一完整
table、無 `<img>`、無 prompt 洩漏),且自動採用與人工裁定走同一道。
