---
title: 來源登記審查 — 259 份，11 個要人判的
date_created: 2026-08-13
date_modified: 2026-08-13
status: living
kind: review
supersedes: ""
superseded_by: ""
summary: "eq-dup 的來源原本從檔名推論、五類全錯。這裡是候選的人核表：機器合併 7 組、自成一組 117 份、判不出來 4 份，加上機器看不出來的『學位論文章節就是庫裡那篇期刊論文』。每一項都附證據與建議答案，只要改不同意的那幾行。"
---

# 來源登記審查（2026-08-13）

**每一項的 `判定：` 那一行是給你改的。** 同意就不用動，不同意就把它改掉、
在下面補一行為什麼。核完我把它凍結成 `verdicts/source-map.json`，
然後同一個 commit 刪掉舊的檔名推論。

**為什麼要判這些**：`eq-dup` 找「同一條公式在不同文獻裡係數不一致」，
而「同一本書的兩章重複一條公式」不算兩篇文獻都這樣寫。判錯的代價是
**叫人去查一個不存在的分歧**。

判不出來就留 unknown，那份文件不計入「跨了幾個來源」——**少報不假報**。

重跑候選：`ssh 100.87.88.7 'cd ~/ghq/…/lightrag && python3 scripts/source-map.py propose'`

---

## A. `0xxxx_` 那 88 份是兩本書，不是一本

機器用章號差分開：流水號 idx，一本的章號 == idx−9、另一本 == idx−6。
實測 88 份**兩者皆合 0 份、皆不合 0 份**，零歧義。

<details><summary>證據：兩本書的排版慣例也不一樣</summary>

```
書 A（50 份）章首只有標題
  01500_6 Sound absorption and sound absorbers  → "Sound absorption and sound absorbers"
  01900_10 Prediction models                    → "Prediction models"

書 B（38 份）章首帶 "Chapter N"
  01500_9 Scattering and Diffraction            → "Chapter 9 Scattering and Diffraction"
  01600_10 Effects of Viscosity …               → "Chapter 10 Effects of Viscosity and Other Dissipative Processes"
```

⚠ 這 88 份原本**全部被當成同一本**，所以兩本書之間真正的公式分歧看不見（少報）；
同時書 A 自己被切到 `01xxx` 與 `02xxx` 兩段，於是它自己跟自己被當成兩篇文獻（假報）。
</details>

**判定：兩本書，分開。**

### A2. 這兩本書叫什麼

書名要填進登記檔的 `label`，只影響報告可讀性，不影響分組。
我沒有書名頁可以引，**所以這一格我不填，等你給**。

<details><summary>我看到的線索（不足以當證據）</summary>

書 A 的章題是室內聲學的順序（吸音材料 → 主觀聽感 → 量測 → 設計 → 預測模型 →
電聲系統）；書 B 是物理聲學的順序（射線振幅 → 散射繞射 → 黏滯耗散 → 非線性）。
兩本我都**沒有翻到標題頁**，`pdfinfo` 也吐不出標題。
</details>

**判定：書 A ＝ ______、書 B ＝ ______（填不出來就留空，不影響分組）**

---

## B. 單字母 A–R 那 18 份是同一本手冊

<details><summary>證據</summary>

`A Conventions` 內文第一句：「The following conventions will be used in **the book**.
Exceptions will be clearly noted in the respective Section」——
章號 A 到 R 連續無缺，18 份的 `pdfinfo` 都只吐得出同一個 `Creator: PDF-XChange Editor 9.1.356`。

⚠ **這是推斷不是實證**：沒有任何一份翻得到書名頁。
</details>

⚠ 這組**最會製造假報**：公式手冊本來就跨章重複公式（`C Equivalent Networks`、
`G Porous Absorbers`、`H Compound Absorbers` 會反覆出現同一族阻抗式）。

**判定：同一本，合併。**

---

## C. 四本學位論文的章節切片

| 組 | 份數 | 原本被切成幾組 |
|---|---|---|
| `2012 - Combined wave and ray based…` | 9 | **2**（檔名差一個空格） |
| `2023 - Perception-of-room-modes` | 9 | **4**（檔名多了 `_Conclusions`／`_Control of Room Modes`／`_Subjective…`） |
| `2021 - Room acoustic modeling with the TD_DG method` | 7 | 1（本來就對） |
| `2026 - hybrid computational framework for room-acoustic` | 7 | 1（本來就對） |

**判定：四組各自合併。**

---

## D. 四份附件歸給正文

<details><summary>證據：每份附件的第一段原文</summary>

```
2019 - Low-frequency … micro-perforated  Supplementary material
    → "Supplementary material to:"                    （沒寫篇名，靠檔名）
2020 - Low-Frequency Broadband … Supplementary Material
    → "Supplementary Material"                        （沒寫篇名，靠檔名）
2022 - Broadband impedance modulation …_supplemental_file
    → "Supplemental Informations for “Broadband impedance modulation via non-local
       acoustic metamaterials\""                      （內文寫了篇名）
41598_2017_5710_MOESM1_ESM
    → "Supplementary material to: Metadiffusers: Deep-subwavelength sound diffusers"
                                                      （內文寫了篇名，檔名完全看不出來）
```
</details>

**判定：**

- `2019 - … Supplementary material` → 併入 `2019 - Low-frequency sound absorption of hybrid absorber based on micro-perforated panel and coiled-up chan…`
- `2020 - … Supplementary Material` → 併入 `2020 - Low-Frequency Broadband Acoustic Metasurface Absorbing Panels`
- `2022 - …_supplemental_file` → 併入 `2022 - Broadband impedance modulation via non-local acoustic metamaterials`
- `41598_2017_5710_MOESM1_ESM` → 併入 `2017 - Metadiffusers Deep-subwavelength sound diffusers`

---

## E. 學位論文的某一章，其實就是庫裡的某篇期刊論文

**這一類機器看不出來，而且是我原本整個漏掉的。** 分對了書也救不了：
論文本體與期刊版是兩個不同的來源 id，於是「兩篇獨立文獻都這樣寫」仍然是假的。

<details><summary>證據：章名 vs 庫裡論文標題（自動比對，人核）</summary>

```
0.98  2026 - hybrid computational framework for room-acoustic_CH03
        章名 "3 A Hybrid Room Acoustic Modeling Approach Combining Image Source,
              Acoustic Diffusion Equation, and Time-Domain Discontinuous Gale…"
        論文 2024 - A hybrid room acoustic modeling approach combining image source,
              acoustic diffusion equation, and ti…

0.90  2021 - Room acoustic modeling  with the TD_DG method_CH2
        章名 "2|Room acoustic modeling with the time-domain nodal discontinuous
              Galerkin met…"
        論文 2019 - Room acoustics modelling in the time-domain with the nodal
              discontinuous Galerkin method

0.74  2026 - hybrid computational framework for room-acoustic_CH02      ← 誤報
        章名 "2.1 Standalone room-acoustic modeling techniques"（這是節標題不是篇名）
        論文 2015 - Overview of geometrical room acoustic modeling techniques
```

`2021 - … TD_DG method_CH4` 的內文另寫著「This chapter is based on **Paper III**」——
**它自己承認是論文重印**，但沒說 Paper III 是哪一篇，要翻它的 paper list。
</details>

**判定：**

- `2026 hybrid` ↔ `2024 - A hybrid room acoustic modeling approach…` → **同一部作品，合併**
- `2021 TD_DG` ↔ `2019 - Room acoustics modelling in the time-domain…` → **同一部作品，合併**
- 0.74 那組 → **否決**（節標題撞名，不是同一篇）

### E2. 沒查完的部分

- `2021 TD_DG` 的 Paper I／III／…分別對應庫裡哪幾篇，**沒查**（要翻論文的 paper list）。
- `2023 Perception-of-room-modes` 的章節與 `2005 - Perception_of_Modal_Distribution_Metrics…`
  疑似同一作品，**這一輪的自動比對沒撈到**（只讀了每章前三段文字），沒查。

⚠ 這兩條先留著不動 —— **少報不假報**。要補的話是下一輪的事。

**判定：這一輪先不查，記進 NEXT。**

---

## F. 政策題：姊妹篇算一個來源還是兩個

`2007 - Hybrid method … part 1` 與 `part 2` 是同作者同一套推導、分兩篇發表。
庫裡還有 `1986 - … Part 2`（目前找不到它的 Part 1）。

- 算**一個**來源：它們不是彼此獨立的證據，兩篇寫同一條公式不代表兩組人各自驗證過。
- 算**兩個**來源：它們確實是兩次獨立的同行審查。

我建議算一個，理由是這支工具問的是「有沒有第二個獨立來源這樣寫」，
而姊妹篇不提供那個。政策定了之後往後自動適用。

**判定：算一個來源。**

---

## 核完之後我會做的

1. 把上面的判定凍結成 `verdicts/source-map.json`（`by` 從 `propose` 改成 `human`）。
2. **同一個 commit** 刪掉 `eq-dup.py` 的 `source_key()` 與那兩條正規表達式，
   改讀登記檔。⚠ 不能分兩次 —— 兩條路並存就是這個專案被咬過五次的形狀。
3. `eq-dup` 的報告表頭加上對帳那一行（語料幾份／已登記幾份／雜湊對得上幾份／
   幾份不計入），沒有這一行就看不出母體被削掉多少。
4. 重跑，把「Tier A 第一名說 3 個來源其實只有 2 個」那個實例的前後對照貼出來。
