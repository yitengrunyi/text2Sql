import pandas as pd
import openai
import asyncio


db_type = 'MYSQL-1'
username, password, dsn, host, port = "", "", "", "", None
if db_type == "MYSQL-1":
    username ='etl'
    password = '5RDsS56g13UU^&O&v'
    host = 'mr-bth0s2yfzy228yweuw.rwlb.rds.aliyuncs.com'
    port = 3306
elif db_type == "MYSQL-2":
    username ='juling'
    password = 'G&N$Ls9LVVMBgL49'
    host = 'rm-2ze3bb361946ye7oq.mysql.rds.aliyuncs.com'
    port = 3306
else:
    assert db_type in ["MYSQL-1", "MYSQL-2"], f"{db_type}为未支持数据库类型"

import aiomysql
from typing import  Any
from typing import Tuple
import numpy as np
import pandas as pd
async def fetch_data_from_MYSQL(final_sql: str, host: str = 'mr-bth0s2yfzy228yweuw.rwlb.rds.aliyuncs.com',
                                user: str = 'etl', password: str = '5RDsS56g13UU^&O&v', port: int = 3306, database_name = 'FUND_INFO') -> Tuple[int, Any]:
    """
    从 MySQL 数据库中获取数据（异步）。

    参数:
    final_sql (str): 要执行的 SQL 查询。
    host (str): 数据库主机地址。
    user (str): 数据库用户名。
    password (str): 数据库密码。
    database (str): 要使用的数据库名称。
    port (int): 数据库端口号，默认为 3306。

    返回:
    Tuple[int, Any]: 状态码和查询结果或错误信息。
    """
    status_code = 200
    return_res = None
    connection = None
    cursor = None

    try:
        # 创建异步数据库连接
        connection = await aiomysql.connect(
            host=host,
            user=user,
            password=password,
            db=database_name,  # 数据库名称
            port=port
        )
        print("Database connection established successfully.")

        # 创建一个异步游标
        cursor = await connection.cursor()
        print("Cursor obtained successfully.")

        # 执行 SQL 查询
        print(final_sql)  # 打印SQL，调试用
        await cursor.execute(final_sql)
        print("Fetch query executed successfully.")

        # 获取查询结果
        rows = await cursor.fetchmany(30000000)  # 只获取前100条记录

        field_names = [desc[0] for desc in cursor.description]  # 获取字段名称
        print(rows)  # 打印查询结果，调试用
        print(f"\n{field_names}\n")  # 打印字段名称，调试用

        # 将数据转换为 DataFrame
        if rows:
            df = pd.DataFrame(rows, columns=field_names)
            return_res = df
        else:
            return_res = "No rows fetched. 查找结果为空，请检查SQL语句"
            status_code = 500
            print("No rows fetched. 查找结果为空，请检查SQL语句")

    except aiomysql.Error as e:
        status_code = 500
        return_res = f"MySQL Database error: {str(e)}"
        print(return_res)

    except Exception as e:
        status_code = 500
        return_res = f"An unexpected error occurred: {str(e)}"
        print(return_res)

    finally:
        # 关闭游标和连接
        try:
            if cursor:
                await cursor.close()
                print("Cursor closed successfully.")
            if connection:
                connection.close()
                print("Database connection closed successfully.")
        except aiomysql.Error as e:
            print("Error closing connection:", str(e))

    # 返回结果
    return status_code, return_res

async def execute_sql(sql: str, username: str, password: str, dsn: str, host: str, port: int, dbtype: str) -> tuple[int, str]:
    """
    执行SQL查询并返回结果。

    参数:
    sql (str): SQL查询语句。
    username (str): 数据库用户名。
    password (str): 数据库密码。
    dsn (str): 数据库服务名。
    host(str)
    port(str): 端口号
    dbtype (str): 一级域的数据库类型。

    返回:
    Tuple[int, str]: 状态码和查询结果或错误信息。
    """
    status_code, result = None, None
    if dbtype == "MYSQL-1":
        status_code, result = await fetch_data_from_MYSQL(sql, host, username, password, port, 'test')
    elif dbtype == "MYSQL-2":
        status_code, result = await fetch_data_from_MYSQL(sql, host, username, password, port, 'juling')
    else:
        assert dbtype in ["MYSQL-1", "MYSQL-2"], f"{dbtype}为不支持查询的数据库类型！\n"

    return status_code, result

# 执行最终 SQL 查询的函数
async def execute_final_sql(sql: str) -> Tuple[int, Any]:
    status_code, result = await execute_sql(sql, username, password, dsn, host, port, db_type)
    return status_code, result

# final_sql="""
# SELECT distinct(NAME_CN) from test.eco_info_pro8 x
#
#
# """
#
# status_code, final_result = await execute_final_sql(final_sql)



def get_query_by_chat(prompt: str) -> str:
    """
    通过与 GPT-4 聊天 API 交互获取查询语句。

    参数:
    prompt (str): 发送给 GPT-4 的提示语。

    返回:
    str: GPT-4o 的响应内容。
    """
    # OpenAI API 密钥设置
    openai.api_key = 'sk-fZy6ocIFW0c_SDsdDyITwX9WE5qdebst0RtjYacBk1T3BlbkFJLy7OXZrQcCxv33vYHNdzVnnVrSuAT8ixWbH5o5NSEA'
    openai.api_base = "https://api.openai.com/v1"

    completion = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[
            {"role": "system",
             "content": "你是讯兔科技研发的金融投研数据查询助手，尤其擅长基于数据库获取所需信息，例如使用NL2SQL方法。"},
            {"role": "user", "content": prompt}
        ],
        temperature=0.001
    )

    res = completion.choices[0].message.content

    # 获取并输出token使用情况
    token_usage = completion.usage
    print(f"Prompt tokens: {token_usage['prompt_tokens']}")
    print(f"Completion tokens: {token_usage['completion_tokens']}")
    print(f"Total tokens: {token_usage['total_tokens']}")

    return res

# get_query_by_chat('你好')
# 假设 execute_final_sql 和 get_query_by_chat 是已经定义好的函数
# async def execute_final_sql(sql):
#     """
#     执行 SQL 查询并返回结果 DataFrame。
#     """
#     # 这里需要实现具体的 SQL 查询逻辑
#     pass
#
# def get_query_by_chat(prompt: str) -> str:
#     """
#     调用大模型生成表格介绍信息。
#     """
#     # 这里需要实现调用大模型的逻辑
#     pass

async def process_excel(file_path: str, output_path: str):
    """
    处理 Excel 文件，生成表格介绍信息并保存到新列。
    """
    # 读取 Excel 文件
    df = pd.read_excel(file_path)

    # 确保输出文件包含新列
    if 'TABLE_DESCRIPTION' not in df.columns:
        df['TABLE_DESCRIPTION'] = None

    # 循环处理每一行
    for index, row in df.iterrows():
        table_ename = row['TABLE_ENAME']

        # 查询表的中文名和表描述
        sql_table = f"""
            SELECT TABLE_CNAME, TABLE_DESC 
            FROM schema_metadata.MDB_TABLE 
            WHERE TABLE_ENAME = '{table_ename}'
        """
        status_code, table_result = await execute_final_sql(sql_table)

        if status_code != 200 or table_result.empty:
            print(f"未找到表 {table_ename} 的信息")
            continue

        table_cname = table_result.iloc[0]['TABLE_CNAME']
        table_desc = table_result.iloc[0]['TABLE_DESC']

        # 查询表的字段信息
        sql_columns = f"""
            SELECT COLUMN_ENAME, COLUMN_CNAME, COLUMN_DESC 
            FROM schema_metadata.MDB_COLUMN_JULING 
            WHERE TABLE_ENAME = '{table_ename}'
        """
        status_code, columns_result = await execute_final_sql(sql_columns)

        if status_code != 200 or columns_result.empty:
            print(f"未找到表 {table_ename} 的字段信息")
            continue

        # 将字段信息格式化为字符串
        columns_info = []
        for _, column_row in columns_result.iterrows():
            column_ename = column_row['COLUMN_ENAME']
            column_cname = column_row['COLUMN_CNAME']
            column_desc = column_row['COLUMN_DESC']
            columns_info.append(f"{column_cname}（{column_ename}）：{column_desc}")

        columns_info_str = "\n".join(columns_info)

        # 构建 Prompt 调用大模型
        prompt = f"""
            表名：{table_cname}
            表描述：{table_desc}
            字段信息：
            {columns_info_str}

            请根据以上信息生成一段表格介绍信息，格式如下：
            收录基金经理的基本情况，包括：从业机构、性别、出生年份、最高学历、管理年限、管理基金数量、换手率、管理规模等。
        """
        table_description = get_query_by_chat(prompt)

        # 将结果保存到 DataFrame 的新列中
        df.at[index, 'TABLE_DESCRIPTION'] = table_description

    # 保存结果到 Excel 文件
    df.to_excel(output_path, index=False)
    print(f"结果已保存到 {output_path}")



# 定义一个异步主函数
async def main():
    # 示例调用
    input_file = "/Users/rabyte_c/Downloads/4o-新增表分类59.xlsx"  # 输入 Excel 文件路径
    output_file = "/Users/rabyte_c/Downloads/output-59.xlsx"  # 输出 Excel 文件路径
    await process_excel(input_file, output_file)

# 运行异步主函数
if __name__ == "__main__":
    asyncio.run(main())