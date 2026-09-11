#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""环境冒烟检查：网关 / Nacos / 三个业务库 / 本地 Redis。"""
import os, sys, time, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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

async def main():
    ok = True
    # 1) pools
    from common.middleware.db_utils import initialize_all_pools
    from service.sql_executor.text_to_sql_exec import execute_sql
    await initialize_all_pools()
    for src in ("MYSQL-1", "MYSQL-2", "MYSQL-4"):
        try:
            t0 = time.perf_counter()
            res = await execute_sql("SELECT 1 AS v", src)
            dt = time.perf_counter() - t0
            print(f"[OK] {src}: status={res[0]} {str(res[1])[:100]} ({dt:.2f}s)")
        except Exception as exc:
            ok = False
            print(f"[FAIL] {src}: {type(exc).__name__}: {exc}")
    # 2) LLM gateway
    try:
        from util.model_helpers import call_llm
        t0 = time.perf_counter()
        out = await call_llm("回复OK两个字母即可", model="gpt-4.1", temperature=0)
        print(f"[OK] LLM gpt-4.1: {str(out)[:80]} ({time.perf_counter()-t0:.1f}s)")
    except Exception as exc:
        ok = False
        print(f"[FAIL] LLM: {type(exc).__name__}: {exc}")
    # 3) redis
    try:
        import redis
        r = redis.Redis.from_url(os.environ["TEXT2SQL_REDIS_URL"])
        r.ping()
        print("[OK] redis 6380")
    except Exception as exc:
        ok = False
        print(f"[FAIL] redis: {exc}")
    print("SMOKE:", "PASS" if ok else "FAIL")
    return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
