"""與 LightRAG 容器互動的唯一入口。

為什麼所有判斷都要問容器、而不是自己重新實作一份：快取有效性、options 簽章、
IR 建構規則都是 LightRAG 的內部契約。在容器外重寫一份等於製造第二套會漂移的
真理 —— 而且漂移時不會有錯誤訊息，只會靜默地做出錯誤決定。

所以這裡只做一件事：把 Python 片段送進容器執行，把結果當 JSON 讀回來。
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
# 容器名不得寫死。compose 取的是 `lightrag-${WORKSPACE}`，而 WORKSPACE 由**這個
# checkout 的 .env** 決定 —— 同一個 repo 會有第二個 worktree（rebuild/acoustics-v2）。
# 寫死的話，在 v2 的 checkout 跑任何工具都會 docker exec 進 v155 的容器：讀到的是
# 另一個 workspace 的檔案，而且**不會報錯**，只會安靜地驗錯對象、把結論貼到錯的庫上。
# .env 沒有 WORKSPACE 時直接拋錯，讓呼叫端決定怎麼中止；不能猜容器名。


def env_workspace() -> str:
    """本 checkout 的 .env 裡的 WORKSPACE。"""
    p = _REPO / ".env"
    if p.is_file():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line.startswith("WORKSPACE=") and not line.startswith("#"):
                v = line.split("=", 1)[1].strip().strip("'\"")
                if v:
                    return v
    raise RuntimeError(".env 沒有 WORKSPACE，無法推導容器名")


def container_for(workspace: str) -> str:
    """workspace → 容器名。單一推導處，改 compose 的命名時只改這裡。"""
    return f"lightrag-{workspace}"


# 這個旗標的判讀只有一份。`compat-check.py` 的 A-07 與 `postprocess.py` 的 apply
# 閘門都用它 —— 兩處各寫一份 `in ("", "0", "false")` 的話，哪天有人只改一邊，
# 就會出現「檢查說安全、修補卻被擋下」，或更糟的反向：檢查放行而資料被刪。
_FORCE_REPARSE_OFF: tuple[str, ...] = ("", "0", "false", "no")


def force_reparse_is_on(value: str) -> bool:
    """`LIGHTRAG_FORCE_REPARSE_MINERU` 是不是開著。

    **不認得的值一律當成「開著」。** 這個旗標開著時 LightRAG 會在重抓之前無條件
    清空 raw_dir，把後處理的修補在生效前刪掉，而且索引照樣建成功、不報錯。
    所以判讀必須往安全那邊倒 —— 猜錯「關著」的代價是靜默毀掉 6–10 小時的解析成果。
    """
    return value.strip().lower() not in _FORCE_REPARSE_OFF


def _default_container() -> str:
    """延遲到真的需要預設容器時才讀 .env，讓明確容器不受影響。"""
    return container_for(env_workspace())


class OracleError(RuntimeError):
    """容器互動失敗。訊息帶原始 stderr，不要吞掉。

    ⚠ **但秘密要遮蔽。** 2026-08-08 實測：一次呼叫錯誤讓這個例外把整份 `.env`
    印進終端機，`LIGHTRAG_API_KEY` 與 `POSTGRES_PASSWORD` 隨之外洩。
    「不要吞掉 stderr」與「不要印出秘密」不衝突——見 `_redact()`。
    """


# 鍵名含這些字樣就當秘密。**用樣式不用白名單**：白名單漏掉新加的鍵時會安靜地
# 洩漏，而樣式最壞只是多遮蔽幾個無害的值。方向要選錯得比較安全的那邊。
_SECRET_HINTS: tuple[str, ...] = ("KEY", "PASSWORD", "TOKEN", "SECRET", "CREDENTIAL")


def is_secret_key(name: str) -> bool:
    """鍵名看起來像不像秘密。`.env.example` 開頭秘密表裡的每一個都會命中。

    刻意會**多**命中：`MAX_TOTAL_TOKENS`、`RERANK_MAX_TOKENS_PER_DOC` 這種含
    `TOKEN` 的普通鍵也回 True。那是上面選定的方向（寧可多遮），實務上無害——
    `_redact()` 另有 `len(value) >= 6` 的護欄，短數值不會被塗掉。
    """
    upper = name.upper()
    return any(hint in upper for hint in _SECRET_HINTS)


def _redact(text: str, env: dict[str, str] | None) -> str:
    """把 env 裡秘密鍵的**值**從文字裡換掉。

    遮的是值不是鍵名——鍵名本身有用（讓人知道是哪一個），值才是不能外流的。
    """
    for key, value in (env or {}).items():
        if value and len(value) >= 6 and is_secret_key(key):
            text = text.replace(value, f"<{key} 已遮蔽>")
    return text


@dataclass(frozen=True)
class Oracle:
    container: str = field(default_factory=_default_container)
    timeout: int = 120
    # None 使用目前宿主程序的 uid:gid；只有明確指定時才切換成其他身分，
    # 例如需要讀取歷史 root-owned bundle 時可傳 user="0:0"。
    user: str | None = None

    # ---- 底層 ----

    def _run(self, argv: list[str], env: dict[str, str] | None = None) -> str:
        exec_user = (self.user if self.user is not None
                     else f"{os.getuid()}:{os.getgid()}")
        # 容器內 lightrag 以 uid 1000 執行，與宿主 florian 相同；但 docker exec
        # 預設以 root 執行，會讓掛載檔案變成 root，宿主後處理便無法修改。
        cmd = ["docker", "exec", "-u", exec_user]

        # **秘密不上指令列。** 舊版用 `-e KEY=VALUE`，於是：
        #   (a) 同一台機器上任何人 `ps aux` 都看得到全部秘密
        #   (b) 逾時那條 `raise` 印的是完整 cmd —— 六個秘密一次全出來
        # `docker exec --env-file` 讀檔，值不進 argv。檔案 0600、用完即刪。
        # 2026-08-08 實測外洩過一次（LIGHTRAG_API_KEY 與 POSTGRES_PASSWORD）。
        env_file: str | None = None
        if env:
            fd, env_file = tempfile.mkstemp(prefix="oracle-env-", suffix=".env")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                os.chmod(env_file, 0o600)
                for k, v in env.items():
                    # 含換行的值會破壞 env-file 格式，而且我們的鍵不該有換行。
                    # 靜靜跳過會讓設定「少一個鍵」且無訊號，所以直接拒絕。
                    if "\n" in v:
                        os.unlink(env_file)
                        raise OracleError(f"環境變數 {k} 的值含換行，無法用 --env-file 傳遞")
                    fh.write(f"{k}={v}\n")
            cmd += ["--env-file", env_file]

        cmd += [self.container, *argv]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout)
        except subprocess.TimeoutExpired as e:
            raise OracleError(_redact(f"逾時 {self.timeout}s：{shlex.join(cmd)}", env)) from e
        except FileNotFoundError as e:
            raise OracleError("找不到 docker 指令") from e
        finally:
            if env_file:
                Path(env_file).unlink(missing_ok=True)
        if p.returncode != 0:
            # stderr 會原樣回聲我們傳進去的東西（容器名、參數），所以也要遮。
            raise OracleError(_redact(
                f"exit {p.returncode}：{shlex.join(cmd[:4])}…\n"
                f"stderr: {p.stderr.strip()[:600]}", env))
        return p.stdout

    def py(self, code: str, env: dict[str, str] | None = None):
        """在容器內跑 Python，回傳它 print 出來的 JSON。

        片段必須自己 print(json.dumps(...))；這裡不做隱式包裝，因為隱式包裝會讓
        「片段沒輸出」和「片段輸出 null」變得無法區分。
        """
        out = self._run(["python", "-c", code], env)
        tail = out.strip().splitlines()
        if not tail:
            raise OracleError(f"片段沒有輸出：\n{code[:300]}")
        try:
            return json.loads(tail[-1])
        except json.JSONDecodeError as e:
            raise OracleError(f"輸出不是 JSON：{tail[-1][:300]}") from e

    def py_argv(self, code: str, argv: list[str], env: dict[str, str] | None = None):
        """跟 py() 一樣，但可以傳位置參數（片段用 sys.argv[1:] 取）。

        參數走 argv 而不是字串插值 —— 檔名裡有引號、空白、中文都不會壞掉，
        也不會有把使用者資料當程式碼執行的問題。
        """
        out = self._run(["python", "-c", code, *argv], env)
        tail = out.strip().splitlines()
        if not tail:
            raise OracleError(f"片段沒有輸出：\n{code[:300]}")
        try:
            return json.loads(tail[-1])
        except json.JSONDecodeError as e:
            raise OracleError(f"輸出不是 JSON：{tail[-1][:300]}") from e

    def sh(self, code: str) -> str:
        return self._run(["sh", "-lc", code])

    # ---- 契約探針 ----

    def alive(self) -> bool:
        try:
            self._run(["python", "-c", "print(1)"])
            return True
        except OracleError:
            return False

    def module_identity(self) -> dict:
        """A-01：確認我們探到的 lightrag 就是 server 在跑的那份。

        容器內可能存在多份 lightrag（/app、.venv/site-packages、build/lib、uv cache）。
        全部 md5 比對；不一致就代表探針與實際執行的不是同一份程式碼。
        """
        return self.py(
            "import json,lightrag,hashlib,pathlib,os\n"
            "from lightrag.parser.external.mineru import cache as c\n"
            "paths=sorted({str(pathlib.Path(m.__file__).resolve()) "
            "for m in (lightrag,c)})\n"
            "cands=[]\n"
            "for root in ('/app/lightrag','/app/.venv/lib/python3.12/site-packages/lightrag',"
            "'/app/build/lib/lightrag'):\n"
            "    p=pathlib.Path(root)/'parser/external/mineru/cache.py'\n"
            "    if p.exists(): cands.append((str(p),"
            "hashlib.md5(p.read_bytes()).hexdigest()))\n"
            "try: cmdline=pathlib.Path('/proc/1/cmdline').read_bytes()"
            ".decode(errors='replace').replace(chr(0),' ').strip()\n"
            "except Exception: cmdline=''\n"
            "print(json.dumps({'imported':paths,'cache_copies':cands,"
            "'pythonpath':os.environ.get('PYTHONPATH',''),'pid1':cmdline}))"
        )

    def constants(self) -> dict:
        """A-03 / A-04：磁碟佈局常數與 manifest 結構。"""
        return self.py(
            "import json\n"
            "from lightrag import constants as C\n"
            "from lightrag.parser.external.mineru import manifest as M\n"
            "import lightrag\n"
            "print(json.dumps({\n"
            " 'lightrag_version': getattr(lightrag,'__version__','?'),\n"
            " 'RAW_SUFFIX': C.MINERU_RAW_DIR_SUFFIX,\n"
            " 'PARSED_SUFFIX': C.PARSED_DIR_SUFFIX,\n"
            " 'PARSED_DIR_NAME': C.PARSED_DIR_NAME,\n"
            " 'MANIFEST_FILENAME': M.MANIFEST_FILENAME,\n"
            " 'MANIFEST_VERSION': str(M.MANIFEST_VERSION),\n"
            " 'MANIFEST_ENGINE': str(M.MANIFEST_ENGINE),\n"
            "}))"
        )

    def bundle_valid(self, raw_dir: str, source_pdf: str,
                     env: dict[str, str] | None = None) -> bool:
        """A-12：問 LightRAG 本人這份 bundle 還算不算數。"""
        return bool(self.py(
            "import json\n"
            "from pathlib import Path\n"
            "from lightrag.parser.external.mineru.cache import is_bundle_valid\n"
            f"print(json.dumps(bool(is_bundle_valid(Path({raw_dir!r}), Path({source_pdf!r})))))",
            env,
        ))

    def options_signature(self, env: dict[str, str] | None = None) -> str:
        """A-11：現行環境算出的 options 簽章。"""
        return self.py(
            "import json\n"
            "from lightrag.parser.external.mineru.cache import "
            "current_mineru_options_signature as s\n"
            "print(json.dumps(s()))",
            env,
        )

    def mineru_options(self, env: dict[str, str] | None = None) -> dict:
        return self.py(
            "import json\n"
            "from lightrag.parser.external.mineru.cache import MinerUParserOptions as O\n"
            "o=O.from_env()\n"
            "print(json.dumps({f:getattr(o,f) for f in "
            "('api_mode','model_version','language','enable_table','enable_formula',"
            "'is_ocr','page_ranges')}))",
            env,
        )

    def force_reparse_flag(self) -> str:
        """A-07：這個旗標會先清空 raw_dir 再重抓，等於在修補生效前把它刪掉。"""
        return self.py(
            "import json,os\n"
            "print(json.dumps(os.environ.get('LIGHTRAG_FORCE_REPARSE_MINERU','')))"
        )

    def ir_text_fields(self) -> list[str]:
        """A-06：_coerce_text 實際會讀哪些欄位。決定「消音」要清哪一個。"""
        return self.py(
            "import json,inspect\n"
            "from lightrag.parser.external.mineru import ir_builder as B\n"
            "src=inspect.getsource(B._coerce_text)\n"
            "import re\n"
            "print(json.dumps(re.findall(r'\"([a-z_]+)\"', src)))"
        )

    def ir_drawing_contract(self) -> dict:
        """A-24：哪些型別會走 _build_ir_drawing，以及該函式讀哪些欄位。

        chart→image 整條規則就建立在這兩件事上：chart **不在**型別集合裡（所以
        圖被丟掉），而 caption 要改名成 image_caption（因為它只讀這個）。哪一邊
        變了，規則就從「修好」變成「多做一次沒用的搬動」或「把 caption 搬丟」。

        用正則錨在 `self._build_ir_drawing` 上，不是抓任何一個 `item_type in {...}`
        —— _detect_heading 裡也有一個，抓錯會驗到不相干的集合還一路 ok。
        """
        return self.py(
            "import json,inspect,re\n"
            "from lightrag.parser.external.mineru import ir_builder as B\n"
            "src=inspect.getsource(B)\n"
            "m=re.search(r'item_type in \\{([^}]*)\\}:\\s*\\n\\s*"
            "drawing, asset = self\\._build_ir_drawing', src)\n"
            "d=inspect.getsource(B.MinerUIRBuilder._build_ir_drawing)\n"
            "print(json.dumps({'types': re.findall(r'\"([a-z_]+)\"', m.group(1)) if m else [],\n"
            "                  'fields': re.findall(r'item\\.get\\(\"([a-z_]+)\"\\)', d)}))"
        )

    def indexed_docs(self, api_key: str, port: int = 9621) -> dict:
        """A-25 的母體：這個 workspace 裡各狀態的文件數。

        A-25 斷言「chunk_top_k=8 回的片段數 > =2 回的」。這在**沒有已索引文件**的
        workspace 上結構性不可能成立 —— 兩邊恆為 0，不是契約壞了。所以要先問
        母體，才知道紅燈該不該亮。

        數的是 processed，不是 /documents 的總筆數：只有 processed 的文件才有
        chunk 進索引。20 份全 pending 跟 0 份一樣驗不了，但兩者的原因不同，
        回報要分得開，所以整份狀態表都帶回去。
        """
        return self.py(
            "import json,os,urllib.request as u\n"
            f"r=u.urlopen(u.Request('http://localhost:{port}/documents',"
            f"headers={{'X-API-Key':{api_key!r}}}),timeout=30)\n"
            "st=json.loads(r.read()).get('statuses') or {}\n"
            "print(json.dumps({k:len(v or []) for k,v in st.items()}))"
        )

    def chunk_top_k_effect(self, api_key: str, ks: tuple[int, ...] = (2, 8),
                           port: int = 9621) -> dict:
        """A-25：chunk_top_k 是否真的在控制回傳的片段數。

        在容器內打 localhost —— 服務只發佈到 ${BIND_ADDR}，從 host 打
        127.0.0.1 會連不上，而「連不上」跟「參數失效」在結果上長得一樣。
        埠要用**容器自己監聽的 PORT**，不是發佈到宿主的 HOST_PORT（v155 兩者
        同值把這個混用藏了一路，v2 換埠才會炸）。
        """
        code = (
            "import json,os,sys,urllib.request as u\n"
            "out={}\n"
            "for k in [int(x) for x in sys.argv[1:]]:\n"
            f"    r=u.Request('http://localhost:{port}/query/data',method='POST',\n"
            "        data=json.dumps({'query':'sound absorption coefficient','mode':'mix',\n"
            "                         'only_need_context':True,'chunk_top_k':k}).encode(),\n"
            "        headers={'X-API-Key':os.environ['LIGHTRAG_API_KEY'],\n"
            "                 'Content-Type':'application/json'})\n"
            "    d=json.load(u.urlopen(r,timeout=180)).get('data') or {}\n"
            "    out[str(k)]=len(d.get('chunks') or [])\n"
            "print(json.dumps(out))"
        )
        return self.py_argv(code, [str(k) for k in ks])

    def pipeline_idle(self, api_key: str, port: int = 9621) -> dict:
        """A-19：apply --commit 前必須確認沒有其他工作在跑。"""
        return self.py(
            "import json,os,urllib.request as u\n"
            f"r=u.urlopen(u.Request('http://localhost:{port}/documents/pipeline_status',"
            f"headers={{'X-API-Key':{api_key!r}}}),timeout=15)\n"
            "d=json.loads(r.read())\n"
            "print(json.dumps({k:d.get(k) for k in "
            "('busy','scanning','destructive_busy','job_name')}))"
        )
