"""MinerU 產物的共用偵測器與磁碟契約。

單一來源：parse-check.py、compat-check.py、postprocess 都從這裡拿偵測邏輯。
分散成三份的話會漂移 —— 而且漂移時不會有錯誤，只是三支腳本對同一份資料給出
不同答案，然後你不知道該信哪個。

本檔案的偵測器已經因為誤判修過三次，每次的原因都寫在對應常數的註解裡。
"""
from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping
from pathlib import Path

# content_list.json 的項目型別。出現沒見過的 = 版面型態超出規則涵蓋範圍。
KNOWN_TYPES = {
    "text", "header", "footer", "table", "equation", "image",
    "page_number", "page_footnote", "code", "list",
    # 論文版面才會出現，C 那本教科書沒有：
    #   aside_text —— 頁邊直排文字（期刊資訊那條）。實測抓到的是 OCR 殘骸
    #     '9r 0 1 -.s] :0006'，而 ir_builder 的 fallback 走 _coerce_text，
    #     它讀 ("text","content","body","code_body") —— aside_text 有 text，
    #     所以**會進索引**。必須當版面雜訊處理。
    #   chart —— 圖表。有 img_path 但 content 是空字串，caption/footnote 也空。
    #     fallback 拿到空字串就不 append，所以**整個被丟掉**（img_path 不在
    #     _coerce_text 的讀取清單裡，雜湊字串不會外洩進索引）。
    #     這不是污染而是資訊遺失：image 走 _build_ir_drawing 有佔位符，
    #     chart 沒有。實測一篇論文 15 張 chart 對索引的貢獻是零。
    "aside_text", "chart",
}

# 會進 IR 正文的型別。header / footer 也在內 —— LightRAG 的 ir_builder 把它們
# 落到 fallback「serialize unknown items as plain text」，所以它們確實會進索引。
PROSE_TYPES = ("text", "header")
# aside_text 也在內：它有 text 欄位，會經 fallback 進索引，跟 header/footer 同性質。
BODY_TYPES = ("text", "header", "footer", "aside_text")

# 掉字偵測器。務必用 \b 這種非消耗性邊界；寫成兩側都是 \s 的
# (\s[a-z]{1,2}\s){5,} 會因為前一次匹配吃掉後一次的前導空白而永遠回 0。
MANGLED = re.compile(r"(?:\s+[a-z]{1,2}\b){5,}")

# 光看「連續 5 個 1–2 字母的小寫詞」會誤判正常英文散文 —— 實測 00712 的
# 「…may not **be so if r is** small…」就命中了：be/so/if/r/is 全是真英文字。
# 這是本專案第七次同一類誤判（偵測器量的東西跟以為的不一樣）。
#
# 真正的掉字長這樣（C p64）：
#   'Ab = = ze = etsosbd) te se  e e e   e o  e e tes rt   d  s    s s    sd'
# 差別在**單字母碎片的密度**：字元被切散時會產生大量孤立字母，正常英文不會
# （英文只有 a / I 是單字母詞）。要求命中的區段裡至少有這麼多個單字母碎片。
MIN_SINGLE_CHARS = 3
_SINGLE = re.compile(r"\b[b-hj-z]\b")

# 行內數學。LaTeX 會把字母拆開排版（\mathrm { i n t e r i o r }），長得跟掉字
# 一模一樣，套 MANGLED 之前必須先剝掉。
MATH = re.compile(r"\$[^$]*\$|\\\(.*?\\\)|\\\[.*?\\\]", re.S)

TAG = re.compile(r"<[^>]+>")

# prompt 洩漏。1.5.5 上游已把 few-shot 範例換成純佔位符，這組留著防退化。
LEAK = re.compile(
    r"Noah Carter|World Athletics|Carbon-Fiber Spikes|100m Sprint|Knowledge Graph Specialist",
    re.I,
)


def strip_math(t: str) -> str:
    return MATH.sub(" ", t or "")


def table_text(body: str | None) -> str:
    """表格的實質文字。剝掉標籤是必要的 —— MinerU 會產出
    <table><tr><td></td></tr></table> 這種空殼，字串非空但內容為零。
    <img> 也不算內容，那只是指向圖片檔的參照。"""
    return TAG.sub("", body or "").strip()


def is_mangled(text: str, item_type: str) -> bool:
    """掉字偵測。只跑散文 —— equation 的 text 是沒有 $ 包裹的裸 LaTeX，
    table_body 整片是標記，兩者本來就長得像掉字。在數學密集的文件上不設限
    會讓每一份都變 ERROR（實測 12 個命中裡 11 個是誤判）。"""
    if item_type not in PROSE_TYPES:
        return False
    for m in MANGLED.finditer(strip_math(text)):
        # 命中區段裡要有足夠的單字母碎片才算掉字。只看「連續短詞」會誤判
        # 正常英文（見 MIN_SINGLE_CHARS 註解）。
        if len(_SINGLE.findall(m.group(0))) >= MIN_SINGLE_CHARS:
            return True
    return False


def item_body(item: dict) -> str:
    """項目的正文欄位。順序與 ir_builder._coerce_text 一致（已由 compat-check A-06 斷言）。"""
    for k in ("text", "content", "body", "code_body"):
        v = item.get(k)
        if isinstance(v, str) and v:
            return v
    return ""


def bbox_to_points(bbox: list, page_w: float, page_h: float) -> tuple[float, float, float, float]:
    """content_list 的 bbox 是每軸正規化到 0–1000，換算成 PDF 點。

    已驗證：content_list [93,136,906,277] 與 page_size (439,666) 換算得
    [40.8, 90.6, 397.7, 184.5]，與 layout.json 記錄的 [41,91,398,185] 吻合。
    注意不是均勻縮放 —— x 與 y 各自正規化，用單一比例會錯。
    """
    x0, y0, x1, y1 = bbox
    return (x0 / 1000 * page_w, y0 / 1000 * page_h,
            x1 / 1000 * page_w, y1 / 1000 * page_h)


class EnvFileMissing(FileNotFoundError):
    """`.env` 不在。**這是致命錯誤，不是空設定。**"""


def load_env(repo: Path, *, required: bool = True) -> dict[str, str]:
    """讀 repo 根目錄的 `.env`。

    **檔案不在時丟例外，不回空字典。** 2026-08-07 把 `.env` 搬到
    `/opt/stacks/lightrag/` 時踩到：舊版在檔案不存在時 `return {}`，於是 16 支
    呼叫端全部拿到「沒有任何設定」**繼續跑**——`MINERU_IS_OCR` 沒了、
    `ENTITY_EXTRACTION_USE_JSON` 沒了，而畫面上一個錯誤訊息都沒有。
    那正是本專案一路在防的形狀：不是壞掉，是安靜地做錯事。

    `required=False` 只給「真的可以沒有設定」的呼叫端，目前沒有。
    """
    p = repo / ".env"
    if not p.exists():
        if not required:
            return {}
        raise EnvFileMissing(
            f"{p} 不存在。現役的 .env 在 dker 的 /opt/stacks/lightrag/.env"
            "（2026-08-07 搬出 git checkout，repo 根目錄放一條 symlink 指過去）。\n"
            "coder 上刻意沒有 .env —— 需要它的腳本只能在 dker 跑。")
    return parse_env_text(p.read_text())


def parse_env_text(text: str) -> dict[str, str]:
    """解析一份 env 檔的內容。

    ⚠ **不要改用 shell `source`。** `LIGHTRAG_PARSER` 的值含 `;`，shell 會把
    分號後面當成指令。這個解析器與 `.env` 的實際寫法綁在一起，覆寫檔必須用
    同一支 —— 兩份解析器對引號、空白、註解的處理只要差一點，覆寫就會
    「看起來設了但沒生效」。
    """
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip("'\"")
    return out


def overlay_env(base: Mapping[str, str], path: Path) -> tuple[dict[str, str], list[tuple[str, str]]]:
    """把一份覆寫檔疊在基底設定之上。回傳 (合併後的設定, [(鍵名, 覆寫/新增)])。

    **為什麼是疊加而不是取代**：受控比對的前提是「只變一個東西」。取代的話
    覆寫檔必須抄一份完整設定，而抄的過程中任何一個鍵抄錯或漏掉，就多變了一個
    變數 —— 而且是安靜地多變。疊加讓覆寫檔只寫真正要改的那幾行。

    **為什麼要回傳異動清單**：呼叫端必須把它印出來。鍵名打錯（`PP_EYE_A_MODLE`）
    時疊加會安靜地成功、什麼都沒改，而實驗結果看起來就像「換了模型但沒差」。
    標成「新增」的鍵就是要看的地方 —— 基底裡沒有這個名字。

    ⚠ 只回傳鍵名，**不要回傳值**：覆寫檔裡會有金鑰。
    """
    if not path.is_file():
        raise EnvFileMissing(f"--env-file 指定的 {path} 不存在")
    over = parse_env_text(path.read_text(encoding="utf-8"))
    merged = dict(base)
    changes: list[tuple[str, str]] = []
    for k, v in over.items():
        changes.append((k, "覆寫" if k in base else "新增"))
        merged[k] = v
    return merged, sorted(changes)


def resolve_env(repo: Path, argv: list[str] | None = None) -> tuple[dict[str, str], list[str]]:
    """讀 `.env`，命令列帶了 `--env-file` 就疊上去。回傳 (設定, 要印出來的行)。

    **必須在建 parser 之前呼叫**：`add_workspace_arg` 拿 `WORKSPACE` 當預設值，
    覆寫檔要能改 workspace 就得比它早。所以這裡用 `parse_known_args` 先撈一次；
    真正的 parser 之後照樣要宣告 `--env-file`，否則 `--help` 看不到它。

    **回傳訊息而不是自己印**：這個模組會被 import，不得 print
    （`tests/test_no_print_in_library_modules.py` 守著）。組裝在這裡、輸出在
    呼叫端，兩支 CLI 才不會各寫一份格式而慢慢長歪。
    """
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--env-file")
    known, _ = pre.parse_known_args(argv)
    env = load_env(repo)
    if not known.env_file:
        return env, []
    env, changes = overlay_env(env, Path(known.env_file))
    lines = [f"設定覆寫：{known.env_file}（{len(changes)} 個鍵）"]
    lines += [f"  {how}　{key}" for key, how in changes]
    lines.append("  ⚠ 標「新增」的鍵基底裡沒有這個名字 —— 不是刻意的話就是鍵名打錯了")
    return env, lines


POSTGRES_CONTAINER_DEFAULT = "lightrag-postgres"


def postgres_container(env: Mapping[str, str]) -> str:
    """回傳工具使用的 Postgres 容器名；設定缺席時使用專用實例。"""
    return (env.get("PP_PG_CONTAINER") or env.get("POSTGRES_HOST")
            or POSTGRES_CONTAINER_DEFAULT).strip()


def _workspace_value(v: str) -> str:
    """argparse 的 type：workspace 不得是空白。

    純空白會一路流進 SQL 的 where 條件、資料路徑與容器名，長出
    `lightrag-  ` 這種東西——**不報錯，只是什麼都對不到**。在入口擋掉。
    """
    v = v.strip()
    if not v:
        raise argparse.ArgumentTypeError("workspace 不能是空字串或純空白")
    return v


def add_workspace_arg(
    ap: argparse.ArgumentParser, env: dict[str, str], *, flag: str = "--workspace"
) -> None:
    """加上 `--workspace`：預設讀 .env，**.env 沒有就強制要求明確指定**。

    為什麼不給字面預設值：這些工具用 workspace 決定 docker 容器名、SQL 的
    where 條件與資料路徑，猜錯的預設**不會報錯**，只會安靜地對別的庫做事。

    **`default` 必須是「已求值的字串或 None」，不能是會讀 .env 的函式呼叫。**
    argparse 的 default 在 parser 建構時就求值——若 default 是
    `env_workspace()` 這種讀不到就 raise 的東西，缺 .env 時**連明確給
    `--workspace` 都救不了**，因為它在 argparse 看到你的參數之前就炸了。
    （2026-08-03 sol 終審抓到，實測 `extract-check.py --workspace X --help`
    在無 .env 時 rc=1。）
    """
    workspace = (env.get("WORKSPACE") or "").strip() or None
    ap.add_argument(flag, type=_workspace_value,
                    default=workspace, required=workspace is None)


def read_json(p: Path):
    return json.loads(p.read_text())
