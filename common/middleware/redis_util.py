import os
from urllib.parse import urlparse

import redis
from rediscluster import RedisCluster, ClusterConnectionPool

from config.nacos.nacos_service import config




redis_config = config.get('redis_config', {})

# redis_config = {
#     "type": "cluster",
#     "username": "redis",
#     "password": "Redis@2020",
#     "nodes": [
#         {
#             "host": "192.168.15.64",
#             "port": 7001
#         },
#         {
#             "host": "192.168.15.64",
#             "port": 7002
#         },
#         {
#             "host": "192.168.15.64",
#             "port": 7003
#         },
#         {
#             "host": "192.168.15.64",
#             "port": 7004
#         },
#         {
#             "host": "192.168.15.64",
#             "port": 7005
#         },
#         {
#             "host": "192.168.15.64",
#             "port": 7006
#         }
#     ]
# }

def get_redis_client():
    local_redis_url = os.environ.get("TEXT2SQL_REDIS_URL")
    if local_redis_url:
        parsed_url = urlparse(local_redis_url)
        if parsed_url.scheme not in {"redis", "rediss"} or not parsed_url.hostname:
            raise ValueError("TEXT2SQL_REDIS_URL must be a valid redis:// or rediss:// URL")
        print(
            "Using Redis URL override: "
            f"{parsed_url.scheme}://{parsed_url.hostname}:{parsed_url.port or 6379}"
        )
        return redis.Redis.from_url(local_redis_url, max_connections=60)

    redis_cluster_list = redis_config["nodes"]
    password = redis_config["password"]
    redis_type = redis_config["type"]
    if redis_type == "cluster":
        pool = ClusterConnectionPool(startup_nodes=redis_cluster_list, password=password,
                                     max_connections=60)
        return RedisCluster(connection_pool=pool)

    raise ValueError(f"Unsupported Redis type: {redis_type!r}")


redis_client = get_redis_client()
