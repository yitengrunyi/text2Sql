#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

export text2sql_env="${text2sql_env:-prod}"
export TEXT2SQL_NACOS_REGISTER=0
export TEXT2SQL_DISABLE_RABBITMQ=1
export TEXT2SQL_SOURCE_DB_USE_LOCAL=1
export TEXT2SQL_MYSQL4_USE_LOCAL=1
export TEXT2SQL_MYSQL1_USE_TEST_NACOS=1
export TEXT2SQL_MYSQL3_USE_TEST_NACOS=1
export TEXT2SQL_SQL_MODEL="${TEXT2SQL_SQL_MODEL:-gpt-4.1}"
export TEXT2SQL_FILTER_EXISTING_TABLES=1
export TEXT2SQL_DB_CONNECT_TIMEOUT="${TEXT2SQL_DB_CONNECT_TIMEOUT:-10}"
export TEXT2SQL_REDIS_PORT="${TEXT2SQL_REDIS_PORT:-6380}"
export TEXT2SQL_REDIS_URL="redis://127.0.0.1:${TEXT2SQL_REDIS_PORT}/0"
unset TEXT2SQL_LOCAL_SIM
unset TEXT2SQL_SOURCE_DB_USE_TEST_NACOS

docker compose -f docker-compose.local.yml up -d --wait redis

# 本地 MySQL(3307) 承载元数据库与 fiu，容器没起会导致应用启动即 ConnectionRefused
if ! docker ps --format '{{.Names}}' | grep -q '^text2sql-mysql$'; then
    if docker ps -a --format '{{.Names}}' | grep -q '^text2sql-mysql$'; then
        echo "Starting stopped container text2sql-mysql ..." >&2
        docker start text2sql-mysql
    else
        echo "本地 MySQL 容器 text2sql-mysql 不存在，请先创建(见 local_sim/README.md)。" >&2
        exit 1
    fi
fi
python_bin_preflight="${TEXT2SQL_PYTHON:-$project_dir/venv/bin/python}"
for _ in 1 2 3 4 5 6 7 8 9 10; do
    if "$python_bin_preflight" - <<'PYEOF' 2>/dev/null
import socket
s = socket.create_connection(("127.0.0.1", 3307), timeout=2)
s.close()
PYEOF
    then break; fi
    sleep 2
done
"$python_bin_preflight" - <<'PYEOF' || exit 1
import socket, pymysql
try:
    socket.create_connection(("127.0.0.1", 3307), timeout=3).close()
except OSError as exc:
    raise SystemExit(f"本地 MySQL 127.0.0.1:3307 不可达: {exc}")
conn = pymysql.connect(host="127.0.0.1", port=3307, user="root",
                       password="123QWEasd!*", connect_timeout=5)
with conn.cursor() as cur:
    cur.execute("SELECT SCHEMA_NAME FROM information_schema.SCHEMATA")
    schemas = {row[0] for row in cur.fetchall()}
conn.close()
missing = {"schema_metadata", "fiu"} - schemas
if missing:
    raise SystemExit(f"本地 MySQL 缺少数据库: {sorted(missing)}，请先执行 local_sim/build_schema_metadata.py build --replace --activate 与 build_fiu.py")
PYEOF

python_bin="${TEXT2SQL_PYTHON:-$project_dir/venv/bin/python}"
if [[ ! -x "$python_bin" ]]; then
    echo "Python executable not found: $python_bin" >&2
    exit 1
fi

echo "Starting Text2SQL at http://127.0.0.1:5903"
exec "$python_bin" app.py
