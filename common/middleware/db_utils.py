import asyncio
import os

import pandas as pd
import pymysql
import yaml
from sqlalchemy.orm import sessionmaker
os.environ["SQLALCHEMY_SILENCE_UBER_WARNING"] = "1"
from sqlalchemy import MetaData, create_engine
from sqlalchemy.pool import QueuePool
from config.nacos.nacos_service import config, fetch_nacos_config, TEST_SERVER
from sqlalchemy import text

import aiomysql
from sqlalchemy.ext.asyncio import create_async_engine


def _env_enabled(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


_test_nacos_config = None


def _get_test_nacos_config():
    global _test_nacos_config
    if _test_nacos_config is None:
        _test_nacos_config = fetch_nacos_config(TEST_SERVER)
        # nacos 客户端在服务器不可用时静默回退本地快照，快照不区分环境，
        # 内容可能指向生产主机(被白名单拦截后表现为启动后莫名超时)。
        # 仅在使用测试 Nacos 的本地远程模式下校验，不影响生产启动。
        for _key in ("source_db_config", "mysql1_config", "mysql3_config"):
            _host = str(_test_nacos_config.get(_key, {}).get("host", ""))
            if _host and not _host.startswith("192.168."):
                raise RuntimeError(
                    f"测试 Nacos({TEST_SERVER}) 配置异常: {_key}.host={_host} "
                    "不在私网段，疑似回退到了指向生产的本地快照，"
                    "请检查 VPN/测试 Nacos 后重启。"
                )
    return _test_nacos_config


source_db_config = config.get('source_db_config', {})
if _env_enabled("TEXT2SQL_SOURCE_DB_USE_LOCAL"):
    source_db_config = {
        "host": os.environ.get("TEXT2SQL_LOCAL_METADATA_HOST", "127.0.0.1"),
        "port": int(os.environ.get("TEXT2SQL_LOCAL_METADATA_PORT", "3307")),
        "user": os.environ.get("TEXT2SQL_LOCAL_METADATA_USER", "root"),
        "password": os.environ.get("TEXT2SQL_LOCAL_METADATA_PASSWORD", "123QWEasd!*"),
        "db": os.environ.get("TEXT2SQL_LOCAL_METADATA_DB", "schema_metadata"),
    }
    print(
        "Source metadata DB uses local config: "
        f"host={source_db_config['host']}, port={source_db_config['port']}, "
        f"db={source_db_config['db']}"
    )
elif _env_enabled("TEXT2SQL_SOURCE_DB_USE_TEST_NACOS"):
    source_db_config = _get_test_nacos_config().get('source_db_config', {})
    print(
        "Source metadata DB uses test Nacos config: "
        f"host={source_db_config.get('host')}, port={source_db_config.get('port')}, "
        f"db={source_db_config.get('db')}"
    )
# source_db_config = {
#     "host": "rm-data-readonly-clusterd59.mysql.rds.aliyuncs.com",
#     "port": 3306,
#     "user": "saas_alpha_ro",
#     "password": "saSadss_#112alGphaD_ro1DF",
#     "db": "schema_metadata"
# }

# source_db_config = {
#     "host": "192.168.15.57",
#     "port": 31513,
#     "user": "root",
#     "password": "123QWEasd!*",
#     "db": "schema_metadata"
# }


mysql1_config = config.get('mysql1_config', {})
if os.environ.get("TEXT2SQL_MYSQL1_USE_TEST_NACOS", "0").strip().lower() in {
    "1", "true", "yes", "on"
}:
    mysql1_config = _get_test_nacos_config().get('mysql1_config', {})
    print(
        "MYSQL-1 uses test Nacos config: "
        f"host={mysql1_config.get('host')}, port={mysql1_config.get('port')}, "
        f"db={mysql1_config.get('db')}"
    )
# mysql1_config = {
#     "host": "rm-data-readonly-clusterd59.mysql.rds.aliyuncs.com",
#     "port": 3306,
#     "user": "etl_ro",
#     "password": "byktetrFGDH#%11579nwFDGD",
#     "db": "FUND_INFO"
# }
mysql2_config = config.get('mysql2_config', {})
# mysql2_config = {
#     "host": "rm-2ze3bb361946ye7oq.mysql.rds.aliyuncs.com",
#     "port": 3306,
#     "user": "juling_ro",
#     "password": "ju11linjhg_ro#123S",
#     "db": "juling"
# }

mysql3_config = config.get('mysql3_config', {})
if os.environ.get("TEXT2SQL_MYSQL3_USE_TEST_NACOS", "0").strip().lower() in {
    "1", "true", "yes", "on"
}:
    mysql3_config = _get_test_nacos_config().get('mysql3_config', {})
    print(
        "MYSQL-3 uses test Nacos config: "
        f"host={mysql3_config.get('host')}, port={mysql3_config.get('port')}, "
        f"db={mysql3_config.get('db')}"
    )
# mysql3_config = {
#     "host": "192.168.15.49",
#     "port": 30635,
#     "user": "root",
#     "password": "123QWEasd!*",
#     "db": "saas"
# }

# 美股
mysql4_config = {
    "host": "mr-bth0s2yfzy228yweuw.rwlb.rds.aliyuncs.com",
    "port": 3306,
    "user": "ruanyf01",
    "password": "NR1123G2lkmnBRNJ,dfv",
    "db": "fiu"
}
# MYSQL-4 可独立使用本地 fiu，不影响 Nacos 和 Doris 的远程配置。
if _env_enabled("TEXT2SQL_LOCAL_SIM") or _env_enabled("TEXT2SQL_MYSQL4_USE_LOCAL"):
    mysql4_config = {
        "host": "127.0.0.1",
        "port": 3307,
        "user": "root",
        "password": "123QWEasd!*",
        "db": "fiu",
    }

# 测试edb
# mysql5_config = {
#     "host": "mr-bth0s2yfzy228yweuw.rwlb.rds.aliyuncs.com",
#     "port": 3306,
#     "user": "ruanyf01",
#     "password": "NR1123G2lkmnBRNJ,dfv",
#     "db": "test"
# }


# 使用配置创建数据库引擎
source_db_engine = create_engine(
    # 注意：这里的格式是 '数据库方言+数据库驱动名://用户名:密码@主机名:端口/数据库名'
    f"mysql+pymysql://{source_db_config['user']}:{source_db_config['password']}@"
    f"{source_db_config['host']}:{source_db_config['port']}/{source_db_config['db']}?charset=utf8mb4",
    poolclass=QueuePool,  # 使用QueuePool作为连接池
    pool_size=10,  # 连接池大小
    max_overflow=100,  # 超过连接池大小外最多创建的连接
    pool_recycle=1800,  # 连接回收时间
)
metadata = MetaData()


saas_db_engine = create_engine(
    # 注意：这里的格式是 '数据库方言+数据库驱动名://用户名:密码@主机名:端口/数据库名'
    f"mysql+pymysql://{mysql3_config['user']}:{mysql3_config['password']}@"
    f"{mysql3_config['host']}:{mysql3_config['port']}/{mysql3_config['db']}?charset=utf8mb4",
    poolclass=QueuePool,  # 使用QueuePool作为连接池
    pool_size=10,  # 连接池大小
    max_overflow=100,  # 超过连接池大小外最多创建的连接
    pool_recycle=1800,  # 连接回收时间
)

# 创建异步引擎（在原有同步引擎定义的位置附近添加）
async_saas_db_engine = create_async_engine(
    f"mysql+aiomysql://{mysql3_config['user']}:{mysql3_config['password']}@"
    f"{mysql3_config['host']}:{mysql3_config['port']}/{mysql3_config['db']}?charset=utf8mb4",
    pool_size=10,
    max_overflow=100,
    pool_recycle=1800,
)

def query_exec_by_saas(sql):
    """
    查询 返回列表
    :param sql:
    :return:
    """
    with saas_db_engine.connect() as conn:
        result = conn.execute(text(sql))
        return result.all()

def execute_sql_by_saas(sql: str, params=None) -> int:
    """
    执行修改类SQL语句(INSERT/UPDATE/DELETE)
    
    Args:
        sql: SQL语句
        params: 参数字典，用于参数化查询
        
    Returns:
        int: 受影响的行数
        
    Examples:
        execute_sql_by_saas("INSERT INTO table (col1) VALUES (:value)", {"value": "some_value"})
        1
        
        execute_sql_by_saas("INSERT INTO table (col1) VALUES ('value')")
        1
    """
    try:
        with saas_db_engine.connect() as conn:
            with conn.begin():  # 开启事务
                if params:
                    result = conn.execute(text(sql), params)
                else:
                    result = conn.execute(text(sql))
                return result.rowcount
    except Exception as e:
        print(f"执行SQL出错: {e}")
        print(f"SQL语句: {sql}")
        raise
    
def query_exec(sql):
    """
    查询 返回列表
    :param sql:
    :return:
    """
    with source_db_engine.connect() as conn:
        print(conn)
        result = conn.execute(sql)
        return result.all()


def insert_exec(sql, param):
    """
    执行插入
    :param sql: insert into user(id,name)values(:1,:2)
    :param param: ("1","kevin")
    :return:
    """
    with source_db_engine.connect() as conn:
        txn = conn.begin()
        try:
            conn.execute(sql, param)
            txn.commit()
        except:
            txn.rollback()
            raise


def query_exec_db(sql: str):
    with source_db_engine.connect() as connection:
        return connection.execute(sql).fetchall()


def exec_db(sql: str):
    with source_db_engine.connect() as connection:
        connection.execute(sql)




async_pools = {}

async def initialize_pool(pool_name, config):
    """
    初始化数据库连接池。

    参数:
    pool_name (str): 连接池的名称。
    config (dict): 包含数据库连接配置的字典。
    """
    global async_pools
    connect_timeout = int(os.environ.get("TEXT2SQL_DB_CONNECT_TIMEOUT", "60"))
    print(
        f"Initializing database pool '{pool_name}': "
        f"host={config['host']}, port={config['port']}, db={config['db']}"
    )
    async_pools[pool_name] = await aiomysql.create_pool(
        host=config['host'],
        user=config['user'],
        password=config['password'],
        db=config['db'],
        port=config['port'],
        autocommit=True,
        minsize=1,
        maxsize=10,
        connect_timeout=connect_timeout,
        # VPN/NAT 会掐空闲长连接，回收避免复用已死连接导致的偶发 Can't connect
        pool_recycle=1800,
    )
    print(f"Database pool '{pool_name}' initialized successfully.")

def get_pool(pool_name):
    """
    获取指定名称的连接池。

    参数:
    pool_name (str): 连接池的名称。

    返回:
    aiomysql.Pool: 数据库连接池。
    """
    global async_pools
    if pool_name not in async_pools:
        raise RuntimeError(f"Database pool '{pool_name}' has not been initialized.")
    return async_pools[pool_name]


# 初始化连接池
async def initialize_all_pools():
    # await initialize_pool('source_db', source_db_config)
    await initialize_pool('mysql1', mysql1_config)
    await initialize_pool('mysql2', mysql2_config)
    await initialize_pool('mysql3', mysql3_config)
    # 生产默认保持关闭；本地远程模式可显式启用真实美股库。
    if (
        _env_enabled("TEXT2SQL_LOCAL_SIM")
        or _env_enabled("TEXT2SQL_MYSQL4_USE_LOCAL")
        or _env_enabled("TEXT2SQL_ENABLE_MYSQL4")
    ):
        await initialize_pool('mysql4', mysql4_config)
    # await initialize_pool('mysql5', mysql5_config)

# 获取连接池
# def get_source_db_pool():
#     return get_pool('source_db')

def get_mysql1_pool():
    return get_pool('mysql1')

def get_mysql2_pool():
    return get_pool('mysql2')

def get_mysql3_pool():
    return get_pool('mysql3')

def get_mysql4_pool():
    return get_pool('mysql4')

# def get_mysql5_pool():
#     return get_pool('mysql5')


if __name__ == '__main__':
    with source_db_engine.connect() as conn:
        result = conn.execute("""SELECT count(1) FROM `paipai_comment`""")
        print(result.all())

async def async_query_exec_by_saas(sql, params=None):
    """
    异步查询函数，返回查询结果列表
    对应同步版本的 query_exec_by_saas
    
    Args:
        sql: SQL查询语句
        params: 参数字典，用于参数化查询（可选）
    Returns:
        list: 查询结果列表
    """
    try:
        async with async_saas_db_engine.connect() as conn:
            # 执行查询
            if params:
                result = await conn.execute(text(sql), params)
            else:
                result = await conn.execute(text(sql))
            # 直接返回所有结果，不需要再await
            return result.fetchall()
    except Exception as e:
        print(f"异步查询出错: {e}")
        print(f"SQL语句: {sql}")
        raise

async def async_execute_sql_by_saas(sql: str, params=None) -> int:
    """
    异步执行修改类SQL语句(INSERT/UPDATE/DELETE)
    对应同步版本的 execute_sql_by_saas
    
    Args:
        sql: SQL语句
        params: 参数字典，用于参数化查询
    Returns:
        int: 受影响的行数
    """
    try:
        async with async_saas_db_engine.connect() as conn:
            async with conn.begin():  # 开启事务
                if params:
                    result = await conn.execute(text(sql), params)
                else:
                    result = await conn.execute(text(sql))
                return result.rowcount  
    except Exception as e:
        print(f"异步执行SQL出错: {e}")
        print(f"SQL语句: {sql}")
        raise

async def async_query_exec_by_saas_with_columns(sql: str, params=None):
    """
    异步查询函数，返回查询结果列表和列名
    
    Args:
        sql: SQL查询语句
        params: 参数字典或元组，用于参数化查询
        
    Returns:
        tuple: (结果列表, 列名列表)
    """
    try:
        pool = get_mysql3_pool()
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                if params:
                    await cursor.execute(sql, params)
                else:
                    await cursor.execute(sql)
                results = await cursor.fetchall()
                # 获取列名
                columns = [d[0] for d in cursor.description] if cursor.description else []
                return results, columns
    except Exception as e:
        print(f"异步查询出错: {e}")
        print(f"SQL语句: {sql}")
        raise

async def async_execute_many_by_saas(sql: str, params_list: list) -> int:
    """
    异步批量执行SQL语句
    
    Args:
        sql: SQL语句
        params_list: 参数列表，每个元素是一个字典或元组
        
    Returns:
        int: 受影响的总行数
    """
    try:
        pool = get_mysql3_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.executemany(sql, params_list)
                await conn.commit()
                return cursor.rowcount
    except Exception as e:
        print(f"异步批量执行SQL出错: {e}")
        print(f"SQL语句: {sql}")
        raise

async def async_transaction_by_saas(operations: list) -> bool:
    """
    异步执行事务，支持多个SQL操作
    
    Args:
        operations: 列表，每个元素是(sql, params)元组
        
    Returns:
        bool: 事务是否成功
    """
    try:
        pool = get_mysql3_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                try:
                    await conn.begin()  # 开始事务
                    for sql, params in operations:
                        if params:
                            await cursor.execute(sql, params)
                        else:
                            await cursor.execute(sql)
                    await conn.commit()
                    return True
                except Exception as e:
                    await conn.rollback()
                    print(f"事务执行出错: {e}")
                    raise
    except Exception as e:
        print(f"异步事务执行出错: {e}")
        raise
