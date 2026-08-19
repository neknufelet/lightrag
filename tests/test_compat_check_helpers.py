"""`compat-check.py` 新增那五條斷言所依賴的純函式與常數表。

**為什麼需要這支**：那五條斷言本身要 docker ＋ `.env` 才跑得起來，只有 dker 上
成立。但它們的判準——鍵名怎麼抽、值怎麼正規化、哪些鍵算預期差異——是純資料，
在哪裡都驗得了。**把驗得了的部分留給 dker，等於整組都沒有測試。**

⚠ 這裡刻意**不**測 A-27～A-31 本身。那五條需要跑著的系統，屬於「在 dker 上跑
compat-check」的範圍；在 coder 上假造一個會過的替身，只會製造「驗過了」的錯覺。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent


def _module() -> ModuleType:
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "compat_check", ROOT / "scripts" / "compat-check.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["compat_check"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_env_key_names_keeps_digits_in_key(tmp_path: Path) -> None:
    """含數字的鍵名不得漏掉。

    **血淚 2026-08-07**：用 `^[A-Z_]+=` 數鍵，`NEO4J_URI` 的 `4` 讓它落選，
    少算 4 個並且把錯的數字寫進了 commit 訊息。
    """
    mod = _module()
    f = tmp_path / ".env"
    f.write_text("NEO4J_URI=bolt://x\nPP_EYE_B_MAX_OUT=6000\nPLAIN=1\n",
                 encoding="utf-8")
    assert mod._env_key_names(f) == {"NEO4J_URI", "PP_EYE_B_MAX_OUT", "PLAIN"}


def test_env_key_names_ignores_comments_and_blanks(tmp_path: Path) -> None:
    """註解、空行、縮排的假鍵都不算鍵——否則兩邊的差異會被雜訊灌爆。"""
    mod = _module()
    f = tmp_path / ".env"
    f.write_text(
        "# COMMENTED_KEY=1\n"
        "\n"
        "  INDENTED=2\n"
        "REAL=3\n"
        "# 中文註解裡提到 ANOTHER_KEY=4 也不算\n",
        encoding="utf-8")
    assert mod._env_key_names(f) == {"REAL"}


def test_as_text_normalises_bool_and_string() -> None:
    """env 只有字串、LightRAG 的選項是 bool，不正規化就會永遠不相符。"""
    mod = _module()
    assert mod._as_text(True) == "true"
    assert mod._as_text(False) == "false"
    assert mod._as_text(" TRUE ") == "true"
    assert mod._as_text("pipeline") == "pipeline"
    # 這一組是 A-31 實際會遇到的：檔案寫 "true"，容器回 Python 的 True
    assert mod._as_text("true") == mod._as_text(True)


def test_http_get_reports_zero_when_unreachable() -> None:
    """連不上要回 0，不能丟例外。

    呼叫端必須分得出「回了 401」與「根本連不上」——前者是金鑰錯，後者是服務
    沒起來，處置完全不同。混成同一種訊號會讓人查錯方向。
    """
    mod = _module()
    code, body = mod._http_get("http://127.0.0.1:1/health", timeout=2)
    assert code == 0
    assert body  # 錯誤原因要留著，否則紅燈沒有診斷價值


def test_optional_keys_are_documented_in_example() -> None:
    """被列為「實機可省」的鍵必須真的記載在 `.env.example` 裡。

    這條規則的正當性完全建立在「範本有記載預設值」上。清單裡放一個範本根本沒
    寫的鍵，就變成純豁免——看起來一切正常，實際上那條斷言少驗了一項。
    """
    mod = _module()
    doc = mod._env_key_names(ROOT / ".env.example")
    missing = sorted(mod.ENV_KEYS_OPTIONAL_IN_LIVE - doc)
    assert not missing, f"列為實機可省、但 .env.example 沒記載：{missing}"


def test_mineru_option_map_keys_exist_in_example() -> None:
    """A-31 要比對的六個 `MINERU_*` 鍵都要在 `.env.example` 裡。

    對照表寫錯鍵名時，`env.get()` 會回空字串、與容器的值不符，於是 A-31 紅燈——
    紅在對照表而不是紅在系統。那種紅燈會訓練人忽略它。
    """
    mod = _module()
    doc = mod._env_key_names(ROOT / ".env.example")
    missing = sorted(k for k, _ in mod.MINERU_ENV_TO_OPTION if k not in doc)
    assert not missing, f"對照表的鍵在 .env.example 不存在：{missing}"


def test_external_eyes_keys_exist_in_example() -> None:
    """A-29 用到的 host／金鑰鍵名都要在 `.env.example` 裡，備援鍵也算。"""
    mod = _module()
    doc = mod._env_key_names(ROOT / ".env.example")
    wanted = {k for _, host, key, fb in mod.EXTERNAL_EYES
              for k in (host, key, fb) if k}
    missing = sorted(wanted - doc)
    assert not missing, f"EXTERNAL_EYES 的鍵在 .env.example 不存在：{missing}"


def test_published_services_port_keys_exist_in_example() -> None:
    """A-27 讀的埠鍵要在 `.env.example` 裡（`None` 表示刻意沒有鍵）。

    審核台就是 `None`：INTAKE_PORT 於 2026-08-08 移除，唯一來源是 intake.py
    的 `--port` 預設值。這裡把「沒有鍵」寫成明確的 None 而不是省略，是為了讓
    「忘了加鍵」與「刻意沒有鍵」在程式裡分得開。
    """
    mod = _module()
    doc = mod._env_key_names(ROOT / ".env.example")
    missing = sorted(k for _, k, _ in mod.PUBLISHED_SERVICES if k and k not in doc)
    assert not missing, f"埠鍵在 .env.example 不存在：{missing}"


def test_vector_table_suffix_handles_slash_in_model_id() -> None:
    """HuggingFace 的模型 ID 含斜線，推導表名時必須換掉。

    **血淚 2026-08-08**：舊版只 `replace("-", "_")`，在 `text-embedding-3-large`
    的時代剛好可用；換成 `BAAI/bge-m3` 之後推導出 `baai/bge_m3_1024d`，而實際表名
    是 `lightrag_vdb_chunks_baai_bge_m3_1024d` ⇒ A-22 報「找不到向量表」。
    那是**假紅燈而且是 hard**（會擋動工），還被同時期的 psql 錯誤蓋住沒人發現。
    """
    mod = _module()
    assert mod._vector_table_suffix("BAAI/bge-m3", "1024") == "baai_bge_m3_1024d"


def test_vector_table_suffix_still_handles_the_old_openai_name() -> None:
    """舊模型的表還在庫裡（保留當退路），推導不能因為修新的而漏掉舊的。"""
    mod = _module()
    assert mod._vector_table_suffix("text-embedding-3-large", "3072") == \
        "text_embedding_3_large_3072d"


def test_vector_table_suffix_matches_real_table_names() -> None:
    """對照 2026-08-08 在 dker 實際查到的六張表名，推導的後綴要真的是它們的結尾。"""
    mod = _module()
    real = [
        "lightrag_vdb_chunks_baai_bge_m3_1024d",
        "lightrag_vdb_entity_baai_bge_m3_1024d",
        "lightrag_vdb_relation_baai_bge_m3_1024d",
    ]
    suffix = mod._vector_table_suffix("BAAI/bge-m3", "1024")
    assert all(name.endswith(suffix) for name in real), suffix


def test_a38_reads_the_key_from_the_env_file_not_the_process() -> None:
    """A-38 的金鑰要從 `.env` 讀，不是從行程環境變數讀。

    2026-08-19 實測：PO 產了金鑰、也放進 `/opt/stacks/lightrag/.env`（74 個鍵，
    `curl` 打 `api.zotero.org` 回 HTTP 200），A-38 **仍然說「這條沒跑」** ——
    因為它讀的是 `os.environ`，而 `daily-check.sh` 不 export `.env`
    （也不該 export：`LIGHTRAG_PARSER` 的值含 `;`，`source` 會炸）。

    ⇒ 這條檢查會**永遠**回「沒跑」而沒有人知道為什麼。同檔裡其他每一條要金鑰的
    斷言走的都是 `load_env(REPO)`，只有它自己一條走 `os.environ`。
    """
    src = (ROOT / "scripts" / "compat-check.py").read_text(encoding="utf-8")

    # ⚠ 判準要看**程式碼**，不是看整段文字 —— 第一版用「這段裡不准出現
    # os.environ」，結果被自己寫的那句註解（「因為它讀 os.environ」）打掛。
    assert 'os.environ["ZOTERO_API_KEY"]' not in src, "A-38 還在讀行程環境變數"
    assert 'os.environ.get("ZOTERO_API_KEY")' not in src, "A-38 還在讀行程環境變數"
    assert 'load_env(REPO).get("ZOTERO_API_KEY"' in src, \
        "A-38 沒有走 load_env(REPO)，跟同檔其他要金鑰的斷言不一致"
