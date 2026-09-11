import json
import pika
import logging as logger

RABBITMQ_HOST = '192.168.63.86'
PORT = 5672

credentials = pika.PlainCredentials('admin', 'rabbitmq@2020')
parameters = pika.ConnectionParameters(
    host=RABBITMQ_HOST,
    port=PORT,
    credentials=credentials,
    heartbeat=600  # 建议设置合理的心跳值（秒），0表示禁用
)


def send_message(message):
    channel.basic_publish(
        exchange='',
        routing_key='ai_text_to_sql_question',  # 保持与队列名称一致
        body=json.dumps(message, ensure_ascii=False),
        properties=pika.BasicProperties(
            message_id=message['questionId'],
            content_type="application/json",
            delivery_mode=2  # 添加消息持久化（2表示持久化）
        ),
    )
    logger.info(f"Sent question to RabbitMQ: {message}")


if __name__ == '__main__':
    rabbitmq_connection = pika.BlockingConnection(parameters)
    channel = rabbitmq_connection.channel()

    # 声明持久化队列（名称与路由键一致）
    channel.queue_declare(
        queue='ai_text_to_sql_question',
        durable=True  # 队列持久化
    )

    request_dict = {
        'question': '2023年宁德时代净利润',
        'questionId': 'O1PpWfA8-jIy15vrq1111191',
        'userId': '853672967236747264',
        'userName': '方煜东',
        'feedbackQuestion': '',
        'feedbackNum': 0,
        'feedbackQuestionId': '',
        'sessionId': 'vRijJpQXFTnRDHscsbE-51739536742088',
        'system': 'sass-web',
        'userInstitutionCode': 'HINST0000000000000191',
        'userInstitutionName': '嘉实基金'
    }

    send_message(request_dict)
    rabbitmq_connection.close()
