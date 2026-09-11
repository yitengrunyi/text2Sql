import json
import os

import aio_pika
import pika
import logging as logger
import asyncio

from aio_pika import DeliveryMode

from config.nacos.nacos_service import config

mq_config = config.get('mq_config', {})
USER_NAME = mq_config['username']
USER_PWD = mq_config['password']
RABBITMQ_HOST = mq_config['host']
PORT = mq_config['port']
EXCHANGE_NAME = mq_config['exchange']  # 定义 Fanout Exchange 名称
RABBITMQ_ENABLED = (
    bool(mq_config.get('enable', True))
    and os.environ.get("TEXT2SQL_DISABLE_RABBITMQ", "0").strip().lower()
    not in {"1", "true", "yes", "on"}
)

class RabbitMQSender:
    _instances = {}

    def __new__(cls, exchange_name, *args, **kwargs):
        if exchange_name not in cls._instances:
            instance = super(RabbitMQSender, cls).__new__(cls)
            instance.exchange_name = exchange_name  # 存储exchange名称
            instance.connection = None
            instance.channel = None
            instance.exchange = None
            cls._instances[exchange_name] = instance
        return cls._instances[exchange_name]

    async def initialize(self):
        """异步初始化连接"""
        if not RABBITMQ_ENABLED:
            return
        if not self.connection or self.connection.is_closed:
            self.connection = await aio_pika.connect_robust(
                host=RABBITMQ_HOST,
                port=PORT,
                login=USER_NAME,
                password=USER_PWD
            )
            self.channel = await self.connection.channel()

            # 声明持久化交换器（改为fanout类型）
            self.exchange = await self.channel.declare_exchange(
                name=self.exchange_name,
                type="fanout",  # 根据注释修正为fanout类型
                durable=True
            )

    async def send_message(self, message):
        if not RABBITMQ_ENABLED:
            logger.info("RabbitMQ is disabled; message was not published.")
            return
        try:
            await self.initialize()  # 确保连接已建立
            message_id = message.get('messageId')
            rmq_message = aio_pika.Message(
                body=json.dumps(message, ensure_ascii=False).encode(),
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                message_id=message_id,
                content_type="application/json"
            )

            await self.exchange.publish(
                message=rmq_message,
                routing_key=''  # fanout交换器无需指定路由键
            )

            logger.info(f"Sent message to {self.exchange_name}: {message}")

        except Exception as e:
            logger.error(f"Message delivery failed: {str(e)}")
            raise

    async def close(self):
        """异步关闭连接"""
        if self.connection:
            await self.connection.close()

# 初始化 RabbitMQSender 实例
rabbitmq_sender = RabbitMQSender(EXCHANGE_NAME)
