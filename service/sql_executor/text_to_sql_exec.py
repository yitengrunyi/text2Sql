import os
import re

from common.middleware.db_utils import get_mysql1_pool, get_mysql2_pool, get_mysql4_pool
from util.db_helpers import fetch_data_from_MYSQL

from typing import List, Tuple

# 只读安全闸：生成的 SQL 仅允许单条 SELECT/WITH/SHOW；拦截写操作与多语句。
# 环境变量 TEXT2SQL_READONLY_GUARD=0 可关闭（默认开启）。
_READ_ONLY_GUARD_DISABLED = os.environ.get("TEXT2SQL_READONLY_GUARD", "1") in ("0", "false", "False")
_WRITE_KEYWORDS = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|rename|grant|revoke|call|lock|unlock|load_file|outfile|dumpfile)\b",
    re.IGNORECASE,
)


def _readonly_guard(sql: str):
    """返回 (403, 拦截原因) 表示拦截；None 表示放行。"""
    if _READ_ONLY_GUARD_DISABLED:
        return None
    stripped = (sql or "").strip().rstrip(";").strip()
    if not stripped:
        return (403, "ReadOnlyGuard: SQL 为空，已拦截")
    if not stripped.lower().startswith(("select", "with", "show")):
        return (403, "ReadOnlyGuard: 只允许 SELECT/WITH/SHOW 只读查询，已拦截")
    if ";" in stripped:
        return (403, "ReadOnlyGuard: 检测到多语句执行，已拦截")
    if _WRITE_KEYWORDS.search(stripped):
        return (403, "ReadOnlyGuard: 检测到写操作/危险关键字，已拦截")
    return None


async def execute_sql(sql: str, dbtype: str) -> Tuple[
    int, str]:
    guarded = _readonly_guard(sql)
    if guarded is not None:
        return guarded
    status_code, result = None, None
    if dbtype == "MYSQL-1":
        status_code, result = await fetch_data_from_MYSQL(sql,get_mysql1_pool())
    elif dbtype == "MYSQL-2":
        status_code, result = await fetch_data_from_MYSQL(sql,get_mysql2_pool())
    #美股数据库
    elif dbtype == "MYSQL-4":
        status_code, result = await fetch_data_from_MYSQL(sql,get_mysql4_pool())
    #测试edb库
    # elif dbtype == "MYSQL-5":
    #     status_code, result = await fetch_data_from_MYSQL(sql, get_mysql5_pool())
    else:
        assert dbtype in ["MYSQL-1", "MYSQL-2"], f"{dbtype}为不支持查询的数据库类型！\n"

    return status_code, result