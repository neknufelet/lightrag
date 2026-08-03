# 裁決盤點 2026-08-04（**未確認，不是先例表**）

> ⚠️ **這份是 codex luna 掃 repo 產出的原始盤點，不是已確認的先例表。**
>
> - 75 條裡**只有 5 條經人工核對，其中 3 條 luna 標過頭**（見下方「已核對」）。
>   ⇒ **剩下 70 條的可信度未知。引用任何一條前，先自己去看出處。**
> - 它**沒有被任何程式使用**，也不是機器可讀的格式。
> - 要升格成真正的先例表，缺三樣：逐條人工確認、schema、**以及一個真的會查它的消費者**。
>   PO 2026-08-04 判定：**先不做**——第一份新文件都還沒跑過，現在定 schema 是猜需求。
>
> **為什麼還是留著**：盤點本身已經抓到兩處文件與程式碼打架（`V5` 的 IDF 過濾、
> `V12` 的數字分母），那兩處會實際害人，已於 `bc7bc4f` 標記。這份留著是為了
> 日後真要做表時不必重掃。
>
> ## 已核對的 5 條
>
> | ID | luna 判定 | 人工核對結果 |
> |---|---|---|
> | X07 | 文件與程式衝突（V5 的 IDF） | ✅ **成立**，已標記 |
> | X14 | 文件與程式衝突（V12 的數字分母） | ✅ **成立**，已標記 |
> | X02 | v155 的 K Muffler 歸因仍在歷史文字 | ❌ 誤報——CLAUDE.md 與 NEXT.md **兩處都已標「已推翻」** |
> | X12 | 二態未接地數字仍在 | ❌ 誤報——那是**三態規則的證據**（二態 55% → 三態 3.4%），不是殘留 |
> | X06 | 舊工單前提「改完自動生效」仍在 | ❌ 誤報——`W9` 那段是**正確的重建索引配方** |
>
> **抽驗 5 條錯 3 條**⇒ 這也回答了「能不能自動匯入」：**不能**。

---

# 總數

按「跨檔重述合併成一條可重用的 X→Y→Z 命題」計算，我找到 **75 條**：

| 類別 | 條數 |
|---|---:|
| 耐久規則 | 35 |
| 易腐觀察（綁模型／實驗） | 12 |
| 一次性決定 | 14 |
| 已被推翻／過時裁決 | 14 |
| **合計** | **75** |

這不把 `SYMBOL-1` 的 50 題、`SYMBOL-2` 的 50 題、160 格 ledger 狀態逐一膨脹成流程規則；它們保留為原始證據。

## 耐久規則：35 條

| ID | 出處 | 遇到什麼 → 判定（理由） | 證據／日期 | 還在成立嗎／探針 |
|---|---|---|---|---|
| D01 | `CLAUDE.md:273-274`; `SKILL.md:21-39,74-107`; `scripts/ledger.py:44-55`; `scripts/compat-check.py:370-376` | 遇到未知型別 → 整份文件停止，不猜；避免新型別靜默丟失 | 未記載；多處流程規格 | 是；`A-16`、`preflight()` |
| D02 | `CLAUDE.md:275-276`; `docs/judgement-flow.md:235-239`; `docs/postprocess-workorder.md:437-456`; `scripts/pp/rules/layout_noise.py:1-9` | 遇到書眉／頁尾雜訊 → 消音並保留 sidecar，不刪 item；因 `self_ref` 是陣列索引 | 明載 7 份文件 | 是；`items`、`mute`、sidecar |
| D03 | `CLAUDE.md:277-279`; `docs/postprocess-workorder.md:374-404`; `scripts/pp/oracle.py:1-40` | 不確定 LightRAG 行為 → 問實際容器 oracle，不自行重實作；避免假契約 | 未記載 | 是；`A-01`～`A-06` |
| D04 | `CLAUDE.md:281-284`; `docs/judgement-flow.md:67-87`; `scripts/parse-check.py:87-92` | 出現異常 → 先查輸入，再查偵測器，最後查模型；因偵測器／裁圖錯誤比模型更常見 | `judgement-flow` 記 15 次 | 是；`parse-check`、人工 top-hit |
| D05 | `CLAUDE.md:285-286`; `docs/judgement-flow.md:147-157`; `scripts/coverage-check.py:1-30` | 門檻異常 → 先看具體符號與量測對象，不先調 threshold；避免把偵測器錯誤調成「通過」 | 多起實測；份數未記載 | 是；coverage、scan baseline |
| D06 | `CLAUDE.md:287-293`; `scripts/parse-check.py:125-142`; `scripts/compat-check.py:409-413`; `scripts/ledger.py:250-262` | 探針不得只查指定文件 → 預設掃全體，並報出隱藏的 pass；因 chart 曾被 `if a.doc` 漏掉 | `A-16` 實測 184 charts | 是；`A-16`、全量掃描 |
| D07 | `CLAUDE.md:294-306`; `scripts/llm-bench.py:179-201` | 結果漂亮地為 0 → 先當量測壞掉，警告而不下結論；因錯 workspace、錯格式、錯欄位都會製造假零 | 3 起實測 | 是；工具內 zero guard |
| D08 | `CLAUDE.md:420-448`; `scripts/ledger.py:2-18`; `docs/judgement-flow.md:215-227`; `scripts/pp/vlm.py:48-71` | 檢查結果 → `pass/fail/unverifiable` 三態；`fail` 不進下一階段，`unverifiable` 必須附理由 | 多份文件 | 是；ledger、VLM、extract |
| D09 | `docs/judgement-flow.md:10-63`; `scripts/coverage-check.py:1-20`; `scripts/extract-check.py:8-14` | 需要判斷正確性 → 優先找獨立對照源，不能只做產出對產出；因一致不代表正確 | 未記載；流程原理 | 是；PDF text layer、source chunk |
| D10 | `CLAUDE.md:432`; `docs/judgement-flow.md:24-28,175-198`; `scripts/pp/eyes.py:1-12,42-90` | 需要兩眼交叉驗證 → 模型必須不同家族、獨立看圖；避免相關錯誤互相投票 | 原理；另有 10 張表實測 | 是；`eyes_from_env()` |
| D11 | `CLAUDE.md:433`; `docs/judgement-flow.md:186-212`; `scripts/pp/crosscheck.py:1-28` | 表格／方程式分歧 → 逐格、內容級比較，不用整表 scalar；因跨頁續表詞彙高度重疊 | 1 份實測＋原理 | 是；cell gate、V10 |
| D12 | `docs/judgement-flow.md:136-171`; `scripts/entity-merge.py:68-93` | 一條規則若有一個反例 → 從自動降級人工；A/B 可自動，C 必須人看 | 多起實測 | 是；entity tier、人工 review |
| D13 | `docs/judgement-flow.md:231-240`; `scripts/pp/apply.py:57-62`; `entity-merge.py:429-431` | 判不準 → 不猜、不刪、不合併，先保留；因刪除／合併不可逆 | 未記載 | 是；apply 拒絕路徑 |
| D14 | `docs/judgement-flow.md:241-267`; `scripts/entity-merge.py:611-618` | 要交人工 → 同時給模型描述、原文、選項與證據可靠度；寬鬆命中不得冒充證據 | 未記載 | 是；review artifact |
| D15 | `docs/judgement-flow.md:159-171`; `scripts/entity-merge.py:77-93` | 實體只差分隔符／長英文大小寫／短 token 或下標 → 分 A/B/C；數學短 token 的大小寫可能有語意 | 未記載 | 是；`entity-merge.py` |
| D16 | `docs/judgement-flow.md:272-288`; `NEXT.md:722-749` | 有問題但未必有價值 → 先量實際檢索代價，再排序；不可逆操作零收益不做 | v155 實測；但 v2 尚未重驗 | 部分成立；v2 需重測 |
| D17 | `docs/judgement-flow.md:200-212`; `scripts/pp/apply.py:45-54,94-111` | VLM 只證明局部錯誤 → 只做定點／只插入修補，不整表覆蓋；避免把模型錯誤寫回 | 多份流程規格 | 是；additive invariant |
| D18 | `docs/postprocess-workorder.md:27-53,515-544`; `scripts/pp/rules/empty_table.py:1-23`; `scripts/postprocess.py:466-478` | `table_body` 已有實質內容或含正常 `<img>` → 不自動修；只修缺鍵／空殼，因覆蓋會製造靜默損壞 | C 表實測 28 張正常表 | 是；`empty_table`、apply gate |
| D19 | `scripts/pp/vlm.py:1-16,38-60,155-260`; `docs/postprocess-workorder.md:566-726` | VLM 輸出截斷、含 prompt leak、外部圖片、數值／列數不符 → 不採用；分母不足 → `unverified` 交人工 | 240 組錯配、57 張表等實測 | 是；`V1`～`V12`、`INDEX-VERIFY`；但 V12 文件與程式衝突，見 X14 |
| D20 | `scripts/eq-check.py:1-19,108-174`; `docs/judgement-flow.md:175-212` | 方程式 → MinerU、兩眼三方判讀；第四眼只處理三方皆異；避免盲目付費 | `model-observations` 記 57%/23%/13% | 設計仍在；v2 尚未完整重跑 |
| D21 | `scripts/pp/pdfcrop.py:1-35`; `tests/model-observations.json:27`; `NEXT.md:464-467` | 裁圖 → 一律從來源 PDF 自己裁；方程式垂直 pad 用 1，表格用 6；因 6 會框入鄰式 | 具體 K Muffler 實測 | 是；crop／VLM |
| D22 | `scripts/coverage-check.py:1-150`; `docs/rebuild-plan.md:130-170`; `README.md:137-157` | coverage → 用 PDF text layer、≥4 字母詞、多重集合、NFKC；≤5% 才過 | 20 份基線；C/N/41598 例外 | 是；`parse.coverage` |
| D23 | `CLAUDE.md:550-590`; `scripts/extract-check.py:1-64,100-115,167-185` | 實體接地 → 產出對來源；符號型 chunk 不可字串驗證，進 `unverifiable`；`SYMBOLIC_RATIO=.35` | 5 份規則證據；C table 實測 | 是；`extract.grounding` |
| D24 | `CLAUDE.md:439-458`; `tests/model-observations.json:2-3`; `scripts/compat-check.py:277-298` | 模型觀察 → 不得直接成為自動裁決；換模型必須重測 | 明載為規則 | 是；`A-23` |
| D25 | `CLAUDE.md:315-316,523-531`; `scripts/extract-check.py:133-147`; `scripts/compare-ws.py:2-31` | 多 workspace／環境 → 每句 SQL 帶 workspace，不猜 workspace、容器、port；否則數字會靜默混庫 | v155/v2 實測 | 是；workspace 重跑、A-19 |
| D26 | `docs/postprocess-workorder.md:63-73`; `scripts/compat-check.py:321-356`; `scripts/parse-only.py:57-76` | bundle → 以 manifest、size、sha256、內容定址驗證；有效 bundle 不重抓；`force reparse` 禁用 | 多項契約測試 | 是；`A-05,A-07,A-10,A-13` |
| D27 | `scripts/postprocess.py:2-8,253-260`; `docs/postprocess-workorder.md:647-666` | 修改 raw → 必須 reindex 才會進索引；不存在「解析後、建 IR 前」自動生效時間窗 | 實際 pipeline 行為 | 是；`X-1`、raw cache hit |
| D28 | `docs/judgement-flow.md:292-313`; `scripts/pp/apply.py:1-23`; `scripts/postprocess.py:414-424` | 寫回任何一份失敗 → 整批回滾；備份不可覆蓋、不可截斷、必須可驗證 | 多項故障實測 | 是；backup hash、batch rollback |
| D29 | `CLAUDE.md:332-357`; `scripts/postprocess.py:177-249`; `tests/canary-baseline.json:1-242` | 改規則 → 先跑 canary 期待失敗，再逐項解釋，最後更新基準 | 20 份基準 | 是；canary；但 CLAUDE 列 8 個量，現行程式／JSON 是 10 個，見下 |
| D30 | `CLAUDE.md:430-431`; `SKILL.md:194-195`; `scripts/pp/rules/layout_noise.py:38-60` | 書眉／頁尾重複 → 門檻 `max(2,min(3,ceil(pages×.5)))`；短文件不能固定要求 3 次 | 明載 7 份文件 | 是；canary `mute/held/ratio` |
| D31 | `CLAUDE.md:435`; `SKILL.md:198`; `layout_noise.py:26-36,119-129` | 頁碼型書眉 → 先把數字轉 `#` 再計樣板；避免每頁字面不同而漏抓 | 明載 2 份文件 | 是；canary |
| D32 | `CLAUDE.md:434`; `SKILL.md:197`; `layout_noise.py:107-146` | `aside_text` → 先跑重複／樣板；只有單次且非語言才用 gibberish；同型別跨期刊可能不同 | 明載 2 份文件 | 是；canary；單文件反例已修正 |
| D33 | `CLAUDE.md:436,508-511`; `SKILL.md:199`; `scripts/pp/rules/chart_type.py:1-23,77-107` | `chart` → 目前需登記並在合法 image asset 存在時轉 `image`；caption 欄位一併改名；dangling 不轉 | CLAUDE 明載 3 份；SKILL 明載 **1 份且脆弱** | 有衝突；`A-24`、canary `charts_convert/charts_dangling` |
| D34 | `scripts/parse-only.py:1-24,57-76`; `scripts/parse-check.py:1-15`; `docs/rebuild-plan.md:49-81` | 解析完成 → 先做 parse gate，再讓 LLM 抽取；避免幾十小時後才發現解析壞掉 | 未記載；流程多處重述 | 是；parse-check |
| D35 | `README.md:25-61`; `docs/rebuild-plan.md:130-170` | 解析設定 → 採用 `pipeline + is_ocr=true`，抽取用 JSON；因實測掉字／表格量較佳 | 3 組解析比較 | 現行主線設定；缺獨立 assertion |

## 易腐觀察：12 條

| ID | 出處 | 遇到什麼 → 判定（理由） | 證據／日期 | 還在成立嗎／探針 |
|---|---|---|---|---|
| P01 | `tests/model-observations.json:9-12`; `CLAUDE.md:592-602` | qwen 偏結構錯、luna 偏字元錯，沒有一眼全面較準 → 保留兩眼 | 10 張表；2026-08-01 | 只綁現行模型；`A-23` |
| P02 | `tests/model-observations.json:21`; `NEXT.md:160-162` | 羅馬數字 I/II/III 是主要錯誤族 → 判讀時特別防護，不直接改模型規則 | 4 個獨立檢查；2026-08-01 | domain fact 可累積；模型部分易腐 |
| P03 | `tests/model-observations.json:13-14`; `CLAUDE.md:604-605` | luna 重抽後分歧消失 → 判為取樣雜訊；重抽一致 → 判為穩定分歧 | 10 張表、5 次重抽；2026-08-02 | 綁 `eye_b`；`A-23` |
| P04 | `tests/model-observations.json:15-16`; `scripts/postprocess.py:349-367` | qwen 遇示意圖會產生外部／假本地 `<img>` → 寫入點再擋一次，按現值允許既有合法參照 | 1/10 擴大到 24/57；2026-08-01～02 | 綁 qwen；`V3/V4`、apply gate |
| P05 | `tests/model-observations.json:18`; `scripts/pp/eyes.py:58-80` | eye_c 候選分數相同但家族高度相關 → 不把相關模型當兩票；選 MiMo 是成本決定 | 4 個三方皆異案例；2026-08-01 | 綁候選模型；無自動相關性探針 |
| P06 | `NEXT.md:503-505` | qwen「系統性切錯列」只有一份文件 → 暫只能視為巧合，不能升格規則 | 1 份文件 | **未成立為耐久規則**；需第二份樣本 |
| P07 | `tests/symbol1-answer-key.json:1-21`; `NEXT.md:123-168` | 1,482 個符號型實體抽 50 題：19 correct、27 restated、4 wrong → 主要問題是檢索價值，不是全是幻覺 | 50 題、6 份文件；2026-08-03 | 易腐；原始 50 筆保留在 JSON |
| P08 | `NEXT.md:172-204`; `tests/symbol2-results.json:1-61` | `restated` 命中率與 retrieval 分布 → 只能作線索，不能當全庫比例或永久裁決 | 30／60 種子；2026-08-03 | **工具未過終審**；無自動 consumer |
| P09 | `NEXT.md:288-298`; `tests/symbol2-results.json:7-50` | 完整 context 比截斷高約 8pp；在其上加推理再高約 10pp → 推理貢獻不可假設較小 | 50 題三臂；2026-08-03 | 綁 luna／題本；無耐久 probe |
| P10 | `NEXT.md:300-331`; `tests/symbol2-results.json:52-61` | 三組模型抓到不相交子集 → 此任務不能用多數決 ensemble | 50 題；2026-08-03 | 實驗結論；不能外推其他任務 |
| P11 | `NEXT.md:580-611` | gleaning 新增候選 93.4% → 足以阻止盲砍，但不足以永久保留或永久封殺 | 1,019 筆 cache；2026-08-03 | **未定案**；缺 parser／relation／query A/B |
| P12 | `NEXT.md:681-694`; `scripts/llm-bench.py:35-42,546-555` | 不同併發度輸出 0/8 逐字相同；c=1 可重現；冷 cache 才代表真實負載 | 受控 benchmark；2026-08-03 | 綁 build／server；benchmark artifact |

## 一次性決定：14 條

| ID | 出處 | 遇到什麼 → 判定（理由） | 證據／日期 | 還在成立嗎／探針 |
|---|---|---|---|---|
| O01 | `NEXT.md:115-117`; `docs/rebuild-plan.md:231-260` | 三份 waiver → 放行進階段 3；理由在 `$RECORDS/ledger/` | **3 份，出處在 repo 外**；2026-08-02 | 已完成；repo 看不到 note |
| O02 | `NEXT.md:253-281` | OCR 污染約 17–30 個、修復需重建重抽 → 既有索引不修 | 7,211 實體 sizing；2026-08-03 | 一次性；未來只做結構性 detector |
| O03 | `NEXT.md:201-204,320-327` | 既有 1,482 不掃、不事後合併；只改未來 prompt → 因無 consumer、不可逆且收益未證明 | SYMBOL-2／3；2026-08-03 | 已定案；無 probe |
| O04 | `NEXT.md:206-233` | prompt 加具體例子反而捏造名稱 → SYMBOL-5 暫停；若重試不得放例子、不得輸出源文不存在名稱 | 6 chunks A/B；2026-08-03 | 暫停；未形成規則 |
| O05 | `NEXT.md:458-463`; `NEXT.md:111-117` | N Flow #1410 overbar/∂ 錯 → 維持 `pp.equations` fail，需整式重轉錄 | 單一已知缺陷；waiver note repo 外 | 目前成立；單一事件 |
| O06 | `NEXT.md:464-467` | C 的 6 個 `x/×` 誤讀位於未授權位置 → 暫不放寬；一次只放一條規則，避免無法歸因 | 6 處；未載日期 | 待辦；無 probe |
| O07 | `NEXT.md:468-475` | C 的 91 個 bbox 未覆蓋詞 → 尚未決定併入哪個 item；不能增加 item 數 | `$RECORDS/review`；repo 外 | **未裁決** |
| O08 | `NEXT.md:476-478` | 首頁期刊／版權資訊只出現一次 → 先不動；只有一份文件證據 | 1 份文件 | 一次性；明確標為巧合風險 |
| O09 | `NEXT.md:482-489`; `scripts/retrieval-check.py:1-20` | retrieval-check 的 0.57%／55% 是單字元假訊號 → 改問題或改報相異字串數 | v155→v2；2026-08-03 | 待改；現有結果不可直接用 |
| O10 | `NEXT.md:490-498` | 裁決材料在 `/data` 但不在 git → 建議把定案節抽入 repo | repo 外材料；2026-08-03 | 尚未完成 |
| O11 | `NEXT.md:557-576` | MTP／vLLM 可能只換來低個位數收益且要換模型／重驗 → 不做 | benchmark＋成本判斷；2026-08-03 | PO 已定案；翻盤條件已記載 |
| O12 | `NEXT.md:646-670` | `MAX_ASYNC` 2→4 約 +28%，4→8 只 +4.6% 且延遲升高 → 採 4，不採 8 | 受控 benchmark；2026-08-03 | 已驗 live config；下次抽取才驗實際行使 |
| O13 | `NEXT.md:544-548` | 冷備份 → 只在資料庫內容指紋改變時停機備份；備援不走 notify 主路徑 | 排程實作；2026-08-03 | 已接排程；timer／OnFailure |
| O14 | `CLAUDE.md:361-418`; `NEXT.md:398-413` | 退役 v155 → 先確認單一 label、跨界關係為 0，再刪除；修正 20,873 是雙 workspace 總和 | 退役前後逐項量測；2026-08-03 | 已完成；歷史數字不可再當現況 |

## 已被推翻／過時：14 條

| ID | 出處 | 原先遇到什麼 → 舊判定 | 後來判定／理由 | 是否已清掉 |
|---|---|---|---|---|
| X01 | `NEXT.md:143-147,189-204` | `restated` 永遠不會被檢索命中 | 27 個中有 6 個被命中；一個反例即推翻全稱命題 | **未刪，已劃線保留** |
| X02 | `CLAUDE.md:586-590`; `NEXT.md:440-450` | v155 的 K Muffler 高 grounding 是概念→引用文獻 | v2 主要是符號→概念；`SYMBOLIC_RATIO=.35` 的邊界效應 | 舊結論仍在歷史文字中 |
| X03 | `NEXT.md:294-298` | 普通模型＋更長 context 應勝過高推理 | C 組高推理再提升約 10pp；推理貢獻不能假設較小 | 已明文標記推翻 |
| X04 | `NEXT.md:580-611` | gleaning 多半是重工／垃圾，可砍半 | 93.4% 是新候選，但證據仍不足以永久「不要砍」 | 已明文標記推翻 |
| X05 | `NEXT.md:525-532,681-686` | 固定 seed、temperature 0 應跨併發度逐字相同 | 實測 0/8；浮點批次組成改變會分岔；只有 c=1 可重現 | 已明文標記推翻 |
| X06 | `scripts/postprocess.py:6-8`; `docs/postprocess-workorder.md:647-666` | 修改 content_list 後會在建 IR 前自動生效 | 已索引文件會被 archive／continue 跳過，必須 reindex | **舊工單前提仍留著** |
| X07 | `docs/postprocess-workorder.md:719-726`; `scripts/pp/vlm.py:1-16,155-260` | 45%／97% recall gate 足以驗表格 | 召回率會讓錯表通過；改成 V8 負向控制與 V1–V12 | 工單寫有自我修正，但舊說法仍可被讀到 |
| X08 | `scripts/scan-partial.py:38-45`; `docs/judgement-flow.md:115-120` | 「被微分量不能又是 accent」→ 可把誤報歸零 | 會漏掉 N Flow 真錯；淨效果更差 | 已列為撤回規則 |
| X09 | `scripts/scan-partial.py:38-53` | 「分數對面有真 `\partial`」→ 可提高精度 | recall 僅 5.1%，因此撤回 | 已列為撤回規則 |
| X10 | `scripts/entity-merge.py:68-93`; `docs/judgement-flow.md:161-171` | 先去分隔符再斷詞 → 安全判定 `Eta_N/Eta_n` | 下標資訊被抹掉；改成原字串斷詞與 A/B/C 分層 | 舊版方法仍在演進說明中 |
| X11 | `scripts/scan-partial.py:14-20,338-352`; `NEXT.md:279-281` | 白名單可解決錯誤型別 | 白名單只是另一種枚舉；結構性規則才可持續 | **明文保留撤回史** |
| X12 | `CLAUDE.md:555-560`; `scripts/extract-check.py:49-60` | 未接地率高 → 大量幻覺 | 符號型 chunk 的字串驗證沒有鑑別力，必須三態 | 舊二態數字仍在歷史中 |
| X13 | `CLAUDE.md:277-279`; `scripts/pp/rules/chart_type.py:1-23` | 曾推測 `chart.img_path` 會污染索引 | 查實際 `_coerce_text` 後發現 chart 是空 fallback，問題是整個圖被丟失 | 已在鐵則中記錄修正 |
| X14 | `docs/postprocess-workorder.md:719-726`; `scripts/pp/vlm.py:180-209` | V12：alpha 或 numeric 任一分母不足就 `unverified` | 現行程式只用 alpha 作 V12；numeric 不足只讓 V6 不適用 | **未解決的文件／程式矛盾** |

## 三種特別問題

### 1. 同一裁決重複且措辭不一致

最明顯的是：

- `chart`：`CLAUDE.md:436` 說「只登記不處理」、同檔 `:508-511` 與 `chart_type.py` 卻定義 `chart→image`；`SKILL.md:199` 又說只有 1 份證據且脆弱。
- Canary：`CLAUDE.md:345-346` 列 8 個量；現行 `scripts/postprocess.py:179-197` 與 `tests/canary-baseline.json` 實際是 10 個，另含 `charts_convert/charts_dangling`。
- V12：`docs/postprocess-workorder.md:719-726` 與 `scripts/pp/vlm.py:180-209` 對 numeric 分母的處置不同。
- v155 的 entity fragmentation：`NEXT.md:722-725` 仍像是正式「不合併」裁決，但 `NEXT.md:499-502` 後來承認 v2 根本尚未量測。

### 2. 已推翻但舊文字仍未劃掉

需要優先處理：

- `NEXT.md:722-725` 的 388／254／51／8，後文已說這些只是 v155 證據，但原段沒有劃掉。
- `docs/postprocess-workorder.md` 的舊 V12 門檻。
- README 與舊工單中的 v155 備份、索引數字、修補生效前提。
- `NEXT.md:410-413` 的 20,873 關係數仍保留，但已說明它是雙 workspace 總和。
- 舊的「grounding 高就是幻覺」二態敘述仍可能被搜尋到。

### 3. 看似規則、其實可能只是巧合

- qwen 切錯列：只有 1 份文件，`NEXT.md:503-505` 已明確說不能升格。
- 首頁期刊資訊：只有 1 份文件，`NEXT.md:476-478`。
- `chart` 的「3 份穩」與 SKILL 的「1 份脆弱」互相矛盾。
- N Flow #1410 是單一方程式，不足以推出一般 equation 規則。
- `SYMBOL-1` 的 50 題只能判形狀，不能外推全庫比例；JSON 自己也明寫答案卷不是客觀真理。

## 是否值得做成結構化資料？

值得。75 條裁決已經超過散文可安全維護的規模，而且目前已有：

- 同一裁決多處重述；
- 明確的推翻關係；
- 模型綁定與文件領域綁定混在一起；
- repo 外 waiver provenance；
- 探針與裁決沒有一致對應；
- 文件與現行程式矛盾。

最小可用欄位建議是：

```json
{
  "id": "D02",
  "trigger": "header/footer repeated",
  "decision": "mute_preserve_sidecar",
  "reason": "self_ref is array-indexed",
  "scope": ["document_ingestion"],
  "status": "active",
  "category": "durable",
  "evidence": ["CLAUDE.md:275-276"],
  "evidence_count": 7,
  "decided_on": null,
  "probe_ids": ["canary.items", "canary.mute"],
  "model_binding": null,
  "supersedes": [],
  "superseded_by": [],
  "external_provenance": []
}
```

最少要有：

`id`、`trigger`、`decision`、`reason`、`scope`、`status/category`、`evidence[]`、`evidence_count`、`decided_on`、`probe_ids`、`model_binding`、`supersedes/superseded_by`、`external_provenance`。

逐題測試結果應另存為 `case_evidence`，不要直接混進 precedent table。這輪沒有修改任何檔案。