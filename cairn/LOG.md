# Project Cairn 流水帳

本檔以逆時序記錄實質進展 —— 最新的一則放最上面、緊接在這一行下方。每則保持簡短：
只放摘要與指標，結論沉澱進 `cairn/<topic>.md`。

## 2026-08-04 · 七條跨專案知識畢業到 Obsidian

- 畢業 7 條 + 1 份索引到 `42_Cairn/lightrag/`，走 WebDAV 直寫，全部逐位元回讀驗證。
- 條目：乾淨的 0 要先當成量錯／先查輸入再查偵測器／探針要在沒人問的時候會響／
  門檻用量的不要用調的／認結構不認字元／對帳要問跑著的系統／設定只活在一台機器上。
- 索引開頭寫明它們是同一件事的七個面：**畫面說的跟實際發生的不一致，而且都不報錯。**
- 前四條來自 `CLAUDE.md` 的鐵則，後三條是 2026-08-04 這一輪長出來的
  （commit `c94d2fe`、`269653b`＋`2e7e2bb`、`42c73ef`＋`5dca4c8`）。
- **上傳時真的踩到自己寫的那條**：〈乾淨的 0〉那篇 PUT 回 `000`——不是 HTTP 碼，
  是 curl 因檔名含空格未編碼而根本沒送出。七個 201 配一個 000，看起來像「大致成功」。
  修 URL 編碼後重驗，八個全 200。

## 2026-08-04 · Project Cairn 初始化

- 初始化 Project Cairn 結構：`AGENTS.md`、`.cairn/config.yaml`、`cairn/LOG.md`。
- 歷史遷移模式：`selective_migrate`。**既有的 4,031 行文件不搬進 `cairn/`** ——
  `docs/precedents-inventory-20260804.md` 已把裁決盤點成 75 條，但抽驗 5 條錯 3 條，
  它自己的結論就是「不能自動匯入」。selective 的範圍只有「跨專案可複用的七條直接畢業」。
- 兩個獨立審查（codex luna xhigh、deepseek v4-pro）都判 **C：只遷移最高信心子集**。
  luna 另外指出 cairn 補的是「agent 查知識」的消費者，**不是「程式查先例表」的消費者**，
  混為一談會產生假完成感 —— 所以機器可讀的先例表仍是未做的事，不因 cairn 落地而消失。
- Obsidian provider 走 **WebDAV 直寫**（vault 在 NAS、本機無掛載亦無 obsidian CLI）。
- 細節見 `AGENTS.md` 與 `.cairn/config.yaml`。
