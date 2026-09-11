import asyncio
import logging
from fastapi import WebSocket
from fastapi.responses import HTMLResponse
import json
from orcl_edb_fetch import init_oracle_pool

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

from common.middleware.db_utils import initialize_all_pools
from common.middleware.mq_consume import RabbitMQConsumer
from common.middleware.mq_send import rabbitmq_sender

from util.http_helpers import SingletonAiohttp
from orcl_edb_fetch import init_oracle_pool

app = FastAPI()
rabbitmq_consumer = RabbitMQConsumer()

@app.on_event("startup")
async def startup_event():
    try:
        await initialize_all_pools()
        await init_oracle_pool()
    except Exception as e:
        logging.error(f"Failed to initialize pools: {e}")
    try:
        await rabbitmq_consumer.initialize()
    except Exception as e:
        logging.error(f"Failed to initialize RabbitMQ consumer: {e}")
@app.get("/")
async def get_index():
    with open("test.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


class QuestionRequest(BaseModel):
    question: str
    questionId: int
    userId: str
    userName: str
    feedbackQuestion: str
    feedbackNum: int




@app.on_event("shutdown")
async def shutdown_event():
    await rabbitmq_sender.close()
    await rabbitmq_consumer.close()

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=5902)
