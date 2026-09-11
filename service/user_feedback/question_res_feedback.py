from service.sql_generator.text_to_sql_generator import extract_sql
from util.model_helpers import get_query_by_chat, get_query_by_chat_o1
import logging


# async def write_sql_with_feedback(combine_prompt, user_feedback, formatted_output, reflect_sql) -> str:
#     added_user_feedback = f"""【用户反馈】：\"{user_feedback}\"。请在生成SQL的时候特别关注用户的反馈，对生成的结果进行一定的调整。
#     【前一次的执行结果片段，请在调整的时候多关注该结果片段，并请特别关注部分字段，按照用户的反馈使用最接近的条件进行筛选！！！同时请特别注意过滤掉空白值！！！】{formatted_output}
#     【前一次生成的SQL】：{reflect_sql}\n
#     """
#
#     first_place = combine_prompt.find('\n')
#     combine_prompt = combine_prompt[:first_place] + f'\n同时我有如下的用户的反馈"{user_feedback}"，请注意用户反馈非常重要，在与原SQL问题有冲突的时候，请结合用户反馈并且以用户反馈的信息为准。\n' + combine_prompt[first_place:]
#
#     # 定义插入点前的标识字符串
#     insert_marker = "请注意，请生成可执行的SQL代码，不要输出思考过程！！！"
#
#     # 找到插入点的位置
#     insert_position = combine_prompt.find(insert_marker)
#
#     # 如果找到了插入点，插入用户反馈
#     if insert_position != -1:
#         # 将用户反馈插入到插入点之前
#         updated_prompt = combine_prompt[:insert_position] + '\n' + added_user_feedback + combine_prompt[insert_position:] + added_user_feedback
#     else:
#         # 如果没有找到标识字符串，则保持原来的 prompt
#         updated_prompt = combine_prompt
#
#     print("新的prompt", updated_prompt)
#
#     generated_sql = await get_query_by_chat_o1(updated_prompt)
#     generated_sql = extract_sql(generated_sql)
#     return generated_sql, updated_prompt


async def write_sql_with_feedback(combine_prompt, user_feedback, formatted_output, reflect_sql, history, query) -> str:
    if history and len(history) == 1:
        added_user_feedback = f"""【用户反馈】：\"{user_feedback}\"。请在生成SQL的时候特别关注用户的反馈，对生成的结果进行一定的调整。
        【前一次的执行结果片段，请在调整的时候多关注该结果片段，并请特别关注部分字段，按照用户的反馈使用最接近的条件进行筛选！！！同时请特别注意过滤掉空白值！！！】{formatted_output}
        【前一次生成的SQL】：{reflect_sql}\n
        """
    else: added_user_feedback = ''



    if history and len(history) != 1:
        # 整合历史反馈
        added_user_feedback += f"""注意，如下是用户过往的交互结果：\n"""
        for step, feedback_info in history.items():
            feedback_question = feedback_info['question']
            feedback_sql = feedback_info['context_snapshot']['reflectedSql']
            feedback_output = feedback_info['context_snapshot']['formattedOutput']
            added_user_feedback += f"""
                【历史反馈 {step}】：\"{feedback_question}\"。
                【历史反馈 {step} 的执行结果片段】：{feedback_output}
                【历史反馈 {step} 生成的SQL】：{feedback_sql}\n
                """



    first_place = combine_prompt.find('\n')
    combine_prompt = combine_prompt[:first_place] + f'\n同时我有如下的用户的反馈"{user_feedback}"，请注意用户反馈非常重要，在与原SQL问题有冲突的时候，请结合用户反馈并且以用户反馈的信息为准。\n' + combine_prompt[first_place:]

    updated_prompt = combine_prompt + added_user_feedback

    logging.info(f"feedback的prompt: {updated_prompt}")

    # # 定义插入点前的标识字符串
    # insert_marker = "请注意，请生成可执行的SQL代码，不要输出思考过程！！！"
    #
    # # 找到插入点的位置
    # insert_position = combine_prompt.find(insert_marker)
    #
    # # 如果找到了插入点，插入用户反馈
    # if insert_position != -1:
    #     # 将用户反馈插入到插入点之前
    #     updated_prompt = combine_prompt[:insert_position] + '\n' + added_user_feedback + combine_prompt[insert_position:] + added_user_feedback
    # else:
    #     # 如果没有找到标识字符串，则保持原来的 prompt
    #     updated_prompt = combine_prompt

    print("新的prompt", updated_prompt)

    generated_sql = await get_query_by_chat_o1(updated_prompt)
    return generated_sql, updated_prompt