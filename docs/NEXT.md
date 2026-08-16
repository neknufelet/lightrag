---
title: NEXT — 接下來做什麼
date_created: 2026-06-20
date_modified: 2026-08-16
status: living
kind: sop
supersedes: ""
superseded_by: ""
summary: "待辦清單。一條一行、動詞開頭，箭頭後面是完成的判準。理由外引。"
---

# NEXT — 接下來做什麼

做完的**刪整行**。`→` 後面是「怎麼知道做完了」，寫不出來的不算待辦。理由外引：
知道但不做 → [KNOWN_ISSUES](KNOWN_ISSUES.md)；裁決 → [decisions/](decisions/)；
發生過的事 → [cairn/LOG.md](../cairn/LOG.md)。**現在的狀態不寫在這裡** —— 跑
`scripts/compat-check.py`，或看 `/data/lightrag/checks/latest.json`（每天 08:30 寫的）。
> 2026-08-16 從 666 行壓回來：刪掉已完成的、隨舊庫退休而作廢的、不是待辦的（搬進 KNOWN_ISSUES）。

## 新庫重建（設計見 [rebuild-v3-design](rebuild-v3-design-20260816.md)）
- ⬜ 進料台接拆章：讀目錄 → 提方案 → 人勾掉不要的 → 才切才解析　→ 一本學位論文走得完
- ⬜ 切章工具的前言／附錄關鍵字加英文　→ `Preface`／`Appendix`／`Index` 認得出來
- ⬜ 消音改走確認清單：規則只做確定的，其餘預先勾好　→ 清單存檔、重抽沿用
- ⬜ 定確認清單的介面與存檔格式　→ 寫進設計文件
- ⬜ 三個 skill 改網址與 workspace　→ 新庫獨立
- ⬜ `mount-guard`／`backup-cold.sh` 加上新 stack　→ 新庫也被守著、也有備份
- ⬜ 決定新 workspace 叫什麼　→ 建好之後改要動 13 張表，現在改免費

## 會說謊的地方
- ⬜ 簿記說 indexed、知識庫卻沒那一列　→ 每日體檢對帳三個來源並**印出名字**
- ⬜ 收件匣空著時每次開審核台都警告　→ 空的是正常狀態，不該叫
- ⬜ 十二道閘門有十道零呼叫點　→ 接回去／刪掉／標記，三選一
- ⬜ `pp/judge.py` 的表格裁判零呼叫點　→ 同上
- ⬜ 「存在的腳本沒人叫」沒有守衛　→ 反方向有守，這一向沒有
- ⬜ `compat-check` 的 A-38 沒有 `ZOTERO_API_KEY` 時「這條沒跑」被算成 soft 不過　→ 分得出「驗不了」
- ⬜ 體檢表八格還有四格沒有寫手　→ 有寫手，或明講這一輪不做

## 資料與備份
- ⬜ **走一次還原**（停掉、換回目錄、啟動）　→ 確認可行（見 [backup-design](backup-design.md)）
- ⬜ `backup-cold.sh` 的指紋只看資料庫　→ 改完解析結果也會備份
- ⬜ `kbapi` 不理 SIGTERM 被硬砍　→ 停機窗從 66 秒降到約 6 秒
- ⬜ 關掉 backrest 備份 `/data/rag` 的排程（已廢除，ADR-0003）
- ⬜ backrest 掛了整個 `/data`，硬碟不見時看得到空目錄　→ 確認會不會覆蓋好備份

## 規則與模型
- ⬜ 眼睛 A 沿用抽取模型時要出一聲　→ 換模型忘了設 `PP_EYE_A_*` 時看得到
- ⬜ 眼睛 A 指向 OpenRouter 時補 `PP_EYE_A_PROVIDER`
- ⬜ `latex_fix.fix_partial` 與 `scan-partial --repair` 合成一條
- ⬜ 裁圖改逐頁換算　→ 「頁面尺寸一致」這條規則可以整條拿掉
- ⬜ 把「判準會隨解析結果變動」寫進 [hard-rules](hard-rules.md)
- ⬜ 決定 V5–V12 哪幾道接回來（現在驗不了：全語料只剩 1 張可修補表格）
- ⬜ 決定縮寫變體要不要處理（`(MPP)`／`(HR)`）
- ⬜ 決定 `region`／`zone`／`mode`／`model`／`part` 那 27 個節點刪不刪
- ⬜ 新文件進來不會自動登記來源　→ intake 放行時寫進登記檔
- ⬜ 補一份 DeepSeek 的 ADR（決定早就做了，只是沒落成文件）

## 進料台
- ⬜ `submit_reset` 的「忙碌中」守衛拿掉　→ 進料期間重置得了
- ⬜ 放行與重抽搶用 `inputs/<ws>` 當暫存區　→ 不共用，或至少有鎖
- ⬜ `health.running` 在整批抽取時是 False　→ 欄位語意與實際相符

## 秘密與外部依賴
- ⬜ 寫 `rotate-secret.sh`　→ 換秘密不必開編輯器
- ⬜ 更換 `LIGHTRAG_API_KEY` 與 `POSTGRES_PASSWORD`　→ 舊值失效、服務起得來
- ⬜ 審核台加「外部依賴」分頁　→ MinerU 到期日、各家餘額看得到

## 上游畢業（standards）
- ⬜ 七條新通則上升（BASELINE 2.0.0）：秘密不經過輸出／部署機落後要有人守／文件不寫死可量
  測的數字／檢查結果要帶版本／寫好的檢查沒被呼叫等於沒寫／改 A 讓 B 安靜失效的相依要有人守／**有權威來源時不得自己重算**
- ⬜ **第八條候選：檢查上線前要證明它分得出東西**（血淚：`parse-check` 的 WARN 佔 283/317）
- 🟡 觀察（執行者「沒有人」，不得寫成條文）**鬧鐘不能代替脈絡**：想加檢查前先問「那人動手
  那一刻看到這句話還會出事嗎」。⇒ 機器判得出且誤判便宜 → hook 擋；誤判貴 → 只警告；判不出 → 收尾 skill。
- ⬜ `test_next_done_ratio.py` 進 `PROJECT_TEMPLATE/`；修上游 `self-check.py` 的 `dead_refs`
- ⬜ 「不可再生／唯一副本」這類描述性標籤要有執行者

## 型別註解的欠帳（棘輪，清完一個刪一行；清單在 `ruff.toml`）
- ⬜ 既有欠帳 102 處：`postprocess.py` 18／`kbapi.py` 17／`entity-merge.py` 14／測試檔 32／
  `pp/crosscheck.py` 8／`parse-check.py` 5／`pp/rules/latex_fix.py` 4／其餘各 1–2
- ⬜ `pp/oracle.py`／`pp/eyes.py`／`mineru_common.py` 要先決定 `json.loads` 回傳型別
  （`Json` 別名還是 `object`）——**那是設計選擇不是打字**，不要在補註解時順手做掉
