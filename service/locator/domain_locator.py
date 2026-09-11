import ast
import asyncio
import logging
import re
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from util.token_tracker import TokenTracker

from util.db_helpers import query_from_db
from util.model_helpers import call_llm
from util.query_intent import has_explicit_forecast_intent, is_forecast_domain
# from util.common import extract_json
import json_repair


async def fetch_and_process_domains_one(query: str, background_info, industry_str, concepts, token_tracker: Optional["TokenTracker"] = None) -> str:
    """
    从数据库中获取一级域（表分类）信息，并根据查询生成定位提示。

    参数:
    query (str): 用户的查询问题。

    返回:
    str: 生成的定位提示信息。
    """
    # SQL查询语句
    sql_query = """
    SELECT DOMAIN_CNAME, DOMAIN_DESC, DOMAIN_LEVEL1 from MDB_DOMAIN_JULING
    WHERE DOMAIN_DESC IS NOT NULL
    """
    # res = await query_from_db(sql_query)
    background_info = background_info.replace('\n', '')
    industry_str = industry_str.replace('\n', '')
    domain_one_locate_prompt = f"""
# 角色与任务
你是一个身处中国投研机构的数据查询专家，需要将用户问题精确分类到最相关的表分类中。

# 可选表分类
以下是候选表分类及其详细说明：

1. 【个股相关】
   - 涵盖信息：个股特定股票（主要指A股和港股）的基本面分析、财务数据、市场表现、公司新闻、管理层变动、重大事件、技术分析指标等
   - 信息用途：评估个股投资价值，制定买卖决策，进行风险管理

2. 【基金相关】
   - 涵盖信息：公募基金产品、ETF、指数基金等的资产配置、历史业绩、费率结构、基金经理信息、持仓股票等
   - 信息用途：选择和评估基金产品，了解投资策略和风险收益特征，处理机构重仓及持仓问题

3. 【指数相关】
   - 涵盖信息：股票市场指数、债券指数、商品指数等的构成、历史表现、波动性、相关性分析、成分股权重分布等
   - 信息用途：评估市场趋势和板块表现，跟踪和复制指数表现，作为投资基准比较和风险管理工具

4. 【美股相关】
   - 涵盖信息：美股上市公司、个股数据、技术指标、资产负债、综合收益、现金流量、行情数据、板块地域拆分数据等
   - 信息用途：评估公司基本面和市场表现，分析财务健康状况，识别行业趋势和地域风险

# 用户问题
【问题】：{query}

# 分类规则与先验知识
1. "社保基金"不属于"基金相关"，当涉及"社保基金"作为公司股东时，应归类为"个股相关"
2. 涉及"题材"或"板块"的问题，归类为"个股相关"
3. 提及"南向资金"(中国内地到港股)或"北向资金"(香港到A股)，归类为"个股相关"

# 背景信息
{background_info}
【行业信息】{industry_str}，如果涉及A股、港股，请以此为准。
【题材信息】{concepts}

# 分析要求
1. 仔细分析用户问题与各表分类的关联度
2. 考虑问题中可能涉及的隐含表分类
3. 返回类别名称只能是下面之一：个股相关, 基金相关, 指数相关, 美股相关
4. 不要创造新的表分类名称

# 输出格式使用json格式
```json
[
    "类别名称"
]
```
"""

    print(domain_one_locate_prompt)

    # 获取分类结果
    # domain_res = await asyncio.get_event_loop().run_in_executor(None, get_query_by_chat, domain_one_locate_prompt)
    domain_res = await call_llm(prompt=domain_one_locate_prompt, model="gpt-4.1", token_tracker=token_tracker)

    domain_res = json_repair.loads(domain_res) #extract_json(domain_res)
    domain_res = domain_res[0]

    return domain_res



def extract_lists(text):
    # 使用正则表达式匹配所有[XXX]格式的内容
    pattern = r'\[.*?\]'
    matches = re.findall(pattern, text)

    # 检查匹配结果是否为空
    if matches:
        return matches[0]  # 返回第一个匹配项
    else:
        return None  # 如果没有匹配项，返回 None



def get_dbtype_from_domain_one(domain_one: str) -> str:
    """
    判断一级域对应的数据库类型

    参数:
    domain_one (str): 一级域名称。

    返回:
    str: 判断结果。
    """
    if domain_one in ["基金相关", "内部信息查询"]:
        return "MYSQL-1"
    elif domain_one in ["个股相关", "指数相关", "基础码表"]:
        return "MYSQL-2"
    elif domain_one in ["美股相关"]:
        return "MYSQL-4"
    else:
        assert 0, f"{domain_one} 为未定义一级域！！\n"
        return None




async def fetch_and_process_domains(query: str, background_info, domain_one: str, industry_str, concepts, token_tracker: Optional["TokenTracker"] = None) -> str:
    """
    从数据库中获取域（表分类）信息，并根据查询生成定位提示。

    参数:
    query (str): 用户的查询问题。

    返回:
    str: 生成的定位提示信息。
    """
    # SQL查询语句
    sql_query = f"""
    SELECT DOMAIN_CNAME, DOMAIN_DESC, DOMAIN_LEVEL1 from MDB_DOMAIN_JULING
    WHERE DOMAIN_LEVEL1 = '{domain_one}' AND DOMAIN_DESC IS NOT NULL
    """

    # 从数据库中获取数据
    res = await query_from_db(sql_query)

    # # 过滤标签
    # labels = ','.join([item[0] for item in res if item[0] != '基金持仓'])
    # 提取标签列表（排除 '基金持仓'）
    labels = [item[0] for item in res if item[0] != '基金持仓']
    labels_str = ','.join(labels)

    # 初始化定义字符串
    define_str = ""

    # 处理每一行数据
    for line in res:
        if line[0] not in ('A股', '港股', '基金持仓'):
            content = line[1].replace('\n', '').replace('\r', '')
            define_str += f"【{line[0]}】: {content}\n"

    domain_cls_str = await fetch_classification_knowledge('DOMAIN_CLS', domain_one)
    background_info = background_info.replace('\n', '')
    industry_str = industry_str.replace('\n', '')
    # 生成定位提示信息
    domain_locate_prompt = f"""
# 角色和目标
你是一个身处中国投研机构的数据查询专家，需要将用户问题精确匹配到最相关的表分类中。

# 指令说明
根据用户问题和表分类信息，识别问题可能涉及的所有相关表分类。

## 可选表分类
[{labels_str}]

## 表分类详细说明
{define_str}

# 用户问题
【问题】：{query}

# 推理步骤
1. 仔细分析用户问题的核心意图和涉及的数据维度
2. 对照每个表分类的定义，判断关联度
3. 考虑问题可能需要多个表分类的数据进行综合分析
4. 验证选择的分类是否都在候选列表中

# 分类约束条件
{domain_cls_str}

# 背景信息
{background_info}

【行业信息】{industry_str}，请以此来区分：A股主板、科创板、港股
【题材信息】{concepts}

# 输出格式
**必须严格按照以下JSON格式输出，不要添加任何其他内容：**

```json
[
    "表分类名称1",
    "表分类名称2"
]
```

# 重要约束
- 只能从候选表分类列表中选择：[{labels_str}]
- 不要创造或编造新的表分类名称
- 如果问题涉及多个维度，可以选择多个相关分类
- 输出必须是有效的JSON数组格式

## 最终指令
请仔细分析问题与各表分类的关联性，严格按照JSON格式返回相关的表分类列表。
    """

    print(domain_locate_prompt)

    # 获取分类结果
    # domain_res = await asyncio.get_event_loop().run_in_executor(None, get_query_by_chat, domain_locate_prompt)
    domain_res = await call_llm(prompt=domain_locate_prompt, model="gpt-4.1", token_tracker=token_tracker)

    # 使用 json_repair 解析 JSON 响应
    try:
        domain_res_cross_valid = json_repair.loads(domain_res)
        if not isinstance(domain_res_cross_valid, list):
            raise ValueError("解析后的 domain_res 不是一个列表。")
    except (ValueError, SyntaxError) as e:
        logging.error(f"无法解析 domain_res JSON 为列表: {domain_res}", exc_info=True)
        raise ValueError(f"无法解析 domain_res JSON 为列表: {domain_res}") from e

    # 验证 domain_res 中的每个值是否在 labels 中
    labels_set = set(labels)  # 使用集合提高查找效率
    invalid_labels = [item for item in domain_res_cross_valid if item not in labels_set]
    #过滤正确的域定位
    valid_labels = [item for item in domain_res_cross_valid if item in labels_set]
    if not has_explicit_forecast_intent(query):
        forecast_labels = [item for item in valid_labels if is_forecast_domain(item)]
        valid_labels = [item for item in valid_labels if not is_forecast_domain(item)]
        for forecast_label in forecast_labels:
            financial_label = forecast_label.replace("业绩预告", "财务")
            if financial_label in labels_set and financial_label not in valid_labels:
                valid_labels.append(financial_label)
        if forecast_labels:
            logging.info(
                "问题未包含明确预测意图，已将预测二级域替换为正式财务域: %s -> %s",
                forecast_labels,
                valid_labels,
            )
    valid_labels_str = str(valid_labels)
    # if invalid_labels:
    #     raise ValueError(f"模型产生了幻觉，以下分类不在预期的 labels 中: {invalid_labels}")
    # 如果有无效标签，记录警告信息
    if invalid_labels:
        logging.warning(f"模型产生了幻觉，以下分类不在预期的 labels 中: {invalid_labels}")

    # 检查 domain_res 是否为空
    if not valid_labels:
        logging.error("模型未找到任何有效二级域。")
        return ""

    return valid_labels_str
async def fetch_classification_knowledge(cls_type, domain_one_for_table_cls: str = "") -> str:
    """
    获取域定义、表定义的相关先验信息。

    参数:
    domain_one_for_table_cls(str): 表分类所需的一级域信息

    返回:
    str: 一般知识信息。
    """
    sql_query = ""
    if cls_type == "TABEL_CLS":
        sql_query = f"""
        SELECT KNOW_TYPE, KNOW_ID, KNOW_DESC FROM MDB_EXPERT_KNOWLEDGE_JULING
        WHERE KNOW_TYPE = "{cls_type}" AND OBJECT_CNAME = '{domain_one_for_table_cls}'
        """
    else:
        sql_query = f"""
        SELECT KNOW_TYPE, KNOW_ID, KNOW_DESC FROM MDB_EXPERT_KNOWLEDGE_JULING
        WHERE KNOW_TYPE = "{cls_type}" AND OBJECT_CNAME = '{domain_one_for_table_cls}'
        """
    general_info = await query_from_db(sql_query)
    general_text = ""
    for idx, item in enumerate(general_info):
        general_text += f"{idx + 1}.{item[2]}\n"
    return general_text
