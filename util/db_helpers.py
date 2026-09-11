import logging

import aiohttp
import openai
import os

import pandas as pd
from sqlalchemy import text
from sqlalchemy.dialects.mysql import aiomysql
import asyncio
import sys


import oracledb

import aiomysql
from typing import Tuple, Any

# 设置递归限制
sys.setrecursionlimit(10000)


from common.middleware.db_utils import source_db_engine






def get_dbtype_from_domain_one(domain_one: str) -> str:
    """
    判断一级域对应的数据库类型

    参数:
    domain_one (str): 一级域名称。

    返回:
    str: 判断结果。
    """
    if domain_one in ["基金相关", "内部信息查询"]:
        return "MYSQL-1"
    elif domain_one in ["个股相关", "指数相关", "基础码表"]:
        return "MYSQL-2"
    else:
        assert 0, f"{domain_one} 为未定义一级域！！\n"
        return None




def query_exec_db(sql: str):
    """
    在数据库上执行 SQL 查询。

    参数:
    sql (str): 要执行的 SQL 查询语句。

    返回:
    ResultProxy: 执行查询的结果。
    """
    with source_db_engine.connect() as connection:
        return connection.execute(text(sql)).fetchall()


def run_with_new_event_loop(func, *args, **kwargs):
    """
    使用新的 asyncio 事件循环运行函数。

    参数:
    func (Callable): 要运行的函数。
    *args: 传递给函数的参数。
    **kwargs: 传递给函数的关键字参数。

    返回:
    Any: 函数调用的结果。
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return func(*args, **kwargs)
    finally:
        loop.close()


def get_or_create_event_loop():
    """
    获取或创建 asyncio 事件循环。

    返回:
    AbstractEventLoop: 当前的事件循环或新的事件循环（如果不存在）。
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop


async def query_from_db(query: str):
    """
    异步查询数据库。

    参数:
    query (str): 要执行的 SQL 查询语句。

    返回:
    List: 查询的结果。
    """
    data = await get_or_create_event_loop().run_in_executor(None, query_exec_db, query)
    return data


async def insert_data_to_mysql(sql: str, params, pool) -> Tuple[int, Any]:
    """
    异步向 MySQL 数据库插入数据（带参数化查询），设置超时限制

    参数:
    sql (str): 要执行的 INSERT SQL 语句（建议使用参数化查询）
    params (list): SQL 参数列表
    pool: MySQL 异步连接池

    返回:
    Tuple[int, Any]: 状态码和影响行数/错误信息
    """
    status_code = 200
    return_res = None
    conn = None
    cursor = None

    try:
        # 从连接池获取连接并创建游标
        conn = await pool.acquire()
        cursor = await conn.cursor()

        # 执行带超时的插入操作（参数化查询）
        await asyncio.wait_for(
            cursor.execute(sql, params),
            timeout=180
        )

        # 提交事务
        await conn.commit()

        # 获取影响行数
        affected_rows = cursor.rowcount
        return_res = {"affected_rows": affected_rows, "message": "Insert successful"}
        print(f"Inserted {affected_rows} rows")

    except asyncio.TimeoutError:
        await conn.rollback()
        status_code = 500
        return_res = "Insert operation timed out"
    except aiomysql.IntegrityError as e:
        await conn.rollback()
        status_code = 500
        return_res = f"Data integrity error: {str(e)}"
    except aiomysql.Error as e:
        await conn.rollback()
        status_code = 500
        return_res = f"MySQL error: {str(e)}"
    except Exception as e:
        await conn.rollback()
        status_code = 500
        return_res = f"Unexpected error: {str(e)}"
    finally:
        # 资源释放
        if cursor and not cursor.closed:
            await cursor.close()
        if conn:
            pool.release(conn)

    return status_code, return_res

async def fetch_data_from_MYSQL(final_sql: str, pool) -> Tuple[int, Any]:
    """
    从 MySQL 数据库中获取数据（异步），设置1分钟超时限制。

    参数:
    final_sql (str): 要执行的 SQL 查询。
    pool: MySQL 异步连接池。

    返回:
    Tuple[int, Any]: 状态码和查询结果或错误信息。
    """
    status_code = 200
    return_res = None
    conn = None
    cursor = None

    async def execute_and_fetch(cursor, final_sql: str):
        """封装执行SQL和获取结果的操作"""
        await cursor.execute(final_sql)
        return await cursor.fetchmany(1000)

    try:
        # 从连接池获取连接并创建游标
        conn = await pool.acquire()
        cursor = await conn.cursor()
        print("Cursor obtained successfully.")

        # 执行带超时的查询（总超时60秒）
        print(f"Executing SQL: {final_sql}")
        rows = await asyncio.wait_for(
            execute_and_fetch(cursor, final_sql),
            timeout=180
        )
        print("Query executed successfully.")

        # 处理查询结果
        field_names = [desc[0] for desc in cursor.description]
        if rows:
            df = pd.DataFrame(rows, columns=field_names)
            return_res = df
            print(f"Fetched {len(rows)} rows.")
        else:
            return_res = "No rows fetched. 查找结果为空，请检查SQL语句"
            status_code = 500
            print(return_res)

    except asyncio.TimeoutError:
        status_code = 500
        return_res = "Query execution timed out."
        print(return_res)
        # 显式关闭游标以终止可能仍在进行的查询
        if cursor:
            await cursor.close()
            print("Cursor closed due to timeout.")
    except aiomysql.Error as e:
        status_code = 500
        return_res = f"MySQL Database error: {str(e)}"
        print(return_res)
    except Exception as e:
        status_code = 500
        return_res = f"An unexpected error occurred: {str(e)}"
        print(return_res)
    finally:
        # 确保资源释放
        try:
            if cursor and not cursor.closed:
                await cursor.close()
                print("Cursor closed successfully.")
            if conn:
                pool.release(conn)
                print("Connection released back to pool.")
        except Exception as e:
            logging.error(f"Error closing resources: {str(e)}")

    return status_code, return_res
async def fetch_data_from_oracle(final_sql: str, username: str, password: str, dsn: str, schema: str = "ODSJY") -> \
        Tuple[int, Any]:
    """
    从 Oracle 数据库中获取数据（异步）。

    参数:
    final_sql (str): 要执行的 SQL 查询。
    username (str): 数据库用户名。
    password (str): 数据库密码。
    dsn (str): 数据库服务名。
    schema (str): 要切换到的模式，默认为 "ODSJY"。

    返回:
    Tuple[int, Any]: 状态码和查询结果或错误信息。
    """
    status_code = 200
    return_res = None
    cursor = None  # 初始化游标变量
    connection = None

    try:
        # 使用 asyncio.to_thread 将同步操作放入线程池，并使用关键字参数传递连接信息
        connection = await asyncio.to_thread(oracledb.connect, user=username, password=password, dsn=dsn)
        print("Database connection established successfully.")

        # 创建一个游标
        cursor = await asyncio.to_thread(connection.cursor)
        print("Cursor obtained successfully.")

        # 切换到特定模式
        await asyncio.to_thread(cursor.execute, f"ALTER SESSION SET CURRENT_SCHEMA = {schema}")
        print(f"Schema switched to {schema} successfully.")

        # 执行SQL查询
        await asyncio.to_thread(cursor.execute, final_sql)
        print("Fetch query executed successfully.")

        # 获取查询结果
        rows = await asyncio.to_thread(cursor.fetchmany, 100)  # 只获取前100条记录
        field_names = [desc[0] for desc in cursor.description]  # 获取字段名称

        # 将数据转换为DataFrame
        if rows:
            # 处理LOB字段
            processed_rows = [
                tuple(col.read() if isinstance(col, oracledb.LOB) else col for col in row)
                for row in rows
            ]
            df = pd.DataFrame(processed_rows, columns=field_names)
            return_res = df
        else:
            return_res = "No rows fetched. 查找结果为空，请检查SQL语句"
            status_code = 500
            print("No rows fetched. 查找结果为空，请检查SQL语句")

    except oracledb.DatabaseError as e:
        status_code = 500
        error, = e.args
        return_res = f"Oracle Database error code: {error.code}, message: {error.message}"
        print(return_res)

    except Exception as e:
        status_code = 500
        return_res = f"An unexpected error occurred: {str(e)}"
        print(return_res)

    finally:
        # 关闭游标和连接
        try:
            if cursor:
                await asyncio.to_thread(cursor.close)
                print("Cursor closed successfully.")
            if connection:
                await asyncio.to_thread(connection.close)
                print("Database connection closed successfully.")
        except oracledb.DatabaseError as e:
            error, = e.args
            print("Error closing connection:", error.message)

    # 返回结果
    return status_code, return_res





if __name__ == "__main__":
    username = 'ngdp_readonly'
