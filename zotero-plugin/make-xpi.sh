#!/usr/bin/env bash
# 打包成 .xpi（就是一個 zip，副檔名不同）。
#
# ⚠ **要從外掛目錄的內容開始壓，不是壓那個目錄本身** —— manifest.json 必須
# 在壓縮檔的根，多包一層 Zotero 會說「不是合法的外掛」而且不告訴你為什麼。
#
# 用 python3 的 zipfile 而不是 `zip`：coder 上沒有 `zip`，而 python3 本來就是
# 這個專案的依賴。少一個「在我這台可以」的理由。
set -euo pipefail

cd "$(dirname "$0")"

VERSION=$(python3 -c 'import json,pathlib;print(json.loads(pathlib.Path("manifest.json").read_text())["version"])')
OUT="lightrag-inbox-${VERSION}.xpi"
rm -f "$OUT"

# tests/ 不進外掛：它是給 node 跑的，裝進 Zotero 只是多佔空間。
python3 - "$OUT" <<'PY'
import sys, zipfile
from pathlib import Path

out = Path(sys.argv[1])
members = ["manifest.json", "bootstrap.js"]
for directory in ("lib", "locale"):
    members += [str(p) for p in sorted(Path(directory).rglob("*")) if p.is_file()]

with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
    for name in members:
        zf.write(name, name)

print(out)
for name in members:
    print("  " + name)
PY
