# -*- coding: utf-8 -*-
"""本地模拟库冒烟测试: 走 pipeline 真实执行路径 (TEXT2SQL_LOCAL_SIM=1 下运行)。"""
import asyncio
import sys

sys.path.insert(0, "/Users/mdb/project/text2sql_renew")


async def main():
    from common.middleware.db_utils import initialize_all_pools
    await initialize_all_pools()
    print("-- 连接池初始化 OK (mysql4 已启用)")

    # ---- 路径1: 美股 (text_to_sql_exec.execute_sql -> MYSQL-4) ----
    from service.sql_executor.text_to_sql_exec import execute_sql
    sql_us = """
    SELECT a.COMB_SYMBOL, a.CSNAME, DATE_FORMAT(t.F001D,'%%Y') AS 年份,
           ROUND(t.F048N/100,1) AS 营收_亿美元, ROUND(t.F032N/100,1) AS 净利润_亿美元,
           ROUND(t.F016N,2) AS EPS
    FROM AMERICAN_STOCK_MAIN a
    INNER JOIN VIEW_COM3103_CUM t ON a.FIU_ID = t.FIU_ID
    WHERE a.COMB_SYMBOL IN ('TSLA.US','NVDA.US') AND t.F003V = 'FY'
      AND t.F001D >= '2023-01-01'
    ORDER BY a.COMB_SYMBOL, t.F001D
    """
    code, res = await execute_sql(sql_us, "MYSQL-4")
    print(f"-- 美股 execute_sql 状态={code}")
    print(res[:600] if isinstance(res, str) else res)

    # ---- 路径2: 宏观 Doris (orcl_edb_fetch) ----
    from orcl_edb_fetch import init_doris_engine, fetch_data_from_doris
    await init_doris_engine()
    sql_edb = """
    SELECT DATE_FORMAT(t1.PERIOD_DATE, '%Y-%m') AS `月份`,
       MAX(CASE WHEN t2.SHOW_NAME_SHORT = '美国:CPI:同比(月)' THEN ROUND(t1.DATA_VALUE, 2) END) AS `CPI同比(%)`
    FROM ECO_DATA_GLOBE_USA t1
    JOIN EDB_INDIC_DATA t2 ON t2.DATA_TABLE = 'ECO_DATA_GLOBE_USA'
         AND t2.ind_der_code = t1.ind_der_code
    WHERE t2.SHOW_NAME_SHORT = '美国:CPI:同比(月)'
      AND t1.PERIOD_DATE >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)
      AND t1.DATA_VALUE IS NOT NULL
    GROUP BY DATE_FORMAT(t1.PERIOD_DATE, '%Y-%m')
    ORDER BY 1 DESC
    LIMIT 3
    """
    code2, res2 = await fetch_data_from_doris(sql_edb)
    print(f"-- EDB fetch_data_from_doris 状态={code2}")
    print(str(res2)[:600])


asyncio.run(main())
