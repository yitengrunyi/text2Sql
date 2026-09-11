# Text2SQL 项目开发指南

## 1. 项目概述

这是一个**智能金融数据查询系统（Text2SQL）**，主要用于将自然语言问题转换为SQL查询，面向中国金融投研领域（A股、港股、美股、基金、指数等）的数据分析需求。

### 核心功能
- 自然语言问题理解与意图识别
- 自动定位数据域（个股、基金、指数、美股、宏观经济等）
- 动态生成SQL查询语句
- SQL执行与结果反思纠错
- 支持多轮对话与用户反馈
- 实时WebSocket通信，流式返回处理进度

### 技术特点
- 采用LLM（大语言模型）驱动的多阶段Pipeline
- 向量检索与RAG（检索增强生成）技术
- 支持多种数据源（MySQL、Oracle）
- 使用Embedding进行语义匹配（行业、题材、股票、指标等）
- 自反思机制纠错SQL生成错误

## 2. 启动入口

### 主入口文件
- **WebSocket服务**: `app.py` 或 `main_websock.py`
  - 端口：5903 (app.py默认)
  - 端口：5902 (main_websock.py，带RabbitMQ消息队列)
  - 启动命令：`python app.py` 或 `python main_websock.py`
  - WebSocket端点：`/ws`
  - 首页：`/` (提供静态HTML页面)

### 启动流程
1. 初始化数据库连接池（MySQL、Oracle）
2. 启动FastAPI服务
3. 接收WebSocket连接
4. 解析用户请求并调用 `handle_message`

## 3. 核心目录结构

```
text2sql_renew/
├── app.py / main_websock.py          # 启动入口
├── handler/                           # 请求处理层
│   ├── handler_message.py            # 主消息分发（新会话/反馈）
│   ├── text2sql_handler.py           # Text2SQL核心处理逻辑
│   └── feedback_handler.py           # 用户反馈处理
│
├── service/                           # 业务逻辑层（核心Pipeline）
│   ├── query_intent/                 # 意图识别（10类意图分类）
│   ├── locator/                      # 定位服务（行业、域、表、股票）
│   │   ├── question_locator.py       # 问题理解与Embedding
│   │   ├── domain_locator.py         # 域定位（个股/基金/指数/美股）
│   │   ├── table_locator.py          # 表定位
│   │   └── stock_and_industry_locator.py  # 股票行业定位
│   ├── sql_generator/                # SQL生成
│   │   ├── text_to_sql_generator.py  # 核心SQL生成逻辑
│   │   ├── TableFetcher.py           # 动态/固定表信息获取
│   │   └── fetch_knowledge.py        # 知识库检索（通用、域、表）
│   ├── sql_executor/                 # SQL执行
│   │   └── text_to_sql_exec.py       # 执行SQL并返回结果
│   ├── self_reflection/              # 自反思纠错
│   │   ├── question_res_self_check.py # SQL反思与纠错
│   │   ├── diagnose.py               # 错误诊断
│   │   └── sql_explanation_info.py   # SQL解释生成
│   ├── analysis/                     # 问题分析
│   │   └── question_analysis.py      # 问题理解与分析
│   ├── EDB_flow/                     # 宏观经济数据（Oracle）
│   │   ├── vector_recall_service.py  # 向量召回
│   │   └── filter_service.py         # LLM过滤
│   ├── feedback_intent/              # 反馈意图识别
│   └── user_feedback/                # 用户反馈处理
│
├── util/                              # 工具类
│   ├── model_helpers.py              # LLM调用封装（GPT/Gemini/DeepSeek等）
│   ├── rag_helpers.py                # Embedding与向量检索
│   ├── db_helpers.py                 # 数据库操作
│   ├── data_formater_helpers.py      # 数据格式化（DataFrame转表格）
│   ├── websocket_util.py             # WebSocket工具
│   ├── token_tracker.py              # Token使用追踪
│   └── fix_fields.py                 # 固定字段与召回表配置
│
├── common/                            # 公共模块
│   ├── middleware/                   # 中间件
│   │   ├── db_utils.py               # 数据库连接池管理
│   │   ├── redis_util.py             # Redis缓存
│   │   ├── resp_util.py              # 响应工具（WebSocket发送）
│   │   ├── mq_send.py / mq_consume.py # RabbitMQ消息队列
│   ├── prompt/                       # Prompt模板
│   └── enum/                         # 枚举类型（数据库类型、模型类型等）
│
├── config/                            # 配置
│   └── nacos/                        # Nacos配置中心
│
├── model/                             # 模型相关
│   └── embedding/                    # Embedding模型
│
├── static/                            # 静态文件（前端HTML/CSS/JS）
├── test/                              # 测试用例
├── script/                            # 脚本工具
├── EDB_search.py                     # 宏观经济数据查询入口
├── orcl_edb_fetch.py                 # Oracle数据获取
└── requirements.txt                  # Python依赖
```

## 4. 数据流向

### 4.1 输入来源
- **用户端**: WebSocket连接 → JSON格式请求
  ```json
  {
    "question": "宁德时代2023年营收是多少",
    "sessionId": "xxx",
    "userId": "xxx",
    "userName": "xxx"
  }
  ```

### 4.2 核心Pipeline流程

```
用户问题
    ↓
① 意图识别 (query_intent/)
    ├─ 10类意图分类（数据查询、拒识、宏观经济等）
    ↓
② 问题理解 (locator/question_locator.py)
    ├─ 生成Query Embedding
    ├─ 抽取关键实体（股票、指标、时间等）
    ↓
③ 多维度定位 (locator/)
    ├─ 股票/行业/题材定位 (stock_and_industry_locator.py)
    ├─ 一级域定位（个股/基金/指数/美股） (domain_locator.py)
    ├─ 二级域定位（具体数据域） (domain_locator.py)
    ├─ 表定位 (table_locator.py)
    ↓
④ 特殊实体召回 (sql_generator/TableFetcher.py)
    ├─ 动态字段Top-K召回（股东、高管等）
    ├─ 固定字段处理
    ↓
⑤ SQL生成 (sql_generator/text_to_sql_generator.py)
    ├─ 获取表结构信息
    ├─ 检索通用知识、域知识、表知识
    ├─ 构建Prompt调用LLM生成SQL
    ↓
⑥ SQL执行 (sql_executor/text_to_sql_exec.py)
    ├─ 根据db_type选择数据库
    ├─ 执行SQL并获取结果
    ↓
⑦ 自反思纠错 (self_reflection/)
    ├─ 若执行失败，诊断错误 (diagnose.py)
    ├─ 聚焦相关表重新生成SQL (question_res_self_check.py)
    ├─ 重新执行
    ↓
⑧ 结果解释 (self_reflection/sql_explanation_info.py)
    ├─ 生成SQL执行逻辑解释
    ↓
⑨ 返回结果
    ├─ 通过WebSocket流式返回各阶段进度
    ├─ 存储中间结果到MySQL
```

### 4.3 数据输出
- **WebSocket流式响应**: 分阶段返回进度（类型码：BACKGROUND_INFO、DOMAIN、TABLE_NAME、SQL1、SQL1_RES、EXPLAIN_RES等）
- **数据库持久化**: 中间结果存储到 `text_to_sql_middle_records` 表
- **用户反馈存储**: 反馈记录存储以支持多轮对话

### 4.4 数据源
- **MySQL**: 
  - A股、港股、基金、指数等结构化数据
  - 元数据表（域、表、字段描述）
  - 用户会话历史
- **Oracle**: 
  - 宏观经济数据（EDB）
  - 行业数据
- **Redis**: 
  - 用户中断标记
  - 缓存
- **向量数据**: 
  - Pickle文件存储的Embedding（股票、行业、题材、指标等）
  - `embedding_dict_*.pkl`

## 5. 新增功能开发指南

### 5.1 阅读顺序建议

如果要**新增功能**，建议按以下顺序阅读代码：

#### 第一步：理解入口与消息流转
1. `app.py` - 了解WebSocket启动流程
2. `handler/handler_message.py` - 理解消息分发逻辑（新会话 vs 反馈）
3. `common/middleware/resp_util.py` - 理解响应类型定义与发送机制

#### 第二步：理解核心Pipeline
4. `handler/text2sql_handler.py` - 核心处理流程（600+行）
   - 重点关注 `handle_query_demo_for_mq` 函数
5. `service/query_intent/query_intent_judgment.py` - 意图识别
6. `service/locator/question_locator.py` - 问题理解与Embedding

#### 第三步：理解定位机制
7. `service/locator/domain_locator.py` - 域定位（一级/二级）
8. `service/locator/table_locator.py` - 表定位
9. `service/locator/stock_and_industry_locator.py` - 股票行业定位

#### 第四步：理解SQL生成
10. `service/sql_generator/text_to_sql_generator.py` - SQL生成主逻辑
11. `service/sql_generator/TableFetcher.py` - 表信息获取（动态/固定）
12. `service/sql_generator/fetch_knowledge.py` - 知识库检索

#### 第五步：理解执行与纠错
13. `service/sql_executor/text_to_sql_exec.py` - SQL执行
14. `service/self_reflection/diagnose.py` - 错误诊断
15. `service/self_reflection/question_res_self_check.py` - SQL反思纠错
16. `service/self_reflection/sql_explanation_info.py` - 结果解释

#### 第六步：理解工具与配置
17. `util/model_helpers.py` - LLM调用封装
18. `util/rag_helpers.py` - Embedding与向量检索
19. `util/db_helpers.py` - 数据库操作
20. `util/fix_fields.py` - 固定召回表配置

### 5.2 常见功能扩展场景

#### 场景1：新增数据源支持
- **修改文件**: `common/middleware/db_utils.py`, `service/sql_executor/text_to_sql_exec.py`
- **步骤**:
  1. 在 `db_utils.py` 添加新数据库连接池
  2. 在 `text_to_sql_exec.py` 的 `execute_sql` 函数添加新db_type分支
  3. 在 `domain_locator.py` 的 `get_dbtype_from_domain_one` 添加映射规则

#### 场景2：新增意图类型
- **修改文件**: `service/query_intent/query_intent_judgment.py`, `handler/handler_message.py`
- **步骤**:
  1. 更新意图分类Prompt
  2. 在 `handler_message.py` 添加新意图处理分支
  3. 在 `resp_util.py` 定义新的响应类型常量

#### 场景3：新增定位维度（如新增"债券相关"域）
- **修改文件**: `service/locator/domain_locator.py`, `handler/text2sql_handler.py`
- **步骤**:
  1. 在数据库添加域元数据（MDB_DOMAIN_JULING表）
  2. 更新 `domain_locator.py` 的Prompt添加新域描述
  3. 添加新域对应的db_type映射
  4. 如需特殊处理，在Pipeline中添加分支逻辑

#### 场景4：新增特殊召回表
- **修改文件**: `util/fix_fields.py`, `handler/text2sql_handler.py`
- **步骤**:
  1. 在 `fix_fields.py` 的 `recall_tables` 字典添加新表配置
  2. 配置格式：`{"表名": (字段名, 字段描述, 示例)}`
  3. Pipeline会自动触发主体词抽取与Top-K召回

#### 场景5：优化SQL生成Prompt
- **修改文件**: `service/sql_generator/text_to_sql_generator.py`, `common/prompt/prompt_template.py`
- **步骤**:
  1. 修改 `construct_output_text` 函数中的Prompt模板
  2. 调整知识检索策略（通用知识、域知识、表知识）
  3. 更新 `fetch_knowledge.py` 中的知识库内容

#### 场景6：新增反馈类型处理
- **修改文件**: `service/feedback_intent/feedback_intent.py`, `handler/feedback_handler.py`
- **步骤**:
  1. 定义新的反馈意图类型
  2. 在 `feedback_handler.py` 添加处理逻辑
  3. 根据反馈类型调整SQL重新生成策略

### 5.3 关键配置文件
- `util/fix_fields.py` - 固定字段召回配置、动态表配置
- `common/enum/` - 数据库类型、模型类型枚举
- `config/nacos/` - Nacos配置中心（模型API配置、数据库连接等）
- `service/locator/*.csv` - 股票映射表（A股、港股、美股）
- `service/locator/*_embeddings.json` - 预计算的Embedding（行业、题材等）

### 5.4 调试建议
1. **日志**: 项目使用 `logging` 模块，关注 `logging.info/error` 输出
2. **中断机制**: 通过Redis的 `text_to_sql_interrupt_{questionId}_0` 键实现用户中断
3. **Token追踪**: `util/token_tracker.py` 追踪LLM调用的Token消耗
4. **WebSocket类型码**: 在 `resp_util.py` 定义，用于前端区分不同阶段的响应

### 5.5 性能优化要点
- 向量检索使用缓存的Embedding文件（避免重复计算）
- 表定位后聚焦相关表（减少SQL生成Prompt长度）
- 支持用户中断（长时间查询可中断）
- 异步IO（数据库、LLM调用均使用async/await）

### 5.6 测试相关
- 测试用例: `test_cases.json`, `test_multi_turn.py`, `evaluate_multi_turn.py`
- 测试结果: `test_results_*.xlsx`

## 6. 技术栈
- **后端**: FastAPI + Uvicorn
- **数据库**: MySQL (aiomysql), Oracle (cx_Oracle)
- **消息队列**: RabbitMQ (aio-pika)
- **缓存**: Redis
- **LLM**: OpenAI GPT-4o, Gemini 2.5, DeepSeek R1等（通过 `model_helpers.py` 封装）
- **Embedding**: BGE-M3, Text2Vec
- **配置中心**: Nacos
- **向量检索**: 基于余弦相似度的Top-K检索

## 7. 注意事项
1. **敏感信息**: 代码中包含API Key和数据库密码，生产环境需迁移到Nacos或环境变量
2. **模型切换**: 可在 `model_helpers.py` 和 `text_to_sql_generator.py` 中调整使用的LLM模型
3. **并发限制**: 当前使用单一WebSocket连接，高并发需考虑连接池管理
4. **数据安全**: SQL执行未做完整的安全校验，需增强SQL注入防护

---

**最后更新**: 2026-07-31
