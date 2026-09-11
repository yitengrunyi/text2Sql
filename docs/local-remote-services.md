# 本地应用连接远程服务

此模式在本机运行 `app.py`，业务依赖继续使用 Nacos 返回的远程地址，但隔离以下副作用：

- 从远程 Nacos 读取配置，不注册服务，不发送心跳。
- 不连接、不消费、不发布 RabbitMQ 消息。
- 查询取消标记和结果缓存写入本机 Redis。
- 元数据数据库使用本机 `127.0.0.1:3307/schema_metadata`，由测试元数据生成，并分别
  按当前 `juling`（MYSQL-2）、`FUND_INFO`（MYSQL-1，测试 Nacos `192.168.15.57:31513`）
  和本地 `fiu`（MYSQL-4）的物理结构校准；远程元数据库保持只读。
- MYSQL-1 使用测试 Nacos 中的 `192.168.15.57:31513/FUND_INFO` 配置。
- MYSQL-4 使用 `127.0.0.1:3307/fiu` 本地模拟库，不影响其他远程配置。
- MYSQL-2、Doris、BGE、DashVector、股票匹配和大模型继续使用远程服务。
- MYSQL-3 使用测试 Nacos 中的 `192.168.15.49:30635/saas`，会写入会话和中间结果。
- SQL 生成默认使用当前远程服务可用的 `gpt-4.1`，可通过 `TEXT2SQL_SQL_MODEL` 独立覆盖。
- 表定位会按目标 MySQL 的实际表目录剔除测试元数据库中的失效表名。
- 年份查询按运行当天判断；只有问题明确包含“预期、预测、预计、业绩预告”等含义时才优先查询预测数据。

## 前置条件

- 已连接公司 VPN，且本机在各远程服务的网络白名单内。
- Docker Desktop 已启动，并允许当前终端访问 Docker。本地 MySQL 容器
  `text2sql-mysql`（127.0.0.1:3307）如已停止，`run_local_remote.sh` 会自动拉起并
  预检 `schema_metadata`/`fiu` 两个库是否存在，缺失时报错并提示生成命令。
- 当前 Python 环境已经安装项目依赖。
- 启动时会校验测试 Nacos 返回的数据库地址必须位于私网段（192.168.x）：
  测试 Nacos 不可用时 nacos 客户端会静默回退到本地快照，而快照内容可能指向
  生产主机（被白名单拦截后表现为莫名超时），校验失败会直接报错终止。

## 启动

首次启动前生成本地元数据库。该命令默认拒绝覆盖已经存在的 `schema_metadata`：

```bash
TEXT2SQL_NACOS_REGISTER=0 \
  ./venv/bin/python local_sim/build_schema_metadata.py build
```

后续只读检查本地元数据与三个物理源是否一致：

```bash
TEXT2SQL_NACOS_REGISTER=0 \
  ./venv/bin/python local_sim/build_schema_metadata.py audit
```

构建和检查报告分别写入 `artifacts/schema_metadata_build_report.json` 和
`artifacts/schema_metadata_audit_report.json`。审计会同时比较测试元数据库的
内容指纹，以及 `juling`、`FUND_INFO`、`fiu` 三个物理源各自的表和字段结构。
如需重建，显式加 `--replace`；脚本会先把原数据库改名为带时间戳的备份库，
不会直接删除。

```bash
./script/run_local_remote.sh
```

浏览器访问 `http://127.0.0.1:5903`。脚本会启动本地 Redis，并设置以下运行参数：

```text
text2sql_env=prod
TEXT2SQL_NACOS_REGISTER=0
TEXT2SQL_DISABLE_RABBITMQ=1
TEXT2SQL_SOURCE_DB_USE_LOCAL=1
TEXT2SQL_MYSQL4_USE_LOCAL=1
TEXT2SQL_MYSQL1_USE_TEST_NACOS=1
TEXT2SQL_MYSQL3_USE_TEST_NACOS=1
TEXT2SQL_SQL_MODEL=gpt-4.1
TEXT2SQL_FILTER_EXISTING_TABLES=1
TEXT2SQL_DB_CONNECT_TIMEOUT=10
TEXT2SQL_REDIS_URL=redis://127.0.0.1:6380/0
```

需要使用其他 Python 解释器或 Redis 端口时：

```bash
TEXT2SQL_PYTHON=/path/to/python TEXT2SQL_REDIS_PORT=6380 \
  ./script/run_local_remote.sh
```

## 停止本地 Redis

应用使用 `Ctrl+C` 停止。本地 Redis 使用以下命令停止并删除容器：

```bash
docker compose -f docker-compose.local.yml down
```

不要设置 `TEXT2SQL_LOCAL_SIM=1`。该变量会跳过远程 Nacos，并将 MYSQL-4 和 Doris 改为本地模拟库。

本地 `fiu` 保留生产表结构和 43 只美股样本，但行情和财务数值是合成数据，不能用于核对生产真实数值。
