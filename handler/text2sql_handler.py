import ast
import copy
import json
import os
import time
import asyncio
import logging
import traceback
import pandas as pd
from websocket import WebSocket
from EDB_search import process_query
from common.middleware.db_utils import get_mysql3_pool
from common.middleware.redis_util import redis_client
from common.middleware.resp_util import send_success_answer, QUERY_INTENT, BACKGROUND_INFO, INDUSTRY_DISPLAY, \
    DOMAIN_ONE, DOMAIN, TABLE_NAME, SQL1, SQL1_CODE, SQL1_RES, EXPLAIN_RES, SELECTED_TABLE, \
    REFLECTED_TABLE_SQL, REFLECTED_TABLE_SQL_CODE, REFLECTED_TABLE_SQL_RES, REFLECTED_FIELD_SQL, \
    REFLECTED_FIELD_SQL_CODE, REFLECTED_FIELD_SQL_RES, EXCEPTION, QUERY_INTENT_PAIPAI, SPECIAL_TASK_NAME, \
    MANAGER_POSITION_INFO, SUBJECT_INFO, TOP3_SHARE_HOLDER, SPECIAL_CASES_SPLIT_SQL, SPECIAL_CASES_SPLIT_CODE, \
    SPECIAL_CASES_SPLIT_RES, DIAG_RES, USER_INTERRUPT, SPECIAL_SPLIT_ITEMS, CONCEPT_DISPLAY, ENTITY_DISPLAY, \
    PROCESS_START, UNREACH_DATA, REJECT, USER_INTENT_REFUSE
from service.analysis.question_analysis import question_analysis, query_intent_recg
from service.locator.domain_locator import fetch_and_process_domains_one, get_dbtype_from_domain_one, \
    fetch_and_process_domains
from service.locator.question_locator import get_query_embedding, extract_and_merge_lists, fetch_and_process_concepts, classify_concepts_track_industry, fetch_and_process_track
from service.locator.stock_and_industry_locator import fetch_stock_industry_topics, fetch_industry_topics
from service.locator.table_locator import fetch_and_process_tables, extract_tables
from service.self_reflection.diagnose import diagnose_result
from service.self_reflection.question_res_self_check import reflect_and_correct_sql, extract_all_fields
from service.self_reflection.sql_explanation_info import get_explanation_info
from service.sql_executor.text_to_sql_exec import execute_sql
from service.sql_generator.handle_revenue_split import handle_revenue_split
from service.sql_generator.text_to_sql_generator import fetch_and_generate_sql_o1, fetch_and_generate_sql
from util.data_formater_helpers import df_to_table, data_limit_num, get_filter_colunms_name
from util.db_helpers import insert_data_to_mysql
from util.fix_fields import recall_tables
from util.model_helpers import call_llm
from util.rag_helpers import get_bgeM3embeddings
from util.common import build_table_fields_description
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from util.token_tracker import TokenTracker

sql_keywords = set([
    'SELECT', 'FROM', 'WHERE', 'JOIN', 'ON', 'WITH', 'AS', 'MAX', 'MIN', 'CASE', 'WHEN', 'THEN', 'ELSE', 'END',
    'ORDER', 'BY', 'DESC', 'ASC', 'PARTITION', 'OVER', 'ROW_NUMBER', 'UNION', 'ALL', 'GROUP', 'HAVING', 'IN', 'TO_DATE', 'AND', 'OR'
])

def extract_sql(sql_text: str) -> str:
    """
    从模型返回的文本中提取并清理SQL代码。
    
    处理多种格式：
    1. ```sql 标记的代码块（各种变体，如有空格、缩进等）
    2. ```SQL 标记的代码块（大写）
    3. 不带标记的纯SQL语句
    
    Args:
        sql_text: 模型返回的可能包含SQL的文本
        
    Returns:
        清理后的SQL语句
    """
    import re
    
    # 去除前后空白
    sql_text = sql_text.strip()
    
    # 检查是否包含代码块标记
    if "```" in sql_text:
        # 尝试提取代码块中的SQL - 处理各种格式
        pattern = r"```(?:sql|SQL)?(?:\s|\n)*([\s\S]*?)```"
        match = re.search(pattern, sql_text)
        if match:
            return match.group(1).strip()
    
    # 如果仍未识别为SQL，返回原始输入
    return sql_text

async def handle_query_demo_for_mq(query_info_req, websocket: WebSocket = None, token_tracker: Optional["TokenTracker"] = None):
    query = query_info_req.get('question')
    # 初始化可能未被赋值的变量
    table_text = ""
    combine_prompt = ""
    formatted_output = ""
    reflected_sql = ""
    final_define = []
    filtered_table_define = []
    general_text = ""
    domain_text = ""
    table_define = []
    formatted_output_for_next = None
    field_recall = False
    explain_res = ""  # 初始化explain_res变量，确保所有执行路径都能返回该变量
    db_type = "MYSQL"  # 为 db_type 提供默认值，防止异常处理中引用未赋值变量
    
    # 获取请求信息
    question_id = query_info_req.get('questionId')
    feedback_question_id = query_info_req.get('feedbackQuestionId')
    user_id = query_info_req.get('userId')
    user_name = query_info_req.get('userName')
    session_id = query_info_req.get('sessionId')
    system = query_info_req.get('system')
    # 创建一个新的字典，只包含需要的字段
    query_info = {
        'question': query,
        'questionId': question_id,
        'userId': user_id,
        'userName': user_name,
        'feedbackNum':0,
        'sessionId':session_id,
        'system':system,
        'messageId':f"{question_id}_0",
        'mode': query_info_req.get('mode')
    }
    
    start_time = time.time()
    res = f"【问题】{query}\n\n";
    formatted_output = ""
    formatted_output_for_next = ""
    analysis_time = time.time()
    try:
        stock_info, companies, us_stock_codes = await fetch_stock_industry_topics(query)
        logging.info(f'美股抽取：{companies},{us_stock_codes}')

        intent_recg,explain_word, res_str = await query_intent_recg(query, stock_info, companies, token_tracker=token_tracker)
        logging.info(f'十大分类结果：{res_str}，解释：{explain_word}')
        if intent_recg =="2":
            await send_success_answer(request_string=query_info,
                                          answer_string=explain_word,type=USER_INTENT_REFUSE,is_end=True,
                                          websocket=websocket, token_tracker=token_tracker)
            return
        elif intent_recg =="3":
            await send_success_answer(request_string=query_info,
                                          answer_string=explain_word,type=USER_INTENT_REFUSE,is_end=True,
                                          websocket=websocket, token_tracker=token_tracker)
            return
        elif intent_recg =="4":
            edb_answer = await process_query(query_info_req = query_info_req, websocket = websocket, token_tracker=token_tracker)
            # await send_success_answer(request_string=query_info,
            #                           answer_string=edb_answer, type=USER_INTENT_REFUSE, is_end=True,
            #                           websocket=websocket)
            return
        if stock_info is None:
            industry_str = await fetch_industry_topics(query, res_str)
        else: industry_str = stock_info

        embedding_time = time.time()
        # Query Understanding
        # background_info = await get_background_info(query)
        query_embedding, explain, extract_res = await get_query_embedding(query, token_tracker=token_tracker)
        background_info = explain

        await send_success_answer(request_string=query_info,
                                  answer_string=f"{background_info}", type=BACKGROUND_INFO,
                                  websocket=websocket)
        await send_success_answer(request_string=query_info,
                                  answer_string=f"{extract_res}", type=ENTITY_DISPLAY,
                                  websocket=websocket)

        interrupt_flag = await jug_user_interrupt(query_info,question_id, token_tracker)
        if interrupt_flag:
            return





        logging.info(f"用户{user_name} 问题{query} 参考的问题分析: {background_info}")
        logging.info(f"用户{user_name} 问题{query} 参考的问题分析耗时:{time.time()-embedding_time}")
        # res = res + f"【执行步骤】同时我定位到问题中关键指标信息以及可能的计算: {explain}\n\n"
        # logging.info(f"同时我定位到问题中关键指标信息以及可能的计算: {explain}")
        industry_time = time.time()
        # 第四步：行业定位

        interrupt_flag = await jug_user_interrupt(query_info,question_id, token_tracker)
        if interrupt_flag:
            return

        # logging.info(f"定位到行业结果: {industry_display}")

        # 题材定位
        concepts = await fetch_and_process_concepts(query, token_tracker=token_tracker)
        # if concepts is not '':
            # await send_success_answer(request_string=query_info,
            #                           answer_string=f"{concepts}", type=CONCEPT_DISPLAY,
            #                           websocket=websocket)

        # 赛道定位
        track = await fetch_and_process_track(query, token_tracker=token_tracker)

        # 赛道、行业、题材综合判断
        concepts_track_industries_mapping = await classify_concepts_track_industry(query, concepts, track, industry_str, token_tracker=token_tracker)
        concepts = concepts_track_industries_mapping['concepts']
        industry_str = (
            concepts_track_industries_mapping['industry']
            if concepts_track_industries_mapping.get('industry') is not ''
            else concepts_track_industries_mapping.get('track')
        )
        logging.info(f"用户{user_name} 问题{query} 定位赛道、行业、题材: {industry_str}")
        logging.info(f"用户{user_name} 问题{query} 定位赛道、行业、题材耗时:{time.time()-industry_time}")

        industry_display = "此问题不涉及到个股、行业或者题材" if industry_str == '' else industry_str
        await send_success_answer(request_string=query_info,
                                  answer_string=f"{industry_display}", type=INDUSTRY_DISPLAY,
                                  websocket=websocket)
        if concepts is not '':
            await send_success_answer(request_string=query_info,
                                      answer_string=f"{concepts}", type=CONCEPT_DISPLAY,
                                      websocket=websocket)
        domain_one_time = time.time()
        # 第二步：定位到域
        # 先定位到一级域，再定位到二级域
        domain_one_res = await fetch_and_process_domains_one(query,background_info, industry_str, concepts, token_tracker=token_tracker)

        logging.info(f"用户{user_name} 问题{query} 一级域定位耗时:{time.time()-domain_one_time}")
        await send_success_answer(request_string=query_info,
                                  answer_string=f"{domain_one_res}", type=DOMAIN_ONE,
                                  websocket=websocket)


        interrupt_flag = await jug_user_interrupt(query_info,question_id, token_tracker)
        if interrupt_flag:
            return

        logging.info(f"用户{user_name} 问题{query}定位到一级域结果{domain_one_res}")
        domain_one_str = domain_one_res.replace('[','').replace(']','').replace('\'','')
        db_type = get_dbtype_from_domain_one(domain_one_str)
        domain_time = time.time()
        domain_res = await fetch_and_process_domains(query, background_info, domain_one_str, industry_str, concepts, token_tracker=token_tracker)
        if not domain_res:
            await send_success_answer(request_string=query_info,
                                      answer_string=f"数据未覆盖", is_end=True,type=UNREACH_DATA,
                                      websocket=websocket, token_tracker=token_tracker)

        logging.info(f"用户{user_name} 问题{query} 二级域定位耗时:{time.time()-domain_time}")
        await send_success_answer(request_string=query_info,
                                  answer_string=f"{domain_res}", type=DOMAIN,
                                  websocket=websocket)

        logging.info(f"用户{user_name} 问题{query}定位到域结果: {domain_res}")

        interrupt_flag = await jug_user_interrupt(query_info,question_id, token_tracker)
        if interrupt_flag:
            return


        table_time = time.time()
        # 第三步：定位到表
        domain_str = domain_res.replace('[', '(').replace(']', ')')
        print(domain_str)
        table_res, table_define = await fetch_and_process_tables(
            query,
            domain_str,
            background_info,
            domain_one_str,
            industry_str,
            concepts,
            db_type,
            token_tracker=token_tracker,
        )
        logging.info(f"用户{user_name} 问题{query} 表定位{table_res}")
        logging.info(f"用户{user_name} 问题{query} 表定位耗时:{time.time()-table_time}")

        await send_success_answer(request_string=query_info,
                                  answer_string=f"{table_res}", type=TABLE_NAME,
                                  websocket=websocket)


        logging.info(f"用户{user_name} 问题{query}定位到表结果: {table_res}")

        interrupt_flag = await jug_user_interrupt(query_info,question_id, token_tracker)
        if interrupt_flag:
            return

        # 初始化 field_recall 为 False
        field_recall = False
        matched_tables = []

        # 判断 table_res 中是否有表名命中 recall_table 的键
        for table_name in table_res:
            if table_name.upper() in recall_tables:
                field_recall = True
                # 取出命中的 key 对应的 value
                field, field_des, field_examples = recall_tables[table_name.upper()]
                matched_tables.append((table_name, field, field_des, field_examples))
        # if field_recall == True:
        await send_success_answer(request_string=query_info,
                                                                answer_string=f"是否命中召回表：{field_recall}", type=SPECIAL_TASK_NAME,
                                                                websocket=websocket)



        entity_embedding = None
        if field_recall:
            #抽取查询主体
            # 提取所有 field_des 值
            field_des_list = [(field_des, field_examples) for _, _, field_des,field_examples in matched_tables]
            # 将 field_des_list 转换为自然语言描述
            field_des_str = "和".join([field_des for field_des, _ in field_des_list])
            field_examples_str = "并且".join([field_examples for _, field_examples in field_des_list])
            subject_extract = (f"""
    # Role
    你是一个专业的关键词抽取专家，专注于从文本中提取与{field_des_str}相关的关键词。
    
    ## Skills
    ### 技能1: 提取{field_des_str}相关关键词
    - 从用户提供的【query】文本中识别与【{field_des_str}】相关的关键词。
    - 输出关键词时，请以Python列表的形式展示。注意！！！只输出python列表不要有其他无关输出
    {field_examples_str}\n
    
    
    query： {query}\n
    """)

            logging.info(subject_extract)
            # subject_of_query = await get_query_by_chat(subject_extract)
            subject_of_query = await call_llm(prompt=subject_extract, model="nulls-gemini-2.5-flash", token_tracker=token_tracker) #o4-mini

            logging.info(f'抽取结果{subject_of_query}')

            await send_success_answer(request_string=query_info,
                                      answer_string=f"{subject_of_query}", type=SUBJECT_INFO,
                                      websocket=websocket)
            # 如果抽的不准可以试试o1
            # subject_of_query = await chat2o1(subject_extract)
            subect_of_query_list = extract_and_merge_lists(subject_of_query)
            # 如果 没抽取到实体词，则将 text2sql_task 修改为 '一般数据查询'
            if not subect_of_query_list:
                field_recall = False
                subject_info = f'未抽取到主体词'
                await send_success_answer(request_string=query_info,
                                          answer_string=f"是否要召回：{field_recall}", type=SPECIAL_TASK_NAME,
                                          websocket=websocket)
                await send_success_answer(request_string=query_info,
                                          answer_string=f"{subject_info}", type=SUBJECT_INFO,
                                          websocket=websocket)

            # subect_of_query_list = ['天津国资委旗下的上市公司']
            subject_info = f'query抽取的主体词是{subect_of_query_list}'
            # 如果确定要召回，才发送主体词
            if field_recall == True:
                await send_success_answer(request_string=query_info,
                                          answer_string=f"{subject_info}", type=SUBJECT_INFO,
                                          websocket=websocket)

            # 获取主体的embedding
            # entity_embedding = text_to_vectors_http_numpy(''.join(subect_of_query_list))
            entity_embedding = get_bgeM3embeddings([''.join(subect_of_query_list)])[0]

        interrupt_flag = await jug_user_interrupt(query_info,question_id, token_tracker)
        if interrupt_flag:
            return


        logging.info("开始生成SQL语句")
        sql_time = time.time()
        await send_success_answer(request_string=query_info,
                                  answer_string="生成查询代码", type=PROCESS_START,
                                  websocket=websocket)
        # 第五步：生成SQL

        generated_sql, final_define, general_text, domain_text, table_text, combine_prompt, top30_candidates_dict, filtered_table_define = await fetch_and_generate_sql_o1(
            us_stock_codes, companies, concepts, field_recall, entity_embedding, query, table_res, domain_res, industry_str, db_type, domain_one_str,
            table_define, query_embedding, token_tracker=token_tracker)


        logging.info(f"用户{user_name} 问题{query} 生成SQL语句 耗时:{time.time()-sql_time}")

        # logging.info(f"用户{user_name} 问题{query}生成的SQL: {generated_sql}")
        generated_sql = extract_sql(generated_sql)

        generated_sql = generated_sql.replace("\n```sql\n", '').replace("\n```", "").replace(';', '')

        drop_time = time.time()
        columns_to_drop = await get_filter_colunms_name(generated_sql)
        logging.info(f"用户{user_name} 问题{query} 需要删除的列{columns_to_drop} 删除列耗时{time.time()-drop_time}")

        interrupt_flag = await jug_user_interrupt(query_info,question_id, token_tracker)
        if interrupt_flag:
            return


        if field_recall == True:
            await send_success_answer(request_string=query_info,
                                      answer_string=f"top30召回:{top30_candidates_dict}", type=TOP3_SHARE_HOLDER,
                                      websocket=websocket)
            logging.info(f'用户{user_name} 问题{query}前三十股东查询:{top30_candidates_dict}')

        await send_success_answer(request_string=query_info,
                                  answer_string=f"{generated_sql}", type=SQL1,
                                  websocket=websocket)


        logging.info("开始执行SQL")
        # await send_success_answer(request_string=query_info,
        #                           answer_string="开始执行SQL", type=PROCESS_START,
        #                           websocket=websocket)

        exec_time = time.time()

        status_code, result = await execute_sql(generated_sql, db_type)
        logging.info(f"用户{user_name} 问题{query} 执行SQL 耗时:{time.time()-exec_time}")
        # 如果是查不到数据就不纠错了
        goReflect = True  # 默认情况下，goReflect 为 True
        if status_code == 500 and "No rows fetched" in result:
            goReflect = False
            logging.info('查询不到数据，结束流程。')
        await send_success_answer(request_string=query_info,
                                  answer_string=f"{status_code}", type=SQL1_CODE,
                                  websocket=websocket)

        if isinstance(result, str):
            formatted_output = result
        else:
            formatted_output_for_next = result[:data_limit_num]
            key = f"{question_id}_0"
            formatted_output_for_next = df_to_table(key,columns_to_drop,formatted_output_for_next)
            formatted_output = df_to_table(key,columns_to_drop,result)


        await send_success_answer(request_string=query_info,
                                  answer_string=f"{formatted_output}", type=SQL1_RES,
                                  websocket=websocket)

        logging.info(f"用户{user_name} 问题{query}第一次执行结果status_code: {status_code}, result: {result}")

        interrupt_flag = await jug_user_interrupt(query_info,question_id, token_tracker)
        if interrupt_flag:
            return



        diag_res = ''
        if status_code == 500:
            diag_time = time.time()
            diag_res = await diagnose_result(query, generated_sql, formatted_output, status_code, token_tracker=token_tracker)
            await send_success_answer(request_string=query_info,
                                      answer_string=f"诊断 {diag_res}", type=DIAG_RES,
                                      websocket=websocket)
            logging.info(f"用户{user_name} 问题{query} 诊断耗时:{time.time() - diag_time}")

        # #大模型检查
        # if status_code_split == 500:
        #     pass
        # else:
        #     generated_sql = Split_check_res



        interrupt_flag = await jug_user_interrupt(query_info,question_id, token_tracker)
        if interrupt_flag:
            return


        reflected_sql = generated_sql
        skip_check = False
        if status_code == 200:
            logging.info("查询成功")


        if status_code == 500 and not skip_check and goReflect:
            # 500 代表执行出错或者为空

            all_fields = extract_all_fields(generated_sql, sql_keywords)
            upper_all_fields = [item.upper() for item in all_fields]
            selected_table = [item for item in table_res if item.upper() in upper_all_fields]
            if concepts is not '' and 'VW_CONCEPT_STK' not in selected_table:
                selected_table.append('VW_CONCEPT_STK')


            await send_success_answer(request_string=query_info,
                                      answer_string=f"{selected_table}", type=SELECTED_TABLE,
                                      websocket=websocket)

            logging.info(f"开始进行反思：【表格聚焦纠错】，聚焦到表格: {selected_table}")
            reflected_time = time.time()
            reflected_sql, final_define, general_text, domain_text, table_text, combine_prompt = await fetch_and_generate_sql(us_stock_codes, companies, concepts,field_recall, entity_embedding, query,
                                                                                                              selected_table,
                                                                                                              domain_res,
                                                                                                              industry_str,
                                                                                                              db_type,
                                                                                                              domain_one_str,
                                                                                                              table_define,
                                                                                                              query_embedding,
                                                                                                              diag_res, generated_sql, token_tracker=token_tracker)
            logging.info(f"用户{user_name} 问题{query} 反思SQL耗时:{time.time() - reflected_time}")

            interrupt_flag = await jug_user_interrupt(query_info, question_id)
            if interrupt_flag:
                return


            # reflected_sql = reflected_sql.replace("```sql\n", '').replace("\n```", "").replace(';', '')
            try:
                reflected_sql = reflected_sql.replace("```sql\n", '').replace("\n```", "").replace(';', '')
            except Exception as e:
                reflected_sql = ''
                logging.error(f'纠错sql出现问题：{e}')

            await send_success_answer(request_string=query_info,
                                      answer_string=f"{reflected_sql}", type=REFLECTED_TABLE_SQL,
                                      websocket=websocket)

            logging.info(f"表格聚焦纠错，生成的SQL:\n\n{reflected_sql}")
            reflect_exe_sql = time.time()
            status_code, result = await execute_sql(reflected_sql, db_type)
            logging.info(f"用户{user_name} 问题{query} 执行反思SQL耗时:{time.time() - reflect_exe_sql}")
            await send_success_answer(request_string=query_info,
                                      answer_string=f"{status_code}", type=REFLECTED_TABLE_SQL_CODE,
                                      websocket=websocket)
            if isinstance(result, str):
                formatted_output = result
            else:
                formatted_output_for_next = result[:data_limit_num]
                key = f"{question_id}_0"
                formatted_output_for_next = df_to_table(key,columns_to_drop, formatted_output_for_next)
                formatted_output = df_to_table(key,columns_to_drop, result)
            logging.info(f"表格聚焦纠错结果status_code: {status_code}, result: {result}")

            await send_success_answer(request_string=query_info,
                                      answer_string=f"{formatted_output}", type=REFLECTED_TABLE_SQL_RES,
                                      websocket=websocket)

            interrupt_flag = await jug_user_interrupt(query_info, question_id)
            if interrupt_flag:
                return

        explanation_time = time.time()
        logging.info(f"开始执行SQL结果的查询解释")
        explain_res, explain_prompt = await get_explanation_info(reflected_sql, query, final_define,
                                                                     filtered_table_define, token_tracker=token_tracker)
        logging.info(f"用户{user_name} 问题{query} 解释耗时:{time.time() - explanation_time}")
        logging.info(f"查询的思考逻辑如下:\n{explain_res}")

        await send_success_answer(request_string=query_info,
                                      answer_string=f"{explain_res}", is_end=True,type=EXPLAIN_RES,
                                      websocket=websocket, token_tracker=token_tracker)


        logging.info(f"用户{user_name} 问题{query} 总耗时:{time.time()-start_time}")
    except Exception as e:
        logging.error(f"问题{query} 处理查询时发生错误: {e}")
        # 获取完整的错误堆栈信息


        error_details = traceback.format_exc()
        logging.error(f"问题{query}处理查询时发生错误 详细堆栈信息:\n{error_details}")

        await send_success_answer(request_string=query_info,
                                  answer_string=f"执行错误: {error_details}",
                                  websocket=websocket, is_end=True, type=EXCEPTION, token_tracker=token_tracker)


    insert_time = time.time()
    # 生成表字段描述
    table_fields_description = build_table_fields_description(final_define, filtered_table_define)
    sql = """INSERT INTO text_to_sql_middle_records
            (question_id, question, table_text, 
             combine_prompt, formatted_output, reflected_sql,
             session_id, general_text, domain_text,
             table_fields_text, db_type, user_id, user_name)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
            question = VALUES(question),
            table_text = VALUES(table_text),
            combine_prompt = VALUES(combine_prompt),
            formatted_output = VALUES(formatted_output),
            reflected_sql = VALUES(reflected_sql),
            session_id = VALUES(session_id),
            general_text = VALUES(general_text),
            domain_text = VALUES(domain_text),
            table_fields_text = VALUES(table_fields_text),
            db_type = VALUES(db_type),
            user_id = VALUES(user_id),
            user_name = VALUES(user_name)"""

    params = (
        feedback_question_id or question_id,  # 如果feedback_question_id为空则使用question_id
        query,
        table_text,
        combine_prompt,
        formatted_output,
        reflected_sql,
        session_id,
        general_text,
        domain_text,
        table_fields_description,  
        db_type,
        user_id,
        user_name
    )
    await insert_data_to_mysql(sql,params,get_mysql3_pool())
    logging.info(f"用户{user_name} 问题{query} 插入/更新表中间数据结果，question_id={question_id} 耗时:{time.time() - insert_time}")
    return res, combine_prompt, db_type, query, final_define, filtered_table_define,general_text, domain_text, table_text, table_define, formatted_output_for_next, reflected_sql,field_recall,explain_res


async def main():
    sql = f"""
    SELECT
        s.SEC_SNAME AS `证券简称`,
        s.SEC_CODE AS `证券代码`,
        f.RPT_DATE AS `报表日期`,
        f.ENDDATE AS `截止日期`,
        f.F110101 AS `归属于母公司净利润`,
        f.F110201 AS `扣除非经常性损益后的净利润`,
        f.F111001 AS `基本每股收益`
    FROM
        (SELECT COMCODE, SEC_SNAME, SEC_CODE
         FROM PUB_SEC_CODE
         WHERE ISVALID = 1
           AND SEC_TYPE = 1
           AND SEC_STYPE = 101
           AND (MKT_TYPE = 1 OR MKT_TYPE = 2)
           AND LIST_STATUS = '正常上市'
           AND SEC_SNAME LIKE '%宁德时代%') s
    INNER JOIN
        STK_FIN_IDX f
    ON s.COMCODE = f.COMCODE
    WHERE f.ISVALID = 1
      AND f.RPT_DATE = f.ENDDATE
      AND DATE_FORMAT(f.ENDDATE, '%m-%d') = '06-30'
      AND f.F110101 IS NOT NULL
    ORDER BY f.ENDDATE DESC
    """

    status_code, new_result = await execute_sql(sql, "MYSQL-1")
    print(f"Status Code: {status_code}")
    print(f"Result: {new_result}")


async def  jug_user_interrupt(query_info,question_id, token_tracker: Optional["TokenTracker"] = None):
    interrupt_value = redis_client.get(f"text_to_sql_interrupt_{question_id}_0")

    if interrupt_value is not None:
        await send_success_answer(request_string=query_info,
                                  answer_string=f"用户中断", type=USER_INTERRUPT,
                                  is_end=True, websocket=None, token_tracker=token_tracker)
        return True

    else:
        return False

if __name__ == '__main__':
    asyncio.run(main())
