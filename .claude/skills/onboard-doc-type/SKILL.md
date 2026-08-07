---
name: onboard-doc-type
description: 把新的文件類型接進 LightRAG 後處理流程。當使用者要加入新的 PDF（新期刊、新書、新版面）、或 postprocess.py 因為未知型別／頁面尺寸不一致而擋下某份文件時使用。涵蓋解析、規則調整、迴歸驗證與記錄。
---

# 接入新的文件類型

## 這份流程存在的理由

規則是從**實際文件量出來的**，不是設計出來的。前七份文件推翻了三個假設：

| 假設 | 實測 |
|---|---|
| 教科書會有空表格 | 只有 C Equivalent Networks 一份有；同一本書的其他章節都是 0 |
| header/footer 涵蓋了版面雜訊 | 論文另有 `aside_text`（會進索引）與 `chart`（整個被丟掉） |
| 書眉重複 ≥3 次 | 3 頁的短章節書眉最多出現 2 次，永遠達不到 |

所以**每接一份新文件都預期會學到東西**。這份流程的目的是讓學到的東西留下痕跡，
而不是被下一個 agent 重新踩一遍。

## 不可違反的四條

這四條是踩過坑換來的。原本的工單 `docs/postprocess-workorder.md` 已於 2026-08-07
刪除（在 tag `archive/pre-rebuild-20260807` 裡）；現行的契約清單見
`docs/rebuild-checklist.md`。

1. **`preflight()` 拒絕，不猜。** 遇到未知型別就停下整份文件。用不適用的規則硬跑
   會產生「有產出但產出錯誤」——這個專案一路在防的就是這個。

2. **消音，不刪除。** `.parsed/` 的 `tables.json` 用 `content_list.json#/6` 這種
   **陣列索引**當 `self_ref`。刪一個項目，其後所有引用靜靜指向別的東西。
   消音走 `_pp_original_text`，可還原、可查帳。

3. **LightRAG 的行為要用 oracle 問，不要推測。** `pp/oracle.py` 是唯一入口，
   在容器裡跑 python。實測踩過：我推測 `chart` 的 `img_path` 雜湊會污染索引，
   查 `_coerce_text` 後發現它只讀 `("text","content","body","code_body")`，
   根本不讀 `img_path` —— 推測錯了，而且方向相反。

4. **門檻用量的，不要用調的。** 覺得誤判太多時，先看**差在哪些具體記號**，
   再決定是規則錯還是門檻錯。實測有三次「以為要調門檻」其實是偵測器
   量錯東西（見下方「常見誤判」）。

## 流程

### 1. 解析

```bash
cp <新PDF> /data/lightrag/inputs/<ws>/
python3 scripts/postprocess.py prepare --workspace <ws>
python3 scripts/postprocess.py prepare --workspace <ws> --commit
```

第一個 `prepare` 是 dry-run，第二個才執行「解析 → 修補 → 掃描」。**不要直接
curl `/documents/scan`**：scan 會把 MinerU 解析與實體抽取綁在一起；若先 scan
再修補，就必須 reindex，等於同一份文件抽取兩次。`prepare` 刻意把修補放在
scan 前，讓抽取只發生一次。

若 pipeline 忙碌，scan 可能回 `scanning_skipped_pipeline_busy`；這代表**沒有排程**，
等閒置後重新執行 `prepare --workspace <ws> --commit`，不要把該回應當成成功。

`prepare` 會等待 `content_list.json` 產出後才進修補；MinerU 先建目錄、最後才寫檔，
所以不要用「目錄出現」當解析完成訊號。

### 2. 看它壞在哪

```bash
python3 scripts/postprocess.py plan            # 全部
python3 scripts/postprocess.py plan --details --doc <關鍵字>
```

三種結果：

- **正常** → 記下數字，進第 5 步
- **被 preflight 擋下** → 第 3 步
- **數字可疑**（消音比例 >10%、待修補表格暴增）→ 第 4 步

### 3. 未知型別

先看實際內容，不要直接加進 `KNOWN_TYPES`：

```bash
python3 -c "
import json,collections
from pathlib import Path
items=json.loads(Path('<raw_dir>/content_list.json').read_text())
print(dict(collections.Counter(i.get('type') for i in items)))
for i,it in enumerate(items):
    if it.get('type')=='<新型別>':
        print(i, {k:str(v)[:80] for k,v in it.items() if k!='bbox'})
"
```

然後查 `ir_builder` 怎麼處理它 —— **這一步決定該做什麼，不能跳過**：

```bash
grep -n 'item_type ==\|item_type in' <ir_builder.py>   # 有沒有專屬分支
grep -n -A6 'def _coerce_text' <ir_builder.py>          # fallback 讀哪些欄位
```

三種可能，對應三種處理：

| ir_builder 的行為 | 性質 | 該做什麼 |
|---|---|---|
| 有專屬分支 | 已正確處理 | 只要加進 `KNOWN_TYPES` |
| 走 fallback 且 `_coerce_text` 拿得到文字 | **污染** | 加進 `KNOWN_TYPES` + `BODY_TYPES`，並想一條消音規則 |
| 走 fallback 但拿不到文字 | **資訊遺失** | 加進 `KNOWN_TYPES`；要救的話改寫成 `image`／`table` 這類有分支的型別 |

**新規則要問「這個型別的訊號是什麼」，不要沿用現成規則。**
**但也不要從一份文件推論型別的性質。** 實測踩過：看到 2016 論文的
`aside_text` 只有一個 OCR 殘骸，就寫成「aside_text 只出現一次，重複次數對它
無效」，直接導向 `is_gibberish`。另一份 ASEE 論文用同一個型別放每頁的
`Page 24.417.N` 頁邊頁尾，15 頁全都是 —— 重複規則明明有效，卻被 `continue`
跳過了。**同一個型別在不同期刊是不同東西。**

現在的結構：重複／樣板規則對三種型別都先跑，`is_gibberish` 只當「單次出現
而且不是語言」的後備。

### 4. 表格：兩雙眼睛

```bash
python3 scripts/postprocess.py check --doc <關鍵字>
```

轉錄快取在 `DATA_ROOT/<ws>/postprocess/<doc>/cache/`（以裁圖 sha256 為鍵），
重跑不重複付費。待判項目在同目錄的 `review.md`。

**兩雙眼睛必須是不同模型家族**（`pp/eyes.py` 會擋同模型）。理由：同模型的
系統性誤讀會一模一樣地重現，互相印證等於沒印證。

判定時：

- **穩定分歧**（重抽 B 仍分歧）→ 真的，需要看圖
- **會翻面** → 取樣雜訊。luna 不接受 `temperature=0`，本質隨機
- **結構不符**（列數不同）→ 需要看圖判斷實際列數

看圖判定後，把「誰對、錯在哪一類」記進 `tests/model-observations.json`，
**不要記進程式碼**。目前累積的觀察在那個檔裡。

**綁模型的觀察一律不得寫成自動裁決規則。** 例如「列數不一致優先採信 B」——
模型半年就換代，換代後那條規則不是變舊，是變成錯的而且錯得很安靜：
新模型的失誤型態可能完全相反，但規則還在照舊裁決。
`compat-check.py` 的 A-23 會比對記錄的模型與 .env 現行設定，不一致就 hard FAIL。

可以累積的是 `domain_facts` —— 文件本身的性質（羅馬數字下標難讀、跨頁續表
詞彙重疊），換模型仍然成立。

### 5. 迴歸：金絲雀

```bash
python3 scripts/postprocess.py canary        # exit 0 通過 / 2 漂移
```

**改完規則必跑。**手動逐份比對數字會漏，而漏掉的漂移不會有錯誤訊息。

正確順序：改 → `canary`（預期失敗）→ 逐條確認每個漂移都是**想要的**
→ `canary --update` → commit 訊息說明**每個數字為什麼變**。
沒說明的數字變動 = 未被察覺的漂移。

實例：書眉門檻從絕對值 3 改成 `max(2, min(3, ceil(pages*0.5)))` 後，
只有 3 頁的 A Conventions 改變（保留待查 2→0、消音 0→2），其餘六份完全
不動 —— 這才算通過。

基準 `tests/canary-baseline.json` 進版控，行為變化會出現在 git diff 裡。

再跑：

```bash
python3 scripts/compat-check.py     # A-19 會因 pipeline 忙碌而 FAIL，那是預期的
```

### 6. 記錄

commit 訊息要寫**這份文件教了什麼**，不是「加了什麼功能」。往回翻要看得出
每條規則是哪份文件逼出來的、以及它有幾份文件的證據。格式參考
`git log` 裡的 `05349f5`、`2c5598e`。

## 常見誤判

實測踩過的，出現同樣症狀時先查這裡：

| 症狀 | 真正原因 |
|---|---|
| 比對兩份 VLM 輸出時相似度全是 1.00 | 沿用了為「轉錄 vs 壞文字層」設計的過濾器，它必須丟掉數學。基準換了，可比對的符號集合就要換 |
| 兩邊憑空出現大量下標不一致 | 斷詞前做了 `replace("{", " { ")`，`X_{...}` 規則配不到，愛用大括號的那個模型下標全消失 |
| 「掉字」誤判 | `equation` 是裸 LaTeX、空殼表格是純標籤。偵測只跑 `("text","header")` |
| 裁圖看起來像表但內容不對 | bbox 整體位移。`assert_rect_plausible()` 抽文字層驗，別只看圖 |
| 模型回空字串但 `finish_reason=stop` | 推理模型把額度吃光。要跟「模型判不出來」分開回報，否則會把預算問題誤讀成能力問題 |

## 目前每條規則的證據基礎

改動前先看它站在多少份文件上：

見 [docs/hard-rules.md](../../../docs/hard-rules.md) 的「規則分兩類」。
（2026-08-07 之前那一節在 `CLAUDE.md`，那個檔已砍到只剩藍桶 9 條與機器關係，
內容搬到 `docs/hard-rules.md`。**本行 2026-08-08 更正**——舊指標指的位置已經沒有
那一節了，而「檔案存在」不等於「那一段還在」。）

⚠ **下表的份數全部來自舊語料（2026-08-02 之前，20 篇）。** 2026-08-07 重建之後
庫裡只有 1 篇，這些數字**沒有一個在新環境重新驗過**。要動任何一條規則之前，
先確認它在新語料上還成不成立。

| 耐久規則（綁文件領域） | 證據 |
|---|---|
| 消音 header/footer，不刪除 | 7 份 |
| 書眉門檻依頁數 | 7 份 |
| 兩雙眼睛必須不同家族 | 原理 |
| `aside_text` 先跑重複/樣板規則，gibberish 只是後備 | 2 份 |
| 書眉/頁尾數**樣板**（數字抹成 `#`） | 2 份 |
| `chart` 只登記不處理 | **1 份，脆弱** |

易腐觀察（綁特定模型）另存 `tests/model-observations.json`，由 A-23 守著。
驗過就把份數更新到 `docs/hard-rules.md`，不要只改這裡 —— 那份是領域規則的 SSOT。
（2026-08-08 更正：原本寫 CLAUDE.md，那個檔 2026-08-07 起只放藍桶 9 條與機器關係。）
