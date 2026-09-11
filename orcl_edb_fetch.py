import pandas as pd
import asyncio
import os
from typing import Tuple, Any, Optional
import logging
import time
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import QueuePool
from util.data_formater_helpers import df_to_table, data_limit_num, get_filter_colunms_name
from config.nacos.nacos_service import config


# ===================== 全局 Doris 连接池 (SQLAlchemy Engine) =====================
_DORIS_ENGINE: Optional[Engine] = None


async def init_doris_engine() -> None:
    """
    创建 SQLAlchemy Engine 连接 Doris（MySQL 协议）。
    从 nacos doris_db_config 读取连接信息，全局单例，只初始化一次。
    内部使用 QueuePool 实现持久连接池，用时 acquire、用完 release。
    """
    global _DORIS_ENGINE
    if _DORIS_ENGINE is not None:
        return

    cfg = config.get("doris_db_config")
    # 本地模拟模式(TEXT2SQL_LOCAL_SIM=1): Doris 指向本机 docker MySQL(local_sim/build_tldata.py)
    if os.environ.get("TEXT2SQL_LOCAL_SIM"):
        cfg = {"host": "127.0.0.1", "port": "3307", "user": "root",
               "password": "123QWEasd!*", "db": "TLDATA"}
    if not cfg:
        logging.warning("doris_db_config not found in Nacos config; skipping Doris engine init.")
        return

    required_keys = ["host", "port", "user", "password", "db"]
    missing = [k for k in required_keys if k not in cfg or cfg.get(k) in (None, "")]
    if missing:
        logging.warning("doris_db_config missing keys: %s; skipping Doris engine init.", ",".join(missing))
        return

    host = cfg["host"]
    port = int(cfg["port"])
    user = cfg["user"]
    password = cfg["password"]
    db = cfg["db"]

    url = f"mysql+pymysql://{user}:{password}@{host}:{port}/{db}?charset=utf8mb4"

    _DORIS_ENGINE = await asyncio.to_thread(
        create_engine,
        url,
        poolclass=QueuePool,
        pool_size=5,
        max_overflow=10,
        pool_recycle=3600,
        pool_pre_ping=True,
    )
    logging.info("Doris 连接池创建成功：host=%s, port=%s, db=%s, pool_size=5", host, port, db)


async def close_doris_engine() -> None:
    """应用退出前调用，优雅关闭连接池。"""
    global _DORIS_ENGINE
    if _DORIS_ENGINE:
        await asyncio.to_thread(_DORIS_ENGINE.dispose)
        logging.info("Doris 连接池已关闭")
        _DORIS_ENGINE = None


async def fetch_data_from_doris(final_sql: str, **kwargs) -> Tuple[int, Any]:
    """
    从 Doris 数据库获取数据（异步，连接池 acquire/release）。

    参数:
        final_sql (str): 要执行的 SQL 查询。
        **kwargs: 兼容旧接口的多余参数，均忽略。

    返回:
        Tuple[int, Any]: 状态码和查询结果(DataFrame)或错误信息(str)。
    """
    global _DORIS_ENGINE
    status_code = 200
    return_res = None

    try:
        if _DORIS_ENGINE is None:
            await init_doris_engine()
        if _DORIS_ENGINE is None:
            return 500, "Doris 配置缺失或不可用（doris_db_config 未设置）"

        def _run_query(sql: str):
            # 从连接池 acquire 一个连接
            conn = _DORIS_ENGINE.connect()
            try:
                logging.info("Doris 连接 acquired（id=%s）", id(conn))
                result = conn.execute(text(sql))
                columns = list(result.keys())
                rows = result.fetchall()
                return rows, columns
            finally:
                # 归还连接到池（release）
                conn.close()
                logging.info("Doris 连接 released（id=%s）", id(conn))

        rows, columns = await asyncio.to_thread(_run_query, final_sql)

        if rows:
            df = pd.DataFrame(rows, columns=columns)
            return_res = df.head(1000)
        else:
            return_res = "No rows fetched. 查找结果为空，请检查SQL语句"
            status_code = 500
            logging.info("Doris 查询无结果")

    except Exception as e:
        status_code = 500
        return_res = f"Doris 查询错误: {str(e)}"
        logging.error(return_res)

    return status_code, return_res


async def execute_final_sql(
    cleaned_sql_query: str,
    query: str,
    query_info
):
    """
    执行最终SQL查询并返回 (status_code, final_sql_result, formatted_output)。
    """
    execute_start_time = time.time()
    status_code, final_sql_result = await fetch_data_from_doris(cleaned_sql_query)
    logging.info(f"▌SQL查询执行完成，耗时: {time.time() - execute_start_time:.2f}s")

    # 格式化输出给用户
    if isinstance(final_sql_result, str):
        formatted_output = final_sql_result
    else:
        key_for_table = f"{query_info.get('questionId')}_0"
        columns_to_drop = await get_filter_colunms_name(cleaned_sql_query)
        formatted_output = df_to_table(key_for_table, columns_to_drop, final_sql_result)

    logging.info(
        f"用户 {query_info.get('userName')} 问题 {query} "
        f"第一次执行结果 status_code: {status_code}, result: {final_sql_result}"
    )

    return status_code, final_sql_result, formatted_output


# ===================== 兼容旧函数名（别名） =====================
fetch_data_from_oracle = fetch_data_from_doris
init_oracle_pool = init_doris_engine
close_oracle_pool = close_doris_engine


if __name__ == "__main__":
    sql = """
    SELECT DATE_FORMAT(t1.PERIOD_DATE, '%Y-%m-%d') AS `日期`,
       MAX(CASE WHEN t2.ind_der_code = 'CN_GDP_YOY' THEN ROUND(t1.DATA_VALUE, 2) END) AS `GDP增速(%)`,
       MAX(CASE WHEN t2.ind_der_code = 'CN_GDP_TOTAL' THEN ROUND(t1.DATA_VALUE, 2) END) AS `GDP总量(亿元)`
    FROM EDB_CN_GDP t1
    JOIN EDB_INDIC_DATA t2 ON t2.DATA_TABLE = 'EDB_CN_GDP'
    WHERE t2.ind_der_code IN ('CN_GDP_YOY', 'CN_GDP_TOTAL')
      AND t1.PERIOD_DATE >= DATE_SUB(CURDATE(), INTERVAL 10 YEAR)
      AND t1.DATA_VALUE IS NOT NULL
    GROUP BY DATE_FORMAT(t1.PERIOD_DATE, '%Y-%m-%d')
    ORDER BY t1.PERIOD_DATE DESC
    """
    print(asyncio.run(fetch_data_from_doris(sql)))
