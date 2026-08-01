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

這四條是踩過坑換來的，改動前先讀 `docs/postprocess-workorder.md`。

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
cp <新PDF> /data/rag/lightrag/<ws>/inputs/<ws>/
KEY=$(grep '^LIGHTRAG_API_KEY=' .env | cut -d= -f2-)
curl -s -X POST -H "X-API-Key: $KEY" http://100.87.88.7:9621/documents/scan
```

服務綁在 `BIND_ADDR`（不是 localhost）。pipeline 忙碌時 scan 會回
`scanning_skipped_pipeline_busy`，要等閒置。

**等待條件要等 `content_list.json`，不要等目錄** —— MinerU 先建目錄、最後才寫檔，
等目錄會提早觸發。

```bash
until [ -f "$P/<檔名>.pdf.mineru_raw/content_list.json" ]; do sleep 20; done
```

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
實例：`header`/`footer` 每頁重現，所以用重複次數；`aside_text` 只出現一次，
重複次數對它無效，改用 `is_gibberish()`（零個真字才消音，刻意保守 ——
沒有重複次數當保險）。

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

看圖判定後，把「誰對、錯在哪一類」記進 commit 訊息。目前累積的觀察：

- luna 會**看錯字元**（`S_n` → `S_h`、`p_I` → `p_l`）
- qwen 會**切錯結構**（該分的併、該併的分）
- 兩者都會錯在**羅馬數字下標**（區域 I / II），方向相反

**這些觀察目前只有 C Equivalent Networks 一份文件的證據，不足以寫成自動規則。**
遇到第二份有空表格的文件時，優先驗證它們。

### 5. 迴歸：改完規則必須確認舊文件沒變

```bash
python3 scripts/postprocess.py plan | grep -E "^=== |過濾：|表格："
```

跟改動前逐份比對。**只有目標文件該改變**。實例：書眉門檻從絕對值 3 改成
`max(2, min(3, ceil(pages*0.5)))` 後，只有 3 頁的 A Conventions 改變
（保留待查 2→0、消音 0→2），其餘六份數字完全不動 —— 這才算通過。

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

| 規則 | 證據 |
|---|---|
| 消音 header/footer，不刪除 | 7 份 |
| 書眉門檻依頁數 | 7 份（1 份逼出來的） |
| `aside_text` 用 `is_gibberish` | **1 份** |
| `chart` 只登記不處理 | **1 份** |
| 空表格用兩雙眼睛交叉比對 | **1 份** |
| 「列數不一致優先採信 luna」 | **1 份，尚未採用** |

粗體的都還很脆弱。遇到相關文件時優先驗證，驗過就把份數更新到這張表。
