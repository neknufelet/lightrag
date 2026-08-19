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
| 4 | backrest 那兩個排程 | **改成指向新庫** ⚠ 見下方「第 4 條要先分清楚是誰的」 |
| 5 | 從 Zotero 怎麼進來 | **走現有的 Zotero 外掛**（0.3.5，在 `zotero-plugin/`） |
| 6 | ~~3 篇驗證時確認清單還沒做~~ | **前提作廢** —— 第 14 條把清單排在刪庫之前，走到第 7 步時它已經做好了。3 篇**照正式流程走**，不用預設值放行 |
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
| 17 | 新資料根放哪顆碟 | **同一顆**（`sda1`）。`/data/lightrag` **整顆清乾淨**，路徑不變；卸載後重新掛回來也可以 |
| 18 | 確認清單要不要跟刪庫解耦 | **不要。先做完確認清單、確定沒事，才刪庫** |

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

### ⚠ 第 4 條要先分清楚是誰的排程

PO 今晚裁「改成指向新庫」，但既有紀錄講的是另外兩件事：CLAUDE.md 與
`docs/NEXT.md` 記著 PO 早就說「要**關**」；`KI-002` 記著其中的 `rag-snapshot`
**是 DeepTutor 的庫、不歸本專案處置**（而它指的路徑實測已不存在）。

⇒ 三份陳述現在互相打架。**做之前要先確認哪個排程是誰的**，不要兩個都指向新庫
——那會變成同一份資料 4 小時、6 小時各備份一次。

⚠ 這一段的排程細節（路徑、頻率）是第二雙眼睛 8/18 讀 backrest 設定查到的，
**我自己沒能重驗**（讀那份設定要 sudo，我這邊拿不到）`(未驗)`。

---

## 零重疊清單（第 9 條的具體內容）

先量了現況才知道要複製幾樣。dker 實測 2026-08-17：

```
$ docker ps --filter label=com.docker.compose.project=lightrag --format "{{.Names}}\t{{.Ports}}"
lightrag-acoustics_v2   100.87.88.7:9621->9621/tcp
kbapi-acoustics_v2      100.87.88.7:9700->9700/tcp
lightrag-postgres       5432/tcp
lightrag-infinity       100.87.88.7:7997->7997/tcp

$ systemctl list-unit-files 'lightrag*' --no-pager --no-legend
lightrag-cold-backup.service   lightrag-daily-check.service
lightrag-intake.service        lightrag-mount-guard.service
lightrag-stack.service
lightrag-cold-backup.timer     lightrag-daily-check.timer            ← 7 個，不是 5 個

$ grep -cE '^[A-Za-z_][A-Za-z0-9_]*=' /opt/stacks/lightrag/.env
73
```

| 東西 | 舊的 | 新的 |
|---|---|---|
| 資料根 | `/data/lightrag`（一顆 916 GB 外接碟） | **同一顆碟、同一個路徑，內容整個清掉**（裁決 17） |
| 資料庫 | `lightrag` | `rag_acoustic` |
| **資料庫使用者** | **`deeptutor`** ← 沿用的證據 | `rag_acoustic` |
| Postgres 容器 | `lightrag-postgres` | 新的一個 |
| 其餘容器 | 3 個 | 各自新的 |
| `.env` | `/opt/stacks/lightrag/.env`（73 鍵） | 新的一份 |
| systemd | **7 個**（5 service ＋ 2 timer） | 各自新的 |
| models | `/data/lightrag/models` 6.4 GB | 複製一份過去 |
| **三個查詢 skill** | `~/.claude/skills/lightrag-{search,fetch,images}/`，寫死 `9700` 與 `acoustics_v2` | 改掉 |
| **`scripts/zotero-sync.py`** | 寫死 `KBAPI` 與 `--workspace acoustics_v2` | 改掉 |
| **fstab／mount-guard／資料根記號檔** | 為「USB 碟會被拔走」設計的一整套 | 見下 |
| **`.env` 的 symlink** | dker 的 repo 根指向 `/opt/stacks/lightrag/.env` | 改指 |
| **寫死路徑的腳本** | repo 裡 11 支寫著 `/data/lightrag` | 見下 |
| **Dockge stack 名／compose label** | `lightrag` | 換名字 |

⚠ **`systemctl list-units --type=service` 天生數不到 timer** —— 這份文件第一版
因此寫成 5 個。要數 unit 用 `list-unit-files`。**只刪 5 個 service 的話，
兩個 timer 每天照響**，對著已經不存在的東西失敗。

⚠ **寫死路徑那條，裁決 17 之後反而變簡單了**：資料根維持 `/data/lightrag`，
所以 `pp/paths.py` 的 `DEFAULT_DATA_ROOT` 與那 11 支腳本**不用改**，
也就沒有「哪一支忘了改就靜靜用回舊路徑」的風險——因為沒有舊路徑了，
碟上是空的。
⇒ 相對地，**第 6 步那支檢查不能拿路徑當判準**，要改成
「碟上舊內容 0 個」＋「舊 workspace `acoustics_v2` 與舊使用者 `deeptutor`
在跑著的設定、unit 檔、compose、三個查詢 skill 裡出現 0 次」。

⚠ **查詢 skill 那條會安靜地騙人**：`lightrag-search` 的說明自己寫著
「search 端點不看網址裡的 workspace」——埠沿用之後，它會**查到新庫卻自稱在查
`acoustics_v2`**。`fetch` 與 `images` 會 400（大聲，反而安全）。

**埠沿用同樣的號碼**（9621／9700／7997／9710）—— 舊的整組刪掉之後那些埠是空的。
**PO 2026-08-19 點頭：「新的也要用同一組」。**
⚠ **但沿用埠正是上一條會出事的原因**，所以三個 skill 一定要跟著改，
不能靠「新庫還沒起來所以查不到」保護。

### ⚠ 磁碟那句話我量錯了檔案系統

```
$ ssh florian-dker 'findmnt /data/lightrag'
TARGET         SOURCE    FSTYPE OPTIONS
/data/lightrag /dev/sda1 ext4   rw,noatime,errors=remount-ro

$ df -h /data /data/lightrag
/dev/nvme1n1p1  234G   13G  209G   6% /data
/dev/sda1       916G   12G  858G   2% /data/lightrag
```

**`/data/lightrag` 不是一個目錄，是一顆 916 GB 外接碟的掛載點。**
這份文件第一版寫「`/data` 234 GB 只用 13 GB」——那量的是 nvme，舊庫根本不在上面。

**PO 裁決 17：同一顆碟、同一個路徑、內容整個清掉。**
原話：「原本那顆不行嗎 data/lightrag 直接清乾淨 你要移除再重新掛載也可以。」

那顆碟上**只有本專案的東西**，實查過：

```
$ ssh florian-dker 'ls /data/lightrag/'
checks  inbox  inputs  intake  library  models  postgres  rag_storage  records  work

$ grep -rl "/data/lightrag" /opt/stacks/ | grep -v '^/opt/stacks/lightrag'
（沒有輸出）                                    ← 別的 stack 沒有掛它

$ docker ps -a --format '{{.Names}}' | while read n; do \
    docker inspect "$n" --format '{{range .Mounts}}{{.Source}} {{end}}' \
    | grep -q /data/lightrag && echo "  $n"; done
  lightrag-acoustics_v2  kbapi-acoustics_v2  lightrag-postgres  lightrag-infinity
```

⇒ 掛著它的四個容器全部是本專案的，**整顆清掉不會動到別人**
（dockge、backrest、roonserver、samba 那些都不在上面）。

⚠ 但「刪掉目錄」這個講法還是要改掉：**要清的是碟的內容**，
而不是那個掛載點目錄本身。乾淨程度由強到弱有兩條路——
umount ＋ 重新格式化（連檔案系統都是新的，最好證明），
或掛著的時候把裡面的東西刪光。**PO 說重新掛載也可以，所以走格式化那條。**
　證明：碟掛回來之後 `ls -A /data/lightrag` 沒有輸出、`df` 顯示用量近乎 0。

---

## 順序

### 1. 修外掛那個已知問題（`KI-016`）
對 PDF 附件那一列按送出會繞過選片規則，中文翻譯本會被直接送進庫。
**它的失敗方式是安靜的**——送進去的當下不會有任何訊號。

⚠ **原本寫的判準「那 50 條測試全綠」證明不了任何事。** 第二雙眼睛 8/18 在
**bug 還沒修**的現狀下實跑，`tests 50 / pass 50 / fail 0` —— 因為那個 bug 在
`zotero-plugin/bootstrap.js` 的 `sendOne()`，而測試檔第一行自己寫著
「檔名是這個外掛裡唯一測得到的部分」。**照舊判準，今天就可以宣稱做完。**

　證明改成：**`KI-016` 那條路徑有一條新測試**，且該測試在修之前是紅的。
　做法上多半要把選片判斷從 `bootstrap.js` 搬進 `lib/` 才測得到。
　（在 coder 跑，dker 沒有 node。）

### 2. 確認清單剩下三層
順序照上一場拆章那條抄：**存檔格式 → 畫面 → 接線**。
存檔的形狀已經比對完，抄 `scripts/chapters/split_record.py`
（提案寫在 `docs/confirm-list-design-20260817.md`，PO 未裁）。
　證明：真資料上跑得出清單，人勾完存得下來、關掉再開接得回去。

⚠ **這一步要在刪舊庫之前做完**——舊庫那 317 份是唯一的真資料，刪了就沒得測。

⚠ **但那句話只對一半，第二雙眼睛 8/18 指出三點：**

1. 那 317 份**全部 apply 過**（317/317 有 `backup/`）。拿它們測清單，
   **機制測得到，內容有系統性偏差** —— 就是這份設計文件自己說的
   「在已經掃過的地板上數灰塵」。
2. **50 份的計畫缺 `title`／`refs` 段**（`docs/NEXT.md` 記著），
   所以「真資料上跑得出清單」這個判準在那 50 份上會打折。
3. **可以解耦**：把 `work/` 那 2.6 GB 抄一份到別的碟（nvme 還有 209 GB），
   第 2 步就不必卡在刪庫之前。
   ⇒ 現在的寫法讓「全移除」被一個畫面功能擋住，而 MinerU 的 token 9/4 到期
   正在倒數。**要不要解耦，PO 裁。**

### 3. 把 models 複製出來
　證明：新位置的檔案數與大小跟舊的一致。

### 3.5 先把 `records/` 與 `checks/` 保住
**336 個檔不在 git**（`records/` 194 個 ＋ `checks/` 全部 142 個），
證據與逐目錄清單在 `docs/clean-cut-rag-acoustic-20260817.md`。
共 38 MB，整包搬走或進版控是一分鐘的事。
⚠ **這些是不是垃圾要 PO 裁**，但在裁之前不能當成「反正在 git」刪掉。
　證明：搬完之後 `comm` 比對，不在新位置的是 0 個。

### 3.6 先確認備份真的能還原
`backrest` 對舊資料根有排程、`cold-backup` 也把整個資料根抄進 restic
`(未驗，第二雙眼睛查到的)`。**在「全移除」這個世界裡，那是唯一的退路。**
⚠ `docs/NEXT.md` 記著「走一次還原」從來沒做過。
　證明：實際列一次快照、抽一個檔還原出來。唯讀、免費。

### 4. 全移除舊庫
容器、資料庫、`/data/lightrag` 這顆碟、**7 個** systemd unit（含 2 個 timer）。

⚠ **`/data/lightrag` 是掛載點不是目錄**（見上方「磁碟那句話我量錯了」）。
「刪目錄」要 umount ＋ 改 `/etc/fstab`，否則重開機空碟又掛回來。

　證明：`docker ps -a` 沒有 `*acoustics_v2`；`psql -l` 沒有 `lightrag`；
　`systemctl list-unit-files 'lightrag*'` 沒有輸出（**不是** `list-units`，
　那個數不到 timer）；`lsblk` 上 `sda1` 沒有掛在任何地方，`/etc/fstab` 沒有它。

### 4.5 backrest 當場處理，不要拖到最後
⚠ **原本排在第 10 步是錯位。** `docs/clean-cut-rag-acoustic-20260817.md`
自己寫著「backrest 在硬碟不見時會怎樣——**這條在拔舊庫之前一定要弄清楚**」，
而這份路標第一版把那句掉了。

不當場處理的後果：排程對著不存在的路徑跑；更糟的是**第 9 步之後 PO 灌進去的
新資料，在第 10 步做完之前完全沒有備份**。
　證明：舊排程停掉或改指，新資料根跑得出一次成功的備份。

### 5. 建新的一整套
　證明：新容器健康檢查過、`psql` 連得上、`current_user` 是 `rag_acoustic`。

### 6. 「沒沾到舊東西」的檢查
把新庫可能沾到舊東西的每一個地方列出來，數字必須是 **0**。
至少要涵蓋上面「零重疊清單」那張表的每一列，**特別是**：
舊路徑 `/data/lightrag`、舊 workspace `acoustics_v2`、舊使用者 `deeptutor`
在跑著的設定、unit 檔、compose、三個查詢 skill 裡各出現 0 次。
　證明：那支檢查跑出來是 0，而且**以後隨時能重跑**（第 16 條要的就是這個）。

### 7. PO 挑 3 篇，用外掛送進來
走完整條線：外掛 → 收件匣 → 解析 → 確認清單 → 抽取 → 查得到。
　證明：那 3 篇真的能被問出東西來。

### 8. 清回全空
含 `work/parsed`。⚠ **不清的話，同一份 PDF 再送會命中快取、悄悄跳過解析**
（`zotero-sync.py` 血淚第 7 條）——那就不叫乾淨了。
　證明：第 6 步那支檢查再跑一次，還是 0；庫裡 0 份文件。

### 9. 交給 PO，他開始灌

⚠ backrest 已經在第 4.5 步處理掉了，**不要再拖到這裡**。

---

## 明講的代價（都是 PO 裁的，寫在這裡是為了以後不用重吵）

**一、從第 4 步到第 9 步，完全沒有知識庫可以查。** 三個查詢 skill 都會斷。
這是選「全移除」而不是「並存」的代價，PO 知道。

**二、語料沒有查過就刪。** 刪 `/data/lightrag` 會連 733 MB、320 份 PDF 一起刪。
要證明「Zotero 真的都有」需要 `ZOTERO_API_KEY`，而那把鑰匙不在 `.env` 裡
（體檢表 A-38 到今天都是「這條沒跑」）。**PO 裁定不查、直接刪**，理由是
「Zotero 應該是用外掛直接送，檔案裡面都有」。
⇒ 這一條萬一錯了就是真的丟東西。⚠ 但**未必沒有退路**：`backrest` 對舊資料根
有每 6 小時的快照 `(未驗，第二雙眼睛查到的)`。所以第 3.6 步先驗還原，不要空手上路。

**三、⚠ 「其餘確認過補得回來」是錯的 —— 336 個檔不在 git。**

這份文件第一版寫了那句，證據只有兩塊：`work/crops/*/verified` 178 個、
`records/ledger/` 317 份。那兩塊確實逐檔在 git，**但它們不是全部**：

```
$ ssh florian-dker 'cd /data/lightrag && find records checks -type f | sort' > /tmp/dker.txt
$ git -c core.quotePath=false ls-files 'verdicts/records/*' | sed 's|^verdicts/||' | sort > /tmp/repo.txt

$ grep -c '^records/' /tmp/dker.txt                                   → 550
$ comm -23 <(grep '^records/' /tmp/dker.txt) /tmp/repo.txt | wc -l    → 194   ← 不在 git
$ grep -c '^checks/' /tmp/dker.txt                                    → 142
$ git ls-files | grep -c 'checks/'                                    → 0     ← 一個都沒有
```

⇒ **194 ＋ 142 ＝ 336 個檔**，包含 `review/` 75 個裁決材料、`removed/` 46 個
移除紀錄、`zotero-tags/`（8/14 誤刪 163 筆標籤時的救命備份）。
逐目錄清單在 `docs/clean-cut-rag-acoustic-20260817.md`。
⇒ **所以才有第 3.5 步。**

⚠ **這是同一個病的第二次**：8/17 早上剛因為「附了驗證指令、數字卻對不上」記過
一次；這次是「驗了兩塊、寫成全部」。**驗證的範圍跟數字一樣要講清楚。**

**四、全部重新解析要花 MinerU 的錢與時間。** 320 份。
⚠ 這份文件第一版寫「實測單份約 6 秒」——**錯了**，那 6.27 秒是
**整批 317 份算計畫**的時間（`docs/confirm-list-design-20260817.md`），
跟解析無關。解析是雲端來回，`parse-only.py` 自己的註解寫 1–2 分／份，
⇒ 粗估 5–10 小時，**沒有實測過 `(未驗,推測)`**。
⚠ MinerU 的 token 2026-09-04 到期。PO 裁定不先換。

⚠ **母體有兩個數字，不要混用**：`library` 底下 **320 份 PDF**；
已解析／有體檢表的是 **317 份文件**。這份文件第一版兩個都用過。

**五、舊庫的圖譜刪掉就沒了。** 重建要花 DeepSeek 的抽取費。
⚠ 同樣地，`cold-backup` 把整個資料根連 `postgres/` 抄進 restic
`(未驗，第二雙眼睛查到的)` —— 一樣要第 3.6 步先驗過才算數。

**六、要刪的其實不只 9.8 GB。** `du` 在沒有權限時讀不到 `postgres/`
（另外 1.7 GB），實際接近 11.5 GB `(未驗，第二雙眼睛查到的)`。

---

## 還沒決定的

（第二雙眼睛 8/18 抓出來的那兩條，PO 當場裁完了 —— 見裁決 17、18。）

- 確認清單的**存檔格式**還是提案（`docs/confirm-list-design-20260817.md`），
  第 2 步開始之前要裁。
- 清單那一頁的網址、審核台上「還有 N 份要確認」那個入口放哪一格。
- 「兩隻眼睛先幫你勾好」PO 說「也不錯」＝方向認可，**時機未裁**。
  建議排在人工那條路走通之後，因為它花錢。
- `rebuild-v3-design-20260816.md` 那 12 條裡，跟品質量測相關的 6 條都還沒裁
  （體檢表補幾格、檢索品質這輪量不量⋯⋯）。這些不擋上線。
