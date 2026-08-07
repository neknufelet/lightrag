# verdicts — 不可再生的人工判定與裁決紀錄

**這個目錄存在的唯一理由：裡面的東西重跑不出來。** 其餘 350 MB 的解析快取、裁圖、
模型轉錄快取都可以重新產生（貴，但可以），這些不行 —— 它們是人看著圖一格一格判出來的。

進 git 之後 GitHub 就是異地備份，`/data` 底下那些可再生的東西可以放心清掉。

## 裡面是什麼

| 路徑 | 內容 | 為什麼不可再生 |
|---|---|---|
| `work/crops/<doc>/verified/*.html` | 人工裁定的表格轉錄（10 張） | 空表格是 MinerU 的上限，兩雙眼睛也讀不出來，只能人看裁圖打出來 |
| `work/crops/<doc>/verified/*.txt` | 人工裁定的文字補格（163 處） | 同上 |
| `work/crops/<doc>/review.md` | 該份文件的裁決過程 | 「為什麼這格這樣判」的理由 |
| `records/review/*.md` | 各族群的裁決材料，每份都有「定案」節 | 例：為什麼 `\mathfrak{O}` 在白名單上、C 的 91 個未覆蓋詞往哪併 |
| `records/review/20260803-speedup-symbol3/` | `SPEEDUP` 與 `SYMBOL-3` 兩條線的工單與終審判定全文 | 15 份，含 fable 的設計單與 sol 的五份判定 |
| `records/ledger/*.pdf.json` | 每份文件的三態體檢表 | 裡面的 `note` 欄記著 waiver 的原文與 120 個可疑實體名 |

**不在這裡**（可再生，刻意不進版控）：`work/parsed`（MinerU 解析快取 307 MB）、
`work/crops/<doc>/crops`（裁圖，從 PDF 重裁）、`work/crops/<doc>/cache`（模型轉錄快取）、
`work/crops/<doc>/backup`（apply 的還原點）、`records/bench`、`records/scanner-rescue-*`、
`records/review/crops`（裁圖 1.5 MB）。

## ⚠ 權威在哪：現役是 `/data`，這裡是副本

程式讀的是 dker 上的 `/data/lightrag/...`（`scripts/pp/paths.py` 推導），**不讀這個目錄**。
所以兩邊會漂移，而且漂移不會有錯誤訊息 —— 那正是這個專案反覆踩到的形狀。

**每次在 dker 上新增或修改人工裁定之後，要把它同步回來**。在 coder 執行：

```bash
cd ~/ghq/github.com/neknufelet/lightrag
ssh florian-dker 'cd /data/lightrag && tar czf - \
  work/crops/*/verified work/crops/*/review.md \
  records/review/*.md records/review/20260803-speedup-symbol3 records/ledger 2>/dev/null' \
  | tar xzf - -C verdicts
git status verdicts        # 有差就是 dker 上有新裁定，commit 它
```

要反向確認 dker 有沒有比 repo 舊（例如 dker 被重建過）：

```bash
ssh florian-dker 'cd /data/lightrag && find work/crops/*/verified records/ledger -type f | wc -l'
find verdicts/work/crops/*/verified verdicts/records/ledger -type f | wc -l
```

兩個數字必須相同。不同就先查清楚哪一邊多，**不要直接覆蓋** —— 人工裁定沒有第二份。

## 為什麼不讓程式直接讀這裡

改讀取路徑會動到 `apply` 的行為，而 `apply` 是碰資料的不可逆操作。目前的分工是
「`/data` 現役、repo 版控」，代價是要記得同步（所以上面那條指令寫成可以直接貼的）。
真要收斂成單一來源，那是另一件事，得走完整審查。

## 誰會發現這個目錄被刪掉

`tests/test_verdicts.py`。它斷言檔案數只准變多不准變少 —— 人工裁定只會累積，
變少就是有東西被誤刪或同步方向搞反了。

這一條是有前例的：`tests/symbol2-results.json` 進了版控但全 repo 沒有任何程式讀它，
於是它成為「最容易被當成暫存檔刪掉」的資產（坑清單 PIT-156）。**沒有消費者的資產
等於沒有備份。**
