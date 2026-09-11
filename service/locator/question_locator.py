import asyncio
import os
import time
import re, ast, logging, textwrap
import json
import json_repair
import pandas as pd
import logging
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from util.token_tracker import TokenTracker

from util.model_helpers import get_query_by_chat,call_llm

from util.rag_helpers import get_bgeM3embeddings
from service.locator.embedding_locator import find_similar_items


def convert_industry_input(input_data):
    """
    Convert the input industry data to a specific string format.

    :param input_data: String representing list of tuples or "无"
    :return: Formatted string
    """
    if input_data == '无' or "\'无\'" in input_data or "\"无\"" in input_data:
        return ""

    # Convert string to list of tuples
    # industry_list = ast.literal_eval(input_data)
    try:
        # Convert string to list of tuples
        industry_list = ast.literal_eval(input_data)
    except (SyntaxError, ValueError) as e:
        # 如果解析失败，记录日志并返回空字符串
        print(f"解析 input_data 失败: {e},input_data为: {input_data}")
        return ""

    # Define industry levels in order of priority
    industry_priority = {
        '申万三级行业': 'SW_INDU_CODE_2021_3',
        '申万二级行业': 'SW_INDU_CODE_2021_2',
        '申万一级行业': 'SW_INDU_CODE_2021_1'
    }

    # Sort the input based on priority
    sorted_input = sorted(industry_list, key=lambda x: list(industry_priority.keys()).index(x[0]))

    # Generate a result for each industry
    results = []
    for industry in sorted_input:
        level_name = industry_priority[industry[0]]
        industry_level = industry[0].replace('申万', '')
        industry_name = industry[1].replace("Ⅲ", "").replace("Ⅱ", "")
        result = f"该问题可能涉及到申万{industry_level}，{industry_level}名称为\"{industry_name}\"，即{level_name} LIKE \"%{industry_name}%\",注意，如果用户询问的是行业相关问题，则优先使用此字段。使用SW_INDU_CODE_2021_1字段时必须使用我指定的匹配值，即 \"%{industry_name}%\""
        results.append(result)

    # Join all results into a single string
    return "\n".join(results)


async def fetch_and_process_industries(query: str, csv_file: str, res_str: str, token_tracker: Optional["TokenTracker"] = None) -> str:
    """
    从CSV文件中读取行业数据，并生成行业判断提示。

    参数:
    query (str): 用户的查询问题。
    csv_file (str): 包含行业数据的CSV文件路径。

    返回:
    str: 生成的行业判断提示信息。
    """
    # 从CSV文件中读取数据
    df = pd.read_csv(csv_file)

    # 获取一级、二级、三级行业名称的唯一值
    first = list(df['一级行业名称'].dropna().unique())
    # second = list(df['二级行业名称'].dropna().unique())
    # third = list(df['三级行业名称'].dropna().unique())
    second = find_similar_items(query=query,embeddings_type="二级行业")
    third = find_similar_items(query=query,embeddings_type="三级行业")

    # 过滤掉一级行业中的'综合'
    first = [item for item in first if item != '综合']

    # 转换为逗号分隔的字符串
    first_str = ','.join(first)
    second_str = ','.join(second)
    third_str = ','.join(third)

    # 赛道映射
    industry_mapping = {
        "周期": [
            "钢铁",
            "基础化工",
            "建筑材料",
            "建筑装饰",
            "交通运输",
            "煤炭",
            "石油石化",
            "有色金属"
        ],
        "制造": [
            "电力设备",
            "公用事业",
            "国防军工",
            "环保",
            "机械设备",
            "汽车"
        ],
        "消费": [
            "纺织服饰",
            "家用电器",
            "美容护理",
            "农林牧渔",
            "轻工制造",
            "商贸零售",
            "社会服务",
            "食品饮料"
        ],
        "金融地产": [
            "房地产",
            "非银金融",
            "银行"
        ],
        "科技": [
            "传媒",
            "电子",
            "计算机",
            "通信"
        ],
        "医药": [
            "医药生物"
        ],
        "总量": [
            "宏观",
            "固收",
            "策略",
            "金融工程"
        ]
    }

    # 生成行业判断提示信息
    industry_define_prompt = f"""

    请根据【条件】以及【行业字典】判断【问题】是否涉及行业及可能所属的行业：

    【问题】"{query}？"

    【条件】

    1. 请判断【问题】是否包含特定行业,如果不涉及行业请直接输出"无"；
    2. 如果【问题】中明确行业所属级别（一级、二级、三级），则优先查找该级别；
    3. 如果没有说明，请找到最匹配的行业，并且一级行业优先，如果没有最相关的则二级优先，以此类推。
    4. 请特别注意，我们分析的对象不是这个问题本身，而是其中可能包含的行业实体！！！！

    【行业字典】

    申万一级行业：{first_str}
    申万二级行业：{second_str}
    申万三级行业：{third_str}

    请特别注意：抽取出的行业必须来源于【行业字典】！！！抽取出的行业必须来源于【行业字典】！！！请不要捏造！！！
    如果用户提到了 "申万XXX行业"，如果该行业不在字典中，请务必从【行业字典】中找出最匹配的行业，如果没有最匹配的则直接输出"无"。
    请直接输出答案，如果不涉及行业请直接输出"无"。如果涉及，请按照如下格式输出：[('申万X级行业'， '行业名'), ...]
    
    
    请特别注意，query中的行业有时可能不在申万行业中，他们的映射关系如下：
    {json.dumps(industry_mapping, ensure_ascii=False)}
    如果命中映射请把对应的申万一级行业全都输出出来!!
    
    请注意！如果是美股相关信息则只抽取申万一级！！！
    该问题为：{res_str}


    """

    # 获取行业结果
    # industry_res = await asyncio.get_event_loop().run_in_executor(None, get_query_by_chat, industry_define_prompt)
    industry_res = await call_llm(prompt=industry_define_prompt, model="gpt-4.1", token_tracker=token_tracker)

    print("TUTU", industry_res)

    # 将结果转换为适当的格式
    industry_str = convert_industry_input(industry_res)

    return industry_str


from typing import List

def chunk_list(lst: List[str], chunk_size: int) -> List[List[str]]:
    """将列表 lst 按照 chunk_size 切分，返回一个二维列表。"""
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]

async def fetch_and_process_concepts(query: str, token_tracker: Optional["TokenTracker"] = None) -> str:
    """
    从CSV文件中读取题材概念数据，并根据 query 进行匹配判断。
    最终返回可能所属的题材信息或空字符串。
    """
    concept_list = find_similar_items(query=query,embeddings_type="概念")
    
    # 将所有概念组合成一个字符串
    concepts_str = ", ".join(concept_list)

    industry_define_prompt = f"""
        请根据【条件】以及【题材板块字典】判断【问题】是否涉及题材板块字典及可能所属的金融题材概念：

        【问题】"{query}？"

        【条件】
        1. 请判断【问题】是否涵盖题材，如果不涉及题材请直接输出"无"；
        2. 如果没有明确说明，请找到最匹配的题材板块字典。请注意，只需找到一个最匹配的题材板块字典。如果不涉及请输出"无"。
        3. 请特别注意，我们分析的对象不是这个问题本身，而是其中可能包含的题材板块字典的（concept或topic）实体！

        【题材板块字典】
        {concepts_str}

        请直接输出答案，如果不涉及题材请直接输出"无"。如果涉及，请按照如下格式输出：['题材板块名1', '题材板块名2', ...]
        """

    # 调用LLM获取结果
    res = await call_llm(prompt=industry_define_prompt, model="gpt-4.1", token_tracker=token_tracker)

    # 处理返回结果
    res_str = res.strip()
    if not res_str or res_str == "无":
        return ""

    # 解析结果并验证
    try:
        topics = ast.literal_eval(res_str)
        validated_topics_set = set()

        if isinstance(topics, list):
            for t in topics:
                if isinstance(t, str) and t.strip() in concept_list:
                    validated_topics_set.add(t.strip())
        elif isinstance(topics, str) and topics.strip() in concept_list:
            validated_topics_set.add(topics.strip())

        if not validated_topics_set:
            return ""

        # 生成结果字符串
        topics_list = sorted(list(validated_topics_set))
        topics_str_for_display = "[" + ", ".join(f"'{t}'" for t in topics_list) + "]"

        # 构造 SQL 查询条件
        if len(topics_list) == 1:
            in_clause = f"CONCEPT_NAME = '{topics_list[0]}'"
        else:
            in_clause = "CONCEPT_NAME IN (" + ", ".join(f"'{t}'" for t in topics_list) + ")"

        # 生成最终的提示信息
        result_str = (
            f"该问题可能涉及的题材包含：{topics_str_for_display}。\n"
            f"请在定位的时候优先考虑 VW_CONCEPT_STK 表，即在 SQL 中加入条件：{in_clause}。"
        )

        return result_str

    except (ValueError, SyntaxError) as e:
        logging.error(f'解析失败：res_str = {res_str}')
        return ""

def convert_track_input(input_data):
    """
    Convert the input industry data to a specific string format.

    :param input_data: String representing list of tuples or "无"
    :return: Formatted string
    """
    # 如果输入是"无"或包含"无"，直接返回空字符串
    if input_data == '无' or "\'无\'" in input_data or "\"无\"" in input_data:
        return ""

    # 将字符串转换为列表
    try:
        industry_list = ast.literal_eval(input_data)
    except (ValueError, SyntaxError):
        return ""

    # 定义行业级别的优先级
    industry_priority = {
        '申万三级行业': 'SW_INDU_CODE_2021_3',
        '申万二级行业': 'SW_INDU_CODE_2021_2',
        '申万一级行业': 'SW_INDU_CODE_2021_1'
    }

    # 生成结果
    results = []
    for item in industry_list:
        # 检查元组长度并相应处理
        if len(item) == 3:
            track_name, industry_level, industry_name = item  # 解包三元组
            if industry_level in industry_priority:
                level_code = industry_priority[industry_level]
                industry_level_short = industry_level.replace('申万', '')
                industry_name_clean = industry_name.replace("Ⅲ", "").replace("Ⅱ", "")
                # 加入赛道名信息
                result = f"该问题可能涉及到赛道\"{track_name}\"!!!，关联到{industry_level}，{industry_level_short}名称为\"{industry_name_clean}\"，sql可以使用{level_code} LIKE \"%{industry_name_clean}%\""
                results.append(result)
        elif len(item) == 2:
            # 处理两元组情况，假设是(赛道名, 行业名)
            track_name, industry_name = item
            # 由于没有明确的行业级别，默认使用一级行业
            industry_level = '申万一级行业'
            level_code = industry_priority[industry_level]
            industry_level_short = industry_level.replace('申万', '')
            industry_name_clean = industry_name.replace("Ⅲ", "").replace("Ⅱ", "")
            result = f"该问题可能涉及到赛道\"{track_name}\"!!!，关联到{industry_level}，{industry_level_short}名称为\"{industry_name_clean}\"，sql可以使用{level_code} LIKE \"%{industry_name_clean}%\""
            results.append(result)
        else:
            # 处理其他情况
            logging.warning(f"无法处理的元组格式: {item}")
            continue

    # 将结果拼接为单个字符串
    return "\n".join(results)


async def fetch_and_process_track(query: str, token_tracker: Optional["TokenTracker"] = None) -> str:
    """
    从CSV文件中读取行业数据，并生成行业判断提示。

    参数:
    query (str): 用户的查询问题。
    csv_file (str): 包含行业数据的CSV文件路径。

    返回:
    str: 生成的行业判断提示信息。
    """

    # 赛道映射
    industry_mapping = {
        "周期": [
            "钢铁",
            "基础化工",
            "建筑材料",
            "建筑装饰",
            "交通运输",
            "煤炭",
            "石油石化",
            "有色金属"
        ],
        "制造": [
            "电力设备",
            "公用事业",
            "国防军工",
            "环保",
            "机械设备",
            "汽车"
        ],
        "消费": [
            "纺织服饰",
            "家用电器",
            "美容护理",
            "农林牧渔",
            "轻工制造",
            "商贸零售",
            "社会服务",
            "食品饮料"
        ],
        "金融地产": [
            "房地产",
            "非银金融",
            "银行"
        ],
        "科技": [
            "传媒",
            "电子",
            "计算机",
            "通信"
        ],
        "医药": [
            "医药生物"
        ]
    }
    # 生成行业判断提示信息
    industry_define_prompt = f"""

    请根据【条件】以及【赛道映射字典】判断【问题】是否涉及赛道，并输出赛道对应的行业：

    【问题】"{query}？"

    【条件】

    1. 请判断【问题】是否包含特定赛道,如果不涉及请直接输出"无"；如果涉及就请吧对应的行业全都输出出来！！！
    2. 【问题】必须和赛道高度相关，否则请直接输出"无"；
    3. 请特别注意，我们分析的对象不是这个问题本身，而是其中可能包含的赛道实体！！！！

    【赛道字典】格式为dict(key:赛道,value:关联的行业列表)
    {json.dumps(industry_mapping, ensure_ascii=False)}


    请特别注意：
    请直接输出答案，如果不涉及行业请直接输出"无"。如果涉及，请按照如下格式输出：[('赛道名','申万一级行业'， '行业名'), ...]



    """
    # track_res = await asyncio.get_event_loop().run_in_executor(None, get_query_by_chat, industry_define_prompt)
    track_res = await call_llm(prompt=industry_define_prompt, model="gpt-4.1", token_tracker=token_tracker)

    print("TUTU", track_res)

    # 将结果转换为适当的格式
    track_str = convert_track_input(track_res)

    return track_str


async def classify_concepts_track_industry(query: str, concepts: str, track: str, industry_str: str, token_tracker: Optional["TokenTracker"] = None) -> str:
    # 确保输入参数为字符串类型
    if not isinstance(query, str):
        logging.error("参数错误：query 必须是字符串类型")
        return {'concepts': '', 'track': '', 'industry': ''}
    if not isinstance(concepts, str):
        logging.error("参数错误：concepts 必须是字符串类型")
        return {'concepts': '', 'track': '', 'industry': ''}
    if not isinstance(track, str):
        logging.error("参数错误：track 必须是字符串类型")
        return {'concepts': '', 'track': '', 'industry': ''}
    if not isinstance(industry_str, str):
        logging.error("参数错误：industry_str 必须是字符串类型")
        return {'concepts': '', 'track': '', 'industry': ''}

    try:
        prompt = f"""
        # 角色
    你是一个查询分析助手，专门判断查询与特定板块、赛道和行业的相关性。

    ## 技能
    ### 技能 1: 识别相关模块
    - 对于每个查询，独立识别其是否与"板块"、"赛道"或"行业"模块强相关。
    - 输出你认为强相关模块的原文，按照['xx模块','xx模块']这样的格式输出。
    - 如果赛道和行业都被认为强相关，只选择一个最相关的。
    - 最多输出两个模块的原文，如果都不相关则输出"无"。

    ## 限制：
    - 只输出强相关模块的原文，不要有任何其他无关的输出。
    - 确保在识别最相关模块时的清晰和准确。
    - 赛道模块 和 股票及行业模块不能同时被选中，只能在这两个中选择最相关的那个，请优先选中股票模块，如果query中明确出现赛道词，则选择赛道模块。

    ## 查询处理
    - 使用每个查询提供的上下文来进行判断：
        【query】{query}
        【板块模块】{concepts}
        【赛道模块】{track}
        【股票及行业模块】{industry_str}
        """
    except Exception as e:
        logging.error(f"构建提示信息时发生错误：{e}")
        return {'concepts': '', 'track': '', 'industry': ''}

    try:
        # return_res = await asyncio.get_event_loop().run_in_executor(None, get_query_by_chat, prompt)
        return_res = await call_llm(prompt=prompt, model="gpt-4.1", token_tracker=token_tracker)
    except Exception as e:
        logging.error(f"调用 get_query_by_chat 时发生错误：{e}")
        return {'concepts': '', 'track': '', 'industry': ''}

    try:
        # 移除返回结果中的多余字符，解析成列表
        modules = return_res.strip("[]").replace("'", "").replace('"', '').split(',')
        modules = [module.strip() for module in modules]
    except Exception as e:
        logging.error(f"处理返回结果时发生错误：{e}")
        return {'concepts': '', 'track': '', 'industry': ''}

    # 初始化结果字典，用于记录各模块是否通过筛选以及对应的内容
    result = {
        'concepts': '',
        'track': '',
        'industry': ''
    }

    try:
        # 判断各模块是否在返回结果中，并按要求处理
        if '无' in modules:
            return result

        # 根据返回结果更新对应的模块内容
        if '板块模块' in modules:
            result['concepts'] = concepts

        # 处理赛道模块和股票及行业模块，根据要求只选择一个最相关的
        if '赛道模块' in modules and '股票及行业模块' in modules:
            # 如果 query 中明确出现赛道词，则选择赛道模块
            track_words = track.split() if track else []
            if any(track_word in query for track_word in track_words):
                result['track'] = track
            else:
                # 否则选择最相关的模块（根据需要，可以调整选择赛道模块或股票及行业模块）
                result['track'] = track  # 假设优先选择赛道模块
        elif '赛道模块' in modules:
            result['track'] = track
        elif '股票及行业模块' in modules:
            result['industry'] = industry_str
    except Exception as e:
        logging.error(f"处理模块信息时发生错误：{e}")
        return {'concepts': '', 'track': '', 'industry': ''}

    return result

async def get_explanation_info(final_sql, query):
    explain_prompt = f"""
    请帮我逐步解释以下SQL查询的逻辑：
    {final_sql}

    【查询设计的Query】：{query}

    我希望你能够提炼出，这个SQL中最核心的字段的定义，并且请用自然语言解释，这个SQL是如何进行计算获取到结果从而去回答"{query}"问题的。

    示例：

    1. **关键实体或者字段**：
        XXXXXXXX

    2. **可能涉及到的计算过程**：
        XXXXXXXX


    请务必【简洁】地表达如上的结果，不要明确显示出字段名、表名等，只需要能够把逻辑表达清楚。
    请以纯文本形式提供答案，不使用 LaTeX 公式排版或 Markdown 语法。所有计算公式也请以普通文本方式呈现。
    """

    return_res = await asyncio.get_event_loop().run_in_executor(None, get_query_by_chat, explain_prompt)

    return return_res

QUERY_DESC_PROMPT_TMPL ="""
【角色】
你是资深金融数据工程师，精通全球统计局数据库与 Oracle SQL。

【任务】
阅读下方【用户Query】，按顺序输出 **三段内容**：

① 45-55 字中文摘要——必须覆盖  
   · 时间频率 · 地区层级 · 指标类型(总量) · 分析用途

② **参考指标如下:** 开头的清单  
   - **仅**枚举该最高层级下所有地区的总量指标  
   - 若层级=国家 ⇒ 列 “<国名>:GDP:现价(年)”；  
     层级=省   ⇒ 列 “<省名>:地区生产总值:现价(年)”；  
     层级=市   ⇒ 列 “<城市>:地区生产总值:现价(年)”； 
   - 果 Query 涉及 **多种主题指标**，**请将所有主题合并到同一个 Python 字典里**，
     字典键为主题、值为指标列表。最终 **仅输出一个 ```python 代码块**。示例： 
       ```python
        {{
          "参考指标(主题A)": ["…",…","…"],
          "参考指标(主题B)": ["…","…","…","…"]
        }}
        ```
   - 格式：`城市:地区生产总值:当期值:现价(年)`  
   - 在query没有强调的情况下请默认选取直接反映总体规模或水平的指标。
   - 若用户提到“排名/前 N/Top N”，应列出同层级全部主体
   

【示例1】
用户Query：查询全国各城市 GDP 排名前十的城市  
输出示例（节选）  
① …（45-55 字摘要）…  
② 参考指标如下: # 实际使用时应替换为全量主体清单
```python
        {{
          "地区生产总值": ["北京:地区生产总值:GDP:年","上海:地区生产总值:GDP:年","深圳:地区生产总值:GDP:年"],         
        }}
        ```
【示例2】
用户Query：北京天津出生率和出生人数对比
输出示例（节选）  
① …（45-55 字摘要）…  
② 参考指标如下: 
```python
        {{
          "出生率": ["北京:出生率:年","天津:出生率:年"],
          "出生人数": ["北京:出生人数:年","天津:出生人数:年"]
        }}
        ```

【格式要求】  
- 两段之间用换行分隔；禁止额外说明、禁止英文引号  
- 段①不换行、不加序号  
- 若缺少单个城市数据，用“待补充”占位，也要写在清单里

【用户Query】  
{query}


"""

async def get_query_description(query: str, *, model: str = "gpt-4.1", token_tracker: Optional["TokenTracker"] = None) -> str:
    """调用 GPT 生成 ≈50 字的 Query 描述"""
    prompt = QUERY_DESC_PROMPT_TMPL.format(query=query)
    query_desc = await call_llm(prompt=prompt, model=model, token_tracker=token_tracker)
    logging.info(f'query描述如下：{query_desc}')
    query_desc_extract, reference_indicators = parse_expansion_output(query_desc)
    # ❶ 扁平化所有参考指标，保证输入是 list[str]
    flat_refs = [
        ind for lst in reference_indicators.values()  # 每个主题的 value 是 list[str]
        for ind in lst
    ]

    # ❷ 取向量（放到线程池，不阻塞 event-loop）
    ref_embs = await asyncio.to_thread(get_bgeM3embeddings, flat_refs)
    return query_desc, reference_indicators, flat_refs, ref_embs, query_desc_extract
# import asyncio
# import logging
#
# async def get_query_description(query: str, *, model: str = "gpt-4.1") -> tuple:
#     """
#     调用 GPT 生成 ≈50 字的 Query 描述。
#     若 LLM 响应 >15 s，则直接返回空结果。
#     返回:
#         (query_desc, reference_indicators, flat_refs, ref_embs, query_desc_extract)
#     """
#     prompt = QUERY_DESC_PROMPT_TMPL.format(query=query)
#
#     try:
#         # ❶ LLM 调用加 15 s 超时
#         query_desc = await asyncio.wait_for(
#             call_llm(prompt=prompt, model=model),
#             timeout=15
#         )
#     except asyncio.TimeoutError:
#         logging.warning(f"get_query_description 超时 (>15s)，返回空占位值。query={query}")
#         # 全空占位，保持返回签名一致
#         return "", {}, [], [], ""
#
#     logging.info(f"query描述如下：{query_desc}")
#
#     # ❷ 正常解析
#     query_desc_extract, reference_indicators = parse_expansion_output(query_desc)
#
#     # ❸ 扁平化
#     flat_refs = [
#         ind for lst in reference_indicators.values()
#         for ind in lst
#     ]
#
#     # ❹ 取向量（线程池，不阻塞）
#     ref_embs = await asyncio.to_thread(get_bgeM3embeddings, flat_refs)
#
#     return query_desc, reference_indicators, flat_refs, ref_embs, query_desc_extract
#


async def get_query_embedding(query, token_tracker: Optional["TokenTracker"] = None):

    prompt = f"""
    你是一个杰出的数据查询专家，现在请你根据用户的这个query，分析出它可能涉及到（1）哪些关键主体，如果是需要计算的指标，请从金融领域考虑（2）它是如何计算的？请简洁地输出[1]关键金融指标以及[2]可能的计算公式。
    用户的【query】如下{query}？
    """
    kimi_res = await call_llm(prompt=prompt, model="gpt-4.1", token_tracker=token_tracker)
    # combine_res = query + kimi_res
    prompt = f"""
    请从以下【文本】中提取"核心实体"和"计算公式"部分涉及的所有核心关键词以及可能的关键词别名。

    【文本】：" {query}。{kimi_res} "
    
    # 输出格式要求
    请严格按照标准JSON数组格式输出，不要包含任何其他格式或说明文字！
    
    请仅输出一个标准的JSON数组:
    ```json
    ["关键词", "关键词2", ...]
    ```
    """
    gpt_res = await call_llm(prompt=prompt, model="gpt-4.1", token_tracker=token_tracker)

    # 使用json_repair解析JSON格式结果
    try:
        extract_res = json_repair.loads(gpt_res)
        if not isinstance(extract_res, list):
            logging.warning(f"解析结果不是列表格式，使用原始查询: {extract_res}")
            extract_res = [query]
    except Exception as e:
        logging.error(f"JSON解析失败: {e}, 原始响应: {gpt_res}")
        # 如果解析失败，使用原始查询作为关键词
        extract_res = [query]
    
    # 确保列表不为空
    if not extract_res:
        extract_res = [query]

    # query_embedding = text_to_vectors_http_numpy(''.join(extract_res))
    query_embedding = get_bgeM3embeddings([''.join(extract_res)])[0]
    return query_embedding, kimi_res, extract_res

async def get_concept_expansion_and_embedding(query, token_tracker: Optional["TokenTracker"] = None):
    """
    使用给定的「多层次细分 Prompt」对 query 进行分析与拆分；
    然后再调用示例函数 get_query_embedding，对 query 做进一步处理和向量化。
    最终返回多层次细分结果与 query embedding 等信息。
    """

    # 1) 多层次细分的 Prompt
    prompt = f'''
     ========== Role ==========
    你是一个能够多层次细分广义概念的助手。之所以需要你执行这一操作，是因为在用户的 Query 中，常常会出现一些概括性、统称性的词汇（如“白电”“小家电”“汽车产业链”“东南亚各国”等），而数据库中的具体指标名称通常并不会以统称出现，而是以更细分的产品、行业、地区、品类等形式存储。如果直接用统称去做向量召回，往往难以找到匹配度高或涵盖全面的指标。

     ========== Task ==========
    为了提升数据检索或召回的准度，你需要主动识别 Query 中可拆分的统称概念，并将其细分成更加具体的层次或子类别，从而帮助后续查询更精确地匹配到数据库中的指标或条目。

     ========== Condition ==========
    1.若用户的 Query 中存在一个或多个可下钻的统称（如行业、产品、地区、厂商品牌、车型、产业链等），请分别展开所有可拆分的部分：
     -例如出现“白电”“小家电”“中国汽车品牌”“欧洲各国”“东南亚各国”“各品类”“各类金融工具”时，都要分别展开。
     -如果某统称还能再细分（如“汽车”可再分“品牌”“车型”；“能源”可再分“煤炭”“石油”“天然气”；“食品饮料”可再分“酒类”“饮料”“乳制品”等），请多层列举常见分类（不必无限展开）。
    2.对于已具体或无需再细分的概念（如明确时间“2025年”、单一品牌“丰田”、明确地区“美国”）则不展开。
    3.【可进一步参考的细分方向】（仅示例，你可根据具体 Query 自行扩展）：
     -地区/国家：湖北省各地区（武汉市、黄石市、十堰市等）、东南亚各国（泰国、越南、老挝、柬埔寨、文莱等）、中东各国、非洲各国……
     -产品：各类细分商品类型，比如小家电（电饭煲、电水壶、微波炉等）
     -产业链或深层细分：如“能源”可再细分煤炭、石油、天然气、页岩油，或“食品饮料”可再细分酒类、乳制品、调味品、饮料等。
     -厂商、品牌：如汽车厂商能分为大众、丰田，手机品牌能被分成苹果、华为等。

     ========== Example ==========
    1. Query: "日本各厂商汽车销量，最近两年月度数据"
       解释: 同时细分了“日本各厂商”和“汽车”
    ```python
    {{
      "日本各厂商": ["丰田","本田","日产","马自达","三菱","斯巴鲁","铃木","雷克萨斯"],
      "汽车": ["轿车","SUV","MPV","跑车","皮卡","新能源汽车"]
    }}
    ```

    2. Query: "白电2025年销售数据"
       解释: 仅细分“白电”
    ```python
    {{
      "白电": ["冰箱","洗衣机","空调","热水器","电饭煲"]
    }}
    ```

    3. Query: "能源价格走势"
       解释: 仅细分“能源”
    ```python
    {{
      "能源": ["煤炭","石油","天然气","页岩油","核能","风能","太阳能"]
    }}
    ```

    4. Query: "中国家电厂商线上销量"
       解释: 仅细分“中国家电厂商”
    ```python
    {{
      "中国家电厂商": ["海尔","美的","格力","TCL","创维","康佳","长虹"]
    }}
    ```

    5. Query: "国产手机品牌市占率"
       解释: 仅细分“国产手机品牌”
    ```python
    {{
      "国产手机品牌": ["华为","小米","OPPO","vivo","荣耀","一加","魅族"]
    }}
    ```

    6. Query: "8月份业绩"
       解释: 仅细分“业绩”
    ```python
    {{
      "业绩": ["营收","净利润","销售额","毛利","运营成本","EPS"]
    }}
    ```

    7. Query: "丰田2025年销量"
       解释: 无可细分的统称
    ```python
    []
    ```

     ========== Output Format ==========
    1.第一行：以“解释:”开头，用一句话概括你对哪些统称做了展开；若无可细分统称则写“无可细分的统称”。
    2.第二行：以一个 Python 对象（如字典或列表）代码块形式给出拆分结果，形如：
     -若多个可拆分概念，可用字典格式，如 {{"中国汽车品牌": [...], "各车型": [...]}}；若无法细分则输出 [] 或 {{}}。

    # ========== Input ==========
    请严格按以上规则处理下方用户 Query，并输出“解释”+ 代码块的形式。
    用户 Query 如下：
    {query}
    '''
    # 2) 调用大模型
    expansion_res = await call_llm(prompt=prompt, model="gpt-4.1", token_tracker=token_tracker)
    logging.info(f'统称拆分结果：{expansion_res}')

    # 3) 本地直接解析，不使用二次LLM
    explanation, expansion_data = parse_expansion_output(expansion_res)

    # 4) 从 expansion_data (若为 dict) 提取 key/values 变成列表，再加上 query 拼接成字符串
    #    如果 expansion_data 可能是 list 也可做兼容，这里以 dict 为主
    expansion_words = []
    if isinstance(expansion_data, dict):
        for _, v in expansion_data.items():
            if isinstance(v, list):
                expansion_words.extend(v)
    elif isinstance(expansion_data, list):
        # 如果直接是列表，就全部加入
        expansion_words.extend(expansion_data)

    # # 拼接成一个大字符串用来向量化：query +  所有 value
    # expansion_input_str = query + " " + " ".join(expansion_words)
    #
    # # 5) 生成向量
    # concept_expansion_embedding = get_bgeM3embeddings([expansion_input_str])[0]

    # 现在新的需求是：对“query + 每个拆分项”分别做embedding
    concept_emb_list = []
    for item in expansion_words:
        combined_str = query.strip() + " " + item.strip()
        emb = get_bgeM3embeddings([combined_str])[0]
        concept_emb_list.append((item, emb))

    #
    # # 6) 再融合 get_query_embedding 结果
    # query_embedding, kimi_res, extract_res = await get_query_embedding(query)


    return explanation, expansion_data, concept_emb_list #, query_embedding, kimi_res, extract_res

# async def get_query_understanding(query: str):
#     """
#     在这里并行执行:
#     1) concept_expansion(query)
#     2) get_query_embedding(query)
#     然后组合结果。
#     """
#     # 1) 创建两个任务
#     concept_expansion_task = asyncio.create_task(get_concept_expansion_and_embedding(query))
#     query_embedding_task = asyncio.create_task(get_query_embedding(query))
#     raw_emb_task = asyncio.create_task(asyncio.to_thread(get_bgeM3embeddings, [query]))
#     desc_task = asyncio.create_task(get_query_description(query))
#
#     # 2) 并行运行
#     (explanation, expansion_data, concept_emb_list), (query_embedding, kimi_res, extract_res), raw_emb,(query_desc, reference_indicators, flat_refs, ref_embs, query_desc_extract) = \
#         await asyncio.gather(
#             concept_expansion_task,
#             query_embedding_task,
#             raw_emb_task,
#             desc_task
#         )
#     raw_emb = raw_emb[0]  # 得到原始 query embedding
#
#     # #  原始 query embedding
#     # raw_emb = get_bgeM3embeddings([query])[0]
#
#     # 3) 组装 embeddings_config
#     embeddings_config = []
#
#     #关键词合并embedding
#     embeddings_config.append({
#         "name": "raw_query",
#         "embedding_vec": raw_emb,
#         "top_k": 30
#     })
#
#     # 3.1 原始 query embedding
#     if query_embedding is not None:
#         embeddings_config.append({
#             "name": "original_query",
#             "embedding_vec": query_embedding,
#             "top_k": 20  # 自行决定多少
#         })
#
#     # 3.2 统称拆分召回：给每个拆分子项都建一条 config
#     for item, emb in concept_emb_list:
#         embeddings_config.append({
#             "name": f"concept_sub:{item}",  # 让名字带上子项
#             "embedding_vec": emb,
#             "top_k": 3  # 需求说每个子项 top10
#         })
#
#     # ---------- 新增：LLM参考指标 Top-5 召回 ----------
#     # 写入 embeddings_config
#     for ind_name, emb in zip(flat_refs, ref_embs):
#         embeddings_config.append({
#             "name": f"ref_ind:{ind_name}",
#             "embedding_vec": emb,
#             "top_k": 10  # 每条参考指标只召回 Top-5
#         })
#
#
#     return (
#         explanation,
#         expansion_data,
#         embeddings_config,
#         query_embedding,
#         kimi_res,
#         extract_res,
#         query_desc
#     )

async def get_query_understanding(query: str, token_tracker: Optional["TokenTracker"] = None):
    """
        在这里并行执行:
        1) concept_expansion(query)
        2) get_query_embedding(query)
        然后组合结果。
        """
    # 1) 并行任务 + 超时封装
    tasks = [
        asyncio.wait_for(get_concept_expansion_and_embedding(query, token_tracker), 15),
        asyncio.wait_for(get_query_embedding(query, token_tracker), 15),
        asyncio.wait_for(asyncio.to_thread(get_bgeM3embeddings, [query]), 15),
        asyncio.wait_for(get_query_description(query, token_tracker=token_tracker), 15),
    ]
    task_names = [
        "concept_expansion",
        "query_embedding",
        "raw_embedding",
        "query_description",
    ]

    # 2) gather，不让单个异常打断
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 3) 统一日志
    for name, res in zip(task_names, results):
        if isinstance(res, asyncio.TimeoutError):
            logging.warning(f"[{name}] 超时 (>15 s) — query='{query[:50]}…'")
        elif isinstance(res, Exception):
            logging.error(f"[{name}] 异常: {type(res).__name__}: {res}", exc_info=res)

    # 2) 拆包 & 是否超时判断
    concept_res, embed_res, raw_res, desc_res = results

    concept_timeout = isinstance(concept_res, asyncio.TimeoutError)
    embed_timeout = isinstance(embed_res, asyncio.TimeoutError)
    raw_timeout = isinstance(raw_res, asyncio.TimeoutError)
    desc_timeout = isinstance(desc_res, asyncio.TimeoutError)

    if not raw_timeout:
        raw_emb = raw_res[0]  # get_bgeM3embeddings 返回的是 list
    else:
        raw_emb = None  # 占位

    # 如果未超时正常拆包；超时就用占位值
    if not concept_timeout:
        explanation, expansion_data, concept_emb_list = concept_res
    else:
        explanation, expansion_data, concept_emb_list = None, None, []

    if not embed_timeout:
        query_embedding, kimi_res, extract_res = embed_res
    else:
        query_embedding, kimi_res, extract_res = None, None, None

    if not desc_timeout:
        query_desc, reference_indicators, flat_refs, ref_embs, query_desc_extract = desc_res
    else:
        query_desc = None
        flat_refs, ref_embs = [], []

    # 3) 组装 embeddings_config
    embeddings_config = []

    #关键词合并embedding
    embeddings_config.append({
        "name": "raw_query",
        "embedding_vec": raw_emb,
        "top_k": 30
    })

    # 3.1 原始 query embedding
    if query_embedding is not None:
        embeddings_config.append({
            "name": "original_query",
            "embedding_vec": query_embedding,
            "top_k": 20  # 自行决定多少
        })

    # 3.2 统称拆分召回：给每个拆分子项都建一条 config
    for item, emb in concept_emb_list:
        embeddings_config.append({
            "name": f"concept_sub:{item}",  # 让名字带上子项
            "embedding_vec": emb,
            "top_k": 3  # 需求说每个子项 top10
        })

    # ---------- 新增：LLM参考指标 Top-5 召回 ----------
    # 写入 embeddings_config
    for ind_name, emb in zip(flat_refs, ref_embs):
        embeddings_config.append({
            "name": f"ref_ind:{ind_name}",
            "embedding_vec": emb,
            "top_k": 10  # 每条参考指标只召回 Top-5
        })


    return (
        explanation,
        expansion_data,
        embeddings_config,
        query_embedding,
        kimi_res,
        extract_res,
        query_desc
    )


def extract_and_merge_lists(text):
    # 尝试直接解析整个文本为列表
    try:
        parsed = ast.literal_eval(text)
        if isinstance(parsed, list):
            return parsed
    except (SyntaxError, ValueError) as e:
        logging.error(f"直接解析文本为列表时发生异常：{e}")
        # 如果直接解析失败，继续后续逻辑

    # 使用正则表达式找到所有的代码块，包括可能的单引号和双引号
    try:
        code_blocks = re.findall(r'(```python|`python|```)(.*?)(```)', text, re.DOTALL)
        if not code_blocks:
            # 如果没有找到，再尝试匹配三引号的代码块
            code_blocks = re.findall(r'(?:"""|\'\'\')`python(.*?)\1', text, re.DOTALL)
    except re.error as e:
        logging.error(f"正则表达式错误：{e}")
        code_blocks = []

    merged_list = []
    for block in code_blocks:
        # 提取代码块内容
        code = block[1].strip()

        # 尝试直接解析整个代码块为列表
        try:
            parsed = ast.literal_eval(code)
            if isinstance(parsed, list):
                merged_list.extend(parsed)
                continue  # 已成功解析为列表，继续处理下一个代码块
        except (SyntaxError, ValueError) as e:
            logging.error(f"解析代码块为列表时发生异常：{e}")
            # 如果解析失败，继续后续逻辑

        # 解析代码块的AST树，查找所有的列表节点
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.List):
                    elements = []
                    for elt in node.elts:
                        if isinstance(elt, (ast.Str, ast.Constant)):
                            # 兼容不同版本的Python
                            value = elt.s if hasattr(elt, 's') else elt.value
                            elements.append(value)
                        else:
                            # 如果元素不是字符串或常量，忽略
                            pass
                    merged_list.extend(elements)
        except SyntaxError as e:
            logging.error(f"解析代码块的AST树时发生异常：{e}")
            # 忽略解析错误

    return merged_list


def parse_expansion_output(llm_text: str):
    """
    从大模型一次性输出的文本中，提取以下两部分：
    1. “解释:”开头的一行（原样保留）
    2. 与之相邻(或文中)的 Python 格式字典或列表 (可能是 {} / [] / {...} )
       并将其解析为一个 Python 对象 (dict 或 list)

    说明：
    - 假设大模型输出格式，形如：
        解释: 我拆分了“白电”
        ```python
        {"白电": ["冰箱","洗衣机","空调","热水器","电饭煲"]}
        ```
      或
        解释: 无可细分的统称
        ```
        []
        ```

    返回:
        (explanation: str, expansion_data: dict 或 list 或 None)
    """
    explanation = ""
    expansion_data = None

    # 1) 提取“解释:”所在行
    # #    - 此处用正则找第一处以“解释:”开头的行。
    # pattern_explanation = r"(解释:.*)"
    # match_explain = re.search(pattern_explanation, llm_text)
    # if match_explain:
    #     explanation = match_explain.group(1).strip()

    explanation = ""
    expansion_data = None

    # ---------- 1. 抓代码块 ----------
    code_block_pattern = r"```python(.*?)```"
    code_blocks = re.findall(code_block_pattern, llm_text, flags=re.DOTALL)

    # ---------- 2. 先找“解释:” ----------
    match_explain = re.search(r"(解释:.*)", llm_text)
    if match_explain:
        explanation = match_explain.group(1).strip()
    else:
        # ---------- 3. 没有“解释:” ⇒ 把所有非代码块文本拼起来 ----------
        #   思路：把代码块替换成特殊占位，再按占位切分
        placeholder = "@@@CODE_BLOCK@@@"
        text_no_code = re.sub(code_block_pattern, placeholder, llm_text, flags=re.DOTALL)
        chunks = [c.strip() for c in text_no_code.split(placeholder) if c.strip()]
        if chunks:
            # 取最后一个非空 chunk，并去掉末尾的“参考指标如下:”行
            lines = [ln.rstrip() for ln in chunks[-1].splitlines() if ln.strip()]
            if lines and lines[-1].startswith("参考指标如下"):
                lines = lines[:-1]
            explanation = "\n".join(lines).strip()

    # 2) 寻找三引号 ```python ``` 之间的内容
    #    - 可能会返回多个匹配，但通常大模型只输出一个主要代码块
    code_pattern = r"```python(.*?)```"
    code_blocks = re.findall(code_pattern, llm_text, flags=re.DOTALL)
    for block in code_blocks:
        candidate = block.strip()
        # 尝试用 ast.literal_eval 直接解析
        # 如果成功且是 dict 或 list，则赋值并跳出
        try:
            parsed_obj = ast.literal_eval(candidate)
            if isinstance(parsed_obj, (dict, list)):
                expansion_data = parsed_obj
                break
        except Exception as e:
            logging.warning(f"无法解析为 Python 对象: {e}")
            # 如果失败，继续尝试下一个块（如果有的话）

    return explanation, expansion_data


if __name__ == '__main__':

    print(get_query_embedding("宁德时代半年报"))



