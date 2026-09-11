import json
import time
import traceback
import logging
from typing import Dict, Any, List, Optional, TYPE_CHECKING
import copy

if TYPE_CHECKING:
    from util.token_tracker import TokenTracker

from common.middleware.db_utils import async_execute_sql_by_saas, async_query_exec_by_saas
from common.middleware.resp_util import send_success_answer, REJECT, RENEW, EXPLAIN_RES, PROCESS_START, SQL1, SQL1_CODE, SQL1_RES, REFLECTED_TABLE_SQL, REFLECTED_TABLE_SQL_CODE, REFLECTED_TABLE_SQL_RES, DIAG_RES, SELECTED_TABLE, EXCEPTION

from service.sql_executor.text_to_sql_exec import execute_sql
from service.self_reflection.diagnose import diagnose_result
from util.data_formater_helpers import data_limit_num, df_to_table
from util.model_helpers import call_llm
from util.common import extract_json, extract_sql
from handler.text2sql_handler import handle_query_demo_for_mq
from common.prompt.prompt_template import main_sql_prompt,edb_sql_prompt, sql_explanation_prompt
import json_repair
from orcl_edb_fetch import fetch_data_from_oracle

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def build_table_fields_description(table_fields_info=None, filtered_table_info=None):
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

# 封装一个函数，用来更新history
def update_history(prev_context, new_context_data, current_question):
    # 如果之前没有history就初始化为空字典
    history = prev_context.get("history", {})
    # 使用当前的num作为步骤key
    current_step = new_context_data.get("feedbackNum", 1)+1

    # 对 new_context_data 深拷贝，避免直接引用同一对象
    context_snapshot = copy.deepcopy(new_context_data)
    # 将这一步的question和当下的context状态存入history
    # 这里的context_snapshot可以根据需要选择存新context还是旧context
    # 一般建议存当前处理结束后最终的context，以便回溯
    history[str(current_step)] = {
        "question": current_question,
        "context_snapshot": context_snapshot
    }
    # 更新回new_context_data
    new_context_data["history"] = history

def _is_valid_feedback_intent_result(result: Dict) -> bool:
    """
    验证从大模型返回的反馈意图分析结果是否有效。

    参数:
        result: 从大模型获取的JSON结果字典。

    返回:
        如果结果有效则为True，否则为False。
    """
    if not result:
        return False
    
    required_fields = ["intent", "result"]
    if not all(field in result for field in required_fields):
        return False
    
    valid_intents = ["NON_QUERY", "SQL_GENERATION", "NEW_QUERY"]
        
    if result.get("intent") not in valid_intents:
        return False
        
    return True

async def execute_sql_and_format(sql, db_type, session_info, user_id):
    """
    执行SQL并统一格式化结果
    
    参数:
        sql: SQL语句
        db_type: 数据库类型
        session_info: 会话信息
        user_id: 用户ID，用于日志
        
    返回:
        success: 是否执行成功
        formatted_output: 格式化后的输出结果
        failed_sql: 执行失败的SQL
        error_message: 错误信息
    """
    try:
        logger.info(f"[{user_id}] 执行SQL: {sql}")
        
        if db_type and db_type.upper() == "EDB":
            # 使用 fetch_data_from_oracle (别名 fetch_data_from_doris) 执行 SQL
            # Doris 连接通过全局 Engine 管理，无需传递凭据
            status_code, query_result = await fetch_data_from_oracle(sql)
        else:
            # 使用原有的 execute_sql 执行 SQL
            status_code, query_result = await execute_sql(sql, db_type)
        
        if status_code == 500:
            error_message = str(query_result) if query_result else "SQL执行出错"
            logger.error(f"[{user_id}] SQL执行出错: {error_message}")
            raise Exception(error_message)
        
        # 格式化结果
        if isinstance(query_result, str):
            formatted_output = query_result
        else:
            key = f"{session_info['question_id']}_{session_info['feedbackNum']}"
            logger.info(f"追问数据存储的key = {key}")
            formatted_output = df_to_table(key, [], query_result)
            
        return True, formatted_output, "", ""  # 成功标志, 格式化结果, 空错误信息, 空错误信息
    except Exception as e:
        error_message = str(e)
        logger.error(f"[{user_id}] SQL执行失败: {error_message}")
        return False, "", sql, f"SQL执行错误: {error_message}"  # 失败标志, 空结果, 原始SQL, 错误信息

async def analyze_user_feedback(
    table_text: str, # General schema of relevant tables
    executed_sql: str,
    query: str,
    table_fields_text: str = "", # Detailed field descriptions, pre-computed from DB
    general_text: str = "",
    domain_text: str = "",
    history: List[str] = None, # Assumed to be non-empty and include the original query by the caller
    db_type: str = "MYSQL",  # 新增db_type参数，默认为MYSQL
    token_tracker: Optional["TokenTracker"] = None
) -> Dict[str, Any]:
    """
    分析用户追问的意图并提供相应处理结果
    
    参数:
        table_text: 数据库表结构信息 (general schema)
        executed_sql: 执行的SQL语句
        query: 用户当前的反馈或问题
        table_fields_text: 详细的表字段信息 (pre-computed, from DB)
        general_text: 一般知识
        domain_text: 领域知识
        history: 查询历史记录列表，只包含用户问题 (caller ensures this includes the original query)
        db_type: 数据库类型，用于选择适合的prompt模板
        
    返回:
        包含意图、处理结果和提示词的字典
    """
    
    # 处理历史记录 (Caller `handle_user_feedback` ensures `history` is populated and includes the original query)
    
    # 构建历史记录文本
    history_text = build_query_history_text(history)
    
    # 根据数据库类型选择对应的prompt模板
    if db_type and db_type.upper() == "EDB":
        prompt_template = edb_sql_prompt
    else:
        prompt_template = main_sql_prompt
    
    # 使用f-string格式化模板
    prompt = prompt_template.format(
        history_text=history_text,
        query=query,
        executed_sql=executed_sql,
        general_text=general_text,
        domain_text=domain_text,
        table_text=table_text,
        table_fields_text=table_fields_text
    )
    
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
  "intent": "意图类型（必须是NON_QUERY、SQL_GENERATION或NEW_QUERY中的一种）",
  "result": "处理结果（根据不同意图类型有不同内容）"
}
```

请确保：
1. 字段名称必须完全匹配："reason"、"intent"和"result"
2. "intent"字段值必须是三种类型之一，不得有其他值
3. 返回的是标准JSON，不包含其他文本或注释
4. 不要在JSON前后添加任何说明文字
"""
                prompt += format_emphasis
            
            # 根据数据库类型选择不同的模型
            model_name = "gpt-4.1" if db_type and db_type.upper() == "EDB" else "nulls-gemini-2.5-pro"
            logger.info(f"使用模型: {model_name} 处理反馈分析")

            response = await call_llm(prompt=prompt, model=model_name, token_tracker=token_tracker)
            result = json_repair.loads(response) #extract_json(response)
            
            # 验证结果格式是否正确
            if _is_valid_feedback_intent_result(result):
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
                    "result": f"未能正确解析反馈，请重新提问。原反馈: {query}", 
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
    query: str,
    table_text: str,
    history: List[str] = None,
    table_fields_text: str = "",
    dbtype: str = "MYSQL",
    token_tracker: Optional["TokenTracker"] = None
) -> Dict[str, str]:
    """
    使用大模型修正SQL错误
    
    参数:
        original_sql: 原始执行失败的SQL
        error_message: 错误信息
        query: 用户的反馈或问题
        table_text: 数据库表结构信息 (general schema)
        history: 历史查询列表，包含用户所有问题
        table_fields_text: 详细的表字段信息 (pre-computed, from DB)
        dbtype: 数据库类型
        
    返回:
        包含修正SQL和修正思考过程的字典
    """
    # 构建历史记录文本
    history_text = build_query_history_text(history) if history else ""
    
    
    prompt = f"""# SQL修正任务
你是讯兔科技研发的金融投研数据查询助手。我正在执行一个用户反馈引起的SQL查询，但遇到了错误。请帮我修正SQL语句。

## 背景信息
- 用户反馈: "{query}"
- 根据用户反馈生成的SQL执行失败，错误信息如下:
```
{error_message}
```

{history_text}

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
        response = await call_llm(prompt=prompt, model="gpt-4.1", token_tracker=token_tracker)
        result = json_repair.loads(response) #extract_json(response)
        
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

async def get_session_history(session_id: str) -> List[Dict]:
    """
    从数据库获取会话历史记录，仅返回最新的10轮对话
    
    参数:
        session_id: 会话ID
        
    返回:
        会话的历史记录列表，按时间排序，最多返回最新的10条记录
    """
    try:
        sql = f"""
            SELECT 
                question_id, question, refined_question, combine_prompt, table_text, 
                formatted_output, reflected_sql, create_time, session_id,
                feedback, general_text, domain_text, table_fields_text, 
                db_type
            FROM (
                SELECT *
                FROM saas.text_to_sql_middle_records 
                WHERE session_id = '{session_id}'
                ORDER BY create_time DESC
                LIMIT 10
            ) sub
            ORDER BY create_time ASC
        """
        # 将同步调用改为异步调用
        results = await async_query_exec_by_saas(sql)
        
        if not results:
            logger.info(f"未找到会话ID为 {session_id} 的历史记录")
            return []
        
        history_records = []
        for row in results:
            record = {
                'question_id': row.question_id,
                'question': row.question,
                'refined_question': row.refined_question if hasattr(row, 'refined_question') else None,
                'combine_prompt': row.combine_prompt,
                'table_text': row.table_text,
                'formatted_output': row.formatted_output,
                'reflected_sql': row.reflected_sql,
                'create_time': row.create_time,
                'session_id': row.session_id,
                'feedback': row.feedback,
                'general_text': row.general_text,
                'domain_text': row.domain_text,
                'table_fields_text': row.table_fields_text,
                'db_type': row.db_type
            }
            history_records.append(record)
        
        logger.info(f"会话 {session_id} 找到 {len(history_records)} 条历史记录")
        return history_records
    
    except Exception as e:
        logger.error(f"获取会话历史记录时出错: {e}", exc_info=True)
        return []


async def save_feedback_result(
    question_id: str,
    question: str,
    session_id: str,
    table_text: str,
    combine_prompt: str,
    formatted_output: str,
    reflected_sql: str,
    refined_question: Optional[str] = None,
    general_text_to_save: Optional[str] = None,
    domain_text_to_save: Optional[str] = None,
    table_fields_text_to_save: Optional[str] = None,
    db_type_to_save: Optional[str] = None,
    user_id: Optional[str] = None,
    user_name: Optional[str] = None,
    intent: Optional[str] = None,
    intent_reason: Optional[str] = None
) -> bool:
    """
    保存反馈处理结果到数据库
    
    参数:
        question_id: 问题ID
        question: 用户原始问题
        session_id: 会话ID
        table_text: 表结构文本
        combine_prompt: 组合提示词
        formatted_output: 格式化输出
        reflected_sql: 生成的SQL
        refined_question: 融合后的问题 (NEW_QUERY意图使用)
        general_text_to_save: 一般知识文本
        domain_text_to_save: 领域知识文本
        table_fields_text_to_save: 表字段信息文本
        db_type_to_save: 数据库类型
        user_id: 用户ID
        user_name: 用户名称
        intent: 追问时意图
        intent_reason: 追问时意图判断思考过程
        
    返回:
        是否保存成功
    """
    try:
        # 检查是否已存在该question_id的记录
        check_sql = "SELECT question_id FROM saas.text_to_sql_middle_records WHERE question_id = :question_id"
        existing_record = await async_query_exec_by_saas(check_sql, {"question_id": question_id})
        
        # 准备参数字典
        params = {
            "question_id": question_id,
            "question": question,
            "session_id": session_id,
            "table_text": table_text,
            "combine_prompt": combine_prompt,
            "formatted_output": formatted_output,
            "reflected_sql": reflected_sql,
            "refined_question": refined_question,
            "general_text": general_text_to_save,
            "domain_text": domain_text_to_save,
            "table_fields_text": table_fields_text_to_save,
            "db_type": db_type_to_save,
            "user_id": user_id,
            "user_name": user_name,
            "intent": intent,
            "intent_reason": intent_reason
        }

        if existing_record:
            # 更新现有记录
            update_sql = """
                UPDATE saas.text_to_sql_middle_records 
                SET 
                    question = :question,
                    session_id = :session_id,
                    table_text = :table_text,
                    combine_prompt = :combine_prompt,
                    formatted_output = :formatted_output,
                    reflected_sql = :reflected_sql,
                    refined_question = :refined_question,
                    general_text = :general_text,
                    domain_text = :domain_text,
                    table_fields_text = :table_fields_text,
                    db_type = :db_type,
                    user_id = :user_id,
                    user_name = :user_name,
                    intent = :intent,
                    intent_reason = :intent_reason
                WHERE 
                    question_id = :question_id
            """
            await async_execute_sql_by_saas(update_sql, params)
            logger.info(f"更新记录: question_id={question_id}")
        else:
            # 插入新记录
            insert_sql = """
                INSERT INTO saas.text_to_sql_middle_records 
                (question_id, question, session_id, table_text, combine_prompt, 
                 formatted_output, reflected_sql, refined_question, general_text, domain_text, 
                 table_fields_text, db_type, user_id, user_name, intent, intent_reason)
                VALUES (
                    :question_id, :question, :session_id, :table_text, :combine_prompt,
                    :formatted_output, :reflected_sql, :refined_question, :general_text, :domain_text,
                    :table_fields_text, :db_type, :user_id, :user_name, :intent, :intent_reason
                )
            """
            await async_execute_sql_by_saas(insert_sql, params)
            logger.info(f"插入新记录: question_id={question_id}")
        
        return True
    except Exception as e:
        logger.error(f"保存反馈结果时出错: {e}", exc_info=True)
        return False

async def _handle_non_query_intent(
    query_info: Dict,
    context: Dict,
    websocket: Any,
    session_id: str,
    user_id: str,
    feedback_result: Dict,
    token_tracker: Optional["TokenTracker"] = None
):
    """处理与数据查询无关的反馈意图"""
    logger.info(f"用户{user_id}反馈与数据查询无关: {query_info.get('feedbackQuestion')}")

    await save_feedback_result(
        question_id=query_info.get('feedbackQuestionId'),
        question=query_info.get('feedbackQuestion'),
        session_id=session_id,
        table_text=context.get('table_text', ''),
        combine_prompt=feedback_result.get('prompt', ''),
        formatted_output=context.get('formatted_output', ''),
        reflected_sql=context.get('executed_sql', ''),
        general_text_to_save=context.get('general_text'),
        domain_text_to_save=context.get('domain_text'),
        table_fields_text_to_save=context.get('table_fields_text'),
        db_type_to_save=context.get('db_type'),
        user_id=user_id,
        user_name=context.get('user_name'),
        intent=feedback_result.get('intent'),
        intent_reason=feedback_result.get('reason')
    )

    #打印query_info
    logger.info('--------------------------------')
    logger.info(f"_handle_non_query_intent query_info: {query_info}")
    logger.info('--------------------------------')
    await send_success_answer(
        request_string=query_info,
        answer_string='您的反馈与数据查询任务无关，此类反馈超出了我们当前的支持范围，本次流程中断请重启新页面。',
        type=REJECT,
        is_end=True,
        websocket=websocket,
        token_tracker=token_tracker
    )

    return {
        "意图分类": "NON_QUERY",
        "处理结果": "反馈与数据查询无关"
    }

async def generate_and_send_sql_explanation(
    sql: str,
    query: str,
    context: Dict,
    query_info: Dict,
    user_id: str,
    websocket: Any,
    reason: str = "",
    token_tracker: Optional["TokenTracker"] = None
) -> None:
    """
    生成SQL解释并发送结果到前端

    参数:
        sql: 要解释的SQL语句
        query: 用户查询问题
        context: 上下文信息字典
        query_info: 查询信息字典
        user_id: 用户ID
        formatted_output: SQL执行的格式化结果
        websocket: WebSocket连接对象
        db_type: 数据库类型
        token_tracker: Token使用量追踪器
    """
    try:
        # 修改变量名，避免与导入的模板名冲突
        formatted_prompt = sql_explanation_prompt.format(
            history_text=build_query_history_text(context.get('history', [])),
            executed_sql=sql,
            query=query,
            reason=reason,
            table_fields_text=context.get('table_fields_text', '')
        )

        # 调用大模型获取SQL解释
        explain_res = await call_llm(prompt=formatted_prompt, model="gpt-4.1", token_tracker=token_tracker)

        logger.info(f"[{user_id}] SQL解释生成成功: {explain_res[:500]}...")

        # 再发送SQL解释

        await send_success_answer(
            request_string=query_info,
            answer_string=explain_res,
            type=EXPLAIN_RES,
            is_end=True,
            websocket=websocket,
            token_tracker=token_tracker
        )

        return explain_res
    except Exception as e:
        logger.error(f"[{user_id}] 生成SQL解释时出错: {str(e)}", exc_info=True)
        return None

async def _handle_sql_generation_intent(
    query_info: Dict,
    context: Dict,
    websocket: Any,
    session_id: str,
    user_id: str,
    feedback_result: Dict,
    db_type: str = "MYSQL",
    token_tracker: Optional["TokenTracker"] = None
):
    """处理SQL优化或生成的反馈意图"""
    # 初始化用于保存结果的变量
    formatted_output = ""
    reflected_sql = ""
    explain_text = ""
    extra_reason = ""
    
    session_info = {
        'question_id': query_info.get('questionId'),
        'user_id': user_id,
        'user_name': query_info.get('userName'),
        'session_id': session_id,
        "feedbackNum":query_info.get('feedbackNumForCache',0)
    }
    logger.info(f"session_info={session_info}")
    # 通知前端开始生成SQL (与text2sql_handler.py保持一致)
    logger.info(f"用户{user_id} 开始生成SQL语句")
    logger.info('--------------------------------')
    logger.info(f"_handle_sql_generation_intent query_info: {query_info}")
    logger.info('--------------------------------')
    await send_success_answer(
        request_string=query_info,
        answer_string="生成查询代码",
        type=PROCESS_START,
        websocket=websocket
    )
    
    # 发送生成的SQL到前端
    generated_sql = feedback_result.get("result", "")
    reflected_sql = generated_sql  # 初始设置为生成的SQL
    
    await send_success_answer(
        request_string=query_info,
        answer_string=f"{generated_sql}",
        type=SQL1,
        websocket=websocket
    )
    
    logger.info(f"用户{user_id} 开始执行SQL")

    success, sql_output, failed_sql, error_msg = await execute_sql_and_format(
        generated_sql, 
        db_type,
        session_info,
        user_id
    )
    
    formatted_output = sql_output  # 设置初始执行结果
    
    # 发送SQL执行状态码
    status_code = 200 if success else 500
    
    await send_success_answer(
        request_string=query_info,
        answer_string=f"{status_code}",
        type=SQL1_CODE,
        websocket=websocket
    )
    
    if success:
        # 发送查询结果
        await send_success_answer(
            request_string=query_info,
            answer_string=formatted_output,
            type=SQL1_RES,
            is_end=False,  # 不是结束，因为还要发送解释
            websocket=websocket
        )

        # 生成SQL解释并发送结果
        explain_text = await generate_and_send_sql_explanation(
            sql=generated_sql,
            query=query_info.get('feedbackQuestion', ''),
            context=context,
            query_info=query_info,
            user_id=user_id,
            websocket=websocket,
            reason=feedback_result.get("reason", ""),
            token_tracker=token_tracker
        )
        
        result_data = {
            "意图分类": "SQL_GENERATION",
            "执行SQL": generated_sql,
            "查询结果": formatted_output
        }
    else:
        # 执行失败时，尝试诊断和修正
        logger.info(f"SQL执行失败，尝试修正: {error_msg}. 原始SQL: {generated_sql}")
        
        # 添加诊断步骤
        diag_res = await diagnose_result(query_info.get('feedbackQuestion', ''), generated_sql, formatted_output, status_code, token_tracker=token_tracker)
        
        await send_success_answer(
            request_string=query_info,
            answer_string=f"诊断 {diag_res}",
            type=DIAG_RES,
            websocket=websocket
        )
        logger.info(f"诊断结果: {diag_res}")
        
        # 尝试修正SQL
        correction_result_obj = await correct_sql_error(
            original_sql=generated_sql,
            error_message=error_msg,
            query=query_info.get('feedbackQuestion', ''),
            table_text=context.get('table_text', ''),
            history=context.get('history', []),
            table_fields_text=context.get('table_fields_text', ''),
            dbtype=db_type,
            token_tracker=token_tracker
        )
        
        corrected_sql = correction_result_obj.get("corrected_sql", "")
        reflected_sql = corrected_sql  # 更新为修正后的SQL
        
        # 将修正后的SQL发送给前端
        await send_success_answer(
            request_string=query_info,
            answer_string=f"{corrected_sql}",
            type=REFLECTED_TABLE_SQL,
            websocket=websocket
        )
        
        # 执行修正后的SQL
        success, sql_output, failed_sql, error_msg = await execute_sql_and_format(
            corrected_sql, 
            db_type,
            session_info,
            user_id
        )
        
        # 更新执行结果
        if success:
            formatted_output = sql_output
        else:
            formatted_output = f"修正SQL执行错误: {error_msg}. 修正后SQL: {corrected_sql}"
        
        # 发送修正后SQL的执行状态码
        status_code = 200 if success else 500
        
        await send_success_answer(
            request_string=query_info,
            answer_string=f"{status_code}",
            type=REFLECTED_TABLE_SQL_CODE,
            websocket=websocket
        )
        
        if success:
            logger.info(f"修正SQL执行成功: {corrected_sql}")
            
            # 发送修正后SQL的执行结果
            await send_success_answer(
                request_string=query_info,
                answer_string=formatted_output,
                type=REFLECTED_TABLE_SQL_RES,
                is_end=False,
                websocket=websocket
            )
            
            # 生成并发送SQL解释
            extra_reason = f"原SQL执行出错，修正原因: {correction_result_obj.get('correction_process', '')}"
            explain_text = await generate_and_send_sql_explanation(
                sql=corrected_sql,
                query=query_info.get('feedbackQuestion', ''),
                context=context,
                query_info=query_info,
                user_id=user_id,
                websocket=websocket,
                reason=extra_reason,
                token_tracker=token_tracker
            )
            
            result_data = {
                "意图分类": "SQL_GENERATION",
                "执行SQL": corrected_sql,
                "查询结果": formatted_output
            }
        else:
            logger.error(formatted_output)
            
            # 发送错误消息
            await send_success_answer(
                request_string=query_info,
                answer_string="很抱歉，无法执行您的查询，请尝试重新表述您的问题。",
                type=REJECT,
                is_end=True,
                websocket=websocket,
                token_tracker=token_tracker
            )
            
            result_data = {
                "意图分类": "SQL_GENERATION",
                "错误类型": "SQL执行错误",
                "错误信息": formatted_output,
                "原始SQL": generated_sql,
                "修正后SQL": corrected_sql
            }
    
    # 在函数末尾统一保存结果到数据库，确保所有执行路径都会保存数据
    await save_feedback_result(
        question_id=query_info.get('feedbackQuestionId'),
        question=query_info.get('feedbackQuestion'),
        session_id=session_id,
        table_text=context.get('table_text', ''),
        combine_prompt=feedback_result.get('prompt', ''),
        formatted_output=formatted_output,
        reflected_sql=reflected_sql,
        general_text_to_save=context.get('general_text'),
        domain_text_to_save=context.get('domain_text'),
        table_fields_text_to_save=context.get('table_fields_text'),
        db_type_to_save=context.get('db_type'),
        user_id=user_id,
        user_name=query_info.get('userName'),
        intent=feedback_result.get('intent'),
        intent_reason=feedback_result.get('reason')
    )
    
    return result_data

async def _handle_new_query_intent(
    query_info: Dict,
    context: Dict,
    websocket: Any,
    session_id: str,
    user_id: str,
    feedback_result: Dict,
    token_tracker: Optional["TokenTracker"] = None
):
    """处理生成新查询的反馈意图"""
    logger.info(f"用户{user_id}，基于反馈生成的新问题: {feedback_result.get('result', '')}")

    await save_feedback_result(
        question_id=query_info.get('feedbackQuestionId'),
        question=query_info.get('feedbackQuestion'),
        refined_question=feedback_result.get('result', ''),
        session_id=session_id,
        table_text=context.get('table_text', ''),
        combine_prompt=feedback_result.get('prompt', ''),
        formatted_output="",
        reflected_sql="",
        general_text_to_save=context.get('general_text'),
        domain_text_to_save=context.get('domain_text'),
        table_fields_text_to_save=context.get('table_fields_text'),
        db_type_to_save=context.get('db_type'),
        user_id=user_id,
        user_name=context.get('user_name'),
        intent=feedback_result.get('intent'),
        intent_reason=feedback_result.get('reason')
    )

    logger.info('--------------------------------')
    logger.info(f"_handle_new_query_intent query_info: {query_info}")
    logger.info('--------------------------------')

    query_info['question'] = feedback_result.get('result', '')
    # query_info['questionId'] = question_id
    await handle_query_demo_for_mq(query_info, websocket, token_tracker)

    # await send_success_answer(
    #     request_string=query_info, # request_string 仍是原始请求信息
    #     answer_string=f"{feedback_result.get('result', '')}", # 返回的是新问题
    #     type=RENEW, # 告知前端需要用新问题重新发起请求
    #     is_end=True,
    #     websocket=websocket
    #     )

    return {
        "意图分类": "NEW_QUERY",
        "融合后查询": feedback_result.get('result', '')
    }

async def _handle_unknown_intent(
    query_info: Dict,
    context: Dict,
    websocket: Any,
    session_id: str,
    user_id: str,
    intent: str,
    feedback_result: Dict,
    token_tracker: Optional["TokenTracker"] = None
):
    """处理未知或无法处理的反馈意图"""
    logger.warning(f"用户{user_id}反馈意图未知或无法处理: {intent}, 反馈: {query_info.get('feedbackQuestion')}")

    # 保存未知意图的结果
    await save_feedback_result(
        question_id=query_info.get('feedbackQuestionId'),
        question=query_info.get('feedbackQuestion'),
        session_id=session_id,
        table_text=context.get('table_text', ''),
        combine_prompt=feedback_result.get('prompt', ''),
        formatted_output=f"未知意图: {intent}. 原因: {feedback_result.get('reason', '无')}",
        reflected_sql=context.get('executed_sql', ''), # 上一轮的SQL
        general_text_to_save=context.get('general_text'),
        domain_text_to_save=context.get('domain_text'),
        table_fields_text_to_save=context.get('table_fields_text'),
        db_type_to_save=context.get('db_type'),
        user_id=user_id,
        user_name=query_info.get('userName'),
        intent=intent, # 未知意图值
        intent_reason=feedback_result.get('reason', '无法确定有效的意图')
    )

    await send_success_answer(
        request_string=query_info,
        answer_string='您的反馈与数据查询任务无关，此类反馈超出了我们当前的支持范围，本次流程中断请重启新页面。',
        type=REJECT,
        is_end=True,
        websocket=websocket,
        token_tracker=token_tracker
        )

    return {
        "意图分类": "UNKNOWN",
        "错误类型": "未知意图",
        "错误信息": f"未知的意图类型: {intent}"
    }

async def handle_user_feedback(query_info_req, websocket=None, token_tracker: Optional["TokenTracker"] = None):
    """
    线上处理用户反馈的函数，直接使用session_id从数据库获取上下文

    参数:
        query_info_req: 请求信息字典，包含用户问题、反馈和会话信息
        websocket: WebSocket连接对象，用于发送结果
        token_tracker: Token使用量追踪器

    返回:
        处理结果
    """
    try:
        # 从请求中提取信息
        question = query_info_req.get('question', '')
        feedback_question = query_info_req.get('feedbackQuestion') or question
        question_id = query_info_req.get('questionId', '')
        user_id = query_info_req.get('userId', '')
        user_name = query_info_req.get('userName', '')
        feedbackNum = 0
        # query_info_req.get('feedbackNum', 0)
        session_id = query_info_req.get('sessionId', '')
        feedback_question_id = query_info_req.get('feedbackQuestionId') or question_id
        
        if not session_id:
            logger.error(f"处理用户反馈时缺少session_id: user_id={user_id}, feedback={feedback_question}")
            return {
                "错误类型": "参数错误",
                "错误信息": "缺少会话ID (session_id)"
            }
        
        # 构造统一的query_info格式
        query_info = {
            'question': feedback_question,
            'questionId': feedback_question_id,
            'userId': user_id,
            'userName': user_name,
            'feedbackNum': feedbackNum,
            'feedbackNumForCache':query_info_req.get('feedbackNum', 0),
            'feedbackQuestion': feedback_question,
            'messageId': f"{question_id}_{feedbackNum}",
            'sessionId': session_id,
            'feedbackQuestionId': feedback_question_id,
             'mode': query_info_req.get('mode')

        }
        logger.info(f"query_info: {query_info}")
        # 从数据库获取会话历史记录
        history_records = await get_session_history(session_id)
        
        if not history_records:
            logger.error(f"用户{user_id}的会话{session_id}没有找到历史记录")
            return {
                "错误类型": "数据错误",
                "错误信息": "未找到会话历史记录"
            }
        
        # 获取最新的一条记录作为当前上下文的基础
        latest_record = history_records[-1]
        
        # 构造上下文信息 (可以考虑进一步封装这个逻辑)
        context = {
            'user_id': user_id,
            'user_name': user_name,
            'combine_prompt': latest_record.get('combine_prompt', ''), # 使用get确保安全
            'table_text': latest_record.get('table_text', ''),
            'formatted_output': latest_record.get('formatted_output', ''),
            'executed_sql': latest_record.get('reflected_sql', ''),
            'history': [record['question'] for record in history_records],
            'db_type': latest_record.get('db_type', 'MYSQL'), # 假设db_type也可能存储在历史中
            'table_fields_text': latest_record.get('table_fields_text', ''), # 如果需要，从历史加载
            'general_text': latest_record.get('general_text', ''),
            'domain_text': latest_record.get('domain_text', ''),
        }
        
        # 使用反馈处理函数分析用户意图
        feedback_result = await analyze_user_feedback(
            table_text=context['table_text'],
            executed_sql=context['executed_sql'],
            query=feedback_question, # Current feedback from user
            table_fields_text=context['table_fields_text'],
            general_text=context['general_text'],
            domain_text=context['domain_text'],
            history=context['history'],
            db_type=context['db_type'],  # 传递db_type参数
            token_tracker=token_tracker
        )

        # 根据意图分发处理
        intent = feedback_result.get("intent")

        # 根据意图分发处理
        if intent == 'NON_QUERY':
            return await _handle_non_query_intent(
                query_info=query_info,
                context=context,
                websocket=websocket,
                session_id=session_id,
                user_id=user_id,
                feedback_result=feedback_result,
                token_tracker=token_tracker
            )

        elif intent == 'SQL_GENERATION':
            return await _handle_sql_generation_intent(
                query_info=query_info,
                context=context,
                websocket=websocket,
                session_id=session_id,
                user_id=user_id,
                feedback_result=feedback_result,
                db_type=context.get("db_type", "MYSQL"),
                token_tracker=token_tracker
            )

        elif intent == 'NEW_QUERY':
            return await _handle_new_query_intent(
                query_info=query_info,
                context=context,
                websocket=websocket,
                session_id=session_id,
                user_id=user_id,
                feedback_result=feedback_result,
                token_tracker=token_tracker
            )

        else: # 包括 intent is None 或其他未明确处理的意图
            return await _handle_unknown_intent(
                query_info=query_info,
                context=context,
                websocket=websocket,
                session_id=session_id,
                user_id=user_id,
                intent=str(intent), # 转换为字符串以防None
                feedback_result=feedback_result,
                token_tracker=token_tracker
            )
    
    except Exception as e:
        logger.error(f"处理用户反馈时发生顶层异常: {e}", exc_info=True)
        
        error_details = traceback.format_exc()
        logger.error(f"处理用户反馈时发生顶层异常详细堆栈信息:\n{error_details}")
        
        # 尝试获取尽可能多的信息用于保存
        # query_info_req 是主函数的输入参数
        # query_info 在try块的早期就已定义
        # context和feedback_result可能已定义也可能未定义
        
        current_question_id = query_info_req.get('feedbackQuestionId') or query_info_req.get('questionId', '')
        current_question = query_info_req.get('feedbackQuestion') or query_info_req.get('question', '')
        current_session_id = query_info_req.get('sessionId', '')
        current_user_id = query_info_req.get('userId', '')
        current_user_name = query_info_req.get('userName', '')

        # 即使在顶层异常情况下也尝试保存反馈结果
        try:
            # 安全地访问context和feedback_result，如果它们不存在则提供默认值
            local_context = locals().get('context', {})
            local_feedback_result = locals().get('feedback_result', {})
            
            await save_feedback_result(
                question_id=current_question_id,
                question=current_question,
                session_id=current_session_id,
                table_text=local_context.get('table_text', ''),
                combine_prompt=local_feedback_result.get('prompt', '出现异常'),
                formatted_output=f"HANDLER_EXCEPTION: {str(e)}",
                reflected_sql=local_context.get('executed_sql', ''),
                general_text_to_save=local_context.get('general_text'),
                domain_text_to_save=local_context.get('domain_text'),
                table_fields_text_to_save=local_context.get('table_fields_text'),
                db_type_to_save=local_context.get('db_type', 'MYSQL'), # Default db_type
                user_id=current_user_id,
                user_name=current_user_name,
                intent="HANDLER_EXCEPTION",
                intent_reason=error_details[:2000]  # Limit reason length if too long
            )
            logger.info(f"[{current_user_id}] 成功将异常详情保存到数据库，会话ID: {current_session_id}")
        except Exception as db_save_error:
            logger.error(f"[{current_user_id}] 保存异常详情到数据库失败: {db_save_error}", exc_info=True)
        
        request_info_for_error = query_info_req if 'query_info_req' in locals() and query_info_req is not None else {}
        
        try:
            await send_success_answer(
                request_string=request_info_for_error, 
                answer_string=f"处理您的反馈时遇到了问题，请稍后再试或联系技术支持。",
                type=EXCEPTION,
                is_end=True,
                    websocket=websocket
                )
        except Exception as ws_send_error:
            logger.error(f"通过websocket发送顶层错误信息失败: {ws_send_error}")

        return {
            "错误类型": "处理异常",
            "错误信息": str(e),
            "错误详情": error_details
        }
