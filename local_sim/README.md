# 本地数据库：元数据库(schema_metadata) + 美股库(fiu) + 宏观Doris库(TLDATA)

`build_schema_metadata.py` 会完整复制测试元数据库，再分别根据当前 `juling`
（MYSQL-2 生产）、`FUND_INFO`（MYSQL-1 测试 Nacos `192.168.15.57:31513`）和本地
`fiu`（MYSQL-4）三个物理源的 `information_schema` 校准表名、字段名、字段类型和
可空属性。测试元数据库和两台远程库都只读；自动发现但缺少人工语义的表和字段
默认 `HISVALID=0`。`--activate` 把三源真实存在的表/列全部置为 `HISVALID=1`。

`build --replace --activate` 还会应用 `semantic_overlay.json` 语义覆盖层（幂等，
每次构建重放）：为 `ETF_PERFORMANCE_DETAIL`/`ETF_INFO_DETAIL`/
`FUND_STATISTICS_YEAR` 补域映射、按表名键写入表级专家知识（注意
`fetch_table_knowledge` 以表名匹配 `OBJECT_HCODE`，hcode 键的 TABLE 知识不会被
注入）、修补代码后缀等列描述。评测实测 FUND_INFO 域 18 题 6→13/18（覆盖层 v2），
后续小幅增补未再逐题验证。

```bash
TEXT2SQL_NACOS_REGISTER=0 ./venv/bin/python local_sim/build_schema_metadata.py build
TEXT2SQL_NACOS_REGISTER=0 ./venv/bin/python local_sim/build_schema_metadata.py audit
```

生产环境两个库都在阿里云内网 RDS（白名单拦截，本机连不上），本目录用一台本地
docker MySQL 8 同时模拟它们。pipeline 通过 pymysql/MySQL 协议连接，对 Doris 的
查询方言（DATE_FORMAT/DATE_SUB/IFNULL/GROUP BY 等）在 MySQL 8 上行为一致。

## 组成

| 文件 | 作用 |
|---|---|
| `fiu_columns_from_metadata.txt` | 美股 20 张表的字段级元数据（从 192.168.15.57 schema_metadata 的 MDB_TABLE/MDB_COLUMN_JULING 导出，SRC='FIU'） |
| `build_fiu.py` | 建 fiu 库：解析上面文件生成 DDL + 生成 43 只真实美股的行情/财务数据 |
| `build_tldata.py` | 建 TLDATA 库：EDB_INDIC_DATA + 27 张 ECO_DATA_* 表，用 important_indic_emb.pkl 的 402 个真实指标生成时间序列 |
| `smoke_test.py` | 走 pipeline 真实路径的冒烟测试（execute_sql MYSQL-4 + fetch_data_from_doris） |

## 数据真实性边界

- **真实**：全部表名/字段名/类型（来自线上元数据）、43 只美股的代码/中文名/交易所/
  申万行业/中概股标签、402 个宏观指标的 ind_der_code/名称/频率/单位/所属表。
- **生成**：所有数值。行情为锚定终点的随机游走；财务按各公司营收量级+增速+利润率
  生成（单位与元数据一致：财务百万美元、市值百万元人民币、每股类美元）；宏观指标
  为 OU 过程（量级按指标名关键词+单位估计）。

## 用法

```bash
# 1. 起容器（已配置过则跳过）
docker run -d --name text2sql-mysql -p 3307:3306 \
  -e 'MYSQL_ROOT_PASSWORD=123QWEasd!*' -e MYSQL_DATABASE=fiu mysql:8 \
  --character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci

# 2. 建库导数（幂等，先 DROP 再建）
./venv/bin/python local_sim/build_fiu.py
./venv/bin/python local_sim/build_tldata.py

# 3. 冒烟测试（需 TEXT2SQL_LOCAL_SIM=1）
TEXT2SQL_LOCAL_SIM=1 ./venv/bin/python local_sim/smoke_test.py
```

## TEXT2SQL_LOCAL_SIM 开关

设置该环境变量后，三处代码切换到本地模拟库，不设置则完全走原逻辑：

- `config/nacos/nacos_service.py`：不连 nacos，直接读 `nacos-data/snapshot/` 本地快照
- `common/middleware/db_utils.py`：mysql4_config 指向 127.0.0.1:3307/fiu，并启用
  原本被注释掉的 mysql4 连接池初始化
- `orcl_edb_fetch.py`：doris_db_config 指向 127.0.0.1:3307/TLDATA

mysql1/2/3、source_db_config 等仍指向测试环境（192.168.15.x，需 VPN）。

## 已知妥协

- 50009/50010/50032/50033/50034/50035 线上是视图（基于 EOD 基表），本地建成同列
  结构的表（原视图 SQL 无从还原）；50011-50016 的 Q/CUM 视图为真实 MySQL 视图
  （`SELECT * FROM COM310X WHERE F003V IN (...)`）。
- **VIEW_COM3105/VIEW_COM3106 没有 F003V 列**（与线上元数据一致，不是模拟库
  缺陷）：查板块/地域分布用 F006V 精确匹配 + F001D 年末日期，别从财务表迁移
  `F003V='FY'` 条件。
- COM3101 只填了关键指标对（市值/PE/PB/PS/股息率等），长尾列为 NULL；F013N 市值
  按元数据"百万元(人民币)"口径 = 美元市值×7.2，与该行 F002V='USD' 并存是照抄
  元数据的结果。
- COM3103.F049N 每股营收 = 当期营收/股本（单季行即单季每股值，未年化）。
- BA/NIO 净利润为负（净利率 -5%/-35%）是刻意保留的真实状态；对应 COM3101 的
  PE/F011N 为 NULL。
- 元数据 bug 照单保留以对齐生产：F006N 是 DECIMAL(6,0) 的 YYYYMM（专家知识里说
  F006N 是频率码，与列元数据冲突，生产同样如此）；F###D 段的 DATE 类型统一修正。
- TLDATA 只有 6 张表有数据（402 个指标所在），其余 21 张 ECO_DATA_* 为空表——
  pkl 里本就没有指向它们的指标，与线上召回范围一致。
- 宏观指标数值为合成值：'%' 类裁剪在基准±6pct 内、PMI 裁剪在 [30,70]，但绝对
  水平（如美国 CPI 3.5%）不代表真实数据，做解释类评测时注意。
- **MySQL 8 开着 ONLY_FULL_GROUP_BY**：`GROUP BY DATE_FORMAT(...)` 后 `ORDER BY
  裸列` 会报 1055（真 Doris 宽松）。orcl_edb_fetch.py:170 的自测样例就是这种
  写法，LLM 若模仿会触发反思重写；可在 generate_doris_specs 里补一条
  "ORDER BY 需用 GROUP BY 表达式或别名"。
