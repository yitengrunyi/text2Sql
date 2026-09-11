import asyncio
import logging
import uuid

# 导入要测试的函数
from handler.handler_message import handle_message
from common.middleware.db_utils import initialize_all_pools

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def test_handler():
    """
    简单测试handle_message函数，方便打断点调试
    """
    # new_session_query = {
    #     "questionId": "test-question-3",
    #     "sessionId": "222",  # 这个ID在数据库中应该不存在
    #     "question": "东南亚各地区债务有多少？",
    #     "userId": "test-user-1"
    # }
    # # 准备测试数据 - 新会话
    # new_session_query = {
    #     "questionId": "test-question-2",
    #     "sessionId": "111",  # 这个ID在数据库中应该不存在
    #     "question": "计算各季度的环比增长率和同比增长率",
    #     "userId": "test-user-1"
    # }
    
    # # 准备测试数据 - 现有会话
    existing_session_query = {
        "questionId": "test-question-7",
        "sessionId": "111",  # 请替换为实际存在的会话ID
        "question": "公募行业过去五年管理规模如何变化?",
        "userId": "test-user-1"
    }
    
    logger.info("===== 开始测试 =====")

    await initialize_all_pools()
    
    # 在这里设置断点并调试
    # logger.info("测试新会话情况...")
    # await handle_message(new_session_query)
    
    logger.info("\n测试现有会话情况...")
    await handle_message(existing_session_query)
    
    logger.info("===== 测试结束 =====")

if __name__ == "__main__":
    asyncio.run(test_handler()) 