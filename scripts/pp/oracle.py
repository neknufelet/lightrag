"""與 LightRAG 容器互動的唯一入口。

為什麼所有判斷都要問容器、而不是自己重新實作一份：快取有效性、options 簽章、
IR 建構規則都是 LightRAG 的內部契約。在容器外重寫一份等於製造第二套會漂移的
真理 —— 而且漂移時不會有錯誤訊息，只會靜默地做出錯誤決定。

所以這裡只做一件事：把 Python 片段送進容器執行，把結果當 JSON 讀回來。
"""
from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass

DEFAULT_CONTAINER = "lightrag-acoustics_v155"


class OracleError(RuntimeError):
    """容器互動失敗。訊息帶原始 stderr，不要吞掉。"""


@dataclass(frozen=True)
class Oracle:
    container: str = DEFAULT_CONTAINER
    timeout: int = 120

    # ---- 底層 ----

    def _run(self, argv: list[str], env: dict[str, str] | None = None) -> str:
        cmd = ["docker", "exec"]
        for k, v in (env or {}).items():
            cmd += ["-e", f"{k}={v}"]
        cmd += [self.container, *argv]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout)
        except subprocess.TimeoutExpired as e:
            raise OracleError(f"逾時 {self.timeout}s：{shlex.join(cmd)}") from e
        except FileNotFoundError as e:
            raise OracleError("找不到 docker 指令") from e
        if p.returncode != 0:
            raise OracleError(
                f"exit {p.returncode}：{shlex.join(cmd[:4])}…\n"
                f"stderr: {p.stderr.strip()[:600]}"
            )
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
