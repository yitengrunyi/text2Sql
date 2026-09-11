import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import json
import asyncio
import logging
import uuid

from common.middleware.db_utils import initialize_all_pools
from handler.handler_message import handle_message
from orcl_edb_fetch import init_oracle_pool
# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI()

# 提供静态文件访问
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.on_event("startup")
async def startup_event():
    # 初始化数据库连接池
    await initialize_all_pools()
    await init_oracle_pool()
    logger.info("数据库连接池已初始化")

@app.get("/")
async def get_index():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket连接已建立")
    
    try:
        while True:
            # 接收前端发送的消息
            data = await websocket.receive_text()
            request = json.loads(data)
            
            # 提取用户查询信息
            question = request.get("question", "")
            session_id = request.get("sessionId", str(uuid.uuid4()))
            user_id = request.get("userId", "test-user-1") # 使用前端传来的userId，默认为test-user-1
            user_name = request.get("userName", "测试用户")
            
            # 准备查询参数
            query_info = {
                "questionId": f"test-{str(uuid.uuid4())[:8]}",
                "sessionId": session_id,
                "question": question,
                "userId": user_id, # 使用从前端获取的userId
                "userName": user_name
                # 不再将websocket放入query_info
            }
            
            logger.info(f"收到查询请求: {query_info}")
            
            # 直接传递websocket参数给handle_message
            await handle_message(query_info, websocket)
            
    except Exception as e:
        logger.error(f"WebSocket处理过程中出错: {e}", exc_info=True)
    finally:
        logger.info("WebSocket连接已关闭")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=5903) 