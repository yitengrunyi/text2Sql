import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
import json
import asyncio


from pydantic import BaseModel
from orcl_edb_fetch import init_oracle_pool
from common.middleware.db_utils import initialize_all_pools
# from common.middleware.mq_consume import RabbitMQConsumer
from handler.text2sql_handler import handle_query_demo_for_mq

app = FastAPI()


@app.on_event("startup")
async def startup_event():

    await initialize_all_pools()
    await init_oracle_pool()


@app.get("/")
async def get_index():
    with open("test.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    while True:
        data = await websocket.receive_text()
        request = json.loads(data)
        question = request["question"]
        query_info = {
                'question': question,
                'questionId': "111111",
                'userId': "00000",
                'userName': "fyd",
                'feedbackNum': 0,
                'messageId': f"{111111}_0"
            }
        res, combine_prompt, db_type, query, final_define,filtered_table_define, general_text, domain_text, table_text, table_define, formatted_output, reflected_sql, text2sql_task, post_tel = await handle_query_demo_for_mq(query_info,websocket)

        new_context = {
                "combine_prompt": f"{combine_prompt}",
                "db_type": f"{db_type}",
                "query": f"{query}",
                "final_define": f"{final_define}",
                "general_text": f"{general_text}",
                "domain_text": f"{domain_text}",
                "table_text": f"{table_text}",
                "table_define": f"{table_define}",
                "formatted_output": f"{formatted_output}",
                "reflected_sql": f"{reflected_sql}",
                "num": 1,
                "text2sql_task": text2sql_task,
                "post_tel": post_tel
            }
            # 发送处理结果回到前端
        await websocket.send_json({
                "data": {
                    "answer": "",  # 返回回答数据
                    "isEnd": True
                },
                "context": new_context  # 返回上下文
            })


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=5903)