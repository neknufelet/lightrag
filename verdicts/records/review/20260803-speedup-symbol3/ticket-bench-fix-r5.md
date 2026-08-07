# 工單 `SPEEDUP-2.1-R5` — 驗證回程抓到的真 bug（範圍極窄）

你是 codex terra。`SPEEDUP-2.1` 已經過終審並提交（`580a6f1`），但**在 dker 實跑
`fixture` 時當場失敗**。修這一個，不要動別的。

## 現象（主線 2026-08-03 在 florian-dker 實跑）

```
$ python3 scripts/llm-bench.py fixture --n 8 --out /data/rag/lightrag/acoustics_v2/records/bench/fixture-8.json
llm-bench.py: error: psql（透過 docker exec 容器 lightrag-postgres）失敗：
ERROR:  syntax error at or near ":"
LINE 4: where workspace = :'workspace' and cache_type = 'extract'
```

## 根因（主線已實測定案）

**psql 的 `-c` 不做 psql 變數插值**，`:'workspace'` 原樣送到伺服器 ⇒ 語法錯誤。
改從 stdin 餵 SQL 就會插值。實測對照：

```
# -c（現行寫法）→ ERROR: syntax error at or near ":"
docker exec lightrag-postgres psql … -v workspace=acoustics_v2 -tAqX -c "… where workspace = :'workspace'"

# stdin（-f -）→ 1019   ← 正確，且與已知的 extract 筆數相符
printf "… where workspace = :'workspace' and cache_type = 'extract';" \
  | docker exec -i lightrag-postgres psql … -v workspace=acoustics_v2 -tAqX -f -
```

## 要改的

1. `_extract_rows()` 改成把 SQL 從 **stdin** 餵進去：
   `docker exec -i <容器> psql -U … -d … -v workspace=<ws> -tAqX -f -`，
   SQL 走 `subprocess.run(..., input=<sql>)`。
   **`docker exec` 一定要帶 `-i`**，否則 stdin 進不去。
   `-v workspace=<ws>` 仍然保留（**不要**改成在 Python 端把 workspace 字串
   拼進 SQL —— 那會把「儲存層靠 workspace 欄位隔離」這件事變成字串拼接）。
2. 在 `_CACHE_QUERY` 或 `_extract_rows()` 上方加一行註解記住這個坑：
   **psql `-c` 不展開 `:'var'`，要走 stdin**。

## 要換掉的測試（這條比修 bug 本身重要）

現有測試斷言的是**字串字面**：

```python
assert "where workspace = :'workspace'" in bench._CACHE_QUERY.lower()
```

字串確實有，所以測試是**綠的**，而真正的呼叫在 dker 上炸掉。
**它測到了字面，沒測到行為。**

改成驗**呼叫形狀**（用 monkeypatch 攔 `subprocess.run`，不打真 DB）：

- 命令裡有 `-i`（在 `docker exec` 之後、容器名之前的位置）
- 命令裡有 `-v workspace=<傳入的 workspace>`
- 命令裡有 `-f -`，且**沒有** `-c`
- SQL 是經由 `input=` 傳入，不是命令列參數
- SQL 內含 workspace 條件與 `cache_type = 'extract'`（這條保留，但它不再是
  唯一的保障）

## 驗收

- `uvx --quiet pytest tests/test_llm_bench.py -q` 綠（你跑不了，主線親跑）。
- 三個 `--help` 在無 `.env` 下仍可印。
- 你**不必**實跑 `fixture`（要 dker 的 DB），主線會在驗證回程親跑。

最後輸出：① 動了哪些檔 ② 怎麼修的 ③ 沒驗證到的部分。
