# Text2SQL 评测套件（简历指标可回溯）

一切数字可回溯：评测集 → 运行产物 → 指标报告 全链路在本目录。

## 组成

| 文件 | 作用 |
|---|---|
| `gold_set_180.json` | 30 轮×6 问分层评测集（4 域/5 难度/7 类追问/3 路由） |
| `drafts/` | 20 个新轮次的出题草稿（11-30 号轮次，对抗校验通过） |
| `build_set.py` | 装配脚本：既有 10 轮 + 草稿 20 轮 → gold_set_180.json；含手工标签表、定向修正表、路由 gold 机械计算 |
| `verify_gold.py` | 机械核验：独立重执行全部 gold SQL（值一致性 0.5% 容差） |
| `run_eval.py` | 主评测 runner（生产链路 + 全量插桩 + 断点续跑 + 4 组消融） |
| `instrument.py` | 插桩：LLM 计时/计数、表候选与选中捕获、列召回捕获、随机表消融、Reflection 消融 |
| `aggregate.py` | 聚合指标：EX/路由 F1/延迟分位/Token/召回/消融对比 |
| `run_safety.py` | 危险 SQL 拦截评测（10 恶意探针 + 6 良性对照） |
| `schema_recall.py` | 从完整管线记录提取关键词，通过 Nacos 配置的 BGE-M3 服务重放字段召回 |
| `dbx.py` | 只读 DB 查询助手（出题/核验用） |
| `schema_*.json / catalog_*.md / active_*.md` | 三源 schema 快照与管线可见候选表清单 |
| `runs/` | 运行产物（每轮次一个 JSON + 聚合报告） |

## 运行方式

```bash
# 0) 环境冒烟（VPN 在线、三库+网关+Redis 可达）
./venv/bin/python evals/smoke_check.py
# 1) 重建评测集（元数据域映射 → 路由 gold 机械计算）
./venv/bin/python evals/build_set.py
# 2) gold 机械核验（全部 SQL 独立重执行，必须 0 失败）
./venv/bin/python evals/verify_gold.py
# 3) 主评测（先跑 full 作为延迟基准，网关对相同 prompt 有缓存）
./venv/bin/python evals/run_eval.py --tag full --ablation full
# 4) 消融（顺序跑，EX 不受缓存影响）
./venv/bin/python evals/run_eval.py --tag ragmem --ablation ragmem
./venv/bin/python evals/run_eval.py --tag rag --ablation rag
./venv/bin/python evals/run_eval.py --tag base --ablation base
# 5) 安全评测
./venv/bin/python evals/run_safety.py
# 6) 聚合
./venv/bin/python evals/aggregate.py --runs full,ragmem,rag,base
# 7) 字段召回补算（不访问 DashVector）
./venv/bin/python evals/schema_recall.py
```

### 10轮 x 5问 Gold Set

`gold_set_10r_50.json` 严格包含 10 轮、每轮 5 问，共 50 问；不含宏观库问题，
也不含依赖 DashVector 字段值召回的问题。每问都包含 `gold_sql`、`gold_value`、
`gold_tables` 和按表归属的 `gold_columns`。

```bash
./venv/bin/python evals/build_gold_set_10r_50.py
./venv/bin/python evals/audit_gold_metadata.py
./venv/bin/python evals/verify_gold.py \
  --set evals/gold_set_10r_50.json \
  --report evals/gold_set_10r_50_verify_report.json
./venv/bin/python evals/run_eval.py \
  --set evals/gold_set_10r_50.json \
  --tag gold50_full --ablation full
./venv/bin/python evals/aggregate.py \
  --set evals/gold_set_10r_50.json --runs gold50_full
./venv/bin/python evals/schema_recall.py \
  --set evals/gold_set_10r_50.json \
  --run-dir evals/runs/gold50_full/turns \
  --output evals/runs/gold50_schema_recall.json \
  --k 10,20,50
```

`aggregate.py` 输出首次执行正确率、Reflection 后正确率、修复成功率、
Table Recall@1/3/5/10、多轮追问正确率、p50/p95 延迟、平均 Token、平均 LLM
调用次数、错误表/字段幻觉率和最终总正确率。`schema_recall.py` 单独输出
Column Recall@10/20/50；它只调用 BGE-M3 生成查询向量并读取本地字段向量文件，
不会访问 DashVector。

断点续跑：`runs/<tag>/turns/r<轮>_t<问>.json` 存在即跳过；`--force` 强制重跑。

## 判分口径

- **EX（主指标，Execution Accuracy）**：harness 独立执行预测 SQL（首次 SQL 与 Reflection 后 SQL 分别执行），执行结果与 gold SQL 执行结果比对——数值 0.5% 相对容差 + 亿/百万/万单位换算，实体/日期须命中，名单题重叠率≥80%。含实体的数值必须出现在同一结果行；预测行数超过 `max(5, 2×Gold行数)` 视为明显过量返回。不比较 SQL 字符串。
- **答案一致率（辅助）**：对最终自然语言解释文本做同口径判分（可发现"执行对但解释错"的忠实性问题）。
- **路由 Macro-F1**：追问三分类（SQL_GENERATION/NEW_QUERY/NON_QUERY）。gold 按二级域表上下文机械计算（对齐 `common/prompt/prompt_template.py` 三分类定义）：当前域表可解=SQL_GENERATION，需跨二级域新表=NEW_QUERY，闲聊=NON_QUERY。
- **首次 EX → Reflection 后 EX**：首次失败且触发反思修复的题中，最终判对的比例为修复成功率。
- gold SQL 执行失败的轮次（数据漂移）不计入 EX 分母，单独披露。

## 消融设计

| tag | Schema RAG | Memory | Reflection | 含义 |
|---|---|---|---|---|
| full | ✔ | ✔ | ✔ | 完整管线 |
| ragmem | ✔ | ✔ | ✘ | +Memory 阶梯 |
| rag | ✔ | ✘ | ✘ | +Schema RAG 阶梯（追问按新问独立会话） |
| base | ✘(随机同数量表候选+全列) | ✘ | ✘ | 基础生成 |

随机表消融为确定性随机（seed=tag+问题+域），可复现。

字段召回补算从完整管线中筛出 63 条实际发生 Schema 选择的问题，只向 Nacos 中
`bge_m3_url` 指向的 BGE-M3 服务发送抽取后的关键词字符串。它不会发送 180 条完整问题，
也不访问 DashVector；向量只用于已有字段向量字典的 Top-K 相似度计算。

## 已知口径与陷阱（面试防线）

1. **网关对完全相同 prompt 有缓存**——延迟指标只取 first run（full）；消融 run 只取 EX。
2. **空结果不触发 Reflection**（goReflect=False 硬编码）——空结果题的恢复率单列。
3. **同义表口径冲突**（如 ETF_INFO_DETAIL vs ETF_LABEL_INFO_CHINA 的 QDII 统计）是真实失败模式，保留为压力题。
4. 测试库 FUND_INFO 数据会隔夜刷新——date-pinned 题也可能漂移，verify_gold 会抓出来。
5. 路由 gold 是机械口径（二级域表上下文），与人工直觉可能有出入（如"换个标的查同域指标"按 prompt 定义属 SQL_GENERATION）。
6. 运行时每条 Gold SQL 的状态和结果摘要已随题保存。2026-09-03 完成评测后再次连接实时库复核，发现 9/180 条动态题结果已变化；最终指标使用各组运行时保存的 Gold 结果，不用新数据反向改判旧运行。
