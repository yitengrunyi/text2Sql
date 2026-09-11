import asyncio
import json
import logging
from typing import Dict, Any, List, Tuple, Optional, Union
import time
import pandas as pd
from datetime import datetime
import uuid
from concurrent.futures import ThreadPoolExecutor
import traceback
import csv
import argparse

from common.middleware.db_utils import initialize_all_pools
from handler.text2sql_handler import handle_query_demo_for_mq
from util.model_helpers import call_llm
from util.common import extract_sql,extract_json
from service.sql_executor.text_to_sql_exec import execute_sql
from util.data_formater_helpers import data_limit_num, df_to_table
from prompt_template import four_intent_prompt, three_intent_prompt


# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ===== 新增辅助函数 =====
async def execute_sql_and_format(sql, db_type, session_info, feedback_num, test_id):
    """
    执行SQL并统一格式化结果
    
    参数:
        sql: SQL语句
        db_type: 数据库类型
        session_info: 会话信息
        feedback_num: 反馈序号
        test_id: 测试ID
        
    返回:
        success: 是否执行成功
        formatted_output: 格式化后的输出结果
        failed_sql: 执行失败的SQL
        error_message: 错误信息
    """
    try:
        print(f"[{test_id}] 执行SQL: {sql}")
        status_code, query_result = await execute_sql(sql, db_type)
        
        if status_code == 500:
            error_message = str(query_result) if query_result else "SQL执行出错"
            print(f"[{test_id}] SQL执行出错: {error_message}")
            raise Exception(error_message)
        
        # 格式化结果
        if isinstance(query_result, str):
            formatted_output = query_result
        else:
            key = f"{session_info['question_id']}_{feedback_num}"
            formatted_output = df_to_table(key, [], query_result)
            
        return True, formatted_output, "", ""  # 成功标志, 格式化结果, 空错误信息, 空错误信息
    except Exception as e:
        error_message = str(e)
        print(f"[{test_id}] SQL执行失败: {error_message}")
        return False, "", sql, f"SQL执行错误: {error_message}"  # 失败标志, 空结果, 原始SQL, 错误信息

async def process_initial_query(test_case, test_id, enable_result_filtering=True):
    """
    处理测试用例的初始查询
    
    参数:
        test_case: 测试用例
        test_id: 测试ID
        enable_result_filtering: 是否启用结果筛选意图
        
    返回:
        session_info: 会话信息
        context: 上下文信息
        result_record: 初始查询结果记录
        error: 错误信息，如果有的话
    """
    initial_query = test_case["initial_query"]
    print(f"\n\n========== 测试用例 {test_id} ==========")
    print(f"初始查询: {initial_query}")
    print(f"反馈序列: {test_case.get('feedbacks', [])}")
    print(f"是否启用结果筛选: {enable_result_filtering}")
    
    # 准备会话信息
    unique_id = str(uuid.uuid4())
    session_info = {
        'question_id': f"test_{unique_id}",
        'user_id': f"test_user_{test_id}",
        'user_name': f"测试用户_{test_id}",
        'session_id': f"test_session_{test_id}_{unique_id}",
        'feedback_num': 0,
        'context': {}
    }
    
    # 准备查询信息
    query_info = {
        'question': initial_query,
        'questionId': session_info['question_id'],
        'userId': session_info['user_id'],
        'userName': session_info['user_name'],
        'feedbackNum': 0,
        'sessionId': session_info['session_id'],
        'messageId': f"{session_info['question_id']}_0",
        'system': "test"
    }
    
    # 执行初始查询
    start_time = time.time()
    logger.info(f"[{test_id}] 处理初始查询: {initial_query}")
    
    websocket = MockWebSocket()
    try:
        results = await handle_query_demo_for_mq(query_info, websocket)
        process_time_seconds = int((time.time() - start_time))
        
        # 检查返回结果是否为None
        if results is None:
            logger.error(f"[{test_id}] 初始查询处理返回为None")
            # 设置默认值以防止后续代码出错
            res = None
            combine_prompt = ""
            db_type = "MYSQL"
            query = initial_query
            table_fields_info = []
            filtered_table_info = []
            general_text = ""
            domain_text = ""
            table_text = ""
            table_define = ""
            formatted_output = "查询结果为None"
            executed_sql = ""
            field_recall = []
            explain_res = ""
        else:
            # 解析返回结果
            res, combine_prompt, db_type, query, table_fields_info, filtered_table_info, general_text, domain_text, table_text, table_define, formatted_output, executed_sql, field_recall, explain_res = results
        
        # 生成表字段描述
        table_fields_description = build_table_fields_description(table_fields_info, filtered_table_info)
        
        # 记录初始查询结果
        result_record = {
            "测试ID": test_id,
            "轮次": 0,
            "用户输入": initial_query,
            "意图分类": "INITIAL_QUERY",
            "处理结果": "初始查询",
            "总时间(秒)": process_time_seconds,
            "执行SQL": executed_sql,
            "查询结果": formatted_output,
            "SQL解释": explain_res,
            "表结构信息": [t[0] for t in filtered_table_info],
            "字段信息": [f"{f[0]}:{f[1]}" for f in table_fields_info] if table_fields_info else [],
            "表字段描述": table_fields_description,
            "历史记录": [initial_query],
            "分析提示词": combine_prompt,
            "结果筛选启用": enable_result_filtering
        }
        
        # 构建上下文
        context = {
            'initial_query': initial_query,
            'current_query': initial_query,
            'question_id': session_info['question_id'],
            'user_id': session_info['user_id'],
            'user_name': session_info['user_name'],
            'combine_prompt': combine_prompt,
            'db_type': db_type,
            'table_fields_info': table_fields_info,
            'general_text': general_text,
            'domain_text': domain_text,
            'table_text': table_text,
            'filtered_table_info': filtered_table_info,
            'formatted_output': formatted_output,
            'executed_sql': executed_sql,
            'field_recall': field_recall,
            'explain_res': explain_res,
            'history': [initial_query],
            'table_fields_description': table_fields_description
        }
        
        return session_info, context, result_record, None
    except Exception as e:
        logger.error(f"[{test_id}] 初始查询处理失败: {str(e)}")
        error = {
            "测试ID": test_id,
            "错误类型": "初始查询失败",
            "错误信息": str(e),
            "错误详情": traceback.format_exc()
        }
        return None, None, None, error

async def process_feedback(feedback, feedback_idx, context, session_info, test_id, enable_result_filtering=True):
    """
    处理单个反馈
    
    参数:
        feedback: 用户反馈
        feedback_idx: 反馈索引
        context: 上下文信息
        session_info: 会话信息
        test_id: 测试ID
        enable_result_filtering: 是否启用结果筛选意图
        
    返回:
        updated_context: 更新后的上下文
        result_record: 反馈处理结果记录
        error: 错误信息，如果有的话
    """
    try:
        feedback_num = feedback_idx + 1
        print(f"\n=== [{test_id}] 处理反馈 {feedback_num}: {feedback} ===")
        
        # 所有时间计算统一放在这里
        time_metrics = {}
        
        # 计时开始 - 总处理时间
        start_total_time = time.time()
        
        # 计时开始 - 意图分析时间
        start_analysis_time = time.time()
        
        # 使用反馈处理函数
        feedback_result = await analyze_user_feedback(
            original_query=context['initial_query'],
            table_text=context['table_text'],
            executed_sql=context['executed_sql'],
            formatted_output=context['formatted_output'],
            feedback=feedback,
            table_fields_info=context.get('table_fields_info', []),
            filtered_table_info=context.get('filtered_table_info', []),
            general_text=context.get('general_text', ''),
            domain_text=context.get('domain_text', ''),
            dbtype=context.get('db_type', 'MYSQL'),
            history=context['history'],
            enable_result_filtering=enable_result_filtering
        )
        
        # 计算意图分析时间(秒)
        analysis_time_seconds = int(time.time() - start_analysis_time)
        
        # 计时开始 - 意图处理时间
        start_process_time = time.time()
        
        intent = feedback_result["intent"]
        result = feedback_result["result"]
        reason = feedback_result.get("reason", "未提供分析过程")
        analysis_prompt = feedback_result.get("prompt", "")
        
        print(f"[{test_id}] 意图分类结果: {intent}")
        print(f"[{test_id}] 分析过程: {reason}")
        
        # 更新会话信息中的反馈次数
        session_info['feedback_num'] = feedback_num
        
        # 根据意图决定是否将原始反馈添加到历史记录
        if intent != 'NEW_QUERY':
            context['history'].append(feedback)
            context['current_query'] = feedback
        
        # 统一初始化修正相关字段
        corrected_sql = ""
        correction_process = ""
        correction_result = ""
        
        # 初始化SQL修正跟踪变量
        original_failed_sql = ""
        original_error_message = ""
        sql_correction_success = False
        new_query = ""
        
        # 根据意图执行不同的后续操作
        if intent == 'NON_QUERY':
            print(f"[{test_id}] 反馈与数据查询无关: {result}")
            # 保留现有SQL上下文，不清空
        
        elif intent == 'RESULT_FILTERING':
            context['formatted_output'] = result
        
        elif intent == 'SQL_GENERATION':
            # SQL优化类反馈，需执行新SQL
            original_sql = result
            
            # 执行SQL
            success, formatted_output, failed_sql, error_msg = await execute_sql_and_format(
                original_sql, 
                context.get('db_type', 'MYSQL'),
                session_info,
                feedback_num,
                test_id
            )
            
            if success:
                context['executed_sql'] = original_sql
                context['formatted_output'] = formatted_output
            else:
                # SQL执行失败，尝试修正
                original_failed_sql = failed_sql
                original_error_message = error_msg
                
                print(f"[{test_id}] 正在尝试修正SQL...")
                correction_result_obj = await correct_sql_error(
                    original_sql=original_sql,
                    error_message=error_msg,
                    feedback=feedback,
                    table_text=context['table_text'],
                    initial_query=context['initial_query'],
                    table_fields_info=context.get('table_fields_info', []),
                    filtered_table_info=context.get('filtered_table_info', []),
                    dbtype=context.get('db_type', 'MYSQL')
                )
                
                corrected_sql = correction_result_obj.get("corrected_sql", "")
                correction_process = correction_result_obj.get("correction_process", "未提供修正思考过程")
                
                # 无论修正后的SQL是否成功执行，都更新执行SQL为修正后的SQL
                context['executed_sql'] = corrected_sql
                
                # 执行修正后的SQL
                success, formatted_output, failed_sql, error_msg = await execute_sql_and_format(
                    corrected_sql, 
                    context.get('db_type', 'MYSQL'),
                    session_info,
                    f"{feedback_num}_fixed",
                    test_id
                )
                
                if success:
                    print(f"[{test_id}] 修正SQL执行成功")
                    context['formatted_output'] = formatted_output
                    sql_correction_success = True
                    correction_result = formatted_output
                else:
                    correction_result = f"修正SQL执行错误: {error_msg}"
                    print(f"[{test_id}] {correction_result}")
        
        elif intent == 'NEW_QUERY':
            new_query = result
            print(f"[{test_id}] 基于反馈生成的新问题: {new_query}")
            
            saved_history = context.get('history', []).copy()
            saved_initial_query = context.get('initial_query', '')
            
            saved_history.append(new_query)
            context['current_query'] = new_query
            
            websocket = MockWebSocket()
            
            query_info = {
                'question': new_query,
                'questionId': session_info['question_id'],
                'userId': session_info['user_id'],
                'userName': session_info['user_name'],
                'feedbackNum': feedback_num,
                'sessionId': session_info['session_id'],
                'messageId': f"{session_info['question_id']}_{feedback_num}",
                'system': "test"
            }
            
            try:
                results = await handle_query_demo_for_mq(query_info, websocket)
                
                # 检查results是否为None
                if results is None:
                    logger.error(f"[{test_id}] 新查询处理返回为None")
                    # 设置默认值以防止后续代码出错
                    res = None
                    combine_prompt = ""
                    db_type = context.get('db_type', 'MYSQL')
                    query = new_query
                    table_fields_info = context.get('table_fields_info', [])
                    filtered_table_info = context.get('filtered_table_info', [])
                    general_text = context.get('general_text', "")
                    domain_text = context.get('domain_text', "")
                    table_text = context.get('table_text', "")
                    table_define = ""
                    formatted_output = "查询结果为None"
                    executed_sql = ""
                    field_recall = []
                    explain_res = ""
                else:
                    # 解析返回结果
                    res, combine_prompt, db_type, query, table_fields_info, filtered_table_info, general_text, domain_text, table_text, table_define, formatted_output, executed_sql, field_recall, explain_res = results
            except Exception as e:
                logger.error(f"[{test_id}] 新查询处理失败: {str(e)}")
                # 即使函数异常，也保留上下文中的值以便记录
                res = None
                combine_prompt = context.get('combine_prompt', "")
                db_type = context.get('db_type', 'MYSQL')
                query = new_query
                table_fields_info = context.get('table_fields_info', [])
                filtered_table_info = context.get('filtered_table_info', [])
                general_text = context.get('general_text', "")
                domain_text = context.get('domain_text', "")
                table_text = context.get('table_text', "")
                table_define = ""
                formatted_output = f"查询处理异常: {str(e)}"
                executed_sql = ""
                field_recall = context.get('field_recall', [])
                explain_res = context.get('explain_res', "")
            
            context = {
                'initial_query': saved_initial_query,
                'current_query': new_query,
                'question_id': session_info['question_id'],
                'user_id': session_info['user_id'],
                'user_name': session_info['user_name'],
                'combine_prompt': combine_prompt,
                'db_type': db_type,
                'table_fields_info': table_fields_info,
                'general_text': general_text,
                'domain_text': domain_text,
                'table_text': table_text,
                'filtered_table_info': filtered_table_info,
                'formatted_output': formatted_output,
                'executed_sql': executed_sql,
                'field_recall': field_recall,
                'explain_res': explain_res,
                'history': saved_history,
                'table_fields_description': build_table_fields_description(table_fields_info, filtered_table_info)
            }
        
        # 计算意图处理时间(秒)
        process_time_seconds = int(time.time() - start_process_time)
        
        # 计算总处理时间(秒)
        total_time_seconds = int(time.time() - start_total_time)
        
        # 记录反馈处理结果
        result_record = {
            "测试ID": test_id,
            "轮次": feedback_num,
            "用户输入": feedback,
            "意图分类": intent,
            "分析过程": reason,
            "处理结果": result,
            "总时间(秒)": total_time_seconds,
            "意图分析时间(秒)": analysis_time_seconds,
            "意图处理时间(秒)": process_time_seconds,
            "执行SQL": context.get('executed_sql', ''),
            "查询结果": context.get('formatted_output', ''),
            "SQL解释": context.get('explain_res', ''),
            "修正SQL": corrected_sql,
            "修正思考过程": correction_process,
            "修正结果": correction_result,
            "原始失败SQL": original_failed_sql,
            "原始错误信息": original_error_message,
            "SQL修正成功": sql_correction_success,
            "分析提示词": analysis_prompt,
            "表结构信息": [t[0] for t in context.get('filtered_table_info', [])],
            "字段信息": [f"{f[0]}:{f[1]}" for f in context.get('table_fields_info', [])] if context.get('table_fields_info') else [],
            "表字段描述": context.get('table_fields_description', ''),
            "历史记录": context.get('history', []),
            "融合后查询": new_query if intent == 'NEW_QUERY' else "",
            "结果筛选启用": enable_result_filtering
        }
        
        return context, result_record, None
    except Exception as e:
        logger.error(f"[{test_id}] 处理反馈 {feedback_num} 时出错: {str(e)}")
        error = {
            "测试ID": test_id,
            "轮次": feedback_num,
            "用户输入": feedback,
            "错误类型": "反馈处理失败",
            "错误信息": str(e),
            "错误详情": traceback.format_exc(),
            "结果筛选启用": enable_result_filtering
        }
        return context, None, error

class MockWebSocket:
    """模拟WebSocket类，用于捕获发送的消息"""
    
    def __init__(self):
        self.sent_messages = []
        
    async def send_json(self, data):
        self.sent_messages.append(data)
        logger.debug(f"WebSocket sent: {json.dumps(data, ensure_ascii=False)[:200]}")
        
    async def send_text(self, data):
        self.sent_messages.append(data)
        logger.debug(f"WebSocket sent: {data[:200]}")
    
    async def accept(self):
        pass
    
    async def receive_text(self):
        return "{}"

def build_table_fields_description(table_fields_info: List = None, filtered_table_info: List = None) -> str:
    """
    构建表格和字段的详细描述
    
    参数:
        table_fields_info: 表字段详情列表
        filtered_table_info: 过滤后的表定义信息列表
        
    返回:
        表格和字段的格式化描述文本
    """
    if not table_fields_info or not filtered_table_info:
        return ""
    
    # 构建表格信息字典
    table_details = {table[0]: {'name': table[1], 'description': table[2].replace('\n', '')} 
                    for table in filtered_table_info if len(table) >= 3}
    
    # 构建输出文本
    output_text = ""
    for table_name in table_details:
        output_text += f"【表格】：{table_name}，该表为{table_details[table_name]['name']}：{table_details[table_name]['description'][:200]}\n"
        output_text += "该表格中的字段详细信息：\n"
        
        # 添加该表的字段信息
        for field in table_fields_info:
            if field[0].upper() == table_name.upper():
                field_name = field[1]
                field_chinese_name = field[2]
                field_type = field[3] if len(field) > 3 else ""
                parent_category = field[4] if len(field) > 4 else ""
                field_detail = field[5] if len(field) > 5 else ""
                
                field_detail_info = f"这个字段的释义以及可能包含的单位量纲的介绍如下：{field_detail}" if field_detail else ""
                parent_category_info = f"同时该字段和'{parent_category}'这个上级类别有关。" if parent_category else ""
                
                output_text += f"{field_name}: {field_chinese_name}，{field_detail_info[:150]}，该字段的数值类别为：{field_type}, {parent_category_info}\n"
        
        output_text += "\n"
    
    return output_text

def build_query_history_text(history: List[str]) -> str:
    """
    构建查询历史记录的文本表示，只包含用户的问题
    
    参数:
        history: 历史记录列表，每个元素为用户问题
        
    返回:
        格式化的历史记录文本
    """
    if not history:
        return ""
        
    history_text = "## 历史查询记录\n"
    
    for idx, question in enumerate(history):
        history_text += f"- 轮次 {idx}: {question}\n"
    
    return history_text

async def analyze_user_feedback(
    original_query: str,
    table_text: str,
    executed_sql: str,
    formatted_output: str,
    feedback: str,
    table_fields_info: List = None,
    filtered_table_info: List = None,
    general_text: str = "",
    domain_text: str = "",
    dbtype: str = "MYSQL",
    history: List[str] = None,
    enable_result_filtering: bool = True
) -> Dict[str, Any]:
    """
    分析用户追问的意图并提供相应处理结果
    
    参数:
        original_query: 原始查询问题
        table_text: 数据库表结构信息
        executed_sql: 执行的SQL语句
        formatted_output: SQL查询结果
        feedback: 用户反馈或追问
        table_fields_info: 表字段详情
        filtered_table_info: 表定义信息
        general_text: 一般知识
        domain_text: 领域知识
        dbtype: 数据库类型
        history: 查询历史记录列表，只包含用户问题
        enable_result_filtering: 是否启用结果筛选意图
        
    返回:
        包含意图、处理结果和提示词的字典
    """
    # 构建表格和字段信息
    table_fields_text = build_table_fields_description(table_fields_info, filtered_table_info)
    
    # 处理历史记录
    if not history or len(history) == 0:
        history = [original_query]
    
    # 构建历史记录文本
    history_text = build_query_history_text(history)
    
    # 选择合适的提示词模板
    if enable_result_filtering:
        # 使用包含结果筛选意图的四意图模板
        prompt_template = four_intent_prompt
    else:
        # 使用不包含结果筛选意图的三意图模板
        prompt_template = three_intent_prompt
    
    # 使用f-string格式化模板
    prompt = f"{prompt_template}".format(
        history_text=history_text,
        executed_sql=executed_sql,
        formatted_output=formatted_output,
        feedback=feedback,
        general_text=general_text,
        domain_text=domain_text,
        table_text=table_text,
        table_fields_text=table_fields_text
    )
    
    # 定义一个验证JSON结果的函数
    def is_valid_result(result: Dict) -> bool:
        if not result:
            return False
        
        required_fields = ["intent", "result"]
        if not all(field in result for field in required_fields):
            return False
        
        if enable_result_filtering:
            valid_intents = ["NON_QUERY", "RESULT_FILTERING", "SQL_GENERATION", "NEW_QUERY"]
        else:
            valid_intents = ["NON_QUERY", "SQL_GENERATION", "NEW_QUERY"]
            
        if result.get("intent") not in valid_intents:
            return False
            
        return True
    
    # 调用大模型获取合并处理结果，最多尝试两次
    max_attempts = 2
    
    for attempt in range(max_attempts):
        try:
            # 如果是第二次尝试，修改提示词强调输出格式
            if attempt > 0:
                logger.info(f"第一次获取JSON格式不正确，尝试第二次调用，强调输出格式")
                # 添加强调格式的提示
                format_emphasis = """
# 重要提示：JSON格式输出要求
你必须严格按照以下JSON格式输出，不要添加任何额外文本或注释：
```json
{
  "reason": "你的分析理由",
  "intent": "意图类型（必须是NON_QUERY、RESULT_FILTERING、SQL_GENERATION或NEW_QUERY中的一种）",
  "result": "处理结果（根据不同意图类型有不同内容）"
}
```

请确保：
1. 字段名称必须完全匹配："reason"、"intent"和"result"
2. "intent"字段值必须是四种类型之一，不得有其他值
3. 返回的是标准JSON，不包含其他文本或注释
4. 不要在JSON前后添加任何说明文字
"""
                prompt += format_emphasis
            
            response = await call_llm(prompt=prompt, model="o1") #gemini-2.5-pro-preview-03-25
            result = extract_json(response)
            
            # 验证结果格式是否正确
            if is_valid_result(result):
                # 如果结果有效，将构造的提示词添加到结果中并返回
                result["prompt"] = prompt
                return result
            elif attempt < max_attempts - 1:
                # 如果结果无效，且还有重试机会，进行下一次尝试
                logger.warning(f"JSON格式校验失败: {str(result)}")
                continue
            else:
                # 没有重试机会了，尝试提供尽可能合理的默认值
                logger.error(f"两次尝试后仍未获取到有效JSON格式，使用默认值。响应: {response}")
                return {
                    "intent": "NEW_QUERY", 
                    "result": f"未能正确解析反馈，请重新提问。原反馈: {feedback}", 
                    "reason": "JSON格式解析错误",
                    "prompt": prompt
                }
                
        except Exception as e:
            if attempt < max_attempts - 1:
                logger.warning(f"反馈分析第{attempt+1}次处理时出错: {e}", exc_info=True)
                continue
            else:
                logger.error(f"反馈分析处理最终失败: {e}", exc_info=True)
                return {
                    "intent": "NEW_QUERY", 
                    "result": f"处理出错: {str(e)}", 
                    "reason": "处理异常", 
                    "prompt": prompt
                }

async def correct_sql_error(
    original_sql: str,
    error_message: str,
    feedback: str,
    table_text: str,
    initial_query: str,
    table_fields_info: List = None,
    filtered_table_info: List = None,
    dbtype: str = "MYSQL"
) -> Dict[str, str]:
    """
    使用大模型修正SQL错误
    
    参数:
        original_sql: 原始执行失败的SQL
        error_message: 错误信息
        feedback: 用户的反馈或问题
        table_text: 数据库表结构信息
        initial_query: 最初的查询问题
        table_fields_info: 表字段详情
        filtered_table_info: 表定义信息
        dbtype: 数据库类型
        
    返回:
        包含修正SQL和修正思考过程的字典
    """
    # 构建表格和字段信息
    table_fields_text = build_table_fields_description(table_fields_info, filtered_table_info)
    
    prompt = f"""# SQL修正任务
你是讯兔科技研发的金融投研数据查询助手。我正在执行一个用户反馈引起的SQL查询，但遇到了错误。请帮我修正SQL语句。

## 背景信息
- 初始用户问题: "{initial_query}"
- 用户反馈: "{feedback}"
- 根据用户反馈生成的SQL执行失败，错误信息如下:
```
{error_message}
```

## 当前生成的SQL（有问题）:
```sql
{original_sql}
```

## 数据库表结构信息:
{table_text}

## 详细的表字段信息:
{table_fields_text}

## 你的任务
1. 分析SQL中的错误
2. 根据错误信息和表结构进行修正
3. 提供一个完整的、能够执行的SQL语句及修正思考过程

## 修正要求
1. 严格限制：只能使用上述提供的表结构中明确列出的字段，不得推测或创建不存在的字段
2. 字段和表的严格对应：每个字段必须存在于你引用的特定表中，不允许从一个表中引用另一个表的字段
3. 表名相似警告：特别注意表名相似的情况（如user_info和user_data），确保字段来自正确的表
4. 验证流程：对于每个使用的字段，请执行以下验证：
   a. 明确字段所属的表名
   b. 核对该字段是否确实存在于该表中
   c. 确认该字段的数据类型和用途符合查询需求
5. 不要混淆不同表中的同名字段，必须通过表名前缀明确指定
6. 如果需要的字段确实不存在，考虑使用其他可用字段替代，或简化SQL逻辑

请以JSON格式返回结果，包含以下字段：
- "corrected_sql": 修正后的完整SQL语句
- "correction_process": 简要说明修正思路和过程，包括确认所用字段都存在于表结构中

返回格式示例：
```json
{{
  "correction_process": "错误原因是字段名不存在，根据表结构将字段名从X修改为Y。我已确认字段Y在表中存在。",
  "corrected_sql": "SELECT column FROM table WHERE condition",
}}
```

corrected_sql 确保返回可执行的SQL语句。
"""
    
    try:
        # 调用大模型获取修正后的SQL
        print(f"修正SQL: {prompt}")
        response = await call_llm(prompt=prompt, model="gpt-4.1")
        result = extract_json(response)
        
        # 如果没有提取到JSON，则尝试提取SQL，构建默认结果
        if not result:
            corrected_sql = extract_sql(response)
            if not corrected_sql:
                corrected_sql = response.strip()
            
            result = {
                "corrected_sql": corrected_sql,
                "correction_process": "未能获取修正思考过程"
            }
        
        return result
    except Exception as e:
        logger.error(f"SQL修正时出错: {e}", exc_info=True)
        # 如果修正过程出错，返回原始SQL和错误信息
        return {
            "corrected_sql": original_sql,
            "correction_process": f"修正出错: {str(e)}"
        }

async def process_single_test_case(test_case: Dict[str, Any], test_id: str, enable_result_filtering: bool = True) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """
    处理单个测试用例
    
    参数:
        test_case: 单个测试用例的字典
        test_id: 测试用例ID
        enable_result_filtering: 是否启用结果筛选意图
        
    返回:
        该测试用例的所有处理结果列表，或者错误信息字典
    """
    try:
        # 初始化结果收集列表
        test_results = []
        
        # 处理初始查询
        session_info, context, initial_result, error = await process_initial_query(test_case, test_id, enable_result_filtering)
        
        # 如果初始查询处理失败，直接返回错误
        if error:
            return error
            
        # 记录初始查询结果
        test_results.append(initial_result)
        
        # 提取反馈序列
        feedbacks = test_case.get("feedbacks", [])
        
        # 处理每个反馈
        for feedback_idx, feedback in enumerate(feedbacks):
            try:
                context, result_record, error = await process_feedback(
                    feedback, feedback_idx, context, session_info, test_id, enable_result_filtering
                )
                if error:
                    test_results.append(error)
                else:
                    test_results.append(result_record)
            except Exception as e:
                error_info = {
                    "测试ID": test_id,
                    "轮次": feedback_idx + 1,
                    "用户输入": feedback,
                    "错误类型": "反馈处理失败",
                    "错误信息": str(e),
                    "错误详情": traceback.format_exc(),
                    "结果筛选启用": enable_result_filtering
                }
                test_results.append(error_info)
                logger.error(f"[{test_id}] 处理反馈 {feedback_idx + 1} 时出错: {str(e)}")
                continue
        
        return test_results
        
    except Exception as e:
        logger.error(f"[{test_id}] 测试用例处理失败: {str(e)}")
        return {
            "测试ID": test_id,
            "错误类型": "测试用例处理失败",
            "错误信息": str(e),
            "错误详情": traceback.format_exc(),
            "结果筛选启用": enable_result_filtering
        }

async def test_multi_turn_dialogue(test_cases: List[Dict[str, Any]], enable_result_filtering: bool = True) -> None:
    """
    优化版多轮对话测试函数，使用并发处理多个测试用例
    
    参数:
        test_cases: 测试用例列表，每个测试用例包含初始查询和反馈列表
        enable_result_filtering: 是否启用结果筛选意图
    """
    try:
        # 初始化数据库连接
        await initialize_all_pools()
        
        # 创建测试任务列表
        tasks = []
        for i, test_case in enumerate(test_cases):
            test_id = f"test_{i+1}"
            task = process_single_test_case(test_case, test_id, enable_result_filtering)
            tasks.append(task)
        
        # 并发执行所有测试用例
        all_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 合并所有测试结果
        test_results = []
        for i, result in enumerate(all_results):
            if isinstance(result, Exception):
                # 处理测试用例执行过程中的异常
                error_info = {
                    "测试ID": f"test_{i+1}",
                    "错误类型": "测试执行异常",
                    "错误信息": str(result),
                    "错误详情": traceback.format_exc(),
                    "结果筛选启用": enable_result_filtering
                }
                test_results.append(error_info)
            elif isinstance(result, dict) and "错误类型" in result:
                # 处理测试用例内部返回的错误信息
                test_results.append(result)
            elif isinstance(result, list):
                # 处理正常的测试结果
                test_results.extend(result)
            else:
                # 处理其他意外情况
                error_info = {
                    "测试ID": f"test_{i+1}",
                    "错误类型": "未知错误",
                    "错误信息": f"未预期的结果类型: {type(result)}",
                    "错误详情": str(result),
                    "结果筛选启用": enable_result_filtering
                }
                test_results.append(error_info)
        
        # 导出结果
        try:
            df = pd.DataFrame(test_results)
            # 确保所有列都存在
            all_columns = set()
            for result in test_results:
                all_columns.update(result.keys())
            
            for column in all_columns:
                if column not in df.columns:
                    df[column] = None
                    
            # 使用日期格式命名文件
            current_date = datetime.now().strftime('%Y%m%d%H%M')
            
            # 保存为Excel格式，可以很好地处理长文本和特殊字符
            excel_file = f"test_results_{current_date}_filtering_{'on' if enable_result_filtering else 'off'}.xlsx"
            df.to_excel(excel_file, index=False, engine='openpyxl')
            print(f"\n测试结果已保存到Excel文件: {excel_file}")
            
        except Exception as e:
            logger.error(f"导出Excel时出错: {e}", exc_info=True)
            print(f"导出Excel时出错: {e}")
            raise
            
    except Exception as e:
        logger.error(f"测试执行过程出错: {e}", exc_info=True)
        raise

async def load_test_cases(test_cases_source=None, json_file_path=None):
    """
    加载测试用例，支持从变量或JSON文件加载
    
    参数:
        test_cases_source: 包含测试用例的Python变量，格式为列表，每个元素是一个测试用例字典
        json_file_path: 测试用例JSON文件的路径
        
    返回:
        测试用例列表
    """
    test_cases = []
    
    # 如果提供了变量形式的测试用例
    if test_cases_source is not None:
        if isinstance(test_cases_source, list):
            test_cases = test_cases_source
            logger.info(f"从变量加载了 {len(test_cases)} 个测试用例")
        else:
            raise ValueError("test_cases_source 必须是包含测试用例字典的列表")
    
    # 如果提供了JSON文件路径且没有提供变量形式的测试用例
    elif json_file_path:
        try:
            with open(json_file_path, 'r', encoding='utf-8') as f:
                test_cases = json.load(f)
            logger.info(f"从文件 {json_file_path} 加载了 {len(test_cases)} 个测试用例")
        except Exception as e:
            logger.error(f"从文件 {json_file_path} 加载测试用例时出错: {e}")
            raise
    
    # 如果两者都没有提供
    else:
        raise ValueError("必须提供 test_cases_source 或 json_file_path 中的至少一个参数")
    
    return test_cases

async def main(test_cases_source=None, json_file_path='test_cases.json', enable_filtering=True, max_cases=30):
    """
    主函数：加载测试用例并执行测试
    
    参数:
        test_cases_source: 包含测试用例的Python变量，格式为列表，每个元素是一个测试用例字典
        json_file_path: 测试用例JSON文件的路径，当test_cases_source未提供时使用
        enable_filtering: 是否启用结果筛选意图（四意图模式），False为三意图模式
        max_cases: 最大测试用例数量
    """
    try:
        # 加载测试用例
        if test_cases_source is not None:
            # 优先使用变量中的测试用例
            test_cases = await load_test_cases(test_cases_source=test_cases_source)
            source_desc = "变量"
        else:
            # 当变量未提供时，从JSON文件加载
            test_cases = await load_test_cases(json_file_path=json_file_path)
            source_desc = f"文件 {json_file_path}"
        
        print(f"成功从{source_desc}加载 {len(test_cases)} 个测试用例")
        
        # 确定最大测试用例数量
        max_cases = min(len(test_cases), max_cases)
        print(f"将使用前 {max_cases} 个测试用例")
        test_subset = test_cases[:max_cases]
        
        # 使用指定的模式运行测试
        mode_desc = "启用" if enable_filtering else "禁用"
        print(f"将执行测试用例（{mode_desc}结果筛选意图）")
        await test_multi_turn_dialogue(test_subset, enable_filtering)
        
    except Exception as e:
        logger.error(f"加载或执行测试用例时出错: {e}", exc_info=True)
        print(f"测试执行出错: {e}")
        raise  # 重新抛出异常，确保错误不会被静默处理

if __name__ == "__main__":
    try:
        # 解析命令行参数
        parser = argparse.ArgumentParser(description="多轮对话测试工具")
        parser.add_argument('--json', type=str, default='test_cases.json', help='测试用例JSON文件路径')
        parser.add_argument('--filtering', type=bool, default=False, help='是否启用结果筛选意图')
        parser.add_argument('--max-cases', type=int, default=30, help='最大测试用例数量')
        args = parser.parse_args()
        
        # 定义示例测试用例变量
        sample_test_cases = [
            {
    "initial_query": "有哪些公司ROE连续两年保持上行？",
    "feedbacks": [
      "再筛选出市值超过100亿的公司",
      "按行业分类统计数量",
      "你能推荐一些投资书籍吗？",
      "这些公司的负债率如何？",
      "资产周转率最高的前10家是哪些？"
    ]
  }
        ]
        # sample_test_cases = None

        # 如果sample_test_cases非空则使用它，否则使用JSON文件
        if sample_test_cases:
            print(f"检测到非空的sample_test_cases变量，使用变量中定义的测试用例...")
            test_source = sample_test_cases
        else:
            print(f"sample_test_cases为空，将从JSON文件加载测试用例...")
            test_source = None
            
        # 使用JSON文件或变量加载测试用例
        asyncio.run(main(
            test_cases_source=test_source,
            json_file_path=args.json,
            enable_filtering=args.filtering,
            max_cases=args.max_cases
        ))
    except KeyboardInterrupt:
        print("\n测试被用户中断")
    except Exception as e:
        print(f"测试执行过程中发生错误: {e}")
        traceback.print_exc()