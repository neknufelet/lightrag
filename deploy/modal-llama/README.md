---
title: 把 llama.cpp 搬到租來的 GPU 上（Modal）
date_created: 2026-08-08
date_modified: 2026-08-08
status: draft
kind: sop
supersedes: ""
superseded_by: ""
summary: "同一個 llama.cpp、同一顆模型、同樣的旗標，跑在 Modal 的單張大卡上。LightRAG 只改一個位址。"
---

# 把 llama.cpp 搬到租來的 GPU 上

**這整件事的重點是「只換位址」。** 模型一樣、llama.cpp 一樣（釘同一個 image
digest）、旗標逐字照抄，所以 LightRAG 那邊只改 `LLM_BINDING_HOST`，
抽取行為不變、規則指紋不變、今天量的那些數字仍然可比。

⚠ **本檔與 `app.py` 都還沒被跑過（未驗）。** 下面每一步的輸出都要親眼看過
再往下走。

## 為什麼是一張大卡，不是很多張小卡

`Qwen3.6-35B-A3B` 是 MoE：**35B 的體積、每個 token 只跑 3B 的計算**。
記憶體重、算力輕，所以先撞到的一定是記憶體。

```
                  記憶體   頻寬        權重 18.6 GB 之後剩下
A10G 24GB         24 GB   0.6 TB/s     5.4 GB    ← 槽開不多
A100 80GB         80 GB   2.0 TB/s    61.4 GB
RTX PRO 6000      96 GB  ~1.8 TB/s    77.4 GB    ← 記憶體最多，但 Blackwell 上
                                                    llama.cpp 的成熟度未驗
H100 80GB         80 GB   3.35 TB/s   61.4 GB    ← 頻寬最高，多半用不到
```

開 N 張小卡的話，**每一張都要自己載一份 18.6 GB 的權重**，記憶體不會合併成
一個池（那需要同一台機器上的張量並行，就是本機兩張 3060 在做的事）。
所以「一張大卡、一份模型、很多槽」才是這個模型該有的形狀。

## 槽開幾個：量，不要算

MoE 的批次效率會隨槽數下降 —— 不同序列的 token 會挑到不同專家，批次越大，
每個 token 平均要讀的權重越接近整個 35B。所以吞吐量到某一點就不再上升，
而那一點跟你的實際文本有關，**任何公式算出來的都不準**。

```
開 8 槽  → 記 tokens/s
開 16 槽 → 再記一次
開 24 槽 → 再記一次      不再上升的那一點就是答案
```

`/metrics` 已經開著，量得到。

## 步驟

**只有第一步需要人**（要開瀏覽器授權）：

```bash
modal setup            # token 寫進 ~/.modal.toml，不會出現在任何輸出裡
```

其餘可以照著跑：

```bash
# 金鑰已經產在 deploy/modal-llama/.env（64 位十六進位、權限 600、gitignore 擋住）。
# 用 --from-dotenv **不要**用 `modal secret create name KEY=值` ——
# 後者會把值放進命令列，而命令列在 `ps` 裡人人看得到（本專案 2026-08-08
# 因此外洩過一次）。
modal secret create llama-api-key --from-dotenv deploy/modal-llama/.env

modal run   deploy/modal-llama/app.py::download    # 抓模型進 Volume（一次，約 18.6 GB）
modal serve deploy/modal-llama/app.py              # 開發模式，會印出網址
```

⚠ **這把金鑰跟本機那把不一樣，而且必須不一樣。** 這是對外的端點，
本機那把只在 Tailnet 裡用。共用一把的話，其中一邊外洩就兩邊都要換。

⚠ `HF_REPO` 那一行**是推測的**（本機那顆沒有留下載紀錄，只從檔名的 `UD-`
推是 Unsloth Dynamic）。抓錯會當場報錯 —— 那比抓到一顆「名字像但不是同一顆」
的模型好。真的不對就改掉重跑，重抓不用錢。

## 先單獨測，測完再碰 LightRAG

```bash
URL=<modal serve 印出來的網址>
KEY=<剛才那把>

curl -s $URL/health
curl -s $URL/v1/models -H "Authorization: Bearer $KEY"
curl -s $URL/v1/chat/completions -H "Authorization: Bearer $KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen","messages":[{"role":"user","content":"1+1=?"}]}'
```

**再比對本機**：同一個 prompt 兩邊各打一次，答案的形狀應該一樣（不會逐字
相同，取樣有隨機性）。差太多就表示不是同一顆模型或同一組旗標，停下來查。

啟動 log 要看的一行：

```
srv load_model: initializing, n_slots = N, n_ctx_slot = M
```

`n_ctx_slot` 就是每槽實際拿到的脈絡。抽取一次約 5–8k，所以這個數字只要
遠大於 8k 就夠；**查詢**才需要 ≥ `MAX_TOTAL_TOKENS`（現在是 50,000）。

## 要換過去的時候

`.env` 在 **florian-dker 的 `/opt/stacks/lightrag/.env`**（不在 repo 裡）：

```
LLM_BINDING_HOST=<modal 的網址>/v1
LLM_BINDING_API_KEY=<那把新的>
MAX_ASYNC=<不要超過槽數>
```

⚠ **改完不能只 `restart`**，要 `docker compose up -d --force-recreate lightrag`
—— restart 不會重讀環境變數，改了等於沒改，而且不會有任何訊息。

⚠ `scripts/pp/eyes.py` 的第一雙眼睛也吃 `LLM_BINDING_HOST`，會一起換過去。
同一顆模型，所以跟第二雙眼睛（OpenAI 的 `gpt-5.6-luna`）的獨立性不受影響。

⚠ 換回本機時三個值要一起改回去（`--parallel` / `MAX_ASYNC` /
`MAX_TOTAL_TOKENS` 是乘除關係，見 `docs/hard-rules.md`）。

## 實測結果：不值得（2026-08-09，A100 80GB，已拆除）

**這條路走通了，而且證明它不划算。** 部署成功、金鑰有效、答案正確
（`n_slots = 16, n_ctx_slot = 8192`），然後量出來：

```
短輸入（36 token）        並行 1 → 16：  72.6 →  187.1 tok/s   2.6 倍
真實抽取形狀（3,000 in）  並行 1 → 16： 401.9 →  848.3 tok/s   2.1 倍
單串流                    81 tok/s（本機 --parallel 2 的歷史值是 84）
```

**16 路並行只換到 2 倍出頭。** 每槽的 decode 從 72 掉到 13.7 tok/s ——
那就是 MoE 的批次退化：不同序列的 token 挑到不同專家，批次越大，
每個 token 平均要讀的權重越接近整個 35B。

扣掉本機自己那兩個槽已經有的並行，淨賺約 2 倍。省 20 分鐘，換來一條新依賴、
一個要維護的部署、每次冷啟動 1–2 分鐘。**不值得，已拆。**

⚠ 沒驗的部分：**沒有用同一支 benchmark 並排打本機**（當時本機正在跑抽取，
測它會同時拖慢那批並量到被干擾的數字）。「2 倍」是 Modal 實測對上本機
歷史值推的，不是並排實測。

## 這次測試真正的價值

把「vLLM 值不值得」從猜測變成有證據：**上面那條曲線平掉的地方，正是 vLLM
的連續批次、PagedAttention、專家並行在解的問題**。而且實測 log 裡每一筆都是
`cached_tokens: 0` —— 我們每次抽取都重算那 1,200 token 的規則提示詞，
一次都沒命中快取。vLLM 的自動前綴快取直接省掉這一塊。

⇒ 見 `deploy/modal-vllm/`。代價是換量化、輸出會變、基準要重新量。

## 什麼時候會需要把這支救回來

**要保住與現有圖譜的一致性、又想要並行**的時候 —— 這是唯一能兩者兼得的路
（同一顆 GGUF、同一版 llama.cpp）。Volume 已刪，`download` 重跑約 2 分鐘。
