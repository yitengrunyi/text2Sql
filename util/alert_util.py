# import traceback
# from enum import Enum
#
# import requests
# import json
#
# from config import alert_url, alert_switch
# from commons import logger
#
#
# class AlertType(Enum):
#     ALERT = 1
#     NOTIFICATION = 2
#
#
# def send_feishu_alert(server_info: str, message: str, exception: Exception = None, alert_type: AlertType = AlertType.ALERT):
#     if not alert_switch:
#         return False
#
#     # 飞书告警机器人地址
#     if not alert_url:
#         logger.error("alert_url为空, 停止报警")
#         return
#
#     if alert_type == AlertType.NOTIFICATION:
#         show_title = f"🌐 {server_info} 通知"
#         info_content = [{"tag": "text", "text": f"💠{message}", "un_escape": True}]
#     else:
#         show_title = f"💢 {server_info} 告警"
#         info_content = [{"tag": "text", "text": f"❗️{message}", "un_escape": True}]
#
#     exception_content = []
#     if exception:
#         # 获取异常类型、值和堆栈跟踪
#         exc_type, exc_value, exc_traceback = type(exception), exception, exception.__traceback__
#
#         # 将堆栈信息和异常信息格式化为字符串列表
#         stack_trace = traceback.format_exception(exc_type, exc_value, exc_traceback)
#         stack_trace_str = ''.join(stack_trace)
#         exception_content = [{"tag": "text", "text": "---------------------------------------", "un_escape": True},
#                              {"tag": "text", "text": "\n", "un_escape": True},
#                              {"tag": "text", "text": stack_trace_str, "un_escape": True}]
#
#     # 构建消息
#     alert_data = {
#         "msg_type": "post",
#         "content": {
#             "post": {
#                 "zh_cn": {
#                     "title": show_title,
#                     "content": [info_content, exception_content] if exception_content else [info_content]
#                 }
#             }
#         }
#     }
#
#     # 发送告警
#     try:
#         response = requests.post(alert_url, headers={'Content-Type': 'application/json'}, data=json.dumps(alert_data))
#         response.raise_for_status()  # 检查响应状态
#
#         # 检查返回的StatusCode
#         if response.json().get('StatusCode', 1) != 0:
#             logger.error("告警发送失败！")
#             return False
#         logger.info("告警发送成功")
#         return True
#     except requests.RequestException as ex:
#         logger.error(f"请求异常: {ex}")
#         return False
#
#
# if __name__ == '__main__':
#     send_feishu_alert("PaiPai", "通知测试", alert_type=AlertType.NOTIFICATION)
#     # 示例使用
#     try:
#         a = 1 / 0
#     except Exception as e:
#         send_feishu_alert("PaiPai", "告警测试", exception=e)
