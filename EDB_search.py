from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime
from typing import Optional, TYPE_CHECKING
from service.EDB_flow.vector_recall_service import do_vector_recall
from service.EDB_flow.filter_service import do_llm_filter
from orcl_edb_fetch import fetch_data_from_oracle, execute_final_sql
import traceback
import ast
import pickle
from service.sql_generator.text_to_sql_generator import build_sql_generation_prompt, build_sql_reflection_prompt, build_boundary_analysis_prompt, do_sql_generation
from pathlib import Path
from util.rag_helpers import text_to_vectors_http, text_to_vectors_http_numpy,get_bgeM3embeddings, get_top_k_similar
from common.middleware.redis_util import redis_client
from common.middleware.resp_util import send_success_answer, QUERY_INTENT, BACKGROUND_INFO, INDUSTRY_DISPLAY, \
    DOMAIN_ONE, DOMAIN, TABLE_NAME, SQL1, SQL1_CODE, SQL1_RES, EXPLAIN_RES, SELECTED_TABLE, \
    REFLECTED_TABLE_SQL, REFLECTED_TABLE_SQL_CODE, REFLECTED_TABLE_SQL_RES, REFLECTED_FIELD_SQL, \
    REFLECTED_FIELD_SQL_CODE, REFLECTED_FIELD_SQL_RES, EXCEPTION, QUERY_INTENT_PAIPAI, SPECIAL_TASK_NAME, \
    MANAGER_POSITION_INFO, SUBJECT_INFO, TOP3_SHARE_HOLDER, SPECIAL_CASES_SPLIT_SQL, SPECIAL_CASES_SPLIT_CODE, \
    SPECIAL_CASES_SPLIT_RES, DIAG_RES, USER_INTERRUPT, SPECIAL_SPLIT_ITEMS, CONCEPT_DISPLAY, ENTITY_DISPLAY, \
    PROCESS_START, UNREACH_DATA, REJECT, USER_INTENT_REFUSE
import time
from websocket import WebSocket
from common.middleware.resp_util import send_success_answer
from service.locator.question_locator import get_query_understanding, get_query_embedding
from service.self_reflection.sql_explanation_info import get_EDBexplanation_info
from fastapi import Request
import logging
from pydantic import BaseModel
from service.sql_generator.text_to_sql_generator import reflection_and_reexecute_sql

if TYPE_CHECKING:
    from util.token_tracker import TokenTracker
from common.middleware.db_utils import get_mysql3_pool
from util.db_helpers import insert_data_to_mysql

import uvicorn
import re



# FastAPI 应用实例
app = FastAPI()

# 配置模板渲染和静态文件处理
templates = Jinja2Templates(directory="templates")


# 定义请求体
class QueryRequest(BaseModel):
    query: str


@app.get("/", response_class=HTMLResponse)
async def get_home(request: Request):
    # 渲染 HTML 页面
    return templates.TemplateResponse("index_edb.html", {"request": request})



username = 'ngdp_readonly'
password = 'eBi#xDPKGTpGAC'
dsn = 'aws-oracle.rabyte.cn:15266/ORCL'
DEEPSEEK_R1_ENDPOINT = "ep-20250204184813-x7d7b"
DEEPSEEK_V3_ENDPOINT = "ep-20250204184841-kxvmq"

# 方法1：使用datetime模块
today = datetime.now()
year = today.year
month = today.month
day = today.day

# 1. 加载embedding数据
with open(Path(__file__).parent / "important_indic_emb.pkl", 'rb') as f:
    embedding_list = pickle.load(f)
    print('获取关键指标表：')
    print(len(embedding_list))


# 解释部分替换list，用来匹配解释里暴露出敏感表信息时进行替换
REPLACE_LIST = [
    "ECO_DATA_CHINA_REGION",
    "ECO_DATA_CHINA",
    "ECO_DATA_IND_ELECTRONIC",
    "ECO_DATA_IND_REALESTATE",
    "ECO_DATA_IND_TEXTILECLOTHING",
    "ECO_DATA_IND_STEEL",
    "ECO_DATA_IND_UTILITYINDUSTRY",
    "ECO_DATA_GLOBE_REST",
    "ECO_DATA_IND_CHEMICAL",
    "ECO_DATA_IND_MACHINERYEQUIP_18",
    "ECO_DATA_IND_BUILDINGMATERIALS",
    "ECO_DATA_IND_TRAFFICTRANSPORT",
    "ECO_DATA_IND_FINANCIALSERVICES",
    "ECO_DATA_IND_CATERINGTOURISM",
    "ECO_DATA_GLOBE_USA",
    "ECO_DATA_IND_ENERGY",
    "ECO_DATA_IND_ARICULTURAL",
    "ECO_DATA_GLOBE_EU",
    "ECO_DATA_IND_COMMERCIALTRADE",
    "ECO_DATA_IND_AUTOMOBILE",
    "ECO_DATA_IND_LIGHTMANUFACTUE",
    "ECO_DATA_IND_FOODBEVERAGE",
    "ECO_DATA_IND_CULTURE",
    "ECO_DATA_IND_INFOSERVICE",
    "ECO_DATA_IND_FINANCIALSERVICES",  # 注意此项与第13项重复
    "ECO_DATA_IND_BIOLOGICALMEDI_21",
    "ECO_DATA_IND_NONFERROUSMETALS",
    "ECO_DATA_IND_OTHERS"
]


def replace_eco_data_values(input_string):
    """
    将字符串中包含REPLACE_LIST中的任何值替换为EDB_DATA_VALUE

    参数:
        input_string (str): 需要处理的字符串

    返回:
        str: 替换后的字符串
    """
    for pattern in REPLACE_LIST:
        if pattern in input_string:
            input_string = input_string.replace(pattern, "EDB_DATA_VALUE")
    return input_string

#美化后选集显示
def format_tuples_as_table(tuple_list):
    """
    将元组列表格式化为对齐的文本表格（无装饰线条，适合作为Prompt）

    参数:
        tuple_list: List[Tuple], 例如:
            [('id1', 'table1', '指标1', '%', '年'),
             ('id2', 'table2', '指标2', '元', '季')]

    返回:
        str: 对齐的多行文本，可直接放入Prompt
    """
    if not tuple_list:
        return ""

    # 计算每列最大宽度（确保至少等于表头宽度）
    headers = ["ind_der_code", "DATA_TABLE", "SHOW_NAME_SHORT", "UNIT", "FREQ", "source"]
    col_widths = [
        max(len(str(item)) for item in col)
        for col in zip(*tuple_list, headers)
    ]

    # 生成表头行
    header_line = " ".join(
        f"{headers[i]:<{col_widths[i]}}"
        for i in range(len(headers))
    )

    # 生成数据行
    data_lines = []
    for row in tuple_list:
        data_line = " ".join(
            f"{str(row[i]):<{col_widths[i]}}"
            for i in range(len(row))
        )
        data_lines.append(data_line)

    # 组合输出（表头与数据间空一行）
    return header_line + "\n\n" + "\n".join(data_lines)


# 使用示例
final_filtered_top_230 = [
    ('10191rk3w49vto5suw9dfpq1vi65', 'ECO_DATA_CHINA', '中国:GDP预测:累计同比(累计)', '%', '季', '国家统计局'),
    ('1013qbtly8uypr2clb599dlvqgov', 'ECO_DATA_CHINA', '中国:人均GDP:增速(年)', '%', '年', '国家统计局')
]
print('候选值格式')
print(format_tuples_as_table(final_filtered_top_230))



# 接收用户查询并执行数据库查询、embedding 相似度计算和 SQL 生成
@app.post("/execute_query/")
async def execute_query(query: str = Form(...)):
    """
    FastAPI 路由处理函数，调用 process_query 处理用户查询。
    """
    result = await process_query(query)
    # return JSONResponse(result, headers={"Content-Type": "application/json; charset=utf-8"})




async def process_query(query_info_req, websocket: WebSocket = None, token_tracker: Optional["TokenTracker"] = None) -> dict:
    try:
        # ========== 1. 解析请求信息 ==========
        query = query_info_req.get('question')
        question_id = query_info_req.get('questionId')
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
            'feedbackNum': 0,
            'sessionId': session_id,
            'system': system,
            'messageId': f"{question_id}_0"
        }
        await send_success_answer(request_string=query_info,
                                  answer_string=f"EDB", type=DOMAIN_ONE,
                                  websocket=websocket)
        start_time = time.time()
        res = f"【问题】{query}\n\n";
        formatted_output = ""
        formatted_output_for_next = ""
        analysis_time = time.time()

        logging.info("▌开始处理EDB查询请求")
        # ========== 2. 金融实体抽取阶段 ==========
        start_time = time.time()
        extract_start = time.time()
        # query_embedding, explain, extract_res = await get_query_embedding(query)
        explanation, expansion_data, embeddings_config, query_embedding, explain, extract_res, query_desc = await get_query_understanding(query, token_tracker=token_tracker)
        background_info = explain
        logging.info(f"▌实体抽取完成 耗时: {time.time() - extract_start:.2f}s")
        logging.info(f"问题{query} 参考的问题分析: {background_info}")


        await send_success_answer(request_string=query_info,
                                  answer_string=f"{background_info}", type=BACKGROUND_INFO,
                                  websocket=websocket)
        await send_success_answer(request_string=query_info,
                                  answer_string=f"{extract_res}", type=ENTITY_DISPLAY,
                                  websocket=websocket)
        interrupt_flag = await jug_user_interrupt(query_info, question_id, token_tracker)
        if interrupt_flag:
            return


        # ========== 3. 向量召回阶段 ==========
        top_230 = await do_vector_recall(
            query=query,
            embeddings_config=embeddings_config,
            embedding_list=embedding_list,  # 你做二次合并用
            global_threshold=0.4,
            final_topN=500
        )

        if interrupt_flag:
            return


        # ========== 4. 大模型过滤阶段 ==========
        final_filtered_top_230, format_final_filtered_top_230, table_res = \
            await do_llm_filter(top_230, query,query_desc, token_tracker=token_tracker)
        await send_success_answer(request_string=query_info,
                                  answer_string=f"{table_res}", type=TABLE_NAME,
                                  websocket=websocket)


        # ========== 5. SQL生成阶段 ==========
        final_sql, columns_to_drop, output_text,table_text,general_text,table_fields_desc = await do_sql_generation(
            query=query,
            format_final_filtered_top_230=format_final_filtered_top_230,
            final_filtered_top_230=final_filtered_top_230,
            query_info=query_info,
            token_tracker=token_tracker
        )

        await send_success_answer(request_string=query_info,
                                  answer_string=f"{final_sql}", type=SQL1,
                                  websocket=websocket)

        # ========== 6. 执行最终 SQL 查询 ==========
        status_code, final_result, formatted_output = await execute_final_sql(
            cleaned_sql_query=final_sql,
            query=query,
            query_info=query_info
        )

        await send_success_answer(request_string=query_info,
                                  answer_string=f"{status_code}", type=SQL1_CODE,
                                  websocket=websocket)

        await send_success_answer(request_string=query_info,
                                  answer_string=f"{formatted_output}", type=SQL1_RES,
                                  websocket=websocket)

        logging.info(f"用户{user_name} 问题{query}第一次执行结果status_code: {status_code}, result: {final_result}")


        # ========== 7. SQL失败时的反思与重写逻辑 ==========
        if status_code == 500 and "No rows fetched" not in str(final_result):
            status_code, final_sql, diag_res, formatted_output = await reflection_and_reexecute_sql(
                original_sql=final_sql,
                sql_result=final_result,
                query=query,
                query_info=query_info,
                token_tracker=token_tracker
            )

            await send_success_answer(request_string=query_info,
                                      answer_string=f"诊断结果： {diag_res}", type=DIAG_RES,
                                      websocket=websocket)

            await send_success_answer(request_string=query_info,
                                      answer_string=f"重写sql：{final_sql}", type=REFLECTED_TABLE_SQL,
                                      websocket=websocket)


            await send_success_answer(request_string=query_info,
                                      answer_string=f"{status_code}", type=REFLECTED_TABLE_SQL_CODE,
                                      websocket=websocket)


            await send_success_answer(request_string=query_info,
                                      answer_string=f"{formatted_output}", type=REFLECTED_TABLE_SQL_RES,
                                      websocket=websocket)

        # ========== 8. 解释代码阶段 ==========
        explanation_time = time.time()
        logging.info(f"开始执行SQL结果的查询解释")
        explain_res, explain_prompt = await get_EDBexplanation_info(final_sql, query, output_text, token_tracker=token_tracker)
        explain_res = replace_eco_data_values(explain_res)
        logging.info(f"用户{user_name} 问题{query} 解释完成 耗时:{time.time() - explanation_time:.2f}s")
        logging.info(f"查询的思考逻辑如下:\n{explain_res}")

        await send_success_answer(request_string=query_info,
                                  answer_string=f"{explain_res}", is_end=True, type=EXPLAIN_RES,
                                  websocket=websocket, token_tracker=token_tracker)

        # 插入查询记录到MySQL
        try:
            sql = """INSERT INTO text_to_sql_middle_records
                    (question_id, question, table_text, 
                     combine_prompt, formatted_output, reflected_sql,
                     session_id, general_text, domain_text,
                     table_fields_text, db_type,user_id,user_name)
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
                question_id,
                query,
                table_text,
                output_text,  
                formatted_output,
                final_sql,      # 使用final_sql作为reflected_sql
                session_id,
                general_text,
                "",            # domain_text为空
                table_fields_desc,
                "EDB",          # 数据库类型为EDB
                user_id,
                user_name
            )
            await insert_data_to_mysql(sql, params, get_mysql3_pool())
            logging.info(f"成功将查询记录插入到MySQL，question_id: {question_id}")
        except Exception as e:
            logging.error(f"插入MySQL记录失败: {e}")

        logging.info(f"用户{user_name} 问题{query} 总耗时:{time.time() - start_time}")
    except Exception as e:
        logging.error(f"问题{query} 处理查询时发生错误: {e}")
        # 获取完整的错误堆栈信息

        error_details = traceback.format_exc()
        logging.error(f"问题{query}处理查询时发生错误 详细堆栈信息:\n{error_details}")

        await send_success_answer(request_string=query_info,
                                  answer_string=f"执行错误: {error_details}",
                                  websocket=websocket, is_end=True, type=EXCEPTION, token_tracker=token_tracker)



# 错误页面
@app.exception_handler(HTTPException)
async def validation_exception_handler(request, exc):
    return HTMLResponse(content="发生了错误: " + str(exc.detail), status_code=exc.status_code)


async def  jug_user_interrupt(query_info,question_id, token_tracker: Optional["TokenTracker"] = None):
    interrupt_value = redis_client.get(f"text_to_sql_interrupt_{question_id}_0")

    if interrupt_value is not None:
        await send_success_answer(request_string=query_info,
                                  answer_string=f"用户中断", type=USER_INTERRUPT,
                                  is_end=True, websocket=None, token_tracker=token_tracker)
        return True

    else:
        return False

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=5902)


