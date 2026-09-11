#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评测集构建用的只读 DB 查询助手（MYSQL-1/2/4）。

用法:
  # 单条 SQL
  ./venv/bin/python evals/dbx.py --source MYSQL-2 --sql "SELECT ..."
  # 批量（JSON 数组，输出 JSON 数组）
  ./venv/bin/python evals/dbx.py --source MYSQL-2 --batch batch.json
  # 导出某库全量表/列结构注释到 evals/schema_<source>.json
  ./venv/bin/python evals/dbx.py --source MYSQL-2 --dump-schema

作为模块:
  from evals.dbx import run_sql, SOURCE_POOL
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 环境必须先于 db_utils 的 import 生效（与 run_local_remote.sh 一致）
os.environ.setdefault("text2sql_env", "prod")
os.environ.setdefault("TEXT2SQL_NACOS_REGISTER", "0")
os.environ.setdefault("TEXT2SQL_DISABLE_RABBITMQ", "1")
os.environ.setdefault("TEXT2SQL_SOURCE_DB_USE_LOCAL", "1")
os.environ.setdefault("TEXT2SQL_MYSQL4_USE_LOCAL", "1")
os.environ.setdefault("TEXT2SQL_MYSQL1_USE_TEST_NACOS", "1")
os.environ.setdefault("TEXT2SQL_MYSQL3_USE_TEST_NACOS", "1")
os.environ.setdefault("TEXT2SQL_SQL_MODEL", "gpt-4.1")
os.environ.setdefault("TEXT2SQL_FILTER_EXISTING_TABLES", "1")
os.environ.setdefault("TEXT2SQL_DB_CONNECT_TIMEOUT", "10")
os.environ.setdefault("TEXT2SQL_REDIS_URL", "redis://127.0.0.1:6380/0")
os.environ.pop("TEXT2SQL_LOCAL_SIM", None)

import asyncio
import json
import re
import time

SOURCE_POOL = {
    "MYSQL-1": ("mysql1", "FUND_INFO"),  # 基金·测试库
    "MYSQL-2": ("mysql2", None),         # 个股/指数·生产只读 juling
    "MYSQL-4": ("mysql4", "fiu"),        # 美股·本地模拟库
}

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|load_file|into\s+(out|dump)file)\b",
    re.IGNORECASE,
)


def assert_readonly(sql: str) -> None:
    stripped = (sql or "").strip().rstrip(";").strip()
    if not stripped.lower().startswith(("select", "with", "show", "desc", "describe", "explain")):
        raise ValueError("只允许 SELECT/WITH/SHOW/DESC/EXPLAIN")
    if ";" in stripped:
        raise ValueError("多语句不允许")
    if _FORBIDDEN.search(stripped):
        raise ValueError("包含写操作关键字")


async def run_sql(source: str, sql: str, limit: int = 50) -> dict:
    """执行只读 SQL，返回 {status, columns, rows, row_count, elapsed_ms}。"""
    assert_readonly(sql)
    from common.middleware.db_utils import initialize_all_pools, get_pool

    pool_name, _ = SOURCE_POOL[source]
    started = time.perf_counter()
    conn = await get_pool(pool_name).acquire()
    try:
        async with conn.cursor() as cursor:
            await cursor.execute(sql)
            rows = await cursor.fetchmany(limit)
            columns = [c[0] for c in cursor.description] if cursor.description else []
    finally:
        get_pool(pool_name).release(conn)
    return {
        "status": 200,
        "columns": columns,
        "rows": [[None if v is None else (str(v) if not isinstance(v, (int, float)) else v) for v in r] for r in rows],
        "row_count": len(rows),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
    }


async def dump_schema(source: str) -> dict:
    """导出目标库全量表→列(含注释)结构。"""
    pool_name, database = SOURCE_POOL[source]
    if database is None:
        from common.middleware.db_utils import mysql2_config

        database = mysql2_config["db"]
    from common.middleware.db_utils import initialize_all_pools, get_pool

    await initialize_all_pools()
    conn = await get_pool(pool_name).acquire()
    try:
        async with conn.cursor() as cursor:
            await cursor.execute(
                """
                SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, COLUMN_COMMENT
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s
                ORDER BY TABLE_NAME, ORDINAL_POSITION
                """,
                (database,),
            )
            rows = await cursor.fetchall()
            await cursor.execute(
                """
                SELECT TABLE_NAME, TABLE_ROWS, TABLE_COMMENT
                FROM information_schema.TABLES
                WHERE TABLE_SCHEMA = %s
                """,
                (database,),
            )
            tables = {r[0]: {"row_estimate": r[1], "comment": r[2]} for r in await cursor.fetchall()}
    finally:
        get_pool(pool_name).release(conn)
    schema: dict = {}
    for tname, cname, ctype, ccomment in rows:
        entry = schema.setdefault(tname, {"comment": tables.get(tname, {}).get("comment", ""), "row_estimate": tables.get(tname, {}).get("row_estimate"), "columns": {}})
        entry["columns"][cname] = {"type": ctype, "comment": ccomment}
    return schema


async def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="只读 DB 查询助手")
    parser.add_argument("--source", required=True, choices=sorted(SOURCE_POOL))
    parser.add_argument("--sql")
    parser.add_argument("--batch", help="JSON 文件: [[label, sql], ...]")
    parser.add_argument("--dump-schema", action="store_true")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()

    from common.middleware.db_utils import initialize_all_pools

    await initialize_all_pools()
    if args.dump_schema:
        out = f"evals/schema_{args.source}.json"
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(await dump_schema(args.source), fh, ensure_ascii=False, indent=1)
        print(f"schema dumped: {out}")
        return 0
    if args.sql:
        print(json.dumps(await run_sql(args.source, args.sql, args.limit), ensure_ascii=False))
        return 0
    if args.batch:
        items = json.loads(open(args.batch, encoding="utf-8").read())
        results = []
        for label, sql in items:
            try:
                results.append({"label": label, "result": await run_sql(args.source, sql, args.limit)})
            except Exception as exc:
                results.append({"label": label, "error": f"{type(exc).__name__}: {exc}"})
        print(json.dumps(results, ensure_ascii=False, indent=1))
        return 0
    parser.error("需要 --sql / --batch / --dump-schema 之一")
    return 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
