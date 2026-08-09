---
title: NEXT — 接下來做什麼
date_created: 2026-06-20
date_modified: 2026-08-09
status: living
kind: sop
supersedes: ""
superseded_by: ""
summary: "待辦清單，依收尾批次排序。一條一行、動詞開頭，箭頭後面是完成的判準。理由外引。"
---

# NEXT — 接下來做什麼

做完的**刪整行**，摘要進 [cairn/LOG.md](../cairn/LOG.md)。
`→` 後面是「怎麼知道做完了」，寫不出來的不算待辦。
理由看 [audit-20260808.md](audit-20260808.md)（`audit N` 指過去），裁決看 [decisions/](decisions/)。

收尾批次順序是 PO 定的：守門先上線 → 文件對齊 → 動抽取 → 秘密 → 剩下的坑 →
上游 → **備份排最後**。第 1、2 批已完成（見 LOG）。

---

## 🔴 2026-08-09：整個清空重來了，下面很多條已經作廢

**知識庫、解析成果、人工裁定、原始 PDF 全部清掉**（PO 裁決：22 份佔總量不到一成，
不值得留）。資料根同時搬到一顆 1TB SSD。做了什麼、驗了什麼在 [LOG](../cairn/LOG.md)。

**⚠ 凡是依賴舊語料的條目一律作廢**，包括：實體碎片化那 84 組候選、`graph-shape`
量到的各種現值（節點 4,746／人名機構 188／位置標記 27）、canary 的 27 份基準、
`verified-findings.json` 記的逐份結論、以及所有「重抽之後量 X」的驗收。
**它們的母體不存在了**，數字不是變舊而是不再指向任何東西。
清單還沒逐條清 —— 下次動到哪一條，先確認它講的東西還在。

**第一批進完了**，過程與十個 bug 在 [LOG](../cairn/LOG.md)。

**現在的狀態不寫在這裡，寫死的那一版撐不過一週。** 要知道就跑，指令不會過期：

```
綠紅        cat /data/lightrag/checks/latest.json     ← timer 每天 08:30 自己寫的
全套檢查    python3 scripts/compat-check.py           ← 想現在就知道
份數        docker exec lightrag-postgres psql -U deeptutor -d lightrag -tAF'|' -c \
              "select count(*) from lightrag_doc_status where workspace='acoustics_v2';"
節點／關聯  同上，把表換成 lightrag_graph_nodes / lightrag_graph_edges
收件匣還剩  ls /data/lightrag/inbox/*.pdf | wc -l
```

⚠ **這一段刻意沒有數字**，理由同 [CLAUDE.md](../CLAUDE.md) 的機器關係表。
往下每一節裡帶日期的量測是**那天量到的**，不是現況——不要拿來當現在的答案。

- ⬜ 把剩下的進料進來　→ 審核台的「已進知識庫」數字對得上 PDF 份數

  ⚠ **MinerU token 2026-09-04 到期**；每天 2,000 頁享最高優先，超過降速不擋，
  所以剩下的本來就會跨好幾天。
  ⚠ **進料途中不要重啟 intake** —— 在途的會退回「等你看」而且不會自己放行，
  當天為此手動補了四輪。
  ⚠ **「等你看」的東西要看實際消音清單，不要看百分比。** 當天三份「參考文獻
  比例超標」逐條查證的結果是兩份乾淨、**一份規則真的圈錯**（附錄被當致謝消掉）。
  只看數字會把那一份放進去，而內容會靜靜少一塊。

- ⬜ `submit_reset` 的「忙碌中」守衛拿掉　→ 進料期間重置得了

  `_busy()` 是循序 worker 時代的產物。parse／admit／retry 三處當天已經拿掉，
  reset 那個留著 —— 它會刪解析成果，序列化有道理，但代價是**進料期間永遠重置不了**
  （當天撞到三次）。要嘛改成只擋真正衝突的情況，要嘛接受它。

- ⬜ 放行要真的併行，得先把 `apply` 挪到「解析剛跑完」那一刻

  當天實測開到 6 條會撞：`apply` 不能在 LightRAG 掃描時跑，而併行時總有人在掃。
  已退回 1 條。**不是調數字，是重構那一段。** 現在的緩解是「修補前先等抽取做完」
  （`INTAKE_IDLE_TIMEOUT`），11 件因此救回來。

## 抽取規則比圖譜新一版（刻意的）

- ⬜ 規則 2a 的小寫修正還沒進圖譜　→ `compat-check` A-32 回綠

  規則已補「不分大小寫」（`a2616c1`），但圖譜還是舊規則抽的。
  **不為了這個重抽**，下次有新文件進來時一起生效，或擇期重抽。
  在那之前 A-32 會一直是 soft FAIL —— 那是它該說的話，不是壞掉。

  ✅ **殘留節點本身 2026-08-09 已用確定性清除處理掉**（`graph-clean.py`）：
  66 → 27，刪掉的 53 個是 `equation N`／`eq. 7`／`figure 4f`／`table i`／
  `reference 1` 那一族。提示詞守不住（實測三次，而且遵守度隨後端變），
  所以改在容器外用樣式掃。`compat-check` A-33 現在守著它。

- ⬜ 決定 `region`／`zone`／`mode`／`model`／`part` 那 27 個節點要不要刪
  → 決定寫進 `docs/decisions/`，`pp/graph_labels.py` 的兩組字首照著調

  PO 2026-08-09 裁決先不動。它們**可能帶語意**（`Region II` 在分層介質或管道
  論文裡是「第 II 區」，與 `b_0`／`B_0` 同一類問題），刪掉不可逆。
  清單跑 `graph-clean.py plan` 就有，`graph-shape.py` 也分開報。
  ⚠ 這 27 個裡有好幾組只差大小寫（`region i`／`region I`／`Region I`），
  與實體碎片化那張審查表是同一批東西，**兩件事應該一起判**。

## 標題頁消音已上線，但要等重抽才看得到（2026-08-09）

`pp/rules/title_block.py` 已掛進 `postprocess.py` 與 `pp/apply.py`，27 份實跑：
16 份有標題頁區塊、消音 76 項、保留待查 14 項、最高比例 3.11%（門檻 8%）。
canary 基準已補回 27 份且全綠。

- ⬜ 重抽之後量 person／organization 有沒有降下來　→ 現值 188，目標大幅下降

  **消音改的是餵給模型的文字，所以圖譜上今天一個節點都不會變。** 效果要等
  下一次重抽。量法：`graph-shape.py` 的 `person／organization` 那一格。
  ⚠ 救不了的三類先寫在這裡，免得屆時把「沒降到 0」當成規則壞掉：
  正文裡的引用（`Almeida et al.` 那種，89 個人名裡有 10 個）、
  期刊推薦區塊（KI-015）、以及 `Helmholtz`／`Cremer`／`Maa`／`Mechel`
  這些**本來就該留著**的聲學史人物。

## 眼睛與文字已拆開，下一步是隔離的測試環境（2026-08-09）

`PP_EYE_A_*` 上線，不設時 fallback 回 `LLM_BINDING_*`，實機驗過行為不變。
拆分的目的是讓「換抽取模型」與「換看圖的模型」不再互相牽連。

✅ **trial 資料根已建好並驗過隔離**（2026-08-09）。`/data/lightrag-trial/work/`
底下是 `parsed` 與 `crops` 的完整複本，跑的時候帶 `PP_DATA_ROOT=/data/lightrag-trial`。
驗證與數字在 [LOG](../cairn/LOG.md)。**要換眼睛還缺下面這條。**

✅ **`--env-file` 已上線**（2026-08-09）。疊加不取代，異動清單一定印且分
「覆寫／新增」。trial 用法：

```bash
PP_DATA_ROOT=/data/lightrag-trial \
  python3 scripts/postprocess.py --env-file /data/lightrag-trial/trial.env check --doc X
```

- ⬜ 眼睛 A 沿用抽取模型時要出一聲　→ 換抽取模型而忘了設 `PP_EYE_A_*` 時看得到

  **拆分不會自動保護你。** fallback 保留舊行為是「今天什麼都不會變」的必要條件，
  所以沒設 `PP_EYE_A_*` 時眼睛 A 仍然跟著 `LLM_MODEL` 走。2026-08-09 反向對照：

  ```
  有指定眼睛 A    文字=deepseek-v4-flash  眼睛A=qwen3.6-35b-a3b     看得見圖=True
  沒指定眼睛 A    文字=deepseek-v4-flash  眼睛A=deepseek-v4-flash   看得見圖=False
  ```

  建議做法是**印一行提示**（「眼睛 A 沿用抽取模型 X」），不要做成硬性擋下 ——
  「哪些模型看得見圖」是綁模型的觀察，照 [hard-rules](hard-rules.md) 不得寫成
  流程中的自動裁決規則，換代後它會變成錯的而且錯得很安靜。

- ⬜ 眼睛 A 要指向 OpenRouter 的話，補 `PP_EYE_A_PROVIDER`
  → 同 `PP_EYE_C_PROVIDER` 的理由：同一個模型 ID 會被路由到不同供應商

  2026-08-09 拆分時刻意沒加 —— 沒有用到的旋鈕沒辦法驗證。

## ✅ 實機 `.env` 已填、抽取與眼睛 A 都換完（2026-08-09 驗）

兩把新金鑰 PO 已經填好，抽取走 DeepSeek、眼睛 A 走 OpenRouter，2026-08-09 在 dker
確認過是 as-built 不是範本。**接哪家、用哪個模型看 [CLAUDE.md](../CLAUDE.md) 的外部服務表**；
併發與預算那幾個旋鈕的現值不抄在這裡：

```
docker exec lightrag-acoustics_v2 env | grep -E '^(LLM_|MAX_|OPENAI_LLM_)'
grep -E '^PP_EYE_A_(HOST|MODEL|PROVIDER)=' /opt/stacks/lightrag/.env
```

- ✅ 填完之後跑 `compat-check`　→ 當天 hard／soft／驗不了全 0

  A-23 是綠的：`tests/model-observations.json` 記的就是
  `qwen/qwen3-vl-32b-instruct + gpt-5.6-luna`，與現行設定相符。
  **現在還綠不綠要自己跑**，判準見本檔開頭那格。

## 🔴 十二道閘門寫了，V5–V12 還沒接（2026-08-09）

**「寫好的檢查沒被呼叫等於沒寫」的現成案例，而且在生產路徑上。**
那條通則本身還在第 6 批等著升上游 —— 這是它的證據。

`pp/vlm.py` 的 `judge()` 定義了十二道，發現當時**整包搜尋零個呼叫點**；
實際在守的是 `postprocess.py` 的 `gate_table_html`，只有三道。
**V1／V2 已於 2026-08-09 接上**（走 `eyes.look()`，見 LOG），剩下八道。

| | 在跑 | 擋什麼 |
|---|---|---|
| V1／V2 | ✅ | **截斷**（`finish_reason != "stop"`、輸出沒有 `</table>` 收尾） |
| V3 | ✅ | 數學被換成圖片（`<img>`） |
| V4 | ✅ | prompt 洩漏 |
| V5 | ❌ | alpha 召回 |
| V6 | ❌ | 數值 precision —— 輸出裡每個數字都該在原文找得到，擋幻覺與抄錯欄 |
| V7 | ❌ | 順序 |
| V8 | ❌ | 負向控制（補「拿別張表也能通過」的洞） |
| V9 | ❌ | caption |
| V10 | ❌ | 列數對帳 |
| V11 | ❌ | 覆蓋率（只記錄不擋） |
| V12 | ❌ | 分母下限 —— 純數字／純符號表在空集合上召回率恆為 1.0，真空通過 |
| 單一完整 table | ✅ | `gate_table_html` 自己那道 |

⚠ **當初就知道有兩條路。** `gate_table_html` 的註解寫著「`vlm.py` 的 V3/V4 本來就
防這個，但 apply 走的是別條路」—— 於是在 apply 這側重寫了三道，其餘留在原地沒人叫。
**V1／V2 的修法是讓兩邊叫同一個函式（`vlm.truncation_failures`），不是再抄一份**
—— 抄一份就是再造第三條「寫了沒人叫」的路。剩下八道接回來時照這個做。

- ⬜ 決定 V5–V12 哪幾道要接回來　→ 決定寫進 `docs/decisions/`

  **不是搬程式碼就好。** `judge()` 需要 `gt_text`、`neighbour_gts`、`caption`、
  `layout_rows`，而現在的路徑（`eyes.look()` → `gate_table_html`）一個都沒在傳。
  接回去等於重新設計那一段。
  ⚠ 而且現在**驗不了**：全語料只剩 1 張可修補表格（canary 基準的 repairable 合計
  ＝ 1），改了也看不出效果。要先有更多帶表格的文件進來。

- ⬜ 方程式那條路（`eq-check.py`）只有 V1 在跑，V2 對它不成立　→ 想清楚裸 LaTeX
  的「有沒有寫完」怎麼判，再決定要不要補

  V2 檢查的是「以 `</table>` 收尾」，而方程式輸出是裸 LaTeX，沒有收尾標記，
  所以那三個呼叫點傳 `closing=None`。**這不是漏接，是判準對它不適用** ——
  但也代表方程式被截斷時只有 `finish_reason` 一個訊號，快取沿用時會少一層。
  ⚠ 目前 `crops/_equations` 底下一筆快取都沒有，這條驗不了。

## 🟡 查詢的重現性：設定已釘住，但正式庫沒重測（2026-08-09）

**同一個問題問兩次，使用者可能拿到不同的答案，而沒有任何訊號。**

`mode=mix` 會先用 LLM 從問題抽關鍵詞再走圖譜，而當時**查詢端的 LLM 跑在溫度 1.0**
（沒有人壓下來，與抽取端同一個成因）。關鍵詞每次不同 → 走到的圖譜不同 →
撈回的原文不同。實測同一題同一端點三次：

```
llama.cpp（當時的正式庫） 0.7624 / 0.8507 / 0.8279     ← 落差 0.09
DeepSeek（溫度 0.2）      0.8507 / 0.8507 / 0.8507     ← 三次全同
```

- ✅ 把查詢端溫度釘住了，而且思考也關了 —— 2026-08-09 as-built 驗過。現值自己看：

  ```
  docker exec lightrag-acoustics_v2 env | grep -E '^OPENAI_LLM_(TEMPERATURE|EXTRA_BODY)='
  ```

  ⚠ `OPENAI_LLM_TEMPERATURE` 是**全域的**（extract／keyword／query／vlm 四個角色都吃），
  所以它同時就是抽取溫度 —— 而抽取溫度那件事**沒有定案，是被這個鍵順帶決定的**。
  要分開設得先確認 LightRAG 的 role-specific 覆寫怎麼寫
  （`binding_options.py` 有 `role_upper` 的機制，還沒查）。

- ⬜ 在正式庫重測「同一題三次分數相同」　→ 上面那組數字是**試驗 stack** 上量的

  設定對了不等於行為對了。正式庫換成 DeepSeek＋0.2 之後沒有重跑過那一題。

- ⬜ 重測 `cairn/retrieval-tuning.md` 的結論　→ 那些「幾個百分點」還站得住嗎

  那份文件的判定（chunk 砍半沒用、維度不影響品質、圖譜與 rerank 互補）
  全部用同一種方法量的。**如果當時查詢端也跑在 1.0，它們有同樣的問題。**
  文件自己已經寫了「八道題太少」，但真正的問題不只是題數 —— 是同一題重跑就跳 0.09。

## ✅ DeepSeek 試驗已收攤（2026-08-09 驗），但 ADR 還沒寫

四件都做完了，逐項驗過：

```
ls -d /opt/stacks/lightrag-ds*   → 不存在
ls -d /data/lightrag-trial       → 不存在
docker ps -a                     → 沒有 ds／trial 容器
select workspace … group by 1    → 只剩正式庫 acoustics_v2
```

⚠ **金鑰還有第三個落點：當天那段對話。** 那份不在這台機器上，PO 自理。

- ⬜ 補一份 ADR　→ **決定其實已經做了**（實機在跑 DeepSeek，庫裡的東西都是它抽的），
  只是沒有落成文件。`docs/decisions/` 目前最新是 0006。

  ⚠ **上線了不等於量完了。** 可行性驗過的是速度、併發、品質、成本；
  **檢索品質仍然沒量** —— DeepSeek 的關係數比 llama.cpp 少約 30%，而 LightRAG
  靠關係走圖譜。那 10 題還沒跑，而現在整個知識庫都是它建的。

## 規則 2b 是唯一還有調整空間的（2026-08-09）

四條抽取規則裡，1 與 2a 現在都有不依賴模型的補救（標題頁消音、`graph-clean.py`），
規則 3 被遵守得很好（大小寫變體 1）。**只有 2b 沒有任何確定性工具能補** ——
`graph-clean` 只會刪或不刪，不會改名，而那些裸標籤正是裁決「先不刪」的那一族。

- ⬜ 比較組必須含教科書章節　→ 否則規則 2b 驗不到

  2026-08-09 量到：`Region I`／`Zone II`／`Part 1` 這種標籤**只出現在教科書**，
  四個配置在三篇論文上全是 0。加了 `C Equivalent Networks` 才量得出 DeepSeek
  的 2b 遵守度是 2／8（做對的長這樣：`chamber (region II)`）。

✅ **「縮寫外溢」假設 2026-08-09 已驗，結果是推翻。** 把 2b 的括號寫法換成逗號、
其餘一字不改，同樣六篇實跑：

```
原規則（括號）  節點 1472　帶括號縮寫 41（2.8%）　碎片 403　裸標籤 6
改規則（逗號）  節點 1454　帶括號縮寫 38（2.6%）　碎片 404　裸標籤 9
```

縮寫幾乎沒動（雜訊內），碎片總數一樣，而**裸標籤反而變差**（6 → 9）。
⇒ DeepSeek 自創 `(MPP)`／`(HR)` 是它自己的行為，不是規則外溢。
⇒ **2b 的括號寫法不要動** —— 原本的寫法遵守度還比較好。

- ⬜ 決定縮寫變體要不要處理　→ 決定寫進 `docs/decisions/`

  兩條路：規則裡明文禁止自創縮寫（要驗模型聽不聽得懂），或抽完之後正規化。
  ⚠ 後者與「**不做符號變體正規化**」那條裁決不衝突：那條怕的是替數學符號
  自創寫法（`Z_Mi`／`ZMi`），而 `micro-perforated panel (MPP)` 併回
  `micro-perforated panel` 沒有這個風險 —— 兩者是不同的東西，不要混用同一條理由。

## 審核台顯示假狀態（2026-08-08 重抽時抓到，同日修掉 `837b78f`）

分節改成一律問知識庫，「已處理」直接等於「已進知識庫」那一節的長度。
放行被守門擋下改成退回「等你看」，並補了 `failed → planned` 的重試。
9 個測試逐一對舊碼驗過會紅。**下面兩條是它留下的尾巴。**

- ⬜ 自己的 job 說 indexed、知識庫卻整份沒有這一列時，畫面仍算它完成
  → 需要一個「簿記說有、知識庫說沒有」的顯示狀態

  目前退回本站簿記，因為重建期間 `/documents` 可能暫時不列出某份文件，
  把它當成「不見了」會在每次重建時誤報。但真的遺失時也一樣安靜。

- ⬜ 放行與重抽搶用 `inputs/<ws>` 當暫存區
  → 兩者不該共用一個目錄，或至少要有鎖

  現在的處置是退回「等你看」讓人稍後再按，代價是**人要記得回來按**。

## 從第 2、3 批檢討出來的規範（見 [review-20260808](review-before-reextract-20260808.md)）

五條已經有執行者了。三條在 `scripts/guard-command.py` ＋ `.claude/settings.json`
（秘密整包輸出、管線後面的 `$?`、直接讀或 source `.env`），
一條在 `tests/test_no_hardcoded_host.py`（寫死 localhost，`ed1f832`），
一條在 `compat-check` 的 A-32（規則改了沒重抽，`0cc70ba`）。**還沒有執行者的：**

- ⬜ 「有權威來源時不得自己重算」　→ 升上游 BASELINE
  （2026-08-08 四次：容器要不要重建、設定雜湊、chunk token 數、實體型別查錯表。
  自己算的全錯，而且**錯的方向都是「看起來沒問題」**）
- ⬜ 「文件不得寫死可量測的數字」要有執行者　→ 不能只靠人記得
  （第 2 批正在根治這個病，而我同一天又犯了一次）
- ⬜ 「啟發式的結果不得直接當數字報」　→ 至少要有一個權威訊號覆驗
  （當天三次：年份密度估 40%（實際 10%）、殘留偵測誤判正文、chunk token 估 600
  （實際 1,818））

## 型別註解的欠帳（棘輪，清完一個刪一行）

ANN 已對整包開啟，**新寫的碼一定要有型別註解**。既有欠帳共 102 處，清單在
`ruff.toml` 的 `per-file-ignores`：

- ⬜ `postprocess.py` 18／`kbapi.py` 17／`entity-merge.py` 14／`test_oracle_secrets.py` 12
- ⬜ `pp/crosscheck.py` 8／`test_gates.py` 7／`test_intake.py` 5／`parse-check.py` 5
- ⬜ `test_deploy_stack.py` 4／`test_canary.py` 4／`pp/rules/latex_fix.py` 4
- ⬜ `pp/oracle.py` 2／`pp/eyes.py` 1／`mineru_common.py` 1
  → 這三個要先決定 `json.loads` 的回傳型別怎麼寫（`Json` 別名還是 `object`），
  **那是設計選擇不是打字**，不要在補註解時順手做掉

## 第 4 批：秘密與外部依賴（3 條）

- ⬜ 寫 `rotate-secret.sh`（audit 20）　→ 換秘密不必開編輯器
- ⬜ 更換 `LIGHTRAG_API_KEY` 與 `POSTGRES_PASSWORD`（audit 20、23）
  → 舊值失效、服務起得來（`POSTGRES_PASSWORD` 目前只有 8 字）
- ⬜ 審核台加「外部依賴」分頁（audit 20）　→ MinerU 到期日、各家餘額看得到

**MinerU token 2026-09-04 到期，但已經有執行者**：`compat-check.py` 的 A-21
（soft），剩 14 天內讓 daily-check 轉警報。分頁是讓它「看得到」，不是唯一防線。

## 第 5 批：剩下的坑（2 條）

- ⬜ 量查詢翻譯的效果（ADR-0005）　→ 中文題分數接近英文檔次
- ✅ intake 失敗語義（audit 22）——2026-08-08 `837b78f`

  守門擋下改成退回 `planned`；`failed` 且計畫仍有效的可以 `/api/retry` 撥回；
  重置改成保留通過審查的解析成果。2017 已用這條路救回，沒有再付 MinerU。
- ⬜ KI-001 表格結構黏連　→ 掉字 10.6% 裡最大的一族（117 詞）

## 第 6 批：上游畢業（standards，4 條）

- ⬜ `test_next_done_ratio.py` 進 `PROJECT_TEMPLATE/`（該目錄目前沒有任何 `.py`）
- ⬜ 「不可再生／唯一副本」這類描述性標籤要有執行者

  2026-08-08 差點出事：`C Equivalent Networks.pdf` 在 `work/parsed` 沒有副本，
  審核台的訊息說「搬到 library 不要直接刪 —— 那可能是唯一副本」，而那句話是對的。
- ⬜ 修上游 `self-check.py` 的 `dead_refs`（黑名單不是驗證器，見該檔 152 行）
- ⬜ 七條新通則上升（BASELINE 目前 2.0.0）：秘密不經過輸出／部署機落後要有人守／
  文件不寫死可量測的數字／檢查結果要帶版本／寫好的檢查沒被呼叫等於沒寫／
  改了 A 讓 B 安靜失效的相依要有人守／**有權威來源時不得自己重算**

## 第 7 批：備份（2 條，PO：資料庫都建好再開始）

- ⬜ 手動跑 `backup-cold.sh`，通過再開排程並從 `PAUSED` 移除（audit 21）
- ⬜ 關掉 backrest 備份 `/data/rag` 的排程（那目錄已廢除，見 ADR-0003）

## ⏸ 暫緩

- ⏸ `:9621` 要不要對外關掉（2026-08-07 決定暫留）

---

## 這次收尾新增的工具（下一個對話會用到）

| 工具 | 回答什麼問題 |
|---|---|
| `scripts/graph-shape.py` | 抽取規則有沒有奏效（節點／標籤／人名／大小寫變體） |
| `scripts/extraction-profile.py` | 圖譜是用哪一版規則建的、跟現行一不一致 |
| `scripts/context-budget.py` | 查詢的 token 預算實際花到哪 |
| `scripts/deploy-stack.py freshness` | 跑著的是不是最新的碼（含 systemd 服務） |
| `scripts/guard-command.py` | 執行前擋下已知會出事的指令形狀 |
| `scripts/graph-clean.py` | 位置標記節點還在不在，要刪的話刪哪些（`plan`／`apply`） |

**共同的原則：不要自己算，去問做決定的那一方。** 上面每一支都是那個原則的實作
（問 compose、問 tokenizer、問 LightRAG 的解析器、問 systemd），因為
2026-08-08 每一次自己重算都算錯了。`graph-clean.py` 也是：刪節點走
`/graph/entity/delete`，不直接對 Postgres 下 DELETE —— 向量表、圖節點表、
圖邊表三者的一致性是 LightRAG 的內部契約，在容器外自己維持等於重做一次。

## 已知但刻意不做

- **不改 workspace 名稱**（`acoustics_v2` → `acoustic`）。功能上只是字串，但要動
  `backup-cold.sh` 的容器名、`systemd-units.py` 的預設值、三個 skill 的 8 處 URL、
  三個測試檔。波及面大、價值低。
- **不擴到 20 篇**。2026-08-08 PO 槓掉，語料就是庫裡現有的那些（**份數不寫死**，
  用 psql 量）。
- **不上 Qwen3-Reranker**。已由 `BAAI/bge-reranker-v2-m3` 取代並上線（`8ebdc6b`）。
- **不做符號變體正規化**（`Z_Mi`／`ZMi`／`Z Mi`）。要模型替數學符號自創正規寫法，
  是錯誤代價最高又最難發現的地方——寫錯成「看起來合理但不是論文用的」符號，
  沒有人看得出來。那類留給重抽後的審查表用原文逐組判斷。
- **不做單複數正規形**。實際候選清單裡根本沒有這種案例（audit 當時的例子已不存在）。
- **`.env` 不要用 `source` 讀**。`LIGHTRAG_PARSER` 的值含 `;`，shell 會把分號後面
  當指令。取值用 `grep -E '^KEY=' … | cut -d= -f2-`。（已有執行者：`guard-command.py`）
- **llama 的金鑰不換、也不從命令列移走。** 2026-08-08 PO 裁決：「不擔心，本地端而且
  只有我用」。事實記著以免重新爭一輪：`--api-key <值>` 在容器的 `Cmd` 上，
  `docker inspect` 與 `ps aux` 都看得到。形狀與 `oracle.py` 當初修掉的
  `-e KEY=VALUE` 相同，但**風險面不同**：那台在 Tailscale 內、單人使用。
  ⇒ 判準不是「有沒有洩漏路徑」，是**誰在那條路徑上**。
