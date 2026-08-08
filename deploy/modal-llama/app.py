"""同一個 llama.cpp、同一顆模型，跑在租來的 GPU 上。

**目的是「只換位址」**：LightRAG 那邊只改 `LLM_BINDING_HOST`，其餘設定一律不動。
所以這裡刻意跟 `deploy/llama-qwen36-moe/compose.yaml` 逐項對齊 ——
image 釘同一個 digest、模型檔同一顆、旗標逐字照抄。**兩邊不一樣的地方只有三個**，
每一個都在下面標了理由。

    ① 少了 `-sm layer` 與 `-ts 0.94,1.06`  單卡不需要分割，那兩個是雙 3060 的參數
    ② `-c` 與 `--parallel` 變成參數        卡不一樣，槽數與脈絡要重新量
    ③ 金鑰從 Modal Secret 進來            本機是從 deploy/…/.env 進來

⚠ **金鑰絕不進命令列。** llama-server 的 `--api-key` 會出現在 `ps` 與容器設定裡，
本專案 2026-08-08 因此外洩過一次。用環境變數 `LLAMA_API_KEY`（注意不是
`LLAMA_ARG_API_KEY`，那是另一個東西，打錯**不會報錯**，伺服器會以「沒設金鑰」
啟動而全部放行）。

用法：

    pip install modal && modal setup          # 互動登入，你自己跑
    modal run    deploy/modal-llama/app.py::download    # 把模型抓進 Volume（一次）
    modal serve  deploy/modal-llama/app.py              # 開發模式，會給你一個網址
    modal deploy deploy/modal-llama/app.py              # 常駐部署

驗它（**先單獨測，確認沒問題再改 LightRAG**）：

    curl -s $URL/health
    curl -s $URL/v1/models -H "Authorization: Bearer $KEY"
    curl -s $URL/v1/chat/completions -H "Authorization: Bearer $KEY" \\
      -H 'Content-Type: application/json' \\
      -d '{"model":"qwen","messages":[{"role":"user","content":"1+1=?"}]}'

⚠ 這個檔**還沒被跑過任何一次**（未驗）。Modal 的 Python API 會演進，第一次跑
出錯是正常的，以他們當期文件為準。
"""
from __future__ import annotations

import subprocess

import modal

# ── 與本機逐項對齊 ────────────────────────────────────────────────────

# 釘 digest，不是 tag：`server-cuda` 是會動的，釘住才有「跑的是哪一版」這回事。
# **與 deploy/llama-qwen36-moe/compose.yaml:23 同一個 digest** —— 換了就不是
# 「同一個 llama.cpp」了，抽取行為可能跟著變。
LLAMA_IMAGE = (
    "ghcr.io/ggml-org/llama.cpp"
    "@sha256:48b8053c05319cde97e64463d117b5747d3fb27475b176f85edf27bd503fa7f9"
)

MODEL_DIR = "/models/qwen3.6-35b-a3b"
MODEL_FILE = "Qwen3.6-35B-A3B-UD-IQ4_XS.gguf"      # 17.7 GB
MMPROJ_FILE = "mmproj-F16.gguf"                     # 0.9 GB

# ⚠ **這個 repo 名是推測的**（檔名的 `UD-` 是 Unsloth Dynamic 量化）。
# 本機那份沒有留下載紀錄。抓錯會在 download 當場報錯 —— 那是好事，
# 比抓到一顆「名字像但不是同一顆」的模型好。真的不對就改這一行重跑。
HF_REPO = "unsloth/Qwen3.6-35B-A3B-GGUF"

# 卡與槽。**這兩個數字不要相信，要量。**
#
#   單卡放得下多少脈絡 = (VRAM − 權重 18.6 GB) ÷ 每 token 的 KV
#   本機實測：131,072 脈絡在不到 3 GB 的 KV 裡（雙 3060 共 20.7 GB，權重 18.6 GB）
#
# 照這個比例，A100 80GB 剩 ~61 GB 可以放很多槽。但 **MoE 的批次效率會隨槽數下降**
# （不同序列的 token 會挑到不同專家，批次越大要讀的權重越接近整個 35B），
# 所以吞吐量到某個槽數就不再上升。開起來看啟動 log 的 `n_ctx_slot`，
# 然後 8／16／24 各量一次 tokens/s，不再上升的那一點才是答案。
GPU = "A100-80GB"
CONTEXT = 131072          # 總脈絡，÷ PARALLEL ⇒ 每槽
PARALLEL = 16             # 抽取一次只吃約 5–8k，所以槽可以切小切多

app = modal.App("lightrag-llama-qwen36")
volume = modal.Volume.from_name("qwen36-moe-gguf", create_if_missing=True)


# ── 一次性：把模型抓進 Volume ──────────────────────────────────────────

download_image = modal.Image.debian_slim().pip_install("huggingface_hub[hf_transfer]")


@app.function(
    image=download_image,
    volumes={MODEL_DIR: volume},
    timeout=60 * 60,
)
def download() -> None:
    """在 Modal 機房裡直接抓，不從家裡上傳 17.7 GB。

    抓進 Volume 之後就一直在那裡，之後每次啟動都是從 Volume 掛載，
    不會重抓。
    """
    import os

    os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"
    from huggingface_hub import hf_hub_download

    for name in (MODEL_FILE, MMPROJ_FILE):
        path = hf_hub_download(repo_id=HF_REPO, filename=name,
                               local_dir=MODEL_DIR)
        print(f"抓好了 {path}")
    volume.commit()


# ── 伺服器 ────────────────────────────────────────────────────────────

serve_image = modal.Image.from_registry(LLAMA_IMAGE, add_python="3.12")


@app.function(
    image=serve_image,
    gpu=GPU,
    volumes={MODEL_DIR: volume},
    secrets=[modal.Secret.from_name("llama-api-key")],   # 提供 LLAMA_API_KEY
    timeout=60 * 60 * 4,
    # 閒置多久之後收掉。抽一整批時它會一直忙，不會被收；收掉之後下一次請求
    # 要付冷啟動（18.6 GB 載進 GPU，幾十秒到幾分鐘）。
    scaledown_window=300,
)
@modal.concurrent(max_inputs=PARALLEL)
@modal.web_server(port=8080, startup_timeout=900)
def serve() -> None:
    """啟動 llama-server。旗標與 compose.yaml:58-110 逐字對齊，差異見檔頭。"""
    command = [
        "/app/llama-server",
        "--model", f"{MODEL_DIR}/{MODEL_FILE}",
        "--mmproj", f"{MODEL_DIR}/{MMPROJ_FILE}",
        "-ngl", "99",                 # 全部層上 GPU
        # ① 少了 -sm layer 與 -ts：單卡不分割
        "-c", str(CONTEXT),
        "--parallel", str(PARALLEL),
        "-fa", "on",                  # flash attention
        "--jinja",                    # 用模型自帶的 chat template
        "--reasoning", "off",         # 不吐 reasoning 段
        "--image-min-tokens", "1024",
        "--host", "0.0.0.0",
        "--port", "8080",
        "--metrics",                  # /metrics，量吞吐要用
    ]
    # 金鑰**不放在這個 list 裡** —— 它會出現在 ps 與容器設定裡。
    # llama-server 自己會讀環境變數 LLAMA_API_KEY，Secret 已經把它放進來了。
    subprocess.Popen(command)
