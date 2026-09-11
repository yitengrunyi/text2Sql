from nacos import NacosClient
import threading
import time
import yaml
import os
from nacos.exception import NacosRequestException


def _env_enabled(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}

# !!!重要提醒!!!
# 环境配置通过环境变量text2sql_env控制:
# - 设置text2sql_env=dev表示测试环境
# - 变量不存在或为空时表示生产环境（适用于无法设置环境变量的生产服务器）
# 测试环境 = 192.168.15.49:31534
# 生产环境 = 192.168.62.157:30788
IS_TEST_ENV = os.environ.get('text2sql_env', '').lower() == 'dev'

IS_PROD_ENV = not IS_TEST_ENV

# Nacos服务器地址配置
TEST_SERVER = "192.168.15.49:31534"
PROD_SERVER = "192.168.62.157:30788"


# 自动选择对应环境的地址
nacos_server_address = PROD_SERVER if IS_PROD_ENV else TEST_SERVER
print(f"当前环境：{'测试环境' if IS_TEST_ENV else '生产环境'} ({nacos_server_address})")

# Nacos命名空间ID（可选）
namespace_id = ""
# 服务名称
service_name = "AiTextToSql"
# 服务IP地址
service_ip = "192.168.67.62"
# 服务端口
service_port = 5902
# 配置文件的Data ID
data_id = "ai_text_to_sql.yml"
# 配置文件的Group
group = ""


def _read_nacos_config(client):
    ori_config = client.get_config(data_id, group)
    if not ori_config:
        raise RuntimeError(f"Nacos config is empty: data_id={data_id!r}, group={group!r}")
    return yaml.safe_load(ori_config)


def fetch_nacos_config(server_address):
    """Read configuration from another Nacos server without registering a service."""
    client = NacosClient(server_address, namespace=namespace_id)
    return _read_nacos_config(client)


# 本地模拟模式(TEXT2SQL_LOCAL_SIM=1): 不连 nacos, 直接读本地快照, 不注册服务/心跳
LOCAL_SIM_ENABLED = _env_enabled("TEXT2SQL_LOCAL_SIM")
LOCAL_REMOTE_MODE_ENABLED = (
    _env_enabled("TEXT2SQL_SOURCE_DB_USE_TEST_NACOS")
    or _env_enabled("TEXT2SQL_MYSQL4_USE_LOCAL")
    or bool(os.environ.get("TEXT2SQL_REDIS_URL"))
)
NACOS_REGISTER_ENABLED = (
    not LOCAL_SIM_ENABLED
    and _env_enabled(
        "TEXT2SQL_NACOS_REGISTER",
        default=not LOCAL_REMOTE_MODE_ENABLED,
    )
)

if LOCAL_SIM_ENABLED:
    import pathlib
    _snap = pathlib.Path(__file__).resolve().parents[2] / "nacos-data" / "snapshot" / \
        "ai_text_to_sql.yml+DEFAULT_GROUP+"
    with open(_snap, encoding="utf-8") as _f:
        config = yaml.safe_load(_f.read())
    print(f"本地模拟模式: nacos 配置读自本地快照 {_snap}")

else:
    # 创建Nacos客户端
    nacos_client = NacosClient(nacos_server_address, namespace=namespace_id)

    # 获取配置不要求注册服务。本地可只读生产配置，同时不出现在生产服务列表中。
    config = _read_nacos_config(nacos_client)
    print(f"Config loaded from Nacos: data_id={data_id}, keys={sorted(config.keys())}")

    if NACOS_REGISTER_ENABLED:
        nacos_client.add_naming_instance(service_name, service_ip, service_port)
        print(f"Service {service_name} registered successfully.")

        def heartbeat_task():
            max_retries = 10
            retry_delay = 10

            while True:
                try:
                    nacos_client.send_heartbeat(service_name, service_ip, service_port)
                except NacosRequestException as e:
                    print(f"Heartbeat failed: {e}")
                    for attempt in range(max_retries):
                        print(f"Retrying in {retry_delay} seconds... (attempt {attempt + 1})")
                        time.sleep(retry_delay)
                        try:
                            nacos_client.send_heartbeat(service_name, service_ip, service_port)
                            print("Heartbeat sent successfully after retry")
                            break
                        except NacosRequestException as retry_error:
                            print(f"Retry attempt {attempt + 1} failed: {retry_error}")
                    else:
                        print("Max retries reached. Continuing with next heartbeat interval...")

                time.sleep(5)

        heartbeat_thread = threading.Thread(target=heartbeat_task, daemon=True)
        heartbeat_thread.start()
    else:
        print("Nacos registration and heartbeat are disabled.")
