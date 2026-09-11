import asyncio

from common.middleware.resp_util import FAIL, send_success_answer, EXCEPTION
import logging

from handler.feedback_handler import handle_user_feedback, get_session_history
from handler.text2sql_handler import handle_query_demo_for_mq
from service.query_intent.query_intent_judgment import feedback_intent_cls
from util.token_tracker import TokenTracker
import copy

async def handle_message(query_info, websocket=None):
    # ================================================================================
    logging.info(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
    logging.info(f"【入口】接收到WebSocket消息，准备处理: query_info 内容: {query_info}")
    logging.info(f"【入口】WebSocket对象: {'存在' if websocket else '不存在'}")
    logging.info("<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<")
    # ================================================================================

    # 创建 TokenTracker 实例用于追踪整个请求的 token 使用
    token_tracker = TokenTracker()

    try:
        question_id = query_info.get('questionId')
        session_id = query_info.get('sessionId')
        question = query_info.get('question')
        logging.info(f"【信息提取】提取基本信息: question_id='{question_id}', session_id='{session_id}', question='{question}'")

        # 检查feedbackQuestionId是否有值，如果有则更新questionId
        feedback_question_id = query_info.get('feedbackQuestionId')
        if feedback_question_id:
            logging.info(f"【反馈处理】检测到feedbackQuestionId: '{feedback_question_id}'，准备更新questionId")
            query_info['questionId'] = feedback_question_id
            logging.info(f"【反馈处理】已更新questionId: '{query_info['questionId']}'")
        else:
            logging.info("【反馈处理】未检测到feedbackQuestionId")

        # 检查feedbackQuestion是否有值，如果有则更新question
        feedback_question = query_info.get('feedbackQuestion')
        if feedback_question:
            logging.info(f"【反馈处理】检测到feedbackQuestion: '{feedback_question}'，准备更新question")
            query_info['question'] = feedback_question
            logging.info(f"【反馈处理】已更新question: '{query_info['question']}'")
        else:
            logging.info("【反馈处理】未检测到feedbackQuestion")

        logging.info(
            f"【开始处理】text2sql_mq_consumer(应为 text2sql_websocket_handler?) 开始处理问题:  请求: {query_info}")

        # 检查session_id是否存在历史记录
        logging.info(f"【历史检查】准备调用 get_session_history，session_id: '{session_id}'")
        history_records = await get_session_history(session_id)
        logging.info(f"【历史检查】get_session_history 调用完毕，history_records: {'存在' if history_records else '不存在或为空'}")

        # 如果 query_info.system == 'sass-app',也调用handle_query_demo_for_mq
        if (not history_records) or (query_info.get('system') == 'sass-app'):
            logging.info("【分支判断】无历史记录，判定为新会话，准备调用 handle_query_demo_for_mq")
            # 如果没有找到历史记录，说明是新会话，使用handle_query_demo_for_mq
            await handle_query_demo_for_mq(query_info, websocket, token_tracker)
            logging.info("【分支调用】handle_query_demo_for_mq 调用完毕")
        else:
            logging.info("【分支判断】有历史记录，判定为已有会话的反馈，准备调用 handle_user_feedback")
            # 如果找到历史记录，说明是已有会话的反馈，使用handle_user_feedback
            await handle_user_feedback(query_info, websocket, token_tracker)
            logging.info("【分支调用】handle_user_feedback 调用完毕")

        logging.info(f"【处理完毕】handle_message 正常执行完毕，question_id: {query_info.get('questionId')}")

    except Exception as e:
        logging.error(f"【异常捕获】handle_message 执行时发生主异常: {e}", exc_info=True)
        # 如果有websocket，发送错误信息
        try:
            logging.info("【异常处理】准备尝试通过 send_success_answer 发送错误信息")
            await send_success_answer(
                request_string=query_info,
                answer_string=f"处理请求时发生错误: {str(e)}",
                type=EXCEPTION,
                is_end=True,
                websocket=websocket,
                token_tracker=token_tracker
            )
            logging.info("【异常处理】send_success_answer 调用完成 (已尝试发送错误信息)")
        except Exception as ws_error:
            logging.error(f"【异常处理】调用 send_success_answer 发送错误信息时失败 (二次异常): {ws_error}", exc_info=True)


def mq_message(query, event_loop):
    future = asyncio.run_coroutine_threadsafe(handle_message(query), event_loop)
    # 等待异步方法执行完毕，并获取结果
    future.result()
    logging.info("执行结束")
