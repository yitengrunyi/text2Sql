import json
from concurrent.futures import ThreadPoolExecutor

import pika
from pika.exchange_type import ExchangeType

RABBITMQ_HOST = '192.168.15.49'
PORT = 31871
NUM_QUEUES = 1

# 创建RabbitMQ连接
credentials = pika.PlainCredentials('user', 'zxcvbn123456')
parameters = pika.ConnectionParameters(host=RABBITMQ_HOST, port=PORT, credentials=credentials, heartbeat=0)
connection = pika.BlockingConnection(parameters)
channel = connection.channel()

# 创建交换机，并将队列绑定到交换机
channel.exchange_declare(exchange='exchange_langchain_ai_answser', exchange_type=ExchangeType.direct, durable=True)  # 确保类型一致

# 创建一个线程池
executor = ThreadPoolExecutor(max_workers=10)

# 异步处理消息
def handle_message(message):
    print(message)

# 接收消息
def consume_message():
    def callback(ch, method, properties, body):
        task_id = properties.message_id
        message = json.loads(body)
        # 使用线程池异步处理消息
        executor.submit(handle_message, message)
        # 确认消息已经被处理
        ch.basic_ack(delivery_tag=method.delivery_tag)

    channel.basic_qos(prefetch_count=3)
    result = channel.queue_declare(queue='', exclusive=True, auto_delete=True)
    queue_name = result.method.queue
    channel.queue_bind(queue=queue_name, exchange="exchange_langchain_ai_answser", routing_key='')
    print(' [*] Waiting for logs. To exit press CTRL+C')

    channel.basic_consume(queue=queue_name, on_message_callback=callback)

    channel.start_consuming()

if __name__ == '__main__':
    consume_message()