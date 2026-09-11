import asyncio
import os
import re
from datetime import date
from typing import List, Tuple, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from util.token_tracker import TokenTracker

from common.middleware.db_utils import get_mysql1_pool, get_mysql2_pool, get_mysql4_pool
from util.db_helpers import query_from_db, fetch_data_from_MYSQL
from util.fix_fields import DEFAULT_TABLES
from util.model_helpers import get_query_by_chat,call_llm
from util.query_intent import (
    has_explicit_forecast_intent,
    has_market_price_intent,
    is_forecast_table,
)

# Initialize the logger
import logging
logger = logging.getLogger(__name__)

# Cross-validation of the model's output
import ast


async def _filter_existing_tables(table_names: List[str], db_type: str) -> List[str]:
    filter_enabled = os.environ.get(
        "TEXT2SQL_FILTER_EXISTING_TABLES",
        "0",
    ).strip().lower() in {"1", "true", "yes", "on"}
    if not filter_enabled:
        return table_names

    pool_getters = {
        "MYSQL-1": get_mysql1_pool,
        "MYSQL-2": get_mysql2_pool,
        "MYSQL-4": get_mysql4_pool,
    }
    pool_getter = pool_getters.get(db_type)
    if not pool_getter or not table_names:
        return table_names

    placeholders = ", ".join(["%s"] * len(table_names))
    sql = f"""
        SELECT UPPER(TABLE_NAME)
        FROM information_schema.tables
        WHERE TABLE_SCHEMA = DATABASE()
          AND UPPER(TABLE_NAME) IN ({placeholders})
    """
    pool = pool_getter()
    async with pool.acquire() as connection:
        async with connection.cursor() as cursor:
            await cursor.execute(sql, tuple(name.upper() for name in table_names))
            existing_tables = {row[0] for row in await cursor.fetchall()}

    missing_tables = [name for name in table_names if name.upper() not in existing_tables]
    if missing_tables:
        logger.warning(
            "Ignoring metadata tables missing from %s: %s",
            db_type,
            missing_tables,
        )
    return [name for name in table_names if name.upper() in existing_tables]
# async def fetch_and_process_tables(query: str, domain_res: str, background_info, domain_one: str, industry_str, concepts) -> List[str]:
#     """
#     从数据库中获取表信息，并根据查询生成定位提示。
#
#     参数:
#     query (str): 用户的查询问题。
#     domain_res (str): 之前获取的域分类结果。
#     domain_one（str）: 一级域。
#     返回:
#     List[str]: 生成的定位提示信息。
#     """
#     # 替换域分类结果中的括号
#     domain_str = domain_res.replace('[', '(').replace(']', ')')
#     # SQL查询语句，获取域对应的表
#
#     sql_query = await get_sql_for_fetch_tables(domain_str, domain_one)
#
#     # sql_query = f"""
#     # SELECT DOMAIN_CNAME, TABLE_ENAME from MDB_DOMN_TB
#     # WHERE DOMAIN_CNAME IN {domain_str}
#     # """
#
#     # 从数据库中获取数据
#     domain_table_map = await query_from_db(sql_query)
#
#     # 获取所有表名
#     combine_table_list = [item[1] for item in domain_table_map]
#
#     # 创建逗号分隔的表名字符串，并为每个表名添加引号
#     table_names = ', '.join(f"'{name}'" for name in combine_table_list)
#
#     # SQL查询语句，获取表的定义
#     sql_query = f"""
#     SELECT TABLE_ENAME, TABLE_CNAME, TABLE_DESC_GENERATED, TABLE_DESC FROM MDB_TABLE
#     WHERE TABLE_ENAME IN ({table_names})
#     """
#
#     table_define = await query_from_db(sql_query)
#     background_info = background_info.replace('\n', '')
#     industry_str = industry_str.replace('\n', '')
#
#     # 构建表定义字符串
#     table_define_str = ""
#     # 构建候选表列表
#     table_candidate_set = set()
#     for line in table_define:
#         if not line[1] or not line[2] or line[0].upper() in DEFAULT_TABLES:
#             continue
#         title = line[1].replace('\n', '').replace('\r', '')
#         content = line[2].replace('\n', '').replace('\r', '')
#         table_define_str += f"【{line[0]}】: {title}, 定义如下：{content}\n"
#         table_candidate_set.add(line[0])
#
#     table_cls_str = await fetch_classification_knowledge('TABLE_CLS', domain_one_for_table_cls=domain_one)
#
#     # 生成定位提示信息
#     table_define_prompt = f"""
#
#     我现在有如下【query】：{query}
#
#     同时我有如下的这些的参考表格信息，请帮我从中筛选出可能有关联用于查询的表格，并返回表名。
#     {background_info}请特别考虑这个问题拆解中所可能涉及的表格!!!
#     【请特别注意】{industry_str}，请以此来区分：A股主板、科创板、港股。{concepts}
#
#     如下为候选的表格的【表格简介】：
#
#     {table_define_str}
#
#     请直接以列表的形式输出分类结果，例如['表格A', '表格B', '表格C']!!!
#
#     请注意：
#
#     {table_cls_str}
#     请务必从候选的表格中获取，不要编造表格名称。请注意选择最相关的最多4个表格！！！
#     请先#简洁地#生成思考的流程和解释，再请列表的形式输出分类结果，例如['表格A', '表格B', '表格C']!!!
#     """
#     logger.info(f"问题{query} 表定位prompt{table_define_prompt}")
#     res = await asyncio.get_event_loop().run_in_executor(None, get_query_by_chat, table_define_prompt)
#     logger.info(f"问题{query} prompt执行结果{res}")
#     table_res = extract_last_list_item(res)
#     logger.info(f"问题{query} extract_lists执行结果{table_res}")
#     try:
#         # 检查 table_res 是否为 None 或空字符串
#         if table_res is None or not isinstance(table_res, str):
#             table_res_list = []  # 如果 table_res 是 None 或非字符串，直接赋值为空列表
#             logger.error(f"table_res为空或不是str，已自动赋值为空列表")
#         else:
#             # 使用 ast.literal_eval 安全地解析字符串
#             table_res_list = ast.literal_eval(table_res)
#             if not isinstance(table_res_list, list):
#                 # # 确保结果是一个列表
#                 table_res_list = []
#                 logger.error(f"table_res无法正常解析为列表，table_res：{table_res}")
#     except Exception as e:
#         logger.error(f"Error parsing table_res: {table_res}. Error: {e}，已自动赋值为空列表")
#         table_res_list = []
#
#     # Normalize the table names to uppercase and strip whitespace
#     table_res_list = [table.strip().upper() for table in table_res_list if isinstance(table, str)]
#
#     # Cross-validate the tables with the candidate set
#     valid_tables = [table for table in table_res_list if table in table_candidate_set]
#     invalid_tables = [table for table in table_res_list if table not in table_candidate_set]
#
#     if invalid_tables:
#         logger.warning(f"The following tables are not in the candidate list and will be ignored: {invalid_tables}")
#
#     # if not valid_tables:
#     #     # No valid tables found after cross-validation
#     #     logger.error("No valid tables found in table_res after cross-validation. The model may have hallucinated.")
#     #     raise ValueError("No valid tables found in table_res after cross-validation.")
#
#     table_res = str(valid_tables)
#
#     # 获取表名结果
#     if table_res is None:
#         table_res = []  # 返回空列表作为默认值
#     else:
#         table_res = eval(table_res)
#     upper_table_res = [item.upper() for item in table_res]
#
#     if "主板" in domain_res:
#         if 'GET_A_INDUSTRY'.upper() not in upper_table_res:
#             table_res.append('GET_A_INDUSTRY')
#         if 'GET_A_SEC_CODE'.upper() not in upper_table_res:
#             table_res.append('GET_A_SEC_CODE')
#     if "科创板" in domain_res:
#         if 'GET_A_SEC_CODE'.upper() not in upper_table_res:
#             table_res.append('GET_A_SEC_CODE')
#         if 'GET_A_INDUSTRY'.upper() not in upper_table_res:
#             table_res.append('GET_A_INDUSTRY')
#     if "港股" in domain_res:
#         if 'HK_COMBINFO'.upper() not in upper_table_res:
#             table_res.append('HK_COMBINFO')
#         if 'HK_STKCODE'.upper() not in upper_table_res:
#             table_res.append('HK_STKCODE')
#         if 'VIEW_HK_INDUSTRY_TRACK'.upper() not in upper_table_res:
#             table_res.append('VIEW_HK_INDUSTRY_TRACK')
#     if "指数" in domain_res:
#         if 'GET_INDX_GEN_INFO'.upper() not in upper_table_res:
#             table_res.append('GET_INDX_GEN_INFO')
#
#     filter_res = list()
#
#     kechuang_flag = True
#     if "科创板" not in query and '科创板' not in industry_str:
#         kechuang_flag = False
#
#     if not kechuang_flag:
#         filter_res = [item for item in table_res if not '科创板' in item]
#     else:
#         filter_res = table_res
#     logger.info(f"问题{query} 过滤的最后结果{filter_res}")
#     return filter_res, table_define


async def process_chunk(chunk_tables: List[tuple], query: str, background_info: str, industry_str: str, concepts: str,
                        table_cls_str: str, token_tracker: Optional["TokenTracker"] = None) -> List[str]:
    """处理单个分块(10个表)的异步任务"""
    chunk_table_define_str = ""
    for line in chunk_tables:
        if not line[1] or not line[2] or line[0].upper() in DEFAULT_TABLES:
            continue
        title = line[1].replace('\n', '').replace('\r', '')
        content = line[2].replace('\n', '').replace('\r', '')
        chunk_table_define_str += f"【{line[0]}】: {title}, 定义如下：{content}\n"

    chunk_prompt = f"""

    我现在有如下【query】：{query}

    当前日期是{date.today().isoformat()}。只有用户明确提到“预期、预测、预计、业绩预告”等预测含义时，才优先选择业绩预告或一致预期表。仅出现年份不代表预测；已经结束的年份应优先选择正式财务报表或财务指标表。专家知识中的固定年份规则如果与当前日期冲突，以本规则为准。

    同时我有如下的这些的参考表格信息，请帮我从中筛选出可能有关联用于查询的表格，并返回表名。
    {background_info}请特别考虑这个问题拆解中所可能涉及的表格!!!
    【请特别注意】{industry_str}，请以此来区分：A股主板、科创板、港股。{concepts}

    如下为候选的表格的【表格简介】：

    {chunk_table_define_str}

    请直接以列表的形式输出分类结果，例如['表格A', '表格B', '表格C']!!!

    请注意：

    {table_cls_str}
    请务必从候选的表格中获取，不要编造表格名称。请注意选择最相关的最多4个表格！！！
    请先#简洁地#生成思考的流程和解释，再请列表的形式输出分类结果，例如['表格A', '表格B', '表格C']!!!
    """
    logger.info(f"问题{query} 表定位prompt{chunk_prompt}")

    try:
        # res = get_query_by_chat(chunk_prompt)
        res = await call_llm(prompt=chunk_prompt, model="gpt-4.1", token_tracker=token_tracker)
        logger.info(f"问题{query} prompt执行结果{res}")
        return extract_last_list_item(res) or []
    except Exception as e:
        logger.error(f"Error processing chunk: {str(e)}")
        return []


async def fetch_and_process_tables(query: str, domain_res: str, background_info, domain_one: str,
                                   industry_str, concepts, db_type: str,
                                   token_tracker: Optional["TokenTracker"] = None) -> List[str]:
    """
    从数据库中获取表信息，并根据查询生成定位提示。

    参数:
    query (str): 用户的查询问题。
    domain_res (str): 之前获取的域分类结果。
    domain_one（str）: 一级域。
    返回:
    List[str]: 生成的定位提示信息。
    """
    # 替换域分类结果中的括号
    domain_str = domain_res.replace('[', '(').replace(']', ')')
    # SQL查询语句，获取域对应的表

    sql_query = await get_sql_for_fetch_tables(domain_str, domain_one)

    # sql_query = f"""
    # SELECT DOMAIN_CNAME, TABLE_ENAME from MDB_DOMN_TB
    # WHERE DOMAIN_CNAME IN {domain_str}
    # """

    # 从数据库中获取数据
    domain_table_map = await query_from_db(sql_query)

    # 获取所有表名
    combine_table_list = [item[1] for item in domain_table_map]

    # 创建逗号分隔的表名字符串，并为每个表名添加引号
    table_names = ', '.join(f"'{name}'" for name in combine_table_list)

    # SQL查询语句，获取表的定义
    sql_query = f"""
    SELECT TABLE_ENAME, TABLE_CNAME,
           COALESCE(NULLIF(TABLE_DESC_GENERATED, ''), TABLE_DESC) AS TABLE_DESCRIPTION,
           TABLE_DESC
    FROM MDB_TABLE
    WHERE TABLE_ENAME IN ({table_names})
    """

    table_define = await query_from_db(sql_query)
    background_info = background_info.replace('\n', '')
    industry_str = industry_str.replace('\n', '')


    # # 构建表定义字符串
    # table_define_str = ""
    # # 构建候选表列表
    # table_candidate_set = set()
    # for line in table_define:
    #     if not line[1] or not line[2] or line[0].upper() in DEFAULT_TABLES:
    #         continue
    #     title = line[1].replace('\n', '').replace('\r', '')
    #     content = line[2].replace('\n', '').replace('\r', '')
    #     table_define_str += f"【{line[0]}】: {title}, 定义如下：{content}\n"
    #     table_candidate_set.add(line[0])

    table_cls_str = await fetch_classification_knowledge('TABLE_CLS', domain_one_for_table_cls=domain_one)

    table_candidate_set = set()
    for line in table_define:
        if not line[1] or not line[2] or line[0].upper() in DEFAULT_TABLES:
            continue
        table_candidate_set.add(line[0])

    # 分块处理逻辑
    chunk_size = 10
    table_chunks = [table_define[i:i + chunk_size] for i in range(0, len(table_define), chunk_size)]

    # 准备所有分块任务
    tasks = [
        process_chunk(
            chunk_tables=chunk,
            query=query,
            background_info=background_info.replace('\n', ''),
            industry_str=industry_str.replace('\n', ''),
            concepts=concepts,
            table_cls_str=table_cls_str,
            token_tracker=token_tracker
        ) for chunk in table_chunks
    ]

    # 并发执行所有分块任务
    chunk_results = await asyncio.gather(*tasks)

    # 合并处理结果
    table_res = []
    for res in chunk_results:
        try:
            if res and isinstance(res, str):
                res1 = ast.literal_eval(res)
                table_res.extend(res1)
        except Exception as e:
            logger.error(f"Error processing chunk result: {str(e)}")

    logger.info(f"问题{query} extract_lists执行结果{table_res}")
    try:
        # 检查 table_res 是否为 None 或空字符串
        if table_res is None or not isinstance(table_res, list):
            table_res_list = []  # 如果 table_res 是 None 或非字符串，直接赋值为空列表
            logger.error(f"table_res为空或不是list，已自动赋值为空列表")
        else:
            # # 使用 ast.literal_eval 安全地解析字符串
            # table_res_list = ast.literal_eval(table_res)
            table_res_list = table_res
            if not isinstance(table_res_list, list):
                # # 确保结果是一个列表
                table_res_list = []
                logger.error(f"table_res无法正常解析为列表，table_res：{table_res}")
    except Exception as e:
        logger.error(f"Error parsing table_res: {table_res}. Error: {e}，已自动赋值为空列表")
        table_res_list = []

    # Normalize the table names to uppercase and strip whitespace
    table_res_list = [table.strip().upper() for table in table_res_list if isinstance(table, str)]

    # Cross-validate the tables with the candidate set
    valid_tables = [table for table in table_res_list if table in table_candidate_set]
    invalid_tables = [table for table in table_res_list if table not in table_candidate_set]

    if invalid_tables:
        logger.warning(f"The following tables are not in the candidate list and will be ignored: {invalid_tables}")

    if not has_explicit_forecast_intent(query):
        forecast_tables = [table for table in valid_tables if is_forecast_table(table)]
        valid_tables = [table for table in valid_tables if not is_forecast_table(table)]
        if forecast_tables:
            logger.info(
                "问题未包含明确预测意图，已剔除预测表: %s",
                forecast_tables,
            )

    if (
        db_type == "MYSQL-4"
        and has_market_price_intent(query)
        and "VIEW_US_EOD_EXPR" in table_candidate_set
        and "VIEW_US_EOD_EXPR" not in valid_tables
    ):
        valid_tables.append("VIEW_US_EOD_EXPR")
        logger.info("美股行情意图已补充 VIEW_US_EOD_EXPR")

    valid_tables = await _filter_existing_tables(valid_tables, db_type)

    # if not valid_tables:
    #     # No valid tables found after cross-validation
    #     logger.error("No valid tables found in table_res after cross-validation. The model may have hallucinated.")
    #     raise ValueError("No valid tables found in table_res after cross-validation.")

    table_res = str(valid_tables)

    # 获取表名结果
    if table_res is None:
        table_res = []  # 返回空列表作为默认值
    else:
        table_res = eval(table_res)
    upper_table_res = [item.upper() for item in table_res]

    if "主板" in domain_res:
        if 'GET_A_INDUSTRY'.upper() not in upper_table_res:
            table_res.append('GET_A_INDUSTRY')
        if 'GET_A_SEC_CODE'.upper() not in upper_table_res:
            table_res.append('GET_A_SEC_CODE')
    if "科创板" in domain_res:
        if 'GET_A_SEC_CODE'.upper() not in upper_table_res:
            table_res.append('GET_A_SEC_CODE')
        if 'GET_A_INDUSTRY'.upper() not in upper_table_res:
            table_res.append('GET_A_INDUSTRY')
    if "港股" in domain_res:
        if 'HK_COMBINFO'.upper() not in upper_table_res:
            table_res.append('HK_COMBINFO')
        if 'HK_STKCODE'.upper() not in upper_table_res:
            table_res.append('HK_STKCODE')
        if 'VIEW_HK_INDUSTRY_TRACK'.upper() not in upper_table_res:
            table_res.append('VIEW_HK_INDUSTRY_TRACK')
    if "指数" in domain_res:
        if 'GET_INDX_GEN_INFO'.upper() not in upper_table_res:
            table_res.append('GET_INDX_GEN_INFO')

    filter_res = list()

    kechuang_flag = True
    if "科创板" not in query and '科创板' not in industry_str:
        kechuang_flag = False

    if not kechuang_flag:
        filter_res = [item for item in table_res if not '科创板' in item]
    else:
        filter_res = table_res
    logger.info(f"问题{query} 过滤的最后结果{filter_res}")
    return filter_res, table_define


async def get_sql_for_fetch_tables(domain_res: str, domain_one: str) -> str:
    """
    根据一级域的类型生成sql获得候选表

    参数:
    domain_res (str): 之前获取的域分类结果。
    domain_one（str）: 一级域。
    返回:
    str: sql查询语句
    """
    domain_str = domain_res.replace('[', '(').replace(']', ')')
    sql_query = ""
    if domain_one == "基金相关":
        report_type_sql = "SELECT REPORT_TYPE from FUND_FRONT_CONTROL"
        _, report_type = await fetch_data_from_MYSQL(report_type_sql,get_mysql1_pool())
        print("report_tpye:", report_type['REPORT_TYPE'][0])
        isQ = bool(int(report_type['REPORT_TYPE'][0]) == 1)
        if isQ:
            sql_query = f"""
            SELECT DOMAIN_CNAME, TABLE_ENAME from MDB_DOMN_TB_JULING
            WHERE DOMAIN_CNAME IN {domain_str} AND TABLE_ENAME NOT LIKE '%%HY' AND HISVALID = 1
            """
        else:
            sql_query = f"""
            SELECT DOMAIN_CNAME, TABLE_ENAME from MDB_DOMN_TB_JULING
            WHERE DOMAIN_CNAME IN {domain_str} AND TABLE_ENAME NOT LIKE '%%Q' AND HISVALID = 1
            """

    else:
        sql_query = f"""       
        SELECT DOMAIN_CNAME, TABLE_ENAME from MDB_DOMN_TB_JULING
        WHERE DOMAIN_CNAME IN {domain_str} AND HISVALID = 1
        """
    print(f"get_sql_for_fetch_tables:{sql_query}")
    # to delete
    return sql_query




async def fetch_classification_knowledge(cls_type, domain_one_for_table_cls: str = "") -> str:
    """
    获取域定义、表定义的相关先验信息。

    参数:
    domain_one_for_table_cls(str): 表分类所需的一级域信息

    返回:
    str: 一般知识信息。
    """
    # sql_query = ""
    # if cls_type == "TABEL_CLS":
    #     sql_query = f"""
    #     SELECT KNOW_TYPE, KNOW_ID, KNOW_DESC FROM MDB_EXPERT_KNOWLEDGE_JULING
    #     WHERE KNOW_TYPE = "{cls_type}" AND OBJECT_CNAME = '{domain_one_for_table_cls}'
    #     """
    # else:
    #     sql_query = f"""
    #     SELECT KNOW_TYPE, KNOW_ID, KNOW_DESC FROM MDB_EXPERT_KNOWLEDGE_JULING
    #     WHERE KNOW_TYPE = "{cls_type}" AND OBJECT_CNAME = '{domain_one_for_table_cls}'
    #     """
    sql_query = f"""
            SELECT KNOW_TYPE, KNOW_ID, KNOW_DESC FROM MDB_EXPERT_KNOWLEDGE_JULING
            WHERE KNOW_TYPE = "{cls_type}" AND OBJECT_CNAME = '{domain_one_for_table_cls}'
            """
    general_info = await query_from_db(sql_query)
    general_text = ""
    for idx, item in enumerate(general_info):
        general_text += f"{idx + 1}.{item[2]}\n"
    return general_text


def extract_last_list_item(text):
    # 使用正则表达式匹配所有[XXX]格式的内容
    pattern = r'\[.*?\]'
    matches = re.findall(pattern, text)

    # 检查匹配结果是否为空
    if matches:
        return matches[-1]  # 返回最后一个匹配项
    else:
        return None  # 如果没有匹配项，返回 None


def extract_lists(text):
    # 使用正则表达式匹配所有[XXX]格式的内容
    pattern = r'\[.*?\]'
    matches = re.findall(pattern, text)

    # 检查匹配结果是否为空
    if matches:
        return matches[0]  # 返回第一个匹配项
    else:
        return None  # 如果没有匹配项，返回 None


def extract_tables(sql: str) -> List[str]:
    # 使用正则表达式提取FROM和JOIN后的表名
    tables = re.findall(r'FROM\s+([`"\w]+)|JOIN\s+([`"\w]+)', sql, re.IGNORECASE)
    # Flatten the list of tuples and remove None
    tables = [table for pair in tables for table in pair if table]
    # Remove surrounding quotes or backticks if any
    tables = [re.sub(r'[`"\s]', '', table) for table in tables]
    return list(set(tables))  # 去重
