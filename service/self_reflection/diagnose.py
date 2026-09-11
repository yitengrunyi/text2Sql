import asyncio
import os
from datetime import datetime
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from util.token_tracker import TokenTracker

from util.model_helpers import get_query_by_chat, get_query_by_chat_o1, get_query_by_chat_o1_by_text,call_llm


SQL_GENERATION_MODEL = os.environ.get(
    "TEXT2SQL_SQL_MODEL",
    "nulls-gemini-2.5-pro",
)


async def diagnose_result(query, sql_res, exe_res, status_code, token_tracker: Optional["TokenTracker"] = None):
    current_date = datetime.today().strftime('%Y年%m月%d日')

    if status_code == 500:

        wrong_prompt = f"""
        请帮我诊断如下的执行结果为什么是错误的或者没有取到结果，请告诉我所有的可能性，包括:
        1. 表格是否可能缺失导致模型没有正确取得；
        2. 数据是否本身可能缺失；
        3. 语法句法可能错误；
        4. 没有对应的字段，模型可能捏造的字段；
        4. 其他可能的问题。 

        请输出最可能的2个原因。

        【问题】{query} 
        【模型生成的SQL】{sql_res}
        【执行结果】{exe_res}

        请注意： 1. 当前MYSQL版本为 8.0.28， 2. 该查询执行时间为{current_date}。
        """

        diagnose_result = await call_llm(
            prompt=wrong_prompt,
            model=SQL_GENERATION_MODEL,
            token_tracker=token_tracker,
        )

        return diagnose_result

    else:

        correct_prompt = f"""
         请帮我诊断如下的执行结果是否存在问题，包括:
         1. 存在重复的行；
         2. 存在大量的空值；
         3. 输出的结果并没有能够回答问题，可能数据或者表格有限导致模型没能取到完整的结果；
         4. 输出的结果违反金融财务或经济常理，例如 持股比例超过100%；
         5. 其他可能的问题。 

         【问题】{query} 
         【模型生成的SQL】{sql_res}
         【执行结果】{exe_res}

         如果不存在问题，请输出"不存在潜在问题"， 否则请输出最可能的两个潜在问题。

         请注意： 1. 当前MYSQL版本为 8.0.28， 2. 该查询执行时间为{current_date}。
         """

        diagnose_result = await call_llm(prompt=correct_prompt, model="gpt-4.1", token_tracker=token_tracker)


        return diagnose_result
