#!/usr/bin/env bash
# 比對舊自製管線 vs LightRAG 1.5.5 對同一份文件的索引結果。
#
#   ./scripts/compare.sh 'Equivalent' acoustics_v155
#
# 舊管線: deeptutor DB / workspace acoustics_books
# 新管線: $NEW_DB（預設 lightrag）/ workspace 由第二參數指定
set -euo pipefail

DOC="${1:?用法: $0 <檔名關鍵字> <新workspace>}"
NEW_WS="${2:?用法: $0 <檔名關鍵字> <新workspace>}"
OLD_WS=acoustics_books
# 新管線的資料庫。舊的測試資料在 lr15_test，正式 stack 用 lightrag。
NEW_DB="${NEW_DB:-lightrag}"
PG="docker exec deeptutor-v4-postgres psql -U deeptutor -tAF| "

# 掉字偵測器 — 已驗證版本，務必用 \y 而非兩側 \s（見 deeptutor-mineru-drops-characters 記憶）
MANGLED="content ~ '(?:\\s+[a-z]{1,2}\\y){5,}'"
# AI 評註偵測 — 舊管線的模態摘要前綴
COMMENT="content ~ '(Header Content|Mathematical Equation|Table|Image) Analysis:'"

q() { $PG -d "$1" -c "$2" 2>/dev/null || echo "n/a"; }

echo "文件關鍵字: $DOC"
echo "================================================================"
printf '%-26s %14s %14s\n' "指標" "舊管線" "LightRAG1.5.5"
echo "----------------------------------------------------------------"

row() { printf '%-26s %14s %14s\n' "$1" "$2" "$3"; }

# --- chunks ---
o=$(q deeptutor  "select count(*) from lightrag_doc_chunks where workspace='$OLD_WS' and file_path ilike '%$DOC%'")
n=$(q "$NEW_DB" "select count(*) from lightrag_doc_chunks where workspace='$NEW_WS' and file_path ilike '%$DOC%'")
row "chunks" "$o" "$n"

# --- 總字元 ---
o=$(q deeptutor  "select coalesce(sum(length(content)),0) from lightrag_doc_chunks where workspace='$OLD_WS' and file_path ilike '%$DOC%'")
n=$(q "$NEW_DB" "select coalesce(sum(length(content)),0) from lightrag_doc_chunks where workspace='$NEW_WS' and file_path ilike '%$DOC%'")
row "chunk 總字元" "$o" "$n"

# --- 含 AI 評註的 chunk ---
o=$(q deeptutor  "select count(*) from lightrag_doc_chunks where workspace='$OLD_WS' and file_path ilike '%$DOC%' and $COMMENT")
n=$(q "$NEW_DB" "select count(*) from lightrag_doc_chunks where workspace='$NEW_WS' and file_path ilike '%$DOC%' and $COMMENT")
row "含 AI 評註的 chunk" "$o" "$n"

# --- MinerU 掉字 chunk（is_ocr 未開的話應 >0）---
o=$(q deeptutor  "select count(*) from lightrag_doc_chunks where workspace='$OLD_WS' and file_path ilike '%$DOC%' and $MANGLED")
n=$(q "$NEW_DB" "select count(*) from lightrag_doc_chunks where workspace='$NEW_WS' and file_path ilike '%$DOC%' and $MANGLED")
row "掉字 chunk" "$o" "$n"

# --- entities / relations ---
o=$(q deeptutor  "select count(*) from lightrag_vdb_entity where workspace='$OLD_WS' and file_path ilike '%$DOC%'")
n=$(q "$NEW_DB" "select count(*) from lightrag_vdb_entity_text_embedding_3_small_1536d where workspace='$NEW_WS' and file_path ilike '%$DOC%'")
row "entities" "$o" "$n"

o=$(q deeptutor  "select count(*) from lightrag_vdb_relation where workspace='$OLD_WS' and file_path ilike '%$DOC%'")
n=$(q "$NEW_DB" "select count(*) from lightrag_vdb_relation_text_embedding_3_small_1536d where workspace='$NEW_WS' and file_path ilike '%$DOC%'")
row "relations" "$o" "$n"

# --- 被丟棄的正文（舊管線的 failed 重複記錄）---
o=$(q deeptutor  "select coalesce(sum(content_length),0) from lightrag_doc_status where workspace='$OLD_WS' and file_path ilike '%$DOC%' and status='failed'")
n=$(q "$NEW_DB" "select coalesce(sum(content_length),0) from lightrag_doc_status where workspace='$NEW_WS' and file_path ilike '%$DOC%' and status='failed'")
row "被丟棄正文字元" "$o" "$n"

echo "================================================================"
echo "Neo4j 圖譜節點/邊："
for ws in "$OLD_WS" "$NEW_WS"; do
  r=$(docker exec deeptutor-v4-neo4j cypher-shell -u neo4j -p '2guiaaji' --format plain \
      "MATCH (n:\`$ws\`) WITH count(n) AS nodes MATCH (:\`$ws\`)-[r]-(:\`$ws\`) RETURN nodes, count(r)/2 AS edges;" 2>/dev/null | tail -1)
  printf '  %-20s %s\n' "$ws" "${r:-n/a}"
done
echo
echo "註：Neo4j 數字是整個 workspace（跨文件），非單一文件。"
