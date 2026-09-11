import asyncio
import logging
import os
from aio_pika import connect, ExchangeType, exceptions
import json

from handler.handler_message import handle_message
from config.nacos.nacos_service import config

mq_config = config.get('mq_config', {})
USER_NAME = mq_config['username']
USER_PWD = mq_config['password']
RABBITMQ_HOST = mq_config['host']
PORT = mq_config['port']
EXCHANGE_NAME = mq_config['exchange']  # 定义 Fanout Exchange 名称
QUEUE_NAME = mq_config['queuename']
RABBITMQ_ENABLED = (
    bool(mq_config.get('enable', True))
    and os.environ.get("TEXT2SQL_DISABLE_RABBITMQ", "0").strip().lower()
    not in {"1", "true", "yes", "on"}
)
# USER_NAME = 'user'
# USER_PWD = 'zxcvbn123456'
# RABBITMQ_HOST = '192.168.15.49'
# PORT = 31871


class RabbitMQConsumer:
    def __init__(self):
        self.connection = None
        self.channel = None
        self.queue = None
        self.connected = False

    async def initialize(self):
        if not RABBITMQ_ENABLED:
            logging.info("RabbitMQ consumer is disabled.")
            return
        while not self.connected:
            try:
                # 建立连接
                self.connection = await connect(
                    f"amqp://{USER_NAME}:{USER_PWD}@{RABBITMQ_HOST}:{PORT}/",
                    heartbeat=600
                )
                self.channel = await self.connection.channel()
                # 声明队列
                self.queue = await self.channel.declare_queue(
                    QUEUE_NAME,
                    durable=True,
                    exclusive=False,
                    auto_delete=False
                )
                await self.channel.set_qos(prefetch_count=5)
                self.connected = True
                logging.info("Connected to RabbitMQ successfully.")
                while True:
                    async with self.queue.iterator() as queue_iter:
                        async for message in queue_iter:
                            await self.process_message(message)
            except (exceptions.AMQPConnectionError, exceptions.AMQPChannelError) as e:
                logging.error(f"Failed to connect to RabbitMQ, retrying in 5 seconds. Error: {e}")
                await asyncio.sleep(5)
    async def process_message(self, message):
        try:
            # 解析消息
            body = message.body.decode()
            properties = message.properties
            task_id = properties.message_id
            data = json.loads(body)

            # 创建任务并发执行
            asyncio.create_task(handle_message(data))
            # 手动确认消息
            await message.ack()
        except Exception as e:
            logging.error(f"Error processing message: {e}")
            await message.ack()
        except exceptions.AMQPChannelError as e:
            logging.error(f"Channel error: {e}")
            await self.reconnect()
        except exceptions.AMQPConnectionError as e:
            logging.error(f"Connection error: {e}")
            await self.reconnect()

    async def reconnect(self):
        self.connected = False
        await self.close()
        await self.initialize()

    async def close(self):
        if self.connection:
            try:
                await self.connection.close()
            except Exception as e:
                logging.error(f"Error closing connection: {e}")
            finally:
                self.connection = None
                self.connected = False
