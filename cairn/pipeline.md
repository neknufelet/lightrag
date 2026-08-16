---
title: 管線 — 一份 PDF 從進門到被查詢
date_created: 2026-08-16
date_modified: 2026-08-16
status: living
kind: reference
supersedes: ""
superseded_by: ""
summary: "當前真相：一份 PDF 經過哪些關卡、每一關動的是什麼、人在哪裡出現。圖上刻意沒有數字——數字撐不過一週，結構變得慢。"
---

# 管線 — 一份 PDF 從進門到被查詢

**這張圖回答一個問題：一份 PDF 進來之後，到底發生了什麼。**

⚠ **圖上刻意沒有任何數字。** 份數、項數、字元數都會變，寫死的那一版撐不過一週。
要數字跑 [handoff-20260816.md](../docs/handoff-20260816.md) 裡的指令。

⚠ **這張圖畫的是「現在跑著的」，不是「設計上應該的」。** 兩者不一樣的地方
用虛線與註記標出來了。

---

## 全景

```mermaid
%%{init: {'themeVariables': {'fontSize':'22px'}, 'flowchart': {'nodeSpacing': 45, 'rankSpacing': 60, 'padding': 12}}}%%
flowchart TD
    subgraph IN["① 進門"]
        Z["Zotero 外掛<br/>（選片 → 帶 item key → 上傳）"]
        INBOX["收件夾<br/>（直接丟 PDF）"]
        GATE1{"進料閘門<br/>intake.py"}
        HUMAN1(["👤 人工放行<br/>審核台 :9710"])
    end

    subgraph PARSE["② 解析（花錢的一步）"]
        MINERU["MinerU 官方 API"]
        RAW["解析成果<br/>content_list.json：一項一項<br/>（一段文字／一張表／一條公式）"]
    end

    subgraph POST["③ 整理　postprocess.py"]
        MUTE["消音：把文字清空<br/>版面雜訊／參考文獻／標題頁"]
        CURATED["人工裁定：整段換掉<br/>verified/&lt;第幾項&gt;.html｜.txt"]
        FIX["機械修補<br/>latex_fix：×誤讀、逐字母排版"]
        HUMAN2(["👤 人看著原圖打<br/>（機器修不掉的才走這裡）"])
        STAMP["蓋回 content_list.json<br/>＋重蓋 manifest 指紋"]
    end

    subgraph EXTRACT["④ 抽取"]
        SCAN["LightRAG 掃描 → 切 chunk"]
        EMB["向量：本機 BGE-M3"]
        LLM["實體與關係：DeepSeek"]
        CLEAN["graph-clean.py<br/>清掉「表 16」這類垃圾節點"]
    end

    subgraph STORE["⑤ 存放　Postgres"]
        DB[("doc_status｜doc_chunks<br/>graph_nodes｜graph_edges")]
    end

    subgraph QUERY["⑥ 查詢"]
        API["LightRAG :9621｜kbapi :9700"]
        RERANK["重排：bge-reranker-v2-m3"]
        ANS["答案"]
    end

    Z --> GATE1
    INBOX --> GATE1
    GATE1 -->|"頁數超過上限就擋<br/>內容雜湊重複就退 409"| HUMAN1
    HUMAN1 --> MINERU
    MINERU --> RAW
    RAW --> MUTE
    MUTE --> CURATED
    HUMAN2 -.寫成檔案.-> CURATED
    CURATED --> FIX
    FIX --> STAMP
    STAMP --> SCAN
    SCAN --> EMB
    SCAN --> LLM
    EMB --> DB
    LLM --> DB
    DB --> CLEAN
    CLEAN --> DB
    DB --> API
    API --> RERANK
    RERANK --> ANS

    STAMP -.->|"reindex：刪掉文件記錄再重掃<br/>不重新付 MinerU"| SCAN

    classDef human fill:#e3eef5,stroke:#3f7d99,stroke-width:2px,color:#0e2530
    classDef paid fill:#fdefdd,stroke:#b3762e,stroke-width:2px,color:#3d2708
    classDef cut fill:#fbe3e3,stroke:#b3454a,stroke-width:2px,color:#3a1114
    class HUMAN1,HUMAN2 human
    class MINERU,LLM,EMB paid
    class MUTE cut
```

> 顏色的意思：🔵 人要出場　🟠 這一步要花錢　🔴 **這一步會把文字刪掉**

---

## 每一關到底動了什麼

| 關卡 | 動的是什麼 | 花錢嗎 | 可逆嗎 |
|---|---|---|---|
| ① 進門 | 只是搬檔案與擋下不該進的 | 否 | 是 |
| ② 解析 | PDF → 一項一項的清單 | **是（MinerU 額度）** | 快取還在就不必重跑 |
| ③ 整理 · 消音 | **把文字清空**（原文存進備份欄位） | 否 | 是，`revert` 讀得回來 |
| ③ 整理 · 人工裁定 | **整段換掉**（原值存進備份欄位） | 否 | 是，同上 |
| ③ 整理 · 機械修補 | 就地正規化 | 否 | 是 |
| ④ 抽取 | 切塊、算向量、抽實體與關係 | **是（DeepSeek）** | 只能重抽，沒有 undo |
| ⑤ 存放 | 寫進資料庫 | 否 | **刪節點沒有 undo** —— 所以 `graph-clean` 每次都存備份 |
| ⑥ 查詢 | 唯讀 | 每次查詢的 LLM 費用 | — |

### ⚠ 三件最容易搞混的事

**一、「改」和「刪」是兩件事，發生在同一關。**

```
消音      把文字清空        → 那段話永遠不會出現在答案裡，而且沒有訊號
人工裁定  把文字換成正確的  → 內容還在，只是換了一版
```

兩者都把原值存進 `_pp_original_*`，所以都還原得回來。
**但刪比改危險**：改錯了內容不對還看得出來，刪掉了你不會知道少了一塊。

**二、改了第 ③ 關，第 ⑤ 關不會自己更新。**

解析成果改了 ≠ 知識庫裡的文字改了。已索引的文件在掃描時會被直接跳過，
**唯一的辦法是 `reindex`：刪掉文件記錄再重掃**（圖上那條虛線）。
PDF 與 AI 快取都留著，所以**不會重新付 MinerU**，沒改到的段落也直接命中快取。

**三、每重抽一次，第 ④ 關就可能生出新的垃圾節點。**

模型會把「表 16」當成一個獨立概念抽出來。提示詞守不住（實測三次），
所以靠 `graph-clean.py` 在容器外用樣式掃掉。
⚠ **但沒有任何東西規定「重抽之後要跑它」** —— 2026-08-16 實測：重抽兩份文件
就帶回三個垃圾節點，是人工發現的。

---

## 人在哪裡出現

```mermaid
%%{init: {'themeVariables': {'fontSize':'22px'}, 'flowchart': {'nodeSpacing': 45, 'rankSpacing': 60, 'padding': 12}}}%%
flowchart LR
    A(["👤 放行<br/>「這份要不要進」"]) --> B(["👤 看圖打字<br/>「MinerU 讀錯了，正確的長這樣」"])
    B --> C(["👤 裁定<br/>「兩個版本不同，用哪一個」"])
    C --> D(["👤 決定判準<br/>「這個警報算不算壞」"])

    classDef human fill:#e3eef5,stroke:#3f7d99,stroke-width:2px,color:#0e2530
    classDef handwork fill:#fdefdd,stroke:#b3762e,stroke-width:2px,color:#3d2708
    classDef judge fill:#fbe3e3,stroke:#b3454a,stroke-width:2px,color:#3a1114
    classDef rule fill:#e4efe4,stroke:#4f7d4f,stroke-width:2px,color:#12240f
    class A human
    class B handwork
    class C judge
    class D rule
```

| 出場 | 頻率 | 現在的做法 |
|---|---|---|
| 放行 | 每一批 | 審核台按一下 |
| 看圖打字 | 只在機器修不掉時 | 存成 `verified/<第幾項>.html｜.txt` |
| 裁定版本 | 罕見 | ⚠ **目前沒有畫面可以比對**，只能讀 HTML 原始碼 |
| 決定判準 | 一次性 | 寫成 `docs/decisions/` 的 ADR |

---

## 這張圖沒畫什麼

- **看圖的模型（三隻眼）** 怎麼互相比對、什麼時候叫第三隻 —— 那是另一張圖
- ✅ **檢查站站在哪裡** —— 已經畫了：[who-guards-what.md](who-guards-what.md)
- **東西存在哪台機器上**、哪些進版控 —— 那是第二張圖
- **重建（藍綠切換）的流程** —— 設計還沒批准，畫了會變

---

## 這張圖的可信度

| 部分 | 依據 |
|---|---|
| ①②③ 的順序與各關動什麼 | 2026-08-16 實跑 `postprocess.py plan／apply／reindex` 逐步看輸出 |
| `reindex` 不重付 MinerU | 同日實跑，零 MinerU 呼叫、總份數不變 |
| 消音三條規則的分工 | 讀 `pp/rules/` 三個檔的判準原文 |
| 重抽會帶回垃圾節點 | 同日實測，`compat-check` 的 A-33 從綠變紅 |
| ④⑤⑥ 的模型與服務 | `CLAUDE.md` 的外部服務表 ＋ `compat-check` 當日輸出 |
| 進料閘門的細節 | 讀 `intake.py`，**沒有實跑過一次完整進料** |

> **PO 批註區：**
>
> （畫法能不能討論、哪裡畫錯了、要不要補另外兩張——寫在這裡）
