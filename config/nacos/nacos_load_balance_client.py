import hashlib
import json
import time
import requests
from requests.exceptions import Timeout
from loguru import logger
"""
负载均衡获取服务 每个服务一个NacosServerBalanceClient对象
"""


def fallbackFun():
    return "request Error"


def timeOutFun():
    return "request time out"


class NacosServerBalanceClient:
    def __init__(self, ip="127.0.0.1", port=8848, service_name="",
                 group="DEFAULT_GROUP", namespace_id="public", timeout=6,
                 fall_back_fun=fallbackFun, time_out_fun=timeOutFun):
        self.ip = ip
        self.port = port
        self.serviceName = service_name
        self.group = group
        self.namespaceId = namespace_id
        self.__LoadBalanceDict = {}
        self.timeout = timeout
        self.fallbackFun = fall_back_fun
        self.timeOutFun = time_out_fun

    def __getAddress(self, service_name, group, namespace_id):
        get_provider_url = "http://" + self.ip + ":" + str(self.port) + "/nacos/v1/ns/instance/list"
        params = {
            "serviceName": service_name,
            "groupName": group,
            "namespaceId": namespace_id
        }
        response = requests.get(get_provider_url, params=params, timeout=2)
        re_json = response.json()
        try:
            msg = re_json['hosts']
        except json.JSONDecodeError:
            msg = []
        hosts = []
        for item in msg:
            hosts.append({
                'ip': item['ip'],
                'port': item['port'],
                'healthy': item['healthy']
            })
        md5 = hashlib.md5()
        md5.update(json.dumps(hosts, ensure_ascii=False).encode("utf-8"))
        md5_content = md5.hexdigest()
        try:
            old_md5 = self.__LoadBalanceDict[service_name + group + namespace_id + "md5"]
        except KeyError:
            self.__LoadBalanceDict[service_name + group + namespace_id + "md5"] = md5_content
            old_md5 = ""
        if old_md5 != md5_content:
            healthy_hosts = []
            for host in msg:
                if host['healthy']:
                    healthy_hosts.append(host)
            self.__LoadBalanceDict[service_name + group + namespace_id] = healthy_hosts
            self.__LoadBalanceDict[service_name + group + namespace_id + "index"] = 0

    def loadBalanceClient(self, service_name, group, namespace_id):
        try:
            x = int(time.time()) - self.__LoadBalanceDict[service_name + group + namespace_id + "time"]
        except KeyError:
            x = 11
        if x > 10:
            self.__getAddress(service_name, group, namespace_id)
            self.__LoadBalanceDict[service_name + group + namespace_id + "time"] = int(time.time())

        index = self.__LoadBalanceDict[service_name + group + namespace_id + "index"]
        service_count = len(self.__LoadBalanceDict[service_name + group + namespace_id])
        if service_count == 0:
            return ""
        if index >= service_count:
            self.__LoadBalanceDict[service_name + group + namespace_id + "index"] = 1
            return self.__LoadBalanceDict[service_name + group + namespace_id][0]['ip'] + ":" + str(
                self.__LoadBalanceDict[service_name + group + namespace_id][0]['port'])
        else:
            self.__LoadBalanceDict[service_name + group + namespace_id + "index"] = index + 1
            return self.__LoadBalanceDict[service_name + group + namespace_id][index]['ip'] + ":" + str(
                self.__LoadBalanceDict[service_name + group + namespace_id][index]['port'])

def get_service(service_name):
    nacosClient = NacosServerBalanceClient(ip="192.168.62.157", port="30788", service_name=service_name)

    ss = nacosClient.loadBalanceClient(group="DEFAULT_GROUP", namespace_id="public",
                                       service_name=service_name)
    return ss


def call_model_method(service_name, method_path, params):
    service_address = get_service(service_name)
    if not service_address:
        return "No available service found"

    url = f"http://{service_address}/{method_path}"
    logger.info(f"调用nacos服务url={url}")
    try:
        response = requests.post(url, params=params, timeout=60*60*2)
        if response.status_code == 200:
            return response.json()
        else:
            return response.text
    except Timeout:
        logger.error(f"调用nacos服务异常 url={url}, 异常信息: Request timed out")
        return "Request timed out"
    except Exception as e:
        logger.error(f"调用nacos服务异常 url={url}, 异常信息: {e}")
        return ""