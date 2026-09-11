import json
import os
from typing import Optional, List, Dict, Any, TYPE_CHECKING

from fastapi import WebSocket
import logging
from common.middleware.mq_send import rabbitmq_sender

if TYPE_CHECKING:
    from util.token_tracker import TokenTracker

# 入参、出参json格式参考 https://rabyte-tech.feishu.cn/docx/VqpkdKhuMoKvMJx3R5ycaOjdnsd
# {
#     "userId": "11",
#     "userName": "张三",
#     "questionId": "1",
#     "taskId": "1",
#     "question": "What is the capital of India?",
#     "context": [{"question":"xxx","answer":"ooo"}]
#     "tag": "【股票】"
#     "system": "saas"
# }
#
MODE = "mode"
USER_ID = "userId"
USER_NAME = "userName"
QUESTION_ID = "questionId"
TASK_ID = "taskId"
SESSION_ID = "sessionId"
QUESTION = "question"
FEEDBACK_QUESTION = "feedbackQuestion"
FEEDBACK_QUESTION_ID = "feedbackQuestionId"
FEEDBACK_NUM = "feedbackNum"
CONTEXT = "context"
TAG = "tag"
SYSTEM = "system"
ANSWER_ORDER = "answerOrder"
IS_END = "isEnd"
ANSWER = "answer"
TYPE = "type"
ROUTE_NAME = "routeName"
SUCCESS = 200
SUCCESS_STR = "成功"
FAIL = 500
ANSWER_EMPTY = 201
ANSWER_EMPTY_STR = "结果为空"
GPT_ANSWER = 202
GPT_ANSWER_STR = "GPT"
USER_RATE_LIMIT = 203
USER_RATE_LIMIT_STR = "用户当日超过限制"
SYSTEM_RATE_LIMIT = 204
SYSTEM_RATE_LIMIT_STR = "系统当前超过限制"
SENSITIVE_WORDS_LIMIT = 206
SENSITIVE_WORDS_LIMIT_STR = "敏感词限制"


PROCESS_START = 2000
PROCESS_END = 2001

EXCEPTION = 1000
EXCEPTION_STR = '异常'

ENTITY_DISPLAY = 998
ENTITY_DISPLAY_STR = '实体抽取结果'

CONCEPT_DISPLAY = 999
CONCEPT_DISPLAY_STR = '题材定位'

QUERY_INTENT = 1001
QUERY_INTENT_STR = '用户意图分析定量'
BACKGROUND_INFO = 1002
BACKGROUND_INFO_STR = '问题分析背景知识'
INDUSTRY_DISPLAY = 1003
INDUSTRY_DISPLAY_STR = '问题行业定位'
DOMAIN_ONE = 1004
DOMAIN_ONE_STR = '一级域定位'
DOMAIN = 1005
DOMAIN_STR = '域定位'
TABLE_NAME = 1006
TABLE_NAME_STR = '表定位'
SQL1 = 1007
SQL1_STR = '首次查询的SQL'
SQL1_CODE = 1008
SQL1_CODE_STR = '首次查询的SQL结果code'
SQL1_RES = 1009
SQL1_RES_STR = '首次查询的SQL结果'
SPECIAL_CASES_SPLIT_SQL = 1010
SPECIAL_CASES_SPLIT_STR = '自主check查询的SQL'
SPECIAL_CASES_SPLIT_CODE = 1011
SPECIAL_CASES_SPLIT_CODE_STR = '自主check查询的SQL结果code'
SPECIAL_CASES_SPLIT_RES = 1012
SPECIAL_CASES_SPLIT_RES_STR = '自主check查询的SQL结果'
SELECTED_TABLE = 1013
SELECTED_TABLE_STR = '纠错聚焦到表'
REFLECTED_TABLE_SQL = 1014
REFLECTED_TABLE_SQL_STR = '表纠错重新生成的SQL'
REFLECTED_TABLE_SQL_CODE = 1015
REFLECTED_TABLE_SQL_CODE_STR = '表纠错重新生成的SQL结果code'
REFLECTED_TABLE_SQL_RES = 1016
REFLECTED_TABLE_SQL_RES_STR = '表纠错重新生成的SQL结果'

REFLECTED_FIELD_SQL = 1017
REFLECTED_FIELD_SQL_STR = '列纠错重新生成的SQL'
REFLECTED_FIELD_SQL_CODE = 1018
REFLECTED_FIELD_SQL_CODE_STR = '列纠错重新生成的SQL结果code'
REFLECTED_FIELD_SQL_RES = 1019
REFLECTED_FIELD_SQL_RES_STR = '列纠错重新生成的SQL结果'

EXPLAIN_RES = 1020
EXPLAIN_RES_STR = '最终思考流程解释'

FIRST_FEEDBACK_SQL = 1021
FIRST_FEEDBACK_SQL_CODE = 1022
FIRST_FEEDBACK_SQL_RES = 1023
FIRST_FEEDBACK_REFLECTED_FIELD_SQL = 1024
FIRST_FEEDBACK_REFLECTED_FIELD_SQL_CODE = 1025
FIRST_FEEDBACK_REFLECTED_FIELD_SQL_RES = 1026

OTHER_FEEDBACK_SQL = 1027
OTHER_FEEDBACK_SQL_CODE = 1028
OTHER_FEEDBACK_SQL_RES = 1029

SPECIAL_TASK_NAME = 1030
MANAGER_POSITION_INFO = 1031
SUBJECT_INFO = 1032
TOP3_SHARE_HOLDER = 1033
DIAG_RES = 1034
SPECIAL_SPLIT_ITEMS = 1035
FEEDBACK_EXPLAIN_RES = 1036
UNREACH_DATA = 1037


REJECT = 1050
RENEW = 1051
QUERY_INTENT_PAIPAI = 1052
USER_INTERRUPT = 1054
USER_INTENT_REFUSE = 1055
def get_question(request_string):
    try:
        request_dict = json.loads(request_string)
        return request_dict.get('question')
    except ValueError:
        return request_string


def get_context(request_string):
    try:
        request_dict = json.loads(request_string)
        return request_dict.get('context')
    except ValueError:
        return request_string


def get_request_dict(request_string):
    try:
        request_dict = json.loads(request_string)
        return request_dict
    except ValueError:
        return request_string


def get_request_param(request_string, param):
    try:
        request_dict = json.loads(request_string)
        return request_dict.get(param)
    except ValueError:
        return request_string


def gen_answer(request_string, code, message, answer_string, is_end, answer_type,
               usage: Optional[List[Dict[str, Any]]] = None):
    try:
        message_id = ''
        if type(answer_string) == dict:
            answer_string = json.dumps(answer_string)
        data = {}
        if request_string is not None:
            if type(request_string) == dict:
                data = {
                    USER_ID: request_string.get(USER_ID),
                    USER_NAME: request_string.get(USER_NAME),
                    QUESTION_ID: request_string.get(QUESTION_ID),
                    QUESTION: request_string.get(QUESTION),
                    SESSION_ID: request_string.get(SESSION_ID),
                    SYSTEM : request_string.get(SYSTEM),
                    FEEDBACK_QUESTION: request_string.get(FEEDBACK_QUESTION),
                    FEEDBACK_QUESTION_ID: request_string.get(FEEDBACK_QUESTION_ID),
                    FEEDBACK_NUM: request_string.get(FEEDBACK_NUM),
                    TYPE: answer_type,
                    ANSWER: answer_string,
                    IS_END: is_end,
                    MODE: request_string.get(MODE)

                }
                message_id = f"{request_string.get(QUESTION_ID)}_{request_string.get(FEEDBACK_NUM)}"
            else:
                data = {TYPE: answer_type, ANSWER: answer_string, IS_END: is_end}
        response_dict = {
            "code": code,
            "message": message,
            "messageId":message_id,
            "data": data
        }
        # 在 is_end=True 时添加 usage 字段（与 data 同级）
        if is_end and usage:
            logging.info(f"[TokenUsage]{usage}")
            response_dict["usage"] = usage
        return response_dict
    except ValueError:
        raise


async def send_fail_answer(request_string, message, answer_string=None, answer_order=None, is_end=True, websocket=None,route_name=None):
    response_dict = gen_answer(request_string, FAIL, message, answer_order, answer_string, is_end, FAIL,route_name)
    await _send_success_answer(response_dict, websocket)


async def send_success_answer(request_string, answer_string,  is_end=False, type=None,
                              websocket=None, token_tracker: Optional["TokenTracker"] = None):
    if not type:
        type = SUCCESS

    # 只在 is_end=True 时获取聚合的 usage
    usage = None
    if is_end and token_tracker is not None:
        usage = token_tracker.get_aggregated_usage()

    response_dict = gen_answer(request_string, SUCCESS, SUCCESS_STR, answer_string, is_end, type, usage=usage)
    await _send_success_answer(response_dict, websocket)


async def send_empty_or_answer(request_string, answer_string,  is_end=False, websocket=None):
    if answer_string:
        response_dict = gen_answer(request_string, SUCCESS, SUCCESS_STR, answer_string, is_end, SUCCESS)
    else:
        response_dict = gen_answer(request_string, SUCCESS, SUCCESS_STR, answer_string, is_end,ANSWER_EMPTY)
    await _send_success_answer(response_dict, websocket)


async def _send_success_answer(response: dict, websocket: WebSocket = None):
    if _get_message_type() == '1':
        print(response['data'][ANSWER], end='')
    else:
        if websocket:
            # logger.info(f"websocket send {response}")
            await websocket.send_text(json.dumps(response, ensure_ascii=False))
        else:
            logging.info(f"mq send{response}")
            logging.info(f"Using rabbitmq_sender instance: {rabbitmq_sender}")
            await rabbitmq_sender.send_message(response)


def _get_message_type():
    try:
        return os.environ['LC_MESSAGE_TYPE']
    except KeyError:
        return None
