import asyncio
import logging

from service.sql_generator.text_to_sql_generator import extract_sql
from util.model_helpers import get_query_by_chat


async def handle_revenue_split(sql, text2sql_task, query, formatted_output, post_tel=None):
    """
    处理 "营收拆分" 任务的方法。

    :param text2sql_task: 任务类型，例如 '营收拆分'
    :param query: 查询语句
    :param formatted_output: 查询结果的格式化输出
    :param res: 当前的结果字符串
    :param websocket: WebSocket 连接对象
    :return: 更新后的结果字符串
    """
    res = ''
    if text2sql_task == '营收拆分' or post_tel == 'Y':
        # 构建提示信息
        split_check = (f'这是query：{query} 通过数据库所查询出来的的数据：\n\n {formatted_output} \n\n '
                        f'请你评估这个数据是否符合query要求，'
                       f'如果符合就原样输出；如果不符合就抽取出你认为相关的行作为查询结果返回给我，注意不需要其他的输出！！！只要抽取后的结果。'
                       f'注意，除了首行以外，你还要抽取出来相关的行，请注意数据里一定有相关的行。'
                       f'注意，首行一定要抽取，就是展示字段名的行')
        logging.info(f"{split_check}")

        # 调用 Chat 模型获取结果
        split_check_res = await asyncio.get_event_loop().run_in_executor(None, get_query_by_chat, split_check)

        split_check_sql = (
            f'这是query：{query} ，这是待纠正的sql：{sql}\n\n这是通过sql所查询出来的的数据：\n\n {formatted_output} \n\n '
            f'这是我期待的结果X:\n{split_check_res}\n'
            f'请你简单修改下我给你的待纠正sql，得到我期待的结果X'
            f'注意：只需要返回生成的SQL语句，不需要其他的输出！！！'
            f'注意：不要添加待纠正sql里没出现的的字段名进来')
        split_check_res_sql = await asyncio.get_event_loop().run_in_executor(None, get_query_by_chat, split_check_sql)

        res = extract_sql(split_check_res_sql)

        # # 更新结果字符串
        # res = res + f"结合问题抽取的结果:\n\n{split_check_res}\n\n"


        # 返回更新后的结果字符串
        return res, split_check_res
    else:
        # 返回默认提示信息
        # default_response = "当前任务类型不需要重新拆分数据。"
        return None, None