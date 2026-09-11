import asyncio
from typing import List, Tuple, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from util.token_tracker import TokenTracker

from util.model_helpers import get_query_by_chat,call_llm
import re
from sql_metadata import Parser


async def get_explanation_info(final_sql: str, query: str,
                               final_define: List[Tuple[str, str, str, str, str, str]],
                               filtered_table_define: List[Tuple[str, str, str]],
                               token_tracker: Optional["TokenTracker"] = None) -> str:
    """
    逐步解释SQL查询的逻辑，并融合字段和表的描述信息以提高解释准确性。

    参数:
    final_sql (str): 最终的SQL查询语句。
    query (str): 查询设计的自然语言描述。
    final_define (List[Tuple]): 字段定义信息，格式如：
        [('STK_COM_PROFILE', 'ISVALID', '是否有效，1表示有效', 'INT', None, '需要在表后面加ISVALID =1 的条件'), ...]
    filtered_table_define (List[Tuple]): 表定义信息，格式如：
        [('STK_COM_PROFILE', '上市公司基本信息表', '上市公司基本信息表（STK_COM_PROFILE）记录了上市公司的最新基本信息，...'), ...]

    返回:
    str: 由大模型生成的SQL解释信息。
    """

    # # Helper function to extract table names from SQL
    # def extract_tables(sql: str) -> List[str]:
    #     # 使用正则表达式提取FROM和JOIN后的表名
    #     tables = re.findall(r'FROM\s+([`"\w]+)|JOIN\s+([`"\w]+)', sql, re.IGNORECASE)
    #     # Flatten the list of tuples and remove None
    #     tables = [table for pair in tables for table in pair if table]
    #     # Remove surrounding quotes or backticks if any
    #     tables = [re.sub(r'[`"\s]', '', table) for table in tables]
    #     return list(set(tables))  # 去重
    #
    # # Helper function to extract field names from SQL
    #
    # def extract_fields_with_sql_metadata(sql: str) -> List[str]:
    #     parser = Parser(sql)
    #     fields = parser.columns
    #     return fields
    #
    # def extract_fields_without_table_prefix(sql: str) -> List[str]:
    #     parser = Parser(sql)
    #     columns = parser.columns  # columns 例如 ['STK_PRI_INCOME_DISTRICT.PeriodDate', 'GET_A_SEC_CODE.SEC_SNAME', ...]
    #     # 去除表名前缀，保留字段名
    #     fields = [col.split('.')[-1] for col in columns]
    #
    #     # 去重和排序是可选的，根据需求决定
    #     unique_fields = list(set(fields))
    #     unique_fields.sort()
    #     return unique_fields
    #
    # # 提取SQL中的表和字段
    # tables_in_sql = extract_tables(final_sql)
    # fields_in_sql = extract_fields_without_table_prefix(final_sql)

    # 创建表描述字典
    # table_desc_dict = {table: desc for table, _, desc in filtered_table_define}
    # 创建表描述字典
    table_desc_dict = {}
    for item in filtered_table_define:
        table = item[0]
        desc = item[2]  # 假设第三个元素是描述信息
        table_desc_dict[table] = desc

    # 创建字段描述字典
    field_desc_dict = {}
    for table, field, desc, dtype, _, additional, *rest in final_define:
        field_desc_dict[(table, field)] = {
            'table': table,
            'field': field,
            'description': desc,
            'data_type': dtype,
            'additional': additional
        }

    # 转换final_sql为小写，便于大小写不敏感匹配
    final_sql_lower = final_sql.lower()

    # 从final_sql中匹配使用到的表
    tables_in_sql = []
    for table in table_desc_dict.keys():
        if table.lower() in final_sql_lower:
            tables_in_sql.append(table)

    # 从final_sql中匹配使用到的字段
    fields_in_sql = []
    for (table, field) in field_desc_dict.keys():
        if field.lower() in final_sql_lower:
            fields_in_sql.append((table, field))

    # 去除重复的表和字段名
    tables_in_sql = list(set(tables_in_sql))
    fields_in_sql = list(set(fields_in_sql))

    # 准备表描述信息
    table_descriptions = ""
    for table in tables_in_sql:
        desc = table_desc_dict.get(table, "无描述信息。")
        table_descriptions += f"**表 `{table}` 描述**:\n{desc}\n\n"

    # 准备字段描述信息
    field_descriptions = ""
    for table, field in fields_in_sql:
        field_info = field_desc_dict.get((table, field), {})
        description = field_info.get('description', "无描述信息。")
        data_type = field_info.get('data_type', "未知类型")
        additional = field_info.get('additional', "")
        field_descriptions += f"- **字段 `{field}`** ({data_type}，所属表 `{table}`): {description}"
        if additional:
            field_descriptions += f"\n  - 备注: {additional}"
        field_descriptions += "\n"

    # 构建最终的提示
    explain_prompt = f"""
# 角色
你是一名网络安全工程师，擅长以简洁明了的方式解释SQL查询的逻辑和计算过程。

## 技能
### 技能1: 解释计算过程（注意解释中不要出现此标题，直接给阐述即可）\n
- 使用公式或自然语言解释关键计算过程。例如：
  - 分红率的计算公式：`平均分红率 = 总分红 / 总股数`
  - 市净率的计算公式：`市净率 = 每股市价 / 每股净资产`
- 不要泄露表字段名，如果直接取值，不需要解释逻辑。
- 如果sql里没有对结果进行计算，请再解释计算过程后加上一句"在此查询中，我们直接使用了已有的财务指标数据。"；注意！！！比如在SELECT中写出类似这样的都算对结果进行了计算：ROUND(s.HOLD_NUM / 100000000, 2) AS 持股数量(亿股),ROUND(s.HOLD_PCT, 2) AS 持股比例(%)
- 评估查询结果是否满足了query的要求，如果满足则在解释计算过程后加上一句"查询结果符合要求"，不满足则要解释原因；

### 技能2: 解释SQL查询逻辑（注意解释中不要出现此标题，直接给阐述即可）\n
- 简单描述查询了哪些信息（请用表的中文描述回答！！！示例：比如STK_COM_PROFILE表你要说成是提供公司基本信息的表、STK_PRI_INCOME_DISTRICT表你要说成是用于存储公司主营业务收入按地区分布的数据的表，千万不要说表名，只说这是个什么作用的表！！！）、用了什么筛选和过滤或者排序方式、子查询不需要解释！！！
- 不要泄露表字段名。请用别名或者表字段描述回答
- 确保回答简明扼要。

## 限制
- 回答内容必须清晰易懂，避免使用专业术语。
- 不讨论与SQL查询无关的内容。
- 请以纯文本形式提供答案，不使用 LaTeX 公式排版或 Markdown 语法。所有计算公式也请以普通文本方式呈现。
- 回答里不要泄露表字段名
- 不要在回答里出现任何sql语句!!!不要在回答里出现任何sql语句!!!不要在回答里出现任何sql语句!!!

## 示例1
【query】恒瑞医药在欧洲市场的销售份额是多少？
【sql】
 SELECT 
    p.CName AS `公司名称`, 
    p.COMCODE AS `公司代码`, 
    d.PeriodDate AS `报告日期`, 
    d.ITEM_NAME AS `地区名称`, 
    d.INCOME AS `主营业务收入(万元)`, 
    d.PRI_RVNU_PCT AS `占营业收入比重(%)`
FROM 
    STK_COM_PROFILE p
JOIN 
    STK_PRI_INCOME_DISTRICT d 
ON 
    p.COMCODE = d.COMCODE
WHERE 
    p.CSName LIKE '%恒瑞医药%' 
    AND d.RPT_TYPE = '合并' 
    AND d.PeriodDate = '2023-12-31' 
    AND p.ISVALID = 1 
    AND d.ISVALID = 1;

- 该查询的主要目的是获取恒瑞医药在特定地区（如欧洲市场）的主营业务收入及其占营，在此查询中，我们直接使用了已有的财务指标数据。查询结果满足要求。

- 查询从两个表中提取数据，通过公司代码字段进行连接。提供公司基本信息的表，提供地区收入分布信息的表。
- 查询选择了公司名称、公司代码、报告日期、地区名称、主营业务收入和占营业收入比重等字段。 
- 通过模糊查询筛选公司简称中包含“恒瑞医药”的记录。 - 仅选择报表类型为“合并”的记录。 - 仅选择报告日期为“2023-12-31”的记录。 - 通过判断是否有效的字段确保选择的记录是有效的。 
- 查询返回符合条件的恒瑞医药在各地区的收入数据，特别关注欧洲市场的销售份额。

## 示例2
【query】A股化工行业连续两年研发资本化率超过50%的公司有哪些
【sql】
 SELECT DISTINCT
    a.SEC_SNAME AS `股票名称`,
    a.SEC_CODE AS `股票代码`,
    c.CSName AS `公司简称`,
    c.OFFICE_ADDR AS `公司办公地址`
FROM
    GET_A_INDUSTRY a
LEFT JOIN
    STK_COM_PROFILE c ON a.COMCODE = c.COMCODE
WHERE
    a.SW_INDU_CODE_2021_1 LIKE '%化工%'
    AND c.ISVALID = 1
ORDER BY
    a.SEC_SNAME

- 该查询的主要目的是获取恒瑞医药在特定地区（如欧洲市场）的主营业务收入及其占营，在此查询中，我们直接使用了已有的财务指标数据。查询结果不符合要求，sql里没有关于20%、两年这些限定条件。

- 查询从两个表中提取数据，通过公司代码字段进行连接。一个表用于汇总记录A股行业信息，另一个表提供上市公司的基本信息。
- 查询选择了股票名称、股票代码、公司简称和公司办公地址等字段。
- 通过筛选申万一级行业名称中包含“化工”的记录，确保只选择化工行业的公司。
- 通过判断是否有效的字段确保选择的记录是有效的。
- 结果按股票名称进行排序。
- 查询返回符合条件的A股化工行业公司信息。

## 错误示例，这里的解释出现了计算过程标题，请不要在回答中出现计算过程、SQL查询逻辑标题，并且下面的解释出现了分级（**计算过程**、**过滤条件**等），请注意所有的解释都是平级的，不要分级!!!
【query】外销业务销售额上升50%以上的公司有哪些
【sql】
SELECT
  s.SEC_SNAME AS `股票名称`,
  s.SEC_CODE AS `股票代码`,
  d.PeriodDate AS `对应时间段`,
  ROUND(d.INCOME / 10000, 3) AS `主营业务收入(亿)`,
  ROUND(d.INCOME_CHNG, 2) AS `主营收入比上年增减比例(%)`
FROM STK_PRI_INCOME_DISTRICT d
JOIN GET_A_SEC_CODE s ON d.COMCODE = s.COMCODE
WHERE
  s.ISVALID = 1
  AND d.ISVALID = 1
  AND d.RPT_TYPE = '合并'
  AND d.PeriodDate = '2024-06-30'
  AND d.ITEM_NAME = '外销'
  AND d.INCOME IS NOT NULL
  AND d.INCOME_CHNG IS NOT NULL
  AND d.INCOME_CHNG > 50
ORDER BY d.INCOME_CHNG DESC

- 该查询的主要目的是获取外销业务销售额同比增长超过50%的公司信息。在此查询中，计算了主营业务收入的单位转换（从万元转换为亿元）和主营收入同比增减比例的保留两位小数的结果。

- **计算过程**：
  - 主营业务收入（亿）通过公式 `主营业务收入(亿) = 主营业务收入(万元) / 10000` 计算得出。
  - 主营收入比上年增减比例（%）直接取值，并保留两位小数。
  - 查询结果符合要求。

- **表连接**：
  - 查询从两个表中提取数据，通过公司代码字段进行连接。一个表用于记录A股证券的基础信息，另一个表用于展示公司在不同地区的主营业务收入分布情况。

- **选择字段**：
  - 查询选择了股票名称、股票代码、对应时间段、主营业务收入（亿）和主营收入比上年增减比例（%）等字段。

- **过滤条件**：
  - 仅选择证券信息和地区收入分布信息均有效的记录。
  - 仅选择报表类型为“合并”的记录。
  - 仅选择报告日期为“2024-06-30”的记录。
  - 仅选择地区名称为“外销”的记录。
  - 排除主营业务收入和同比增减比例为空的记录。
  - 筛选主营收入同比增减比例大于50%的记录。

- **排序方式**：
  - 按主营收入同比增减比例降序排列。

- **结果**：
  - 查询返回符合条件的外销业务销售额同比增长超过50%的公司信息。

到此为止示例结束！接下来请根据下面的信息执行任务
## 表描述信息
    {table_descriptions}
## 字段描述信息
    {field_descriptions}
## 【查询设计的Query】：
    {query}
## 【查询的sql语句】：
    {final_sql}

    """

    # 获取大模型的回答
    return_res = await call_llm(prompt=explain_prompt, model="gpt-4.1", token_tracker=token_tracker)

    return return_res, explain_prompt




async def get_EDBexplanation_info(final_sql: str, query: str, R1_prompt:str, token_tracker: Optional["TokenTracker"] = None):
    """
    逐步解释SQL查询的逻辑，并融合字段和表的描述信息以提高解释准确性。

    参数:
    final_sql (str): 最终的SQL查询语句。
    query (str): 查询设计的自然语言描述。
    final_define (List[Tuple]): 字段定义信息，格式如：
        [('STK_COM_PROFILE', 'ISVALID', '是否有效，1表示有效', 'INT', None, '需要在表后面加ISVALID =1 的条件'), ...]
    filtered_table_define (List[Tuple]): 表定义信息，格式如：
        [('STK_COM_PROFILE', '上市公司基本信息表', '上市公司基本信息表（STK_COM_PROFILE）记录了上市公司的最新基本信息，...'), ...]

    返回:
    str: 由大模型生成的SQL解释信息。
    """



    # 构建最终的提示
    explain_prompt = f"""
# 角色
你是一名网络安全工程师，擅长以简洁明了的方式解释SQL查询的逻辑和计算过程。

## 技能
### 技能1: 解释计算过程（注意解释中不要出现此标题，直接给阐述即可）\n
- 使用公式或自然语言解释关键计算过程。例如：
  - 分红率的计算公式：`平均分红率 = 总分红 / 总股数`
  - 市净率的计算公式：`市净率 = 每股市价 / 每股净资产`
- 不要泄露表字段名和别名，如果直接取值，不需要解释逻辑。
- 如果sql里没有对结果进行计算，请再解释计算过程后加上一句"在此查询中，我们直接使用了已有的财务指标数据。"；注意！！！比如在SELECT中写出类似这样的都算对结果进行了计算：ROUND(s.HOLD_NUM / 100000000, 2) AS 持股数量(亿股),ROUND(s.HOLD_PCT, 2) AS 持股比例(%)
- 评估查询结果是否满足了query的要求，如果满足则在解释计算过程后加上一句"查询结果符合要求"，不满足则要解释原因；

### 技能2: 解释SQL查询逻辑（注意解释中不要出现此标题，直接给阐述即可）\n
- 简单描述查询了哪些信息（请用表的中文描述回答！！！示例：比如STK_COM_PROFILE表你要说成是提供公司基本信息的表、STK_PRI_INCOME_DISTRICT表你要说成是用于存储公司主营业务收入按地区分布的数据的表，千万不要说表名，只说这是个什么作用的表！！！）、用了什么筛选和过滤或者排序方式、子查询不需要解释！！！
- 不要泄露表字段名。请用别名或者表字段描述回答
- 确保回答简明扼要。
- 如果收到的sql是类似这样的，则表明系统中无可用数据，请返回查询结果符合要求：SELECT '无可用数据' AS "提示" FROM DUAL

## 限制
- 回答内容必须清晰易懂，避免使用专业术语。
- 不讨论与SQL查询无关的内容。
- 请以纯文本形式提供答案，不使用 LaTeX 公式排版或 Markdown 语法。所有计算公式也请以普通文本方式呈现。
- 回答里不要泄露表字段名
- 不要在回答里出现任何sql语句!!!不要在回答里出现任何sql语句!!!不要在回答里出现任何sql语句!!!

## 示例1
【query】恒瑞医药在欧洲市场的销售份额是多少？
【sql】
 SELECT 
    p.CName AS `公司名称`, 
    p.COMCODE AS `公司代码`, 
    d.PeriodDate AS `报告日期`, 
    d.ITEM_NAME AS `地区名称`, 
    d.INCOME AS `主营业务收入(万元)`, 
    d.PRI_RVNU_PCT AS `占营业收入比重(%)`
FROM 
    STK_COM_PROFILE p
JOIN 
    STK_PRI_INCOME_DISTRICT d 
ON 
    p.COMCODE = d.COMCODE
WHERE 
    p.CSName LIKE '%恒瑞医药%' 
    AND d.RPT_TYPE = '合并' 
    AND d.PeriodDate = '2023-12-31' 
    AND p.ISVALID = 1 
    AND d.ISVALID = 1

- 该查询的主要目的是获取恒瑞医药在特定地区（如欧洲市场）的主营业务收入及其占营，在此查询中，我们直接使用了已有的财务指标数据。查询结果满足要求。

- 查询从两个表中提取数据，通过公司代码字段进行连接。提供公司基本信息的表，提供地区收入分布信息的表。
- 查询选择了公司名称、公司代码、报告日期、地区名称、主营业务收入和占营业收入比重等字段。 
- 通过模糊查询筛选公司简称中包含“恒瑞医药”的记录。 - 仅选择报表类型为“合并”的记录。 - 仅选择报告日期为“2023-12-31”的记录。 - 通过判断是否有效的字段确保选择的记录是有效的。 
- 查询返回符合条件的恒瑞医药在各地区的收入数据，特别关注欧洲市场的销售份额。

## 示例2
【query】A股化工行业连续两年研发资本化率超过50%的公司有哪些
【sql】
 SELECT DISTINCT
    a.SEC_SNAME AS `股票名称`,
    a.SEC_CODE AS `股票代码`,
    c.CSName AS `公司简称`,
    c.OFFICE_ADDR AS `公司办公地址`
FROM
    GET_A_INDUSTRY a
LEFT JOIN
    STK_COM_PROFILE c ON a.COMCODE = c.COMCODE
WHERE
    a.SW_INDU_CODE_2021_1 LIKE '%化工%'
    AND c.ISVALID = 1
ORDER BY
    a.SEC_SNAME

- 该查询的主要目的是获取恒瑞医药在特定地区（如欧洲市场）的主营业务收入及其占营，在此查询中，我们直接使用了已有的财务指标数据。查询结果不符合要求，sql里没有关于20%、两年这些限定条件。

- 查询从两个表中提取数据，通过公司代码字段进行连接。一个表用于汇总记录A股行业信息，另一个表提供上市公司的基本信息。
- 查询选择了股票名称、股票代码、公司简称和公司办公地址等字段。
- 通过筛选申万一级行业名称中包含“化工”的记录，确保只选择化工行业的公司。
- 通过判断是否有效的字段确保选择的记录是有效的。
- 结果按股票名称进行排序。
- 查询返回符合条件的A股化工行业公司信息。

## 错误示例，这里的解释出现了计算过程标题，请不要在回答中出现计算过程、SQL查询逻辑标题，并且下面的解释出现了分级（**计算过程**、**过滤条件**等），请注意所有的解释都是平级的，不要分级!!!
【query】外销业务销售额上升50%以上的公司有哪些
【sql】
SELECT
  s.SEC_SNAME AS `股票名称`,
  s.SEC_CODE AS `股票代码`,
  d.PeriodDate AS `对应时间段`,
  ROUND(d.INCOME / 10000, 3) AS `主营业务收入(亿)`,
  ROUND(d.INCOME_CHNG, 2) AS `主营收入比上年增减比例(%)`
FROM STK_PRI_INCOME_DISTRICT d
JOIN GET_A_SEC_CODE s ON d.COMCODE = s.COMCODE
WHERE
  s.ISVALID = 1
  AND d.ISVALID = 1
  AND d.RPT_TYPE = '合并'
  AND d.PeriodDate = '2024-06-30'
  AND d.ITEM_NAME = '外销'
  AND d.INCOME IS NOT NULL
  AND d.INCOME_CHNG IS NOT NULL
  AND d.INCOME_CHNG > 50
ORDER BY d.INCOME_CHNG DESC

- 该查询的主要目的是获取外销业务销售额同比增长超过50%的公司信息。在此查询中，计算了主营业务收入的单位转换（从万元转换为亿元）和主营收入同比增减比例的保留两位小数的结果。

- **计算过程**：
  - 主营业务收入（亿）通过公式 `主营业务收入(亿) = 主营业务收入(万元) / 10000` 计算得出。
  - 主营收入比上年增减比例（%）直接取值，并保留两位小数。
  - 查询结果符合要求。

- **表连接**：
  - 查询从两个表中提取数据，通过公司代码字段进行连接。一个表用于记录A股证券的基础信息，另一个表用于展示公司在不同地区的主营业务收入分布情况。

- **选择字段**：
  - 查询选择了股票名称、股票代码、对应时间段、主营业务收入（亿）和主营收入比上年增减比例（%）等字段。

- **过滤条件**：
  - 仅选择证券信息和地区收入分布信息均有效的记录。
  - 仅选择报表类型为“合并”的记录。
  - 仅选择报告日期为“2024-06-30”的记录。
  - 仅选择地区名称为“外销”的记录。
  - 排除主营业务收入和同比增减比例为空的记录。
  - 筛选主营收入同比增减比例大于50%的记录。

- **排序方式**：
  - 按主营收入同比增减比例降序排列。

- **结果**：
  - 查询返回符合条件的外销业务销售额同比增长超过50%的公司信息。

到此为止示例结束！接下来请根据下面的信息执行任务

## 【查询设计的Query】：
    {query}
## 【查询的sql语句】：
    {final_sql}

    """

    # 获取大模型的回答
    return_res = await call_llm(prompt=explain_prompt, model="gpt-4.1", token_tracker=token_tracker)

    return return_res, explain_prompt

