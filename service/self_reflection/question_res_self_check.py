import asyncio
import re
from typing import Set, List, Tuple

from service.sql_executor.text_to_sql_exec import execute_sql
from service.sql_generator.text_to_sql_generator import extract_sql
from util.db_helpers import fetch_data_from_MYSQL
from util.model_helpers import get_query_by_chat

# 定义SQL关键字集合
sql_keywords = set([
    'SELECT', 'FROM', 'WHERE', 'JOIN', 'ON', 'WITH', 'AS', 'MAX', 'MIN', 'CASE', 'WHEN', 'THEN', 'ELSE', 'END',
    'ORDER', 'BY', 'DESC', 'ASC', 'PARTITION', 'OVER', 'ROW_NUMBER', 'UNION', 'ALL', 'GROUP', 'HAVING', 'IN', 'TO_DATE',
    'AND', 'OR'
])


def extract_all_fields(sql: str, keywords: Set[str]) -> Set[str]:
    """
    从SQL语句中提取所有字段名称，排除SQL关键字。

    参数:
    sql (str): 给定的SQL语句。
    keywords (Set[str]): SQL关键字集合。

    返回:
    Set[str]: 提取到的字段名称集合。
    """
    field_pattern = re.compile(r'\b[A-Za-z_]+\b')
    fields = set()

    for match in field_pattern.findall(sql):
        if match.upper() not in keywords:
            fields.add(match)

    return fields


def format_field_info(data_list: List[Tuple], candidate_fields: Set[str], table_define) -> str:
    """
    格式化字段信息。

    参数:
    data_list (List[Tuple]): 字段信息列表。
    candidate_fields (Set[str]): 候选字段集合。

    返回:
    str: 格式化的字段信息字符串。
    """
    field_dict = {}
    for item in data_list:
        table_name, field_name = item[0], item[1]
        if field_name in candidate_fields:
            if table_name not in field_dict:
                field_dict[table_name] = []
            field_dict[table_name].append(item)

    print("TABLE_DEFINE", table_define)

    table_details = {table[0]: {'name': table[1], 'description': table[2].replace('\n', '')} for table in
                     table_define}

    result = []
    for table_name, fields in field_dict.items():
        result.append(
            f"【表格{table_name}】：该表为{table_details[table_name]['name']}：{table_details[table_name]['description'][:200]}\n")
        for field in fields:
            field_info = f"  {field[1]}: {field[2][:150]}，该字段的数值类别为：{field[3]}"
            if field[5]:
                field_info += f"，{field[5]}"
            result.append(field_info)
        result.append("\n\n")

    return "\n".join(result)





async def reflect_and_correct_sql(query: str, final_sql: str, final_define: List[Tuple], general_text: str,
                                  domain_text: str, table_text: str, error_info: str, dbtype: str, table_define,
                                  user_feedback, status_code) -> str:
    """
    反思和纠正SQL查询。

    参数:
    query (str): 用户的查询需求。
    final_sql (str): 初步生成的SQL查询语句。
    final_define (List[Tuple]): 字段定义信息列表。
    general_text (str): 一般知识信息。
    domain_text (str): 域知识信息。
    table_text (str): 表格知识信息。
    error_info (str): 初步执行结果的错误信息。
    dbtype(str): 一级域的数据库类型。

    返回:
    str: 修改后的SQL查询语句。
    """
    candidate_fields = extract_all_fields(final_sql, sql_keywords)
    formatted_string = format_field_info(final_define, candidate_fields, table_define)

    domain_text = domain_text.replace(
        "当您询问关于“营收占比”的信息时，可以参考“PRI_RVNU_PCT”这一字段。此外，如果您的问题中包含了特定的筛选条件，例如“海外”或“国内”等，我们可以通过模糊匹配的方式，在“ITEM_NAME”字段中进行查询，例如使用查询语句 ITEM_NAME LIKE '%海外%' 来检索包含“海外”关键词的相关记录。",
        "请特别注意，如果初步执行结果为空，并且生成的SQL中有字段的模糊查询，例如ITEM_NAME LIKE“%海外%”，那么请对于不涉及查询问题主体的字段，适当放宽条件，剔除该字段对应的条件！！！").replace(
        "请特别注意：如果您的问题中包含了特定的营收拆分或者筛选条件，例如“海外收入占比”或“国内收入占比”，“学习机业务收入占比”等，我们可以通过模糊匹配的方式，在“ITEM_NAME”字段中进行查询，例如使用查询语句 ITEM_NAME LIKE '%海外%' 来检索包含“海外”关键词的相关记录。",
        "请特别注意，如果初步执行结果为空，并且生成的SQL中有字段的模糊查询，例如ITEM_NAME LIKE“%海外%”，那么请对于不涉及查询问题主体的字段，适当放宽条件，剔除该字段对应的条件！！！")

    if user_feedback:
        added_user_feedback = f"【用户反馈】：\"{user_feedback}\"。请在生成SQL的时候特别关注用户的反馈，对生成的结果进行一定的调整。\n"
    else:
        added_user_feedback = ""

    if status_code == 500:

        if "invalid identifier" in error_info.lower() or "00904" in error_info.lower():

            correct_instruct = """
            从报错信息可以发现，存在查询的列名可能不存在于目标表中。请进行检查并进行调整！！！
            请特别关注，字段和对应的表是否一致。请一定要关注你所使用的【字段】在对应的【表】中，否则请进行调整！！！请一定要关注你所使用的【字段】在对应的【表】中，否则请进行调整！！！请一定要关注你所使用的【字段】在对应的【表】中，否则请进行调整！！！
            """

        else:

            correct_instruct = """
            请特别关注，字段和对应的表是否一致。请一定要关注你所使用的【字段】在对应的【表】中，否则请进行调整！！！请一定要关注你所使用的【字段】在对应的【表】中，否则请进行调整！！！请一定要关注你所使用的【字段】在对应的【表】中，否则请进行调整！！！
            同时，请特别注意，如果初步执行结果为空，并且生成的SQL中有字段的模糊查询，例如ITEM_NAME LIKE “%海外%”，那么请对于不涉及查询问题主体的字段，适当放宽条件，剔除该字段对应的条件！！！
            请特别注意，如果初步执行结果为空，并且生成的SQL中有字段的模糊查询，例如ITEM_NAME LIKE “%海外%””，那么请对于不涉及查询问题主体的字段，适当放宽条件，剔除该字段对应的条件！！！
            请特别注意，如果初步执行结果为空，并且生成的SQL中有字段的模糊查询，例如ITEM_NAME LIKE “%海外%”，那么请对于不涉及查询问题主体的字段，适当放宽条件，剔除该字段对应的条件！！！
            如果初步执行结果为空，也可能是由于缺少最新数据。请尝试调整查询范围，不要仅依赖整个表中的最新数据，而是查找与问题主体相关的最新时间对应的数据！！！
            请特别注意，如果初步结果为空，并且生成的SQL中包含GROUP BY方法，那么请考虑是否有可能导致分组过于细化，甚至每条记录都是一个组。请放宽条件！！！
            请特别注意，如果初步结果为空，并且生成的SQL中包含GROUP BY方法，那么请考虑是否有可能导致分组过于细化，甚至每条记录都是一个组。请放宽条件！！！
            检查的时候，请特别关注SQL中是否存在这样的片段：A表.InnerCode = B表.CompanyCode，请特别注意，CompanyCode（公司代码）作为主键的表能先与SECUMAIN进行关联，设置相应的限定条件，以便获得InnerCode（股票代码）后再与其他股票维度的表进行关联。我们展示给用户的结果必须是股票维度的，而非公司维度。请注意不同表的COMPANYCODE不能和INNERCODE直接关联起来        
            """

        reflect_prompt = f"""
        如下为针对TEXT2SQL生成结果的反思、纠错流程，请针对报错信息，结合相关字段以及专家知识，进行修改：

        我有以下查询需求：“{query}？”。同时，我已经生成了以下SQL查询语句，请注意这个SQL语句已经基于之前的表格定义和列定义生成，尽量不要添加未知的信息（例如表明、字段名）：
        请注意数据库类型为：{dbtype}

        {final_sql}

        请在执行的时候，注意如下细节：
        {general_text}

        同时请注意如下的专家知识，供参考：
        {domain_text}
        如下的专家知识，请特别注意，只对对应的表格有效：
        {table_text}

        【附件一】我有如下的初步执行结果：

        {error_info}

        【附件二】

        以下是生成的SQL语句中涉及字段的详细信息，作为参考：
        {formatted_string}
        {correct_instruct}
        {added_user_feedback}

        【任务】请认真核对上述信息，对生成的SQL语句进行必要的调整。
        请注意，请直接生成【可执行的SQL代码】，请不要输出思考过程！！！请直接生成【可执行的SQL代码】，请不要输出思考过程！！！请直接生成【可执行的SQL代码】，请不要输出思考过程！！！
        """
    elif status_code == 200:
        reflect_prompt = f"""
        如下为针对TEXT2SQL生成结果的进行检查，请结合相关字段以及专家知识，判断书写的SQL和初步生成的结果是否满足专家知识的条件，如果没有请进行修改，如果符合要求则请输出原SQL：

        我有以下查询需求：“{query}？”。同时，我已经生成了以下SQL查询语句，请注意这个SQL语句已经基于之前的表格定义和列定义生成，尽量不要添加未知的信息（例如表明、字段名）：
        请注意数据库类型为：{dbtype}

        {final_sql}

        请在执行的时候，注意如下细节：
        {general_text}

        同时请注意如下的专家知识，供参考：
        {domain_text}
        如下的专家知识，请特别注意，只对对应的表格有效：
        {table_text}

        【附件一】我有如下的初步执行结果：

        {error_info}

        【附件二】

        以下是生成的SQL语句中涉及字段的详细信息，作为参考：
        {formatted_string}
        请特别关注，字段和对应的表是否一致。请一定要关注你所使用的【字段】在对应的【表】中，否则请进行调整！！！请一定要关注你所使用的【字段】在对应的【表】中，否则请进行调整！！！请一定要关注你所使用的【字段】在对应的【表】中，否则请进行调整！！！
        同时，请特别注意，如果初步执行结果为空，并且生成的SQL中有字段的模糊查询，例如ITEM_NAME LIKE “%海外%”，那么请对于不涉及查询问题主体的字段，适当放宽条件，剔除该字段对应的条件！！！
        请特别注意，如果初步执行结果为空，并且生成的SQL中有字段的模糊查询，例如ITEM_NAME LIKE “%海外%”，那么请对于不涉及查询问题主体的字段，适当放宽条件，剔除该字段对应的条件！！！
        请特别注意，如果初步执行结果为空，并且生成的SQL中有字段的模糊查询，例如ITEM_NAME LIKE“%海外%”，那么请对于不涉及查询问题主体的字段，适当放宽条件，剔除该字段对应的条件！！！
        如果初步执行结果为空，也可能是由于缺少最新数据。请尝试调整查询范围，不要仅依赖整个表中的最新数据，而是查找与问题主体相关的最新时间对应的数据！！！
        请特别注意，如果初步结果为空，并且生成的SQL中包含GROUP BY方法，那么请考虑是否有可能导致分组过于细化，甚至每条记录都是一个组。请放宽条件！！！
        请特别注意，如果初步结果为空，并且生成的SQL中包含GROUP BY方法，那么请考虑是否有可能导致分组过于细化，甚至每条记录都是一个组。请放宽条件！！！
        检查的时候，请特别关注SQL中是否存在这样的片段：A表.InnerCode = B表.CompanyCode，请特别注意，CompanyCode（公司代码）作为主键的表能先与SECUMAIN进行关联，设置相应的限定条件，以便获得InnerCode（股票代码）后再与其他股票维度的表进行关联。我们展示给用户的结果必须是股票维度的，而非公司维度。请注意不同表的COMPANYCODE不能和INNERCODE直接关联起来
        {added_user_feedback}

        【任务】请认真核对上述信息，对生成的SQL语句进行必要的调整。
        请注意，请直接生成【可执行的SQL代码】，请不要输出思考过程！！！请直接生成【可执行的SQL代码】，请不要输出思考过程！！！请直接生成【可执行的SQL代码】，请不要输出思考过程！！！
        """
    print(reflect_prompt)
    reflect_res = await asyncio.get_event_loop().run_in_executor(None, get_query_by_chat, reflect_prompt)
    reflect_res = extract_sql(reflect_res)
    return reflect_res, reflect_prompt


async def process_sql_execution(query: str, final_sql: str, final_define: List[Tuple], general_text: str,
                                domain_text: str, table_text: str, username: str, password: str, dsn: str) -> Tuple[
    int, str]:
    """
    处理SQL执行和反思纠错流程。

    参数:
    query (str): 用户的查询需求。
    final_sql (str): 初步生成的SQL查询语句。
    final_define (List[Tuple]): 字段定义信息列表。
    general_text (str): 一般知识信息。
    domain_text (str): 域知识信息。
    table_text (str): 表格知识信息。
    username (str): 数据库用户名。
    password (str): 数据库密码。
    dsn (str): 数据库服务名。

    返回:
    Tuple[int, str]: 状态码和最终查询结果或错误信息。
    """
    status_code, result = await execute_sql(final_sql, username, password, dsn)

    if status_code == 200:
        return status_code, result
    elif status_code == 500:
        reflect_res = await reflect_and_correct_sql(query, final_sql, final_define, general_text, domain_text,
                                                    table_text, result)
        status_code, result = await execute_sql(reflect_res, username, password, dsn)
        return status_code, result
