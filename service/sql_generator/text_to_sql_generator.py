import asyncio
import os
from datetime import datetime
from typing import List, Tuple, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from util.token_tracker import TokenTracker

from common.middleware.redis_util import redis_client
from service.sql_generator.TableFetcher import DynamicTableFetcher, FixTableFetcher, TableInfoService
from service.sql_generator.fetch_knowledge import (fetch_general_knowledge, fetch_table_knowledge, fetch_domain_knowledge,
                                                   fetch_EDB_tables_knowledges, fetch_EDB_knowledge)
import collections
from util.data_formater_helpers import  get_filter_colunms_name
import pickle
from orcl_edb_fetch import fetch_data_from_oracle
from util.data_formater_helpers import df_to_table, data_limit_num, get_filter_colunms_name
import re
import time
from util.db_helpers import query_from_db
from util.fix_fields import FIX_FIELDS, DYNAMIC_TABLES
from util.model_helpers import get_query_by_chat, get_query_by_chat_o1, chat2o1, get_query_by_chat_o1_low, get_gemini_2_5_response, get_gpt_4_1_response,get_query_by_chat_gpt_4_1,call_llm,async_R1_volcano
from util.rag_helpers import fetch_topk_rag_result, fetch_topk_rag_fix_result
import logging

today = datetime.now()
year = today.year
month = today.month
day = today.day

print("Current working directory:", os.getcwd())
script_dir = os.path.dirname(os.path.abspath(__file__))
SQL_GENERATION_MODEL = os.environ.get(
    "TEXT2SQL_SQL_MODEL",
    "nulls-gemini-2.5-pro",
)


def _temporal_query_guidance(db_type: str = "") -> str:
    guidance = (
        f"当前日期是{datetime.now().date().isoformat()}。只有用户明确提到‘预期、预测、预计、业绩预告’等预测含义时，"
        "才使用业绩预告或一致预期数据。仅出现年份不代表预测；已经结束的年份应优先查询正式财务数据。"
    )
    if db_type == "MYSQL-4":
        guidance += (
            "查询美股最新行情时，必须从行情表用MAX(TRADE_DATE)取得实际最新交易日，"
            "不能假定当天已有收盘数据，也不能直接写死当前日期。"
        )
    return guidance

# 构建文件的绝对路径
# 加了外部key todo
juling_path = os.path.join(script_dir, 'embedding_dict_update_juling_0216.pkl')
update_path = os.path.join(script_dir, 'embedding_dict_updated.pkl')
async def fetch_and_generate_sql_o1(us_stock_codes:list, companies: list, concepts, field_recall: bool, entity_embedding, query: str, table_res: List[str], domain_res: str, industry_str: str, dbtype: str, domain_one: str, table_define, query_embedding, token_tracker: Optional["TokenTracker"] = None) -> str:
    """
    获取表信息、知识信息，并生成SQL查询提示。

    参数:
    query (str): 用户的查询问题。
    table_res (List[str]): 表名列表。
    domain_res (str): 域分类结果。
    industry_str (str): 行业字符串。
    dbtype (str): 所查表的数据库类型
    domain_one(str): 一级域

    返回:
    str: 生成的SQL查询提示信息。
    """
    # 如果是 '股东查询' 则 True，否则 False
    need_top30_candidates = True if field_recall == True else False

    # 加载嵌入字典
    embedding_dict = load_from_pickle(juling_path)
    # embedding_dict_field = load_from_pickle('embedding_dict_updated.pkl')

    # 初始化不同的fetcher
    dynamic_fetcher = DynamicTableFetcher(embedding_dict=embedding_dict, query_embedding=query_embedding)
    fix_fetcher = FixTableFetcher(
        embedding_dict=embedding_dict,
        entity_embedding=entity_embedding,
        # embedding_dict_field=embedding_dict_field,
        need_top30_candidates=need_top30_candidates
    )

    # 将两个fetcher组合进服务类
    service = TableInfoService(dynamic_fetcher=dynamic_fetcher, fix_fetcher=fix_fetcher)
    final_define, top30_candidates_dict = await service.fetch_table_info(us_stock_codes, table_res, query, companies)

    # final_define, top30_candidates_dict = await fetch_table_info(entity_embedding, embedding_dict_field, table_res, query_embedding, embedding_dict)
    general_text = await fetch_general_knowledge()
    domain_text = await fetch_domain_knowledge(concepts, domain_res, industry_str, domain_one)

    table_text = await fetch_table_knowledge(top30_candidates_dict, table_res)
    upper_table_res = [item.upper() for item in table_res]
    filtered_table_define = [item for item in table_define if item[0].upper() in upper_table_res]

    combine_prompt = construct_output_text(query, table_res, general_text, domain_text, table_text, final_define, filtered_table_define, dbtype, industry_str)
    print("最终Prompt", combine_prompt)


    try:
        # generated_sql = await get_query_by_chat_o1(combine_prompt)
        generated_sql = await call_llm(
            prompt=combine_prompt,
            model=SQL_GENERATION_MODEL,
            token_tracker=token_tracker,
        )

        if generated_sql is None:
            raise ValueError("生成的 SQL 查询为空")
    except Exception as e:
        import traceback
        error_stack = traceback.format_exc()
        logging.error(f"生成SQL时发生错误: {e}")
        logging.error(f"详细错误堆栈: \n{error_stack}")
        # 可以继续抛出异常,但包含更多上下文
        raise RuntimeError(f"生成SQL时发生错误: {e}. 详细堆栈: {error_stack}") from e


    return generated_sql, final_define, general_text, domain_text, table_text, combine_prompt, top30_candidates_dict, filtered_table_define




async def fetch_and_generate_sql(us_stock_codes:list, companies:list, concepts: str, field_recall: bool, entity_embedding, query: str, table_res: List[str], domain_res: str, industry_str: str, dbtype: str, domain_one: str, table_define, query_embedding, diagnose_res: Optional[str] = None, wrong_sql: Optional[str] = None, token_tracker: Optional["TokenTracker"] = None) -> str:
    """
    获取表信息、知识信息，并生成SQL查询提示。

    参数:
    query (str): 用户的查询问题。
    table_res (List[str]): 表名列表。
    domain_res (str): 域分类结果。
    industry_str (str): 行业字符串。
    dbtype (str): 所查表的数据库类型
    domain_one(str): 一级域

    返回:
    str: 生成的SQL查询提示信息。
    """
    # 如果是 '股东查询' 则 True，否则 False
    need_top30_candidates = True if field_recall == True else False

    embedding_dict = load_from_pickle(juling_path)
    # embedding_dict_field = load_from_pickle('embedding_dict_updated.pkl')

    # final_define, top30_candidates_dict = await fetch_table_info(entity_embedding, embedding_dict_field, table_res, query_embedding, embedding_dict)
    # 初始化不同的fetcher
    dynamic_fetcher = DynamicTableFetcher(embedding_dict=embedding_dict, query_embedding=query_embedding)
    fix_fetcher = FixTableFetcher(
        embedding_dict=embedding_dict,
        entity_embedding=entity_embedding,
        # embedding_dict_field=embedding_dict_field,
        need_top30_candidates=need_top30_candidates
    )

    # 将两个fetcher组合进服务类
    service = TableInfoService(dynamic_fetcher=dynamic_fetcher, fix_fetcher=fix_fetcher)
    final_define, top30_candidates_dict = await service.fetch_table_info(us_stock_codes, table_res, query, companies)


    general_text = await fetch_general_knowledge()
    domain_text = await fetch_domain_knowledge(concepts, domain_res, industry_str, domain_one)

    table_text = await fetch_table_knowledge(top30_candidates_dict, table_res)
    upper_table_res = [item.upper() for item in table_res]
    filtered_table_define = [item for item in table_define if item[0].upper() in upper_table_res]

    combine_prompt = construct_sql_correction_prompt(query, table_res, general_text, domain_text, table_text, final_define, filtered_table_define, dbtype, industry_str, diagnose_res, wrong_sql)
    print("最终Prompt", combine_prompt)

    generated_sql = await call_llm(
        prompt=combine_prompt,
        model=SQL_GENERATION_MODEL,
        token_tracker=token_tracker,
    )
    return generated_sql, final_define, general_text, domain_text, table_text, combine_prompt




def load_from_pickle(file_path):
    with open(file_path, 'rb') as pickle_file:
        return pickle.load(pickle_file)


async def fetch_table_info(entity_embedding, embedding_dict_field: dict, table_res: List[str], query_embedding, embedding_dict: dict) -> List[Tuple]:
    """
    异步获取表格信息。

    参数:
    - table_res (List[str]): 表名列表。
    - sent_model: 句子嵌入模型。
    - query (str): 查询字符串。
    - embedding_dict (dict): 嵌入向量字典。

    返回:
    - List[Tuple]: 表格信息列表，包含表名、列名、列描述等。
    """
    K = 50  # RAG查询的Top K结果数

    final_table_list = tuple(table_res)
    dynamic_tables = [table_name.upper() for table_name in final_table_list if table_name.upper() in DYNAMIC_TABLES]
    final_table_res = []
    table_field_map = collections.defaultdict(list)

    # 新增一个字典，用于存储每个字段的Top 3字段值
    top30_candidates_dict = {}

    for table_name in dynamic_tables:
        table_field_map[table_name].extend(FIX_FIELDS[table_name])
        filtered_res = fetch_topk_rag_result(table_name, query_embedding, embedding_dict, K)

        # 添加过滤后的字段到 map
        for item, _ in filtered_res:
            if item not in table_field_map[table_name]:
                table_field_map[table_name].append(item)

        # 确保当只有一个字段时，tuple 生成的语法是正确的
        field_tuple = tuple(table_field_map[table_name])
        if len(field_tuple) == 1:
            field_tuple = f"('{field_tuple[0]}')"  # 单字段时，手动生成 SQL IN 语法
            field_order_by = f"FIELD(COLUMN_ENAME, '{field_tuple[0]}')"  # 单字段的排序逻辑
        else:
            combine_str = ', '.join([f"'{f}'" for f in field_tuple])
            field_order_by = f"FIELD(COLUMN_ENAME, {combine_str})"  # 多字段排序逻辑

        # # 确保当只有一个字段时，tuple 生成的语法是正确的
        # field_tuple = tuple(table_field_map[table_name])
        # if len(field_tuple) == 1:
        #     field_tuple = f"('{field_tuple[0]}')"  # 单字段时，手动生成 SQL IN 语法
        #     field_order_by = f"FIELD(COLUMN_ENAME, '{field_tuple[0]}')"  # 单字段的排序逻辑
        # else:
        #     combine_str = ', '.join([f"'{f}'" for f in field_tuple])
        #     field_order_by = f"FIELD(COLUMN_ENAME, {combine_str})"  # 多字段排序逻辑

        sql_query = f"""
        SELECT TABLE_ENAME, COLUMN_ENAME, COLUMN_CNAME, COLUMN_TYPE, COLUMN_CATEGORY, COLUMN_DESC
        FROM MDB_COLUMN_JULING
        WHERE TABLE_ENAME = '{table_name}' AND COLUMN_ENAME IN {field_tuple} AND HISVALID=1
        ORDER BY {field_order_by}
        """

        query_res = await query_from_db(sql_query)

        # 对 query_res 中的每个记录，长度为 6，新增一个 None 作为占位，使其长度为 7
        for record in query_res:
            final_table_res.append(tuple(record) + (None,))  # 将 record 转换为元组后拼接

        # final_table_res.extend(query_res)

    fix_tables = [table_name.upper() for table_name in final_table_list if table_name.upper() not in DYNAMIC_TABLES]

    print("FIX_TABLES", fix_tables)

    if len(fix_tables) == 0:
        return final_table_res, top30_candidates_dict

    fix_tables = tuple(fix_tables) if len(fix_tables) > 1 else f"('{fix_tables[0]}')"

    if fix_tables:
        sql_query = f"""
        SELECT TABLE_ENAME, COLUMN_ENAME, COLUMN_CNAME, COLUMN_TYPE, COLUMN_CATEGORY, COLUMN_DESC
        FROM MDB_COLUMN_JULING
        WHERE TABLE_ENAME IN {fix_tables} AND HISVALID=1
        """
        print("SQL_QUERY", sql_query)
        query_res = await query_from_db(sql_query)

        # 对于每个固定表，获取 Top 3 字段候选值
        for table_name in fix_tables:
            # 获取该表的tuple列表
            table_fields = [row for row in query_res if row[0].upper() == table_name.upper()]

            # 获取该表的所有字段名列表
            field_names = [row[1] for row in table_fields]

            # 从 embedding_dict_field 中获取该表的字段嵌入向量
            if table_name in embedding_dict_field:
                table_field_embeddings = embedding_dict_field[table_name]
            else:
                # 如果没有嵌入，所有记录的第七个值为 None
                for record in table_fields:
                    final_table_res.append(tuple(record) + (None,))
                continue


            for field in field_names:
                if field in table_field_embeddings:
                    # 获得字段值embedding dict
                    field_values_embeddings = table_field_embeddings[field]
                    # 使用 entity_embedding 和字段值嵌入向量，获取 Top 3 字段值候选
                    topk_field_values = fetch_topk_rag_fix_result(table_name, entity_embedding, field_values_embeddings, K=3)

                    # 获取候选值列表
                    matched_values = [candidate_value for candidate_value, _ in topk_field_values]



                    # 将候选值添加到 top30_candidates_dict
                    key = (table_name, field)
                    top30_candidates_dict[key] = matched_values

                    # 便利tuple列表获取该字段对应的记录
                    field_records = [record for record in table_fields if record[1] == field]

                    # 添加匹配的候选值到记录中
                    for record in field_records:
                        # final_table_res.append(tuple(record) + ('该字段的候选值是：' + str(matched_values) + '注意不是所有的候选值都需要使用，请你根据需要来选择。',))
                        final_table_res.append(tuple(record) + ('该字段的候选值是：' + str(matched_values),))
                else:
                    # 如果字段没有嵌入，记录的第七个值为 None
                    field_records = [record for record in table_fields if record[1] == field]
                    for record in field_records:
                        final_table_res.append(tuple(record) + (None,))


        # final_table_res.extend(query_res)

    return final_table_res, top30_candidates_dict






def extract_sql(input_text):
    # 尝试匹配以```sql或```SQL包裹的代码块
    pattern_code_block = r"```(?:sql|SQL)\s*([\s\S]*?)```"
    match_code_block = re.search(pattern_code_block, input_text)
    if match_code_block:
        sql_code = match_code_block.group(1).strip()
        return sql_code

    # 如果没有代码块标记，则尝试匹配从常见SQL关键词开始的代码片段
    pattern_sql = r"(?i)\b(WITH|SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|TRUNCATE|REPLACE)\b[\s\S]*?;"
    match_sql = re.search(pattern_sql, input_text)
    if match_sql:
        # 直接获取匹配到的 SQL 代码
        sql_code = match_sql.group(0).strip()
        return sql_code

    # 如果仍未匹配到SQL代码，返回原始输入或提示未找到SQL代码
    return None  # 或者 return input_text.strip()


def construct_sql_correction_prompt(query: str, table_names: List[str], general_knowledge: str, domain_knowledge: str, table_knowledge: str,
                                    final_definitions: List[Tuple], filtered_table_definitions: List[Tuple], db_type: str, industry_str: str,
                                    diagnosis: Optional[str] = None, wrong_sql: Optional[str] = None) -> str:
    """
    构建用于修正SQL查询的提示文本。

    参数:
    query (str): 用户的查询问题。
    table_names (List[str]): 涉及的表名列表。
    general_knowledge (str): 一般知识信息。
    domain_knowledge (str): 域知识信息。
    table_knowledge (str): 表格知识信息。
    final_definitions (List[Tuple]): 表格字段详细信息。
    filtered_table_definitions (List[Tuple]): 过滤后的表格定义。
    db_type (str): 数据库类型。
    industry_str (str): 行业信息。
    diagnosis (Optional[str]): 对错误SQL的诊断结果。
    wrong_sql (Optional[str]): 错误的SQL查询语句。

    返回:
    str: 用于修正SQL查询的提示文本。
    """

    number_of_tables = len(table_names)
    output_text = ""

    # 将错误SQL和诊断结果放在最前面
    if wrong_sql and diagnosis:
        output_text += f"### 用户查询：“{query}”\n\n"
        output_text += f"### 错误的SQL语句：\n{wrong_sql}\n"
        output_text += f"### 错误SQL的诊断结果：\n{diagnosis}\n\n"
        output_text += "您的任务是根据以下信息，修正上述SQL查询语句。\n请特别注意，如果是超时报错，请注意优化原SQL的写法，让它执行更高效！！！\n\n"
    else:
        output_text += f"### 用户查询：“{query}”\n\n"
        output_text += "您的任务是根据以下信息，编写对应的SQL查询语句。\n\n"

    output_text += f"{_temporal_query_guidance(db_type)}\n\n"

    # output_text += f"您可以使用的表共有{number_of_tables}个，详情如下，数据库类型为：{db_type}。\n"
    output_text += "请注意：并非所有的表都需要使用，您应根据需求选择最合适的表。\n\n"

    table_details = {table[0]: {'name': table[1], 'description': table[2].replace('\n', '')} for table in filtered_table_definitions}
    for idx, table_name in enumerate(table_details):
        output_text += f"【表{idx + 1}】：{table_name}（{table_details[table_name]['name']}）\n"
        output_text += f"表描述：{table_details[table_name]['description'][:200]}\n"
        if table_name == 'STK_COM_SW_INDU_CHNG':
            output_text += industry_str + '\n'
        output_text += "字段信息：\n"
        for field in final_definitions:
            if field[0].upper() == table_name.upper():
                field_name, field_chinese_name, field_type, parent_category, field_detail = field[1], field[2], field[3], field[4], field[5]
                field_detail_info = f"释义及单位：{field_detail}" if field_detail else ""
                parent_category_info = f"所属类别：'{parent_category}'。" if parent_category else ""
                output_text += f"- {field_name}: {field_chinese_name}，{field_detail_info[:150]} 数据类型：{field_type}。{parent_category_info}\n"
        output_text += '\n'

    # # 添加专家知识部分
    if general_knowledge or domain_knowledge or table_knowledge:
        output_text += "### 专家知识（供参考）：\n"
        if general_knowledge:
            output_text += f"【一般知识】\n{general_knowledge}\n\n"
        if domain_knowledge:
            output_text += f"【领域知识】\n{domain_knowledge}\n\n"
        # if table_knowledge:
        #     output_text += f"【表格知识】\n{table_knowledge}\n\n"

    # 最后的指引
    output_text += """请根据以上信息，修正SQL查询语句。要求如下：

1. **提供一个完整且可直接执行的SQL查询语句**，确保语法正确，无需包含解释或中间步骤。

2. **遵循MySQL语法**，避免使用不被支持的函数或特性。

3. **字段和表名必须来自上述提供的表和字段**，不得凭空编造或使用未提供的表和字段。

4. **准确反映用户的查询意图**，查询结果应满足用户需求。

5. **注意数据类型和单位的正确使用**，避免类型错误或单位混淆。

6. **进行必要的单位换算和格式化显示**，规则如下（请在SQL中实现）：
    - 最高价、最低价、开盘价、收盘价：**保留2位小数**
    - 市值：以“亿”为单位，**保留1位小数**
    - 成交额：以“亿”为单位，**保留2位小数**
    - 股东户数：以“万”为单位，**保留2位小数**
    - 股本：以“亿”为单位，**保留2位小数**
    - 市盈率、市净率：**保留2位小数**
    - 每股收益、每股净资产：**保留3位小数**
    - 营业收入：以“亿”为单位，**保留3位小数**
    - 归母净利润、扣非净利润：以“万”为单位，**保留1位小数**
    - 毛利率、净资产收益率、股息率、净利率、资产负债率、销售净利率、销售毛利率：以“%”为单位，**保留2位小数**
    - 基金经理规模、基金规模：以“亿”为单位，**保留2位小数**

7. **使用中文字段别名**，使查询结果更易读。

8. 最终请**只输出修正后的SQL查询语句**，不需要包含任何解释、注释或中间过程。

"""

    logging.info(f"生成的SQL修正提示：{output_text}")
    return output_text


def construct_output_text(query: str, table_res: List[str], general_text: str, domain_text: str, table_text: str,
                          final_define: List[Tuple], filtered_table_define: List[Tuple], dbtype: str, industry_str,
                          diagnose_res: Optional[str] = None, wrong_sql: Optional[str] = None) -> str:
    """
    构建输出文本。

    参数:
    query (str): 用户的查询问题。
    table_res (List[str]): 表名列表。
    general_text (str): 一般知识信息。
    domain_text (str): 域知识信息。
    table_text (str): 表格知识信息。
    final_define (List[Tuple]): 表格字段详细信息。
    filtered_table_define (List[Tuple]): 过滤后的表格定义。

    返回:
    str: 输出文本。
    """

    number_of_tables = len(table_res)
    output_text = f"你是讯兔科技研发的金融投研数据查询助手，尤其擅长基于数据库获取所需信息，例如使用NL2SQL方法。请从给出的{number_of_tables}个表中,提取“{query}”的SQL \n"
    output_text += f"以下是{number_of_tables}个表的详细信息 ，请注意数据库类型：MYSQL \n"
    output_text += "请注意：不是所有表格都是需要的！\n\n"
    output_text += f"{_temporal_query_guidance(dbtype)}\n\n"
    output_text += f"请在执行的时候，注意如下细节：\n{general_text}\n\n"

    background_info = f"""
    同时请注意如下的专家知识，供参考：
    {domain_text}
    如下的专家知识，请特别注意，只对对应的表格有效：
    {table_text}
    """
    output_text += background_info

    table_details = {table[0]: {'name': table[1], 'description': table[2].replace('\n', '')} for table in
                     filtered_table_define}
    for idx, table_name in enumerate(table_details):
        output_text += f"【表格{idx + 1}】：{table_name}，该表为{table_details[table_name]['name']}：{table_details[table_name]['description'][:200]}\n"
        # if table_name == 'STK_COM_SW_INDU_CHNG':
        #     output_text += industry_str + '\n'

        output_text += "该表格中的字段详细信息：\n"
        for field in final_define:
            if field[0].upper() == table_name.upper():
                field_name, field_chinese_name, field_type, parent_category, field_detail = field[1], field[2], field[
                    3], field[4], field[5]
                field_detail_info = f"这个字段的释义以及可能包含的单位量纲的介绍如下：{field_detail}" if field_detail else ""
                parent_category_info = f"同时该字段和'{parent_category}'这个上级类别有关。" if parent_category else ""
                output_text += f"{field_name}: {field_chinese_name}，{field_detail_info[:150]}，该字段的数值类别为：{field_type}, {parent_category_info}\n"
        output_text += '\n'


    background_info = f"""
    # 请注意如下的专家知识，供参考：
    # {domain_text}
    # {table_text}


    请根据以上要求生成**一个完整的**可直接执行的SQL查询语句（请勿输出思考过程和步骤解释，直接给出最终SQL代码）：

    1. 确保生成的SQL语句完整可执行。
    2. 所有字段均须来自已提供的表和字段，不得凭空编造。
    3. 查询结果中需包含：
        - 对应的时间段（如日期、时间字段）；
        - 股票名称；
        - 股票代码；
        - 与【问题】高度相关的其它字段；
        - 与查询条件（WHERE子句中使用）的字段；
    4. 请对相关数值字段进行单位换算与格式化显示，规则如下（查询结果中请以中文字段别名展示）：
        - 最高价、最低价、开盘价、收盘价：保留2位小数
        - 市值：以"亿"为单位，保留1位小数
        - 成交额：以"亿"为单位，保留2位小数
        - 股东户数：以"万"为单位，保留2位小数
        - 股本：以"亿"为单位，保留2位小数
        - 市盈率、市净率：保留2位小数
        - 每股收益、每股净资产：保留3位小数
        - 营业收入：以"亿"为单位，保留3位小数
        - 归母净利润、扣非净利润：以"万"为单位，保留1位小数
        - 毛利率、净资产收益率、股息率、净利率、资产负债率、销售净利率、销售毛利率：以"%"为单位并保留2位小数
        - 基金经理规模、基金规模：以"亿"为单位，保留2位小数

    请在最终SQL中严格执行上述格式化要求，并以中文输出字段别名。直接输出最终SQL查询语句，不要包含解释说明和中间推导过程。
     """
    output_text += background_info

    # 如果有 diagnose_res，将其插入到输出文本中
    if diagnose_res:
        output_text += (f"###错误的sql参考：\n {wrong_sql} "
                        f"\n【错误sql诊断结果】：{diagnose_res}\n\n")

    logging.info(f"表格级纠错prompt: {output_text}")
    return output_text
def embedding_sec_data():
    # update_path = os.path.join(script_dir, 'embedding_dict_STOCK_SNAME_updated.pkl')
    update_path = '/Users/rabyte_c/Desktop/experimental/text2sql_renew/vector/1VIEW_america_embedding_dict_updated.pkl'
    with open(update_path, 'rb') as pickle_file:
        return pickle.load(pickle_file)

def embedding_data():
    # update_path = os.path.join(script_dir, 'embedding_dict_updated_STI_updated.pkl')
    update_path = '/Users/rabyte_c/Desktop/experimental/text2sql_renew/vector-US/VIEW_nasdaq_embedding_dict_updated.pkl'
    with open(update_path, 'rb') as pickle_file:
        return pickle.load(pickle_file)



# ====================== Doris/MySQL规范提示生成 ======================
def generate_doris_specs() -> str:
    """生成Doris数据库特殊规范提示"""
    return """
注意！当前是使用 Doris (MySQL 协议兼容) 数据库进行查询，请注意如下书写细节：
1.【语法限制】请注意SQL 语句末尾不要有多余字符（比如分号;）；
2.【语法限制】使用 LIMIT n 来限制返回行数，不要使用 FETCH FIRST n ROWS ONLY；
3.【语法限制】日期格式化请使用 DATE_FORMAT(date, '%Y-%m-%d')，不要使用 TO_CHAR(date, 'YYYY-MM-DD')；
4.【语法限制】使用 IFNULL 代替 NVL；
5.【语法限制】日期比较直接使用字符串比较（如 PERIOD_DATE >= '2020-01-01'），不要使用 TO_DATE(...)；
6.【语法限制】使用 DATE_SUB(CURDATE(), INTERVAL n YEAR/MONTH/DAY) 进行日期运算，不要使用 ADD_MONTHS；
7.【语法限制】当使用UNION、UNION ALL时，必须确保对应列的数据类型完全一致；
8.【语法限制】任何出现在 SELECT 中且未被聚合的列，必须出现在 GROUP BY 中；
9. 注意！！！按年份分组时直接按照固定年份即可！不要使用多余的动态年份逻辑！
10. 注意！！！请按时间范围拉取所有数据！ 而不是总是按”最新日期”取一行！！
"""


# 保留旧名称别名兼容
generate_oracle_specs = generate_doris_specs

# ====================== EDB数据表字段说明生成 ======================
def generate_edb_field_descriptions() -> str:
    """生成EDB数据表字段说明"""
    return """
我来介绍下EDB数据表中包含的字段有哪些以及都是什么意思：

1. ind_der_code 用来定位的，你需要使用召回的指标对应的ind_der_code去相应的表中进行召回；
2. DATA_VALUE 指标对应的值，用户就想要查询这个；
3. PERIOD_DATE 数据周期日期。数据类型为 DATE， 举例：2025-02-28 00:00:00.000。请在展示该数据时注意使用DATE_FORMAT格式化为'%Y-%m-%d'形式的字符串（如'2025-03-15'）,不要直接展示DATE类型数据！！！
4. UPDATE_TIME 更新时间
5. PUBLISH_DATE 数据发布日期


注意！！数据表中有且仅有如上字段！！！请不要在sql中加入其他字段！！！
注意！！以上字段不存在于EDB_INDIC_DATA表！！！不要在EDB_INDIC_DATA表中查询DATA_VALUE、PERIOD_DATE、UPDATE_TIME、PUBLISH_DATE字段！！！
注意！！不要在select里出现重复的列名！
注意！！如果问题涉及时间序列，请在写sql中注意默认按照时间从最新到最旧展示！
注意！请从背景信息指标对应的表中获取数据。
注意！DATA_TABLE字段的值是告诉你每一个ind_der_code的数据该去哪个表里找，一个ind_der_code对应一个DATA_TABLE。
注意！当query涉及时间范围的时候，PERIOD_DATE请不要用=表达式来指定，而要选择适当的范围。
注意！若无相关数据可用，请写sql为：SELECT '无可用数据' AS `提示`
请注意所提供的表格中，可能会涵盖较多的NULL行，因此在使用WHERE条件的时候，请尽量添加去除NULL的条件。
"""




# ====================== SQL生成提示构建 ======================
async def build_sql_generation_prompt(
        query: str,
        format_final_filtered_top_50,
        final_filtered_top_50
) -> str:
    """
    构建SQL生成提示模板

    参数:
        query: 用户查询文本
        general_text: 通用知识文本
        table_text: 表结构知识文本
        filtered_indicators: 过滤后的指标列表
        year/month/day: 当前日期

    返回:
        完整的提示文本
    """
    table_text = await fetch_EDB_tables_knowledges(final_filtered_top_50)
    general_text = await fetch_EDB_knowledge()

    output_text = (
        f"你是讯兔科技研发的金融投研数据查询助手，尤其擅长基于数据库获取所需信息，例如使用NL2SQL方法。以下是需求的相信信息，请注意数据库类型为：Doris (MySQL 协议兼容)"
        f"今天的日期为 {year}年{month}月{day}日 \n")

    doris_info = generate_doris_specs()
    output_text += f"请在执行的时候，注意如下细节：\n{general_text}"
    output_text += doris_info

    table_info = \
        f"""\n如下的专家知识，请特别注意，只对对应的表格有效：
                {table_text}\n"""
    output_text += table_info

    output_text += (
        f'当前你所使用的数据为EDB数据，背景信息中会提供与用户query相关的指标名称以及对应的该指标所在的表DATA_TABLE、用来快速定位的唯一的ind_der_code以及对应的值DATA_VALUE，单位unit、统计频率\n'
        f'\n用户query为：{query}\n')

    data_info = generate_edb_field_descriptions()
    output_text += data_info
    output_text += (f"""\n            
目前分析发现该 query 可能涉及以下数据库指标，请选择下列信息中与query相关的指标编写 SQL 查询以满足用户需求。

下列表格中每行代表：
- ind_der_code：指标唯一ID（**仅用于筛选，不得在 SELECT 中展示**）
- DATA_TABLE：该指标所属数据表（仅限 EDB_INDIC_DATA 中存在）
- SHOW_NAME_SHORT：指标名称（**请在 SELECT 中通过 CASE 表达式定义中文别名**，**不要直接展示**）
- UNIT、FREQ、source：单位、频率和来源（仅供参考）

【重要规则】：
1. **SELECT 子句中严禁出现 ind_der_code、其编号、或 SHOW_NAME_SHORT 字段原文**；
2. **请仅使用 ind_der_code 或 SHOW_NAME_SHORT 精确匹配（= 或 IN）进行筛选，严禁使用 LIKE 模糊匹配**；
3. **只允许查询以下给出的 DATA_TABLE 表，禁止引用其他表！**

【相关指标信息】：
{format_final_filtered_top_50}

【严禁示例】（请避免如下错误用法）：
```sql
WHERE t2.SHOW_NAME_SHORT LIKE '%美国%'
  AND t2.SHOW_NAME_SHORT LIKE '%PPI%'
  AND t2.SHOW_NAME_SHORT LIKE '%环比%'

请务必严格按照以上规范，生成符合要求的 Doris (MySQL 协议兼容) SQL 查询语句。


请根据以上要求生成**一个完整的**可直接执行的SQL查询语句（请勿输出思考过程和步骤解释，直接给出最终SQL代码）：

1. **提供一个完整且可直接执行的SQL查询语句**，确保语法正确，无需包含解释或中间步骤。

2. **遵循MySQL语法**，避免使用不被支持的函数或特性。

3. **字段和表名必须来自上述提供的表和字段**，不得凭空编造或使用未提供的表和字段。

4. **准确反映用户的查询意图**，查询结果应满足用户需求。

5. **注意数据类型和单位的正确使用**，避免类型错误或单位混淆。

6. **进行必要的单位换算和格式化显示**，规则如下（请在SQL中实现）：
    - 最高价、最低价、开盘价、收盘价：**保留2位小数**
    - 市值：以“亿”为单位，**保留1位小数**
    - 成交额：以“亿”为单位，**保留2位小数**
    - 股东户数：以“万”为单位，**保留2位小数**
    - 股本：以“亿”为单位，**保留2位小数**
    - 市盈率、市净率：**保留2位小数**
    - 每股收益、每股净资产：**保留3位小数**
    - 营业收入：以“亿”为单位，**保留3位小数**
    - 归母净利润、扣非净利润：以“万”为单位，**保留1位小数**
    - 毛利率、净资产收益率、股息率、净利率、资产负债率、销售净利率、销售毛利率：以“%”为单位，**保留2位小数**
    - 基金经理规模、基金规模：以“亿”为单位，**保留2位小数**

7. **使用中文字段别名**，使查询结果更易读。

8. 最终请**只输出修正后的SQL查询语句**，不需要包含任何解释、注释或中间过程。

9. 请严格按以下格式生成SQL代码：
 ```sql
 [SQL语句] 
            """)

    return output_text,table_text,general_text,format_final_filtered_top_50
    # return "\n".join(prompt_parts)


def build_sql_reflection_prompt(
        error_sql: str,
        execution_result: str
) -> str:
    """
    构建SQL错误反射提示

    参数:
        error_sql: 有问题的SQL语句
        execution_result: SQL执行结果或错误信息
        available_fields: 可用的字段说明(可选)
        strict_format: 是否强制要求严格格式

    返回:
        完整的反射提示文本
    """
    reflect_prompt = f"""
            如下sql有问题，请重新生成sql并解释原因，请严格按以下格式生成SQL代码：
             ```sql
             [SQL语句] 
            """

    doris_info = generate_doris_specs()
    reflect_prompt += doris_info

    warnning_output = """
                请注意你仅可以使用如下字段：
                ind_der_code 用来定位的，你需要使用召回的指标对应的ind_der_code去相应的表中进行召回；
                DATA_VALUE 指标对应的值，用户就想要查询这个；
                PERIOD_DATE 数据周期日期。数据类型为 DATE。请在展示该数据时注意使用DATE_FORMAT格式化为'%Y-%m-%d'形式的字符串（如'2025-03-15'）,不要直接展示DATE类型数据！！！
                UPDATE_TIME 更新时间
                PUBLISH_DATE 数据发布日期

                注意！！以上字段不存在于EDB_INDIC_DATA表！！！不要在EDB_INDIC_DATA表中查询DATA_VALUE、PERIOD_DATE、UPDATE_TIME、PUBLISH_DATE字段！！！
                请注意数据库类型为：Doris (MySQL 协议兼容)

                如果错误sql中包含EDB_INDIC_DATA表，这个表仅包含的字段如下：
                ind_der_code（指标ID）、DATA_TABLE（指标所属的表，仅在EDB_INDIC_DATA表中存在）、SHOW_NAME_SHORT（你要选中的指标名，注意用CASE表达式来命名你选中的ind_der_code，ind_der_code不能直接展示，仅在EDB_INDIC_DATA表中存在）、UNIT(指标单位，仅在EDB_INDIC_DATA表中存在)、FREQ（指标的统计频率，仅在EDB_INDIC_DATA表中存在）


                注意！！！仅生成一段错误原因解释和一段修正后的SQL！！
                SQL必须符合以下格式：
                ```sql
             [SQL语句]


                """
    reflect_prompt += warnning_output
    reflect_prompt += f"错误sql：{error_sql}\n\n 结果：{execution_result}"
    logging.info(f'反思prompt如下：\n{reflect_prompt}')
    return reflect_prompt


def build_boundary_analysis_prompt(
        query: str
) -> str:
    """
    构建需求边界分析提示

    参数:
        query: 用户原始问题
        analysis_rules: 自定义分析规则(可选)
        output_format: 自定义输出格式(可选)
        example: 自定义示例(可选)

    返回:
        完整的分析提示文本
    """
    boundaries_prompt = f"""
            你是一个专业的数据需求分析专家，任务是根据用户提出的问题，明确其需求边界，并输出清晰的需求定义。以下是具体要求：

    问题描述：

    用户提出了一个问题：{query}
    目标：
    1.明确问题的具体需求边界。
    2.确定需要的数据范围、时间跨度、地理区域、数据类型等关键要素。
    3.指出可能的歧义点，并提供明确的解决方案。

    需求边界识别规则：
    1.时间范围：明确“最近十年”的起止年份（例如，2013年至2023年）。
    2.地理范围：确认“中国”是否包括所有省份及地区，或者是否有特定的细分需求（如某几个省份或城市）。
    3.数据类型：确定“CPI”是否指全国平均值、月度数据、年度数据，还是其他形式的统计指标。
    4.频率：明确数据的时间频率（如月度、季度、年度）。
    5.来源：建议可能的数据来源（如国家统计局、世界银行、IMF等）。
    6.其他潜在需求：考虑用户是否需要额外信息（如CPI的变化趋势分析、与其他经济指标的相关性分析）。

    输出格式：
    请以结构化的方式输出需求边界识别结果，格式如下：

        "问题": "用户提出的问题",
        "时间范围": "明确的时间跨度",
        "地理范围": "明确的地理区域",
        "品类范围":"关注的是整体值核心值、还是某个品类（如肉类、生活服务、水电燃料等）",
        "指标范围"："问题里的指标应该对应哪些范围，是要的该指标的细分的数据还是只要该指标整体的数据"，
        "数据类型": "问题里要的是什么指标",
        "频率": "数据的时间频率",
        "来源": "推荐的数据来源",
        "其他需求": "可能的扩展需求或备注"


    示例输出：

        "问题": "美国最近十年的CPI",
        "时间范围": "2013年1月至2023年12月",
        "地理范围": "美国（包含所有州及地区）",
        "品类范围"："关注的是整体核心值，排除其他细分品类数据，比如通信服务、鲜菜、其他用品和服务等"
        "数据类型": "我们只关注居民消费价格指数（CPI），不包括其他类型的数据（如PPI）",
        "频率": "年度数据",
        "来源": "美国国家统计局",
        "其他需求": "用户可能需要CPI的变化趋势分析以及与GDP增长率的相关性分析"

    注意！！！不要输出其他无关内容！！        
            """
    # boundaries_query = get_query_by_chat(boundaries_prompt)
    boundaries_query =  get_query_by_chat_gpt_4_1(boundaries_prompt)
    return boundaries_query

SYSTEM_PROMPT = """
你是一名资深金融数据 SQL 生成器。  
在输出 SQL 时，你**必须**遵循以下最高级规则：

1. **单位与数量级统一**  
   • 识别并将所有数值字段转换到统一基准单位  
     – 如“万”→ ×1e4，“亿”→ ×1e8，“千吨”→ ×1e3 kg；  
   • 在代码中添加清晰的行内注释，说明换算系数。

2. **指标UNIT一致性**  
   • 若操作数使用不同UNIT，务必先行换算后再计算。   
   • 禁止直接比较/相除仍处于不同币种的值。
   • 采用下面的的2024年汇率表换算,本币不参与换算; 
   • 在代码中添加清晰的行内注释，说明汇率换算流程。
     附注，汇率表，数据基于历史年度平均汇率：
            年度	USD/CNY (1美元=×元)	CNY→JPY (1元≈×日元)	CNY→HKD (1元≈×港元)	CNY→KRW (1元≈×韩元)	CNY→EUR (1元≈×欧元)
                2024	7.1217	21.09	1.0867	189.81	0.1285
               
3. **频率FREQ对齐**  
   • 确保所有参与计算的指标的时间序列在同一频率粒度  
     （如全部为“月”或全部为“年”）。 
    若存在高频 vs 低频：  
     – **先对高频数据聚合**到低频（如 `SUM()`12 个月→1 年，`AVG()`、`MAX()` 视业务而定）；  
     – 或反向使用累计列/年频指标替代，确保 `JOIN` 时主键唯一。  
   • 代码示例：`GROUP BY EXTRACT(YEAR FROM period_date)` 并加注释说明。  
   • 若无法对齐，需在结果处添加 `-- TODO: unresolved frequency mismatch` 并返回 `NULL`。
   • 在代码中添加清晰的行内注释，释说明频率是否对齐。

4. **SQL 质量**  
   • 输出符合 ANSI-SQL 的 Oracle / PostgreSQL 可执行脚本；  
     代码块内部不得写自然语言解释。  
   • 使用明确的列别名及易懂的子查询命名。

5. **兜底机制**  
   • 如缺少任何必要的单位、数量级或汇率信息，  
     仍应生成查询，但需在缺口处添加 `TODO` 注释，而非臆测填值。

回复内容**只包含最终 SQL**（如需 Markdown，请用 ```sql … ``` 包裹）。

"""

# ────────────────────────────── 新增两个小工具 ──────────────────────────────
def has_required_tokens(sql: str, required_tokens: List[str]) -> bool:
    """判断 SQL 字符串里是否包含所有必需字段（不区分大小写）"""
    sql_lower = sql.lower()
    return all(tok.lower() in sql_lower for tok in required_tokens)

def build_retry_prompt(orig_prompt: str, missing_tokens: List[str]) -> str:
    """给大模型的二次提示：说明缺了哪些字段，要求补上"""
    missing_str = ", ".join(missing_tokens)
    feedback = (f"\n\n注意！你生成的 SQL 不能缺少以下必需字段: {missing_str}，"
                f"请在保持业务逻辑正确的前提下重新生成，只返回 SQL。")
    return orig_prompt + feedback

# ────────────────────────────── 主函数改写 ──────────────────────────────
async def do_sql_generation(
    query: str,
    format_final_filtered_top_230: str,
    final_filtered_top_230: list,
    query_info,
    *,
    required_tokens: List[str] = ["ind_der_code"],
    max_retry: int = 2,
    model_name: str = "gpt-4.1",
    token_tracker: Optional["TokenTracker"] = None,
) -> Tuple[str, List[str], str, str, str, str]:
    """
    调用大模型生成 SQL，并返回清洗后的 SQL 字符串。
    若 SQL 缺少 required_tokens 中任一字段，将自动重试生成，最多 max_retry 次。
    """
    # ① 先构建基础 prompt
    prompt_text, table_text, general_text, table_fields_desc = \
        await build_sql_generation_prompt(query,
                                          format_final_filtered_top_230,
                                          final_filtered_top_230)
    logging.info(f"user prompt内容:\n{prompt_text}")
    logging.info(f"developer prompt内容:\n{SYSTEM_PROMPT}")

    for attempt in range(max_retry + 1):        # 第 0 次 + 若干重试
        t0 = time.time()
        logging.info(f"⏳ SQL 生成尝试 {attempt + 1}/{max_retry + 1} …")

        # ② 调用 LLM
        sql_query = await call_llm(prompt=prompt_text, model=model_name, SYSTEM_PROMPT = SYSTEM_PROMPT, token_tracker=token_tracker)
        elapsed = time.time() - t0
        logging.info(f"✅ SQL 生成完成，耗时 {elapsed:.2f}s")

        # ③ 清理 Markdown 包装
        cleaned_sql_query = (
            sql_query.replace("```sql", "")
                     .replace("```", "")
                     .strip()
        )

        # ④ 快速检测
        if has_required_tokens(cleaned_sql_query, required_tokens):
            logging.info("🎉 SQL 检测通过。")
            break  # 生成成功，跳出重试循环
        else:
            missing = [tok for tok in required_tokens
                       if tok.lower() not in cleaned_sql_query.lower()]
            logging.warning(f"⚠️ SQL 缺失字段 {missing}，准备重试…")

            if attempt == max_retry:
                logging.error("❌ 已达到最大重试次数，返回最后一次结果。")
                break  # 不再重试，返回现有 SQL
            # 更新 prompt，提示模型补缺字段
            prompt_text = build_retry_prompt(prompt_text, missing)
            logging.info(f"修复prompt内容:\n{prompt_text}")

    # ⑤ 计算后续派生值
    columns_to_drop = await get_filter_colunms_name(cleaned_sql_query)
    logging.info(f"用户 {query_info.get('userName')} 的问题 «{query}» 最终 SQL:\n{cleaned_sql_query}")

    return (cleaned_sql_query,
            columns_to_drop,
            prompt_text,
            table_text,
            general_text,
            table_fields_desc)



async def reflection_and_reexecute_sql(
    original_sql: str,
    sql_result,
    query: str,
    query_info,
    token_tracker: Optional["TokenTracker"] = None
):
    """
    当初次SQL执行失败时，调用大模型对SQL进行反思并改写，然后再次执行。
    返回 (status_code, final_sql_result)。
    """

    reflect_time_start = time.time()
    reflect_prompt = build_sql_reflection_prompt(original_sql, str(sql_result))
    reflect_res = await call_llm(prompt=reflect_prompt, model="gpt-4.1", token_tracker=token_tracker)
    logging.info(f"▌反思SQL完成，耗时: {time.time() - reflect_time_start:.2f}s")

    # 抽取SQL和诊断结果
    reflect_sql = extract_sql(reflect_res)
    diag_result = reflect_res.replace(reflect_sql, '')

    logging.info(f"诊断结果: {diag_result}")
    logging.info(f"用户 {query_info.get('userName')} 问题 {query} 重写的SQL: {reflect_sql}")

    reflect_execute_start = time.time()
    status_code, final_sql_result = await fetch_data_from_oracle(reflect_sql)
    logging.info(f"▌重写SQL查询执行完成，耗时: {time.time() - reflect_execute_start:.2f}s")


    if isinstance(final_sql_result, str):
        formatted_output = final_sql_result
    else:
        columns_to_drop = await get_filter_colunms_name(reflect_sql)
        formatted_output_for_next = final_sql_result[:data_limit_num].to_string(index=False)
        key_for_reflect_table = f"{query_info.get('questionId')}_0"
        formatted_output = df_to_table(key_for_reflect_table, columns_to_drop, final_sql_result)

    return status_code, reflect_sql, diag_result, formatted_output
