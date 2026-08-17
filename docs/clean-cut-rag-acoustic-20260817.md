# 新庫 `rag_acoustic`：怎麼跟舊庫乾淨切開

**PO 2026-08-17 的要求原話：**

> 我們有沒有什麼辦法能乾淨的清除，或是直接先把舊的關掉移除。
> 因為之前就有新舊交雜很噁心，你說拔乾淨了但結果沒有。舊的斷掉沒關係，我只要求乾淨。

**PO 同日裁定新庫叫 `rag_acoustic`。**

---

## 一、為什麼上次沒拔乾淨（實測，2026-08-17）

**新舊本來就是擠在同一批表裡的。** dker 實查：

```
$ docker exec lightrag-postgres psql -U deeptutor -d lightrag -tAc \
    "select count(distinct table_name) from information_schema.columns
     where column_name='workspace' and table_schema='public'"
13

$ ... -tAc "select distinct workspace from lightrag_doc_status"
acoustics_v2

$ ... 最大的幾張表
lightrag_relation_chunks                  77148
lightrag_vdb_relation_baai_bge_m3_1024d   76259
lightrag_graph_edges                      76259
```

⇒ LightRAG 預設的分法是**同一批表、加一個 `workspace` 欄**。
新庫如果照預設建，13 張表裡就會同時躺著新舊兩份資料。

**那就是「拔不乾淨」的根源**：要清舊的得在 13 張表上各刪一次，而
「刪完了沒有」只能靠再查一次去證明 —— 漏一張表不會有任何地方報錯。

---

## 二、乾淨的做法：新庫用**自己的資料庫**

實測確認做得到 —— 資料庫名稱與 workspace 是**兩個獨立的設定**：

```
$ docker exec lightrag-acoustics_v2 printenv | grep -E 'POSTGRES_DATABASE|WORKSPACE'
POSTGRES_DATABASE=lightrag
WORKSPACE=acoustics_v2
```

所以：

| | 舊庫 | 新庫 |
|---|---|---|
| 資料庫 | `lightrag` | **`rag_acoustic`** ← 換這個 |
| workspace | `acoustics_v2` | `rag_acoustic` |
| 容器 | `lightrag-acoustics_v2`、`kbapi-acoustics_v2` | 兩個新的 |

**乾淨在哪裡**：拔掉舊的只要 `DROP DATABASE lightrag`。**一個指令，沒有第 13 張表
可以漏**；而且在那之前，兩邊在資料庫層級就是隔離的，不可能互相污染。

⚠ 這是**偏離 LightRAG 預設用法**的決定。代價是同一台 Postgres 上多一個資料庫
（磁碟與連線數的成本可忽略），換到的是「可證明的乾淨」。

---

## 三、舊庫到底佔了哪些東西（完整清單，2026-08-17 實查）

拔乾淨的前提是先數得出來。這是全部：

| # | 東西 | 現況 | 拔的動作 |
|---|---|---|---|
| 1 | 容器 `lightrag-acoustics_v2` | Up 40 小時 | 停掉、移除 |
| 2 | 容器 `kbapi-acoustics_v2` | Up 40 小時 | 停掉、移除 |
| 3 | 資料庫 `lightrag`（13 張表，最大 77k 列） | 在用 | `DROP DATABASE` |
| 4 | `/data/lightrag/work` 2.6 GB | 解析結果 | 刪或搬 |
| 5 | `/data/lightrag/library` 733 MB | 語料 | **先確認 Zotero 有原件再刪** |
| 6 | `/data/lightrag/rag_storage`、`inputs` | 小 | 刪 |
| 7 | `/data/lightrag/records`、`checks` 38 MB | **人工裁定與體檢表** | ⚠ **不要刪**，見下 |
| 8 | `/data/lightrag/models` 6.4 GB | 本機 embedding 模型 | **留著**，新庫也要用 |
| 9 | `/opt/stacks/lightrag/` 的 compose 與 `.env` | 在用 | 改成新庫的 |
| 10 | systemd：`lightrag-stack`、`intake`、`mount-guard`、`daily-check`、`cold-backup` | 5 個 | 指向新庫 |
| 11 | backrest 的兩個 rag 排程 | **PO 早就說要關，還沒關** | 關掉或改指向 |
| 12 | 三個查詢 skill 的網址與 workspace | 指著舊庫 | 改 |

### ⚠ 第 7 項是唯一不能刪的

`/data/lightrag/records/` 裡是**重跑不出來的人工判定**（`verdicts/README.md` 的整個
前提）：表格轉錄、LaTeX 修正、體檢表、圖譜清理的備份。

⚠ 而且它**還沒有完整進版控**：2026-08-17 實測 `pull-verdicts.py` 顯示體檢表
317 份逐檔一致，但那只是體檢表一種。**拔舊庫之前要先跑一次
`scripts/pull-verdicts.py --apply` 並提交**，否則就是把不可再生的東西跟舊庫一起丟掉。

---

## 四、順序（每一步都要能證明做完了）

**這一段是提案，還沒有執行。** 每一步後面那行是「怎麼證明」。

1. **先救人工裁定** —— `scripts/pull-verdicts.py --apply`，看過再 commit。
   　證明：`git log verdicts/` 有這次的 commit。
2. **確認語料的原件還在** —— 733 MB 的 `library` 是從 Zotero 來的。
   　證明：Zotero 裡的份數 ≥ library 的份數。⚠ 這條沒做就不要動第 5 項。
3. **建新資料庫 `rag_acoustic`**（空的，不動舊的）。
   　證明：`psql -l` 看得到，且新庫容器起得來、健康檢查過。
4. **新庫跑通一份文件**（一份就好）。
   　證明：那份文件在新庫查得到，而**舊庫完全沒被動到**。
5. **舊庫停機**（只停，先不刪）。
   　證明：舊容器 `Exited`，而新庫仍然健康。
6. **觀察幾天**。⚠ 這一步不能省 —— 停機與刪除之間留退路。
7. **刪舊的**：`DROP DATABASE lightrag`、移除兩個舊容器、刪 `work`／`library`。
   　證明：`psql -l` 沒有 `lightrag`；`docker ps -a` 沒有 `*acoustics_v2`。

---

## 五、還沒裁的（`rebuild-v3-design-20260816.md` 那 12 條，白話版）

那份文件是 8/16 寫的新庫設計，七張圖講整條加工線。最後一節列了 12 件要 PO 決定
但還沒決定的事。**已經裁掉一條**（新庫叫 `rag_acoustic`），剩 11 條：

**跟今天的清理直接相關（建議先裁）：**

1. **backrest 在硬碟不見時會怎樣** —— 會不會拿一個空目錄去覆蓋掉好的備份。
   ⚠ 這條在拔舊庫之前一定要弄清楚。

**跟「確認清單」相關（下一個要做的功能）：**

2. 確認清單長什麼樣、放哪裡（審核台還是獨立畫面）
3. 確認結果存成什麼格式
4. 兩隻眼睛預先幫你勾好那一段，這一輪要不要做（先人工也行，只是慢）

**跟品質量測相關（可以晚點裁）：**

5. 體檢表那八格，這一輪要補幾格、哪幾格明講「不做」
6. 「檢查上線前要證明它分得出東西」要不要這輪就上
7. 四個門檻的數字是量出來的還是隨手調的，要不要查
8. 第四層（檢索品質）這輪要不要量 —— DeepSeek 建的庫從沒量過

**跟新庫內容相關：**

9. 參考書目消音在「只有論文」的新庫要不要維持原判（比例會放大）
10. 那 946 項正文型別要不要逐條看（舊事故就在這裡）

**技術債：**

11. 十二道閘門裡有十道沒人呼叫：接回去／刪掉／標記，三選一
