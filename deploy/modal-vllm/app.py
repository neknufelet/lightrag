"""vLLM + 官方 FP8 權重。**這條路會換掉模型的數值行為，不是「只換位址」。**

跟 `deploy/modal-llama/`（已拆）的差別，一句話：那支保證輸出一致但只快 2 倍，
這支可能快很多但**輸出會變**。

    llama.cpp + IQ4_XS（本機現役）   17.7 GB   輸出與現有圖譜一致
    vLLM      + FP8                  ~35 GB   輸出會變 ⇒ 基準要重新量

⚠ **所以這支只有在「反正要重抽一次」的時候才該用。** 本專案目前確實欠一次
（規則 2a 的小寫修正還沒進圖譜，`compat-check` 的 A-32 是紅的），所以時機剛好；
但那是一個要明確做的決定，不是順手切換。

## 為什麼是 FP8 + H100，不是 BF16 也不是 A100

    BF16 + A100 80G   70 GB 權重塞進 80 GB → 只剩 10 GB 給 KV，槽開不多
    FP8  + A100 80G   省了記憶體，但 **Ampere 沒有 FP8 張量核心**，vLLM 會即時
                      反量化回 BF16 —— 算力一點都沒賺到
    FP8  + H100 80G   35 GB 權重 + 45 GB KV，而且 FP8 在 Hopper 上是原生的  ✅

## vLLM 值得試的地方（也正是實測到 llama.cpp 平掉的地方）

2026-08-09 實測 llama.cpp 在 A100 上跑這顆 MoE：並行 1→16 只換到 2.1 倍
（401.9 → 848.3 tok/s，真實抽取形狀）。三個機制正好打在那個瓶頸上：

    連續批次        請求結束就補新的，不用等整批對齊
    PagedAttention  KV 像分頁一樣管，不會因為每槽預留 8192 而浪費
    專家並行        MoE 專用核心，正是上面那條曲線平掉的原因

用法：

    modal secret create vllm-api-key --from-dotenv deploy/modal-vllm/.env
    modal run    deploy/modal-vllm/app.py::download    # 約 35 GB，一次
    modal deploy deploy/modal-vllm/app.py

⚠ 這個檔**還沒被跑過（未驗）**。
"""
from __future__ import annotations

import subprocess

import modal

# 要試哪個量化就改這裡。**量化方式會改變抽取結果**，換了就要重測，
# 所以每一種用自己的 Volume，不要混在一起。
#
# 2026-08-09 實測（同溫度 0.2、同三篇論文）：
#   本機 llama.cpp + UD-IQ4_XS   泛用標籤 0、人/機構 36   ← 目前最好
#   vLLM + FP8                   泛用標籤 7、人/機構 47   ← 退步
#
# 猜測是「均勻量化 vs 選擇性保精度」：UD-IQ4_XS 會挑重要張量保高精度，
# FP8 一視同仁。AWQ 是 activation-aware，同一個思路 —— 換上來就是在驗這個猜測。
QUANT = "awq"                            # fp8 | awq
_MODELS = {
    "fp8": ("Qwen/Qwen3.6-35B-A3B-FP8", "qwen36-fp8"),          # 約 35 GB
    "awq": ("cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit", "qwen36-awq"),  # 約 20 GB
}
MODEL_NAME, VOLUME_NAME = _MODELS[QUANT]
MODEL_DIR = f"/models/qwen3.6-35b-a3b-{QUANT}"
SERVED_NAME = "qwen3.6-35b-a3b"          # LightRAG 的 LLM_MODEL 對這個名字

# ⚠ **這個 tag 是會動的。** 第一次跑成功之後要換成 digest ——
# 沒釘住的話「跑的是哪一版 vLLM」答不出來，而抽取結果會跟著版本變。
# （本機那支 llama.cpp 就是釘 digest 的，見 deploy/llama-qwen36-moe/compose.yaml:23）
VLLM_IMAGE = "vllm/vllm-openai:latest"

GPU = "H100"

# 單槽最大脈絡。**這裡刻意開到查詢也夠用**：
#   抽取一次約  8,000 token
#   查詢       MAX_TOTAL_TOKENS = 50,000
# llama.cpp 那邊被迫二選一（總脈絡 ÷ 槽數），vLLM 的 PagedAttention 是動態分配，
# 所以可以同時滿足兩者 —— 這是換過來最實際的好處之一。
# 2026-08-09 實測：16 個並行的抽取請求只用掉 7.9% 的 KV（45.93 GiB ≈ 81 萬 token）。
# **`max_model_len` 是單一請求的上限，不是預留** —— 這是 vLLM 與 llama.cpp 最本質的
# 差別（後者 `-c ÷ --parallel` 是零和，槽數與脈絡只能二選一）。所以開到 128k
# 不會少掉任何併發，只是允許更長的單一請求。實際併發由請求多長決定：
#   抽取 4k／請求  → 約 200 個   查詢 50k／請求 → 約 16 個   131k／請求 → 約 6 個
MAX_MODEL_LEN = 131072

# 併發上限。vLLM 是連續批次，這只是天花板不是預先切好的槽。
# **實際該設多少要量**：8／16／32／64 各跑一次，吞吐不再上升的那一點。
MAX_NUM_SEQS = 64

app = modal.App("lightrag-vllm-qwen36")
volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)

# torch.compile 與 CUDA graph 的結果。**不留住的話每次冷啟動都要重編。**
# 2026-08-09 實測冷啟動 562 秒，其中 torch.compile 163 秒、CUDA graph 約 90 秒
# ——那 250 秒是每次都在重做同一件事。
compile_cache = modal.Volume.from_name("vllm-compile-cache", create_if_missing=True)


download_image = modal.Image.debian_slim().pip_install("huggingface_hub[hf_transfer]")


@app.function(image=download_image, volumes={MODEL_DIR: volume}, timeout=60 * 60)
def download() -> None:
    """在機房裡抓 35 GB，不從家裡上傳。"""
    import os

    os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"
    from huggingface_hub import snapshot_download

    snapshot_download(
        repo_id=MODEL_NAME,
        local_dir=MODEL_DIR,
        # GGUF 與 pytorch bin 都不要 —— 這個 repo 只需要 safetensors 與設定檔
        ignore_patterns=["*.pt", "*.bin", "*.gguf"],
    )
    volume.commit()


# ⚠ 兩個參數都不能省，各擋一個實測踩到的坑（2026-08-09）：
#   add_python   Modal 認不出這個 image 裡的 Python，會回 ConflictError
#                「unable to determine the version of Python」而**整個 app 建不起來**
#                （連只用另一個 image 的 download 也一起卡住）。
#   entrypoint([]) 官方 image 的 ENTRYPOINT 是 `vllm serve` 的包裝，會攔截
#                Modal 要跑的 runtime。llama.cpp 那支也踩過同一個坑。
serve_image = modal.Image.from_registry(VLLM_IMAGE, add_python="3.12").entrypoint([])


@app.function(
    image=serve_image,
    gpu=GPU,
    volumes={MODEL_DIR: volume, "/root/.cache/vllm": compile_cache},
    secrets=[modal.Secret.from_name("vllm-api-key")],   # 提供 VLLM_API_KEY
    timeout=60 * 60 * 4,
    scaledown_window=300,
)
@modal.concurrent(max_inputs=MAX_NUM_SEQS)
@modal.web_server(port=8000, startup_timeout=900)
def serve() -> None:
    """啟動 vLLM 的 OpenAI 相容伺服器。

    ⚠ **金鑰走環境變數 `VLLM_API_KEY`，不進命令列。** `--api-key` 會出現在
    `ps` 與容器設定裡，本專案 2026-08-08 因此外洩過一次。
    """
    command = [
        "vllm", "serve", MODEL_DIR,
        # LightRAG 的 `LLM_MODEL` 認這個名字，兩邊必須一致
        "--served-model-name", SERVED_NAME,
        "--max-model-len", str(MAX_MODEL_LEN),
        "--max-num-seqs", str(MAX_NUM_SEQS),
        # ⚠ **關掉思考模式。** 本機那支是 `--reasoning off`，vLLM 這邊完全不同機制：
        # 走 chat template 的 kwarg。不關的話，2026-08-09 實測 300 個 token
        # 全部花在「Here's a thinking process that leads to…」，正題一個字沒寫。
        # LightRAG 不會在請求裡帶 chat_template_kwargs，所以**一定要設成伺服器預設**。
        "--default-chat-template-kwargs", '{"enable_thinking": false}',
        # 每次抽取都送同一份約 1,200 token 的規則提示詞，前綴快取才不會白算 3,000 遍。
        # ⚠ 量它的時候題本要用沒跑過的（ADR-0002）：同題重跑會量到殘影不是效能。
        "--enable-prefix-caching",
        # 留一成給啟動時的暫時配置，剩下都給 KV
        "--gpu-memory-utilization", "0.90",
        "--host", "0.0.0.0",
        "--port", "8000",
    ]
    subprocess.Popen(command)
