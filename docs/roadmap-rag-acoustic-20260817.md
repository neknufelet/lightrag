# 路標：走到「新庫 `rag_acoustic` 上線，PO 可以直接開始測試」

**PO 2026-08-17 晚上裁完 16 條。這份是把那些答案排成順序，不是新的提案。**
每一步後面那行是「怎麼證明做完了」——沒有那一行的步驟不算步驟。

## 終點長什麼樣

> 新庫是一個**完全空的**知識庫，跟舊的沒有任何共用。PO 用 Zotero 外掛
> 自己送文件進去，送一份、確認一份、放行一份。

⚠ **不是「我灌好一批給你」。** PO 原話：「我要從 zotero 跑乾淨的」。
我的工作是把管線修好、證明它走得通，然後**交出一個空的**。

---

## PO 裁的（16 條，2026-08-17 晚）

| # | 問的是什麼 | 裁決 |
|---|---|---|
| 1 | 「可以開始測試」是什麼 | 我先用 **3 篇**驗證整條線能走到「有內容可以問」，**然後交一個空庫** |
| 2 | ~~新舊並存嗎~~ | **作廢** —— 見第 12 條 |
| 3 | 317 份要不要再花 MinerU 的錢 | **要，全部重新解析**（不沿用備份） |
| 4 | backrest 那兩個排程 | **改成指向新庫** |
| 5 | 從 Zotero 怎麼進來 | **走現有的 Zotero 外掛**（0.3.5，在 `zotero-plugin/`） |
| 6 | 3 篇驗證時確認清單還沒做 | **用規則的預設值直接放行**；要點畫面的話 Playwright 可以 |
| 7 | 「清空」清到什麼程度 | **全空。pure。** |
| 8 | MinerU token 9/4 到期要不要先換 | **不急，照現在的用** |
| 9 | 零重疊做到哪一層 | **整組自己的**——見下方「零重疊清單」 |
| 10 | 外掛那個已知問題 | **上線前先修**（`KI-016`） |
| 11 | 驗證的 3 篇誰挑 | **PO 自己挑** |
| 12 | 舊庫怎麼辦 | **全移除。** PO 原話：「他媽全移除掉比較快」 |
| 13 | 先修外掛還是先刪庫 | **先修外掛** —— 沒修之前送出來的可能是中文翻譯本，那 3 篇白驗 |
| 14 | 確認清單畫面排哪裡 | **PO 開始灌之前要做好** —— 先抽再確認等於花兩次錢 |
| 15 | models 那 6.4 GB | **刪之前先複製出來**（那是上游下載的權重，不是舊庫的東西） |
| 16 | 「乾淨」怎麼證明 | **寫一支檢查，數字必須是 0**，不是列清單給人看 |

### ⚠ 第 12 條是 PO 當場改的

原本第 2 條裁的是「新舊一起跑、觀察幾天再拔」。看到**資料庫的使用者到今天
還叫 `deeptutor`** 之後改成全移除：

```
$ docker exec lightrag-postgres psql -U deeptutor -d lightrag -tAc \
    "select current_user, current_database()"
deeptutor|lightrag
```

PO 原話：「之前從 deeptutor 拔過來就說乾淨了結果裡面一堆沿用。」
**這一格就是證據**，不是抱怨。

---

## 零重疊清單（第 9 條的具體內容）

先量了現況才知道要複製幾樣。dker 實測 2026-08-17：

```
$ docker ps --filter label=com.docker.compose.project=lightrag --format "{{.Names}}\t{{.Ports}}"
lightrag-acoustics_v2   100.87.88.7:9621->9621/tcp
kbapi-acoustics_v2      100.87.88.7:9700->9700/tcp
lightrag-postgres       5432/tcp
lightrag-infinity       100.87.88.7:7997->7997/tcp

$ systemctl list-units --type=service --all 'lightrag*' --no-pager --no-legend
lightrag-cold-backup / daily-check / intake / mount-guard / stack     ← 5 個

$ grep -cE '^[A-Za-z_][A-Za-z0-9_]*=' /opt/stacks/lightrag/.env
73
```

| 東西 | 舊的 | 新的 |
|---|---|---|
| 資料根 | `/data/lightrag` | `/data/rag_acoustic` |
| 資料庫 | `lightrag` | `rag_acoustic` |
| **資料庫使用者** | **`deeptutor`** ← 沿用的證據 | `rag_acoustic` |
| Postgres 容器 | `lightrag-postgres` | 新的一個 |
| 其餘容器 | 3 個 | 各自新的 |
| `.env` | `/opt/stacks/lightrag/.env`（73 鍵） | 新的一份 |
| systemd | 5 個 | 各自新的 |
| models | `/data/lightrag/models` 6.4 GB | 複製一份過去 |

**埠沿用同樣的號碼**（9621／9700／7997／9710）—— 舊的整組刪掉之後那些埠是空的，
記兩套號碼只會多一個出錯的地方。⚠ 這一條我自己決定的，不同意就講。

⚠ 磁碟不是限制：`/data` 234 GB，現在只用 13 GB。

---

## 順序

### 1. 修外掛那個已知問題（`KI-016`）
對 PDF 附件那一列按送出會繞過選片規則，中文翻譯本會被直接送進庫。
**它的失敗方式是安靜的**——送進去的當下不會有任何訊號。
　證明：外掛那 50 條測試全綠（在 coder 跑，dker 沒有 node）。

### 2. 確認清單剩下三層
順序照上一場拆章那條抄：**存檔格式 → 畫面 → 接線**。
存檔的形狀已經比對完，抄 `scripts/chapters/split_record.py`
（提案寫在 `docs/confirm-list-design-20260817.md`，PO 未裁）。
　證明：真資料上跑得出清單，人勾完存得下來、關掉再開接得回去。

⚠ **這一步要在刪舊庫之前做完**——舊庫那 317 份是唯一的真資料，刪了就沒得測。

### 3. 把 models 複製出來
　證明：新位置的檔案數與大小跟舊的一致。

### 4. 全移除舊庫
容器、資料庫、`/data/lightrag` 整個目錄、5 個 systemd unit。
　證明：`docker ps -a` 沒有 `*acoustics_v2`；`psql -l` 沒有 `lightrag`；
　`/data/lightrag` 不存在。

### 5. 建新的一整套
　證明：新容器健康檢查過、`psql` 連得上、`current_user` 是 `rag_acoustic`。

### 6. 「沒沾到舊東西」的檢查
把新庫可能沾到舊東西的每一個地方列出來，數字必須是 **0**。
　證明：那支檢查跑出來是 0，而且**以後隨時能重跑**（第 16 條要的就是這個）。

### 7. PO 挑 3 篇，用外掛送進來
走完整條線：外掛 → 收件匣 → 解析 → 確認清單 → 抽取 → 查得到。
　證明：那 3 篇真的能被問出東西來。

### 8. 清回全空
含 `work/parsed`。⚠ **不清的話，同一份 PDF 再送會命中快取、悄悄跳過解析**
（`zotero-sync.py` 血淚第 7 條）——那就不叫乾淨了。
　證明：第 6 步那支檢查再跑一次，還是 0；庫裡 0 份文件。

### 9. 交給 PO，他開始灌

### 10. backrest 那兩個排程改指向新庫
　證明：排程指到新路徑，且跑得出一次成功的備份。

---

## 明講的代價（都是 PO 裁的，寫在這裡是為了以後不用重吵）

**一、從第 4 步到第 9 步，完全沒有知識庫可以查。** 三個查詢 skill 都會斷。
這是選「全移除」而不是「並存」的代價，PO 知道。

**二、語料沒有查過就刪。** 刪 `/data/lightrag` 會連 733 MB、320 份 PDF 一起刪。
要證明「Zotero 真的都有」需要 `ZOTERO_API_KEY`，而那把鑰匙不在 `.env` 裡
（體檢表 A-38 到今天都是「這條沒跑」）。**PO 裁定不查、直接刪**，理由是
「Zotero 應該是用外掛直接送，檔案裡面都有」。
⇒ **這一條萬一錯了就是真的丟東西**，其餘都補得回來。

**三、其餘確認過補得回來**：

```
$ ssh florian-dker 'cd /data/lightrag/work/crops && find */verified -type f | sort' > /tmp/dker.txt
$ cd verdicts/work/crops && find */verified -type f | sort > /tmp/repo.txt
$ comm -23 /tmp/dker.txt /tmp/repo.txt        # dker 有而 repo 沒有的
（沒有輸出）                                   # 178 個人工裁定全在 git

$ .venv/bin/python scripts/pull-verdicts.py
ledger：新增 0、更新 0、沒變 317、repo 才有 5   # 體檢表 317 份逐檔一致
```

**四、全部重新解析要花 MinerU 的錢與時間。** 320 份，實測單份約 6 秒的是
「算計畫」不是「解析」；解析是雲端來回，`parse-only.py` 自己的註解寫 1–2 分/份
⇒ 粗估 5–10 小時。**這個時間沒有實測過（未驗,推測）。**
⚠ MinerU 的 token 2026-09-04 到期，今天 8/17。PO 裁定不先換。

**五、舊庫的圖譜刪掉就沒了。** 重建要花 DeepSeek 的抽取費。

---

## 還沒決定的

- 確認清單的**存檔格式**還是提案（`docs/confirm-list-design-20260817.md`），
  第 2 步開始之前要裁。
- 清單那一頁的網址、審核台上「還有 N 份要確認」那個入口放哪一格。
- 「兩隻眼睛先幫你勾好」PO 說「也不錯」＝方向認可，**時機未裁**。
  建議排在人工那條路走通之後，因為它花錢。
- `rebuild-v3-design-20260816.md` 那 12 條裡，跟品質量測相關的 6 條都還沒裁
  （體檢表補幾格、檢索品質這輪量不量⋯⋯）。這些不擋上線。
