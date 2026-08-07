---
type: project_topic
status: active
summary: "驗證容器自動復原時，兩種最直覺的殺法都不會觸發重啟——而失敗的樣子跟「策略壞掉」一模一樣，很容易誤判成事故。"
tags: [docker, 驗證方法, 自動復原, 假警報]
contains: [lesson, procedure]
created: "2026-08-07"
updated: "2026-08-07"
related: []
authoring_mode: ai_generated
---

# 測試 restart policy：兩種直覺的殺法都是錯的

## 形成背景

2026-08-07 重建後要驗「當機或重開機之後系統會不會自己回來」。三個容器都設了
`restart: unless-stopped`，但**設了不等於會動**——這個專案的核心紀律就是不接受
「設定看起來對」當證據。

真的重開 dker 會打斷別人的九個容器（dockge、roon、backrest、samba、nginx、
rustdesk、vibevoice…），所以要在不重開的前提下驗。

## 當前結論

**兩種直覺的殺法都不會觸發重啟，而且失敗的畫面跟「策略壞掉」完全一樣。**

| 做法 | 結果 | 為什麼 |
|---|---|---|
| `docker kill <容器>` | ❌ 不重啟 | Docker 把它算成**使用者明確停止**，而 `unless-stopped` 的定義就是「除非被明確停止」。daemon log 會寫 `stopping restart-manager` |
| 在容器內 `kill -9 1` | ❌ 什麼都沒發生 | 核心對 PID namespace 的 **PID 1 忽略來自同一 namespace 的 SIGKILL**（除非它自己裝了 handler） |
| **從宿主殺容器主程序** | ✅ 重啟 | 不在容器的 namespace 裡，是真正的當機模擬 |

正確做法：

```bash
pid=$(docker inspect <容器> --format '{{.State.Pid}}')
sudo kill -9 "$pid"
# 等 10–15 秒，然後看 RestartCount 有沒有從 0 變 1
docker inspect <容器> --format '{{.State.Status}} {{.RestartCount}}'
```

**判準是 `RestartCount` 增加**，不是「狀態是 running」——狀態可能只是還沒死透。

不重開機也能涵蓋整條路徑，把三件事分開驗即可：

1. `systemctl is-enabled docker containerd` → 開機時 daemon 會不會起
2. 每個容器的 `HostConfig.RestartPolicy.Name` → daemon 起來後容器會不會跟著起
3. 從宿主殺主程序 → 策略是不是真的會動

## 教訓

**「驗證方法本身也會失敗，而且失敗的樣子跟被驗的東西壞掉一模一樣。」**

這次前兩種殺法都讓我看到「容器沒回來」，第一次我甚至寫下「restart policy 設了卻
沒生效，系統不會自己復原」——**那是假警報**。真正的原因是我用的工具在那個情境下
按設計就不該觸發重啟。

差別在哪裡被抓到：**去看 daemon 的 log**（`journalctl -u docker`），它寫著
`stopping restart-manager`——那句話說的是「有人叫我別重啟」，不是「我試了但失敗」。
**沒有那行 log，這個誤判會一路寫進文件。**

與鐵則第 4 條同族：「先查輸入，再查偵測器，最後才查模型。」這裡的偵測器就是殺法
本身。看到紅燈先問「我的測法對嗎」，比先問「東西壞了嗎」更常命中。

## 更正：分開驗**不能**取代重開機（2026-08-07 當天推翻）

本文最初的結論是「把三件分開驗就夠了，不必真的重開機」。**同一天 PO 授權後真的重開，
那個結論被推翻。**

殺程序測試通過（`RestartCount` 0→1），但重開機**失敗**：

```
failed to bind host port 100.87.88.7:9621/tcp: cannot assign requested address
```

開機時 docker 比 tailscale 早起，而容器綁的是 Tailscale 位址。**綁定失敗發生在容器
啟動階段，不是程序死亡**——restart policy 對它無效（`RestartCount` 停在 0）。

**殺程序測不到這個，因為那時網路早就好了。** 兩種測試驗的是不同的東西：

| 測法 | 驗到什麼 | 測不到什麼 |
|---|---|---|
| 從宿主殺主程序 | 程序死掉後會不會被拉回來 | **啟動階段的依賴**（網路、掛載、其他服務） |
| 真的重開機 | 整條開機路徑 | — |

**教訓（比原本那條更重要）**：「把大測試拆成幾個小測試」時，要問**拆掉的縫裡有什麼**。
這次拆掉的縫正好就是缺陷所在——開機順序。分開驗每一件都通過，合起來卻是壞的。

## 修法與驗證（2026-08-08 完成）

`lightrag-stack.service`：`After=docker.service tailscaled.service`，加一段
`ExecStartPre` **自己等位址真的出現在某張介面上**（最多 120 秒）——`After=` 只保證
那個 unit 起了，不保證位址已指派，那正是原本失敗的那條縫。

第二次重開機實測，**零人工介入**：

```
lightrag-stack.service   active (exited)
  ExecStartPre           status=0/SUCCESS   ← 等到位址了
  ExecStart              status=0/SUCCESS
容器                     12 / 12 running
埠                       9621 → 100.87.88.7:9621、9700 → 100.87.88.7:9700
資料                     節點 1,239、邊 1,995
端點                     全通
```

**判準是「重開之後不碰它，服務自己好」**，不是「重開之後我修好了」。

## 未決

- 「`docker compose ps` 顯示 running 但 `docker port` 是空的」這個狀態**沒有任何檢查
  會發現**。它看起來完全正常，而外面連不上——我被騙過一次。要驗服務活著，
  判準必須是「打得到端點」，不是「容器在跑」。
- 失敗的容器要 `docker compose up -d --force-recreate` 才救得回來，單純 `up -d`
  只是 Starting 它，埠不會綁回來。
