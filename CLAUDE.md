# lightrag-v1

LightRAG 1.5.5 的部署與 MinerU 解析後處理。**這份是唯一真相來源(SSOT)**,
其他文件從這裡連出去。改動任何規則或流程時,這裡要跟著改。

## 文件地圖

| 檔案 | 內容 | 什麼時候看 |
|---|---|---|
| **CLAUDE.md**(本檔) | 現況、鐵則、每條規則的證據基礎 | 每次開工 |
| [.claude/skills/onboard-doc-type/SKILL.md](.claude/skills/onboard-doc-type/SKILL.md) | 接入新文件類型的完整流程與常見誤判 | 要加新 PDF、或 preflight 擋下某份 |
| [docs/postprocess-workorder.md](docs/postprocess-workorder.md) | 後處理的完整工單(W0–W14) | 要動 `scripts/pp/` 之前 |
| [README.md](README.md) | 部署、解析選項實測、備份範圍 | 環境有問題時 |
| [tests/canary-baseline.json](tests/canary-baseline.json) | 金絲雀基準數字 | 不要手改,用 `canary --update` |

## 四條鐵則

踩過坑換來的。違反前先讀工單。

1. **`preflight()` 拒絕,不猜。** 遇到未知型別就停整份文件。
   用不適用的規則硬跑會產生「有產出但產出錯誤」—— 這個專案一路在防的就是它。
2. **消音,不刪除。** `.parsed/` 的 `tables.json` 用 `content_list.json#/6` 這種
   **陣列索引**當 `self_ref`。刪一個項目,其後所有引用靜靜指向別的東西。
3. **LightRAG 的行為用 `pp/oracle.py` 問,不要推測。**
   實測踩過:推測 `chart` 的 `img_path` 會污染索引,查 `_coerce_text` 後發現
   它只讀 `("text","content","body","code_body")`,根本不讀 `img_path`。
4. **門檻用量的,不要用調的。** 覺得誤判多時先看**差在哪些具體記號**。
   實測有五次「以為要調門檻」其實是偵測器量錯東西(清單見 SKILL.md)。

## 常用指令

```bash
python3 scripts/parse-only.py                     # 只解析不抽取（規則建立期用這個）
python3 scripts/postprocess.py plan               # 只讀,算出打算改什麼
python3 scripts/postprocess.py plan --details --doc <關鍵字>
python3 scripts/postprocess.py check --doc <關鍵字>   # 兩雙眼睛 + 逐格比對
python3 scripts/postprocess.py canary             # 規則漂移偵測 ← 改規則後必跑
python3 scripts/compat-check.py                   # LightRAG 契約斷言
python3 scripts/extract-check.py                  # 抽取品質：接地檢查（三態）
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
文件      20 份已納入基準（9 論文、10 教科書章節/6 本不同的書、1 份補充材料）
索引      C Equivalent Networks 148 chunks / 1,135 entities / 1,812 relations
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

## 已知待辦

- **W7 `apply.py`** —— 第一個真的寫檔的步驟(消音 + 表格修補 + 更新 manifest)。
  520 項消音已有 20 份文件證據,比表格修補成熟得多。
- **`chart` → `image`** —— 目前論文的圖表對索引貢獻為零(`content` 是空字串,
  fallback 不 append)。改寫型別即可走 `_build_ir_drawing`,不必改 LightRAG。
- **`K Muffler Acoustics.pdf` 抽取失敗** —— chunk-041 `Worker execution timeout
  after 480s`。設定問題不是品質問題,逾時對大章節不夠。
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
