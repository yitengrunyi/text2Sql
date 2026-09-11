import asyncio
import logging
from typing import Optional, TYPE_CHECKING
import re

if TYPE_CHECKING:
    from util.token_tracker import TokenTracker
import ast
import aiohttp
from service.sql_generator.fetch_knowledge import fetch_EDB_knowledge
import requests
from fastapi import HTTPException
import concurrent.futures
import openai
from config.nacos.nacos_service import config
from openai import AsyncOpenAI
import json
# from openai.error import OpenAIError, RateLimitError, AuthenticationError

# from config.nacos.nacos_service import config
#
# config = yaml.safe_load(config)
# model_config = config.get('model_config', {})

# gpt_4o_key = model_config['gpt_4o_key']
# gpt_4o_api_base = model_config['gpt_4o_api_base']
#
# kimi_key = model_config['kimi_key']
# kimi_api_base = model_config['kimi_api_base']

openai.api_key = 'sk-_A6o-hsX-MSHh-z3I2HUAQ'
openai.api_base = "https://llm.rabyte.cn/v1"
API_KEYS = [
    'sk-fZy6ocIFW0c_SDsdDyITwX9WE5qdebst0RtjYacBk1T3BlbkFJLy7OXZrQcCxv33vYHNdzVnnVrSuAT8ixWbH5o5NSEA']

# aruze_configs = [
#     {  # 主账号
#         "endpoint": "https://rabyte-openai.openai.azure.com/openai/deployments/gpt-4o-2/chat/completions?api-version=2024-08-01-preview",
#         "key": "9e2d6f76cd1c4b03814d54bbdd2f7b75"
#     },
#     {  # 备用账号
#         "endpoint": "https://rabyte-gpt.openai.azure.com/openai/deployments/gpt-4o/chat/completions?api-version=2024-02-15-preview",
#         "key": "e69f5dfd88d248cb832c9836677d22d8"
#     }
# ]

aruze_configs = config.get('aruze_configs', {})
o1_configs = config.get('o1_configs', {})


def get_query_by_chat(prompt: str) -> str:
    pass


def get_query_by_chat_azure(prompt: str) -> str:
    pass

# http://146.235.237.169:8930/4o
# http://146.235.237.169:8930/4o_empty

def chat2R1(prompt: str) -> str:
   pass


async def async_chat2R1(prompt: str) -> str:
   pass


async def async_R1_volcano(prompt: str, endpoint: str = 'ep-20250204184813-x7d7b') -> dict:
    pass

async def get_gemini_2_5_response(
        prompt: str,
        endpoint: str = "nulls-gemini-2.5-pro-preview-03-25",
        max_retries: int = 1,
        retry_delay: float = 1.0
) -> dict:
    pass


def get_query_by_chat_gpt_4_1(prompt: str) -> str:
   pass

async def get_gpt_4_1_response(
        prompt: str,
        endpoint: str = "gpt-4.1-2025-04-14"
) -> dict:
    pass

def get_kimi_chat_completion(query):
    pass


async def get_query_by_chat_o3_mini(prompt: str) -> str:
    pass

def get_gemini_2_5_response_local(query: str) -> str:
    pass

def get_query_by_chat_gpt_empty_aruze(prompt: str) -> str:
    pass


def get_query_by_chat_gpt_empty(prompt: str) -> str:
    pass


async def get_query_by_chat_o1(prompt: str) -> str:
    pass



async def get_query_by_chat_o1_low(prompt: str) -> str:
    pass


def chat2o1(prompt: str) -> str:
    pass


async def get_query_by_chat_o1_by_text(prompt: str) -> str:
    pass


async def detect_difference(original_sql, new_sql):
    prompt = f"""
    我现在有一个【原始SQL】，以及通过大模型进行检查后写出来的【调整SQL】，请帮我判断：
    【原始SQL】和【调整SQL】是否逻辑完全一致，同时其中的字段等细节也完全一致。

    请按照如下格式输出：完全一致，请输出“1”， 有区别请输出“2”

    【原始SQL】：
    {original_sql}

    【调整SQL】：
    {new_sql}

    请直接输出结果，不要输出思考过程，请按照如下格式输出：完全一致，请输出“1”， 有区别请输出“2”
    """

    res = await asyncio.get_event_loop().run_in_executor(None, get_query_by_chat, prompt)
    res = str(res)

    return res


def extract_sql(input_text):
    # 尝试匹配以```sql或```SQL包裹的代码块
    pattern_code_block = r"```(?:sql|SQL)\s*([\s\S]*?)```"
    match_code_block = re.search(pattern_code_block, input_text)
    if match_code_block:
        sql_code = match_code_block.group(1).strip()
        return sql_code

    # 如果没有代码块标记，则尝试匹配从常见SQL关键词开始的代码片段
    pattern_sql = r"(?i)\b(WITH|SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|TRUNCATE|REPLACE)\b[\s\S]*?;"
    match_sql = re.search(pattern_sql, input_text)
    if match_sql:
        # 直接获取匹配到的 SQL 代码
        sql_code = match_sql.group(0).strip()
        return sql_code

    # 如果仍未匹配到SQL代码，返回原始输入或提示未找到SQL代码
    return None  # 或者 return input_text.strip()

def reverse_indicator_name(name: str, keep: int = None) -> str:
    """
    先按 '_' 反转，再可选保留前 keep 段。
    - name  : 原指标完整路径字符串
    - keep  : 反转后保留的段数；None 表示全部保留
    """
    if isinstance(name, tuple):          # 若误传二元组，自动取最后一位
        name = name[-1]

    parts = name.split('_')[::-1]        # 反转
    if keep is not None:
        parts = parts[:keep]             # 截断
    return '_'.join(parts)

def _format_chunk_line(i: int, name: str, freq: str, src: str) -> str:
    return f"{i}. {reverse_indicator_name(name)} | {freq} | {src}"


def loosely_filter_indicators(chunk, query, filter_rules, query_desc):
    """第一版（可复用你现有的 prompt A）"""
    # formatted_chunk = "\n".join(f"{i}. {name}" for i, name in chunk)
    formatted_chunk = "\n".join(
        f"{i}. {reverse_indicator_name(name)}"  # ← 直接反转
        for i, name in chunk
    )

    prompt = f"""
        ========= Role =========
        你是金融领域的指标提取专家。  
        候选集的 EDB 金融指标覆盖范围：
        - 国际宏观数据
        - 行业经济及经营数据
        - 中国宏观数据
        - 区域经济数据
        - A 股和港股相关经营数据

        ========= Task =========
        你的目标：从候选指标中挑出 **最能回答用户 Query 的指标**。  
        务必在脑中完成推理，不得泄露思考过程，只给最终答案。  
        - 若能找到 **可直接回答问题** 的指标，请 **只保留这些直接指标**；  
        - 若找不到直接指标，则保留所有“相关或可能相关”的指标；  
        - 若完全无关，则返回空列表 `[]`。      

        输出格式 **仅** 包含两行：  
        1. 描述每个指标的筛选理由(#需要标注出每个指标的序号#)，缺省的指标被哪个指标替代，当前回答有没有满足筛选规则4，是否满足参考指标；
        2. 合法 Python 列表（如 `[0,2,5]`）给出保留指标序号；  
           无符合指标则输出 `[]`。  
        **禁止** 输出指标名称。
        举例：筛选理由：已准确覆盖中国层面的年度GDP总量（#57）、年度总人口（#119）、年度全国平均气温（#79），均为全国年频绝对量，完全匹配用户需求，未降级，无缺项，已满足筛选规则4。

        ========= Condition =========
        【用户 Query】  
        {query}
        
        【query意图解读】
        {query_desc}

        【候选指标列表】（共 {len(chunk)} 条，序号自 0 起）：  
        {formatted_chunk}
        

        筛选规则  
        1. **相关指标**（满足其一即可视为相关）  
           - 名称/路径/描述含与 Query 匹配或高度近似的主题、地域、行业、频率、单位；  
           - 虽无法直接回答，但与其他数据组合后可能满足需求；  
           - 与用户明确强调条件（如“名义金额”“中国”“全部行业”“月频”等）相符或近似。  

        2. **不相关指标**  
           - 与 Query 意图无关，且与其他指标组合也难以回答问题。  

        3. **用户需求注意事项**  
        {filter_rules}

        4. 覆盖完整性（硬性要求）
           - 若用户 Query 同时点名多个 **主体**（国家 / 地区 / 行业 / 品牌 / 产品 / 机构 …），结果中必须保证 **每个主体至少保留 1 条指标**。  
           - 若某主体没有与主题“完全匹配”的指标，则按以下通用顺序降级，选择语义上最接近者：
                ① 同主题但粒度 / 频率不同的指标  
                ② 同一主题大类的替代指标（例：核心 ⇄ headline、利润 ⇄ 收入）  
                ③ 同一分析目的下可互换或高度相关的指标  
           - 保留降级项时，应在筛选理由中用简短文字说明 “某主体缺少直接指标，已用 **同类替代**”。       

        5. 绝对量优先
           - 若同一主题既有“当月值/累计值”等绝对量，也有“同比/环比/增速”等相对量，
             且用户 Query 未出现“同比、环比、增长率”等词，则 **只选绝对量**。
           - 仅当绝对量缺失时，才用相对量作替代，并在理由中说明原因。

        6. **保留原则**（若进入“相关”集合后同时适用）  
           a. 优先保留综合性总指标（宏观总量、总指数等）；  
            - 若同一主题同时出现「总计 / 全部 / 总数 / 总量 / Overall / 整体」与任意 细分维度（年龄段、性别、行业等），优先保留总计；
           b. 优先保留与“中国 / 全国 / 全部行业”相关指标；  
           c. 若 Query 未注明日期，优先保留频率更高者（日 > 周 > 月 > 季 > 年）。 
、
        ========= Example =========
        候选指标示例（5 条）：  
        0. 中国:出口金额:美元(月)  
        1. 中国:GDP:环比:季调(季)  
        2. 中国:GDP:不变价:同比(季)  
        3. 中国:美国:出口金额(年)  
        4. 中国:美国:进出口金额(月)  

        示例1  
        【用户Query】“中国出口美国的GDP占比”

        - 用户想要“对美国出口”与“中国GDP”指标。  
        - #0 虽是中国出口，但并未限定美国；若用户希望更精确，可以选择删除，也可酌情保留。  
        - #1、#2 均是中国GDP指标，但都不是名义量；若用户严格要求名义金额，则意义不大，可删。  
        - #3 （中国:美国:出口金额(年)）明确是对美国的出口金额（名义值），与需求紧密匹配，宜保留；  
        - #4 （中国:美国:进出口金额(月)）含有进出口总额，无法单独得出“对美国出口”金额；可删或酌情保留。  


        筛选理由：保留了与中国对美出口及GDP相关的指标，用于占比计算。
        ```python
        [3]
        ```

        示例2
        【用户Query】“我只要中国进出口美国的月频数据”
        - 用户仅关心“对美国出口”+“月频”。
        - #4（中国:美国:进出口金额(月)）与需求完全匹配，保留；
        - 其他指标要么非月频，要么与美国出口无关。
        筛选理由：仅保留了中国对美出口的月频指标。
        ```python
        [4]
        ```

        若全都不符合用户需求，则直接输出：
        筛选理由：无相关指标。
        ```python
        []
        ```

        """
    return prompt

def strictly_filter_indicators(chunk, query, filter_rules, query_desc):
    """第二版（你给出的改进示例，记得把全文粘进去）"""
    # formatted_chunk = "\n".join(f"{i}. {name}" for i, name in chunk)
    formatted_chunk = "\n".join(
        f"{i}. {reverse_indicator_name(name)}"  # ← 直接反转
        for i, name in chunk
    )

    prompt = f"""
        ========= Role =========
        你是金融领域的指标提取专家。  
        候选集的 EDB 金融指标覆盖范围：
        - 国际宏观数据
        - 行业经济及经营数据
        - 中国宏观数据
        - 区域经济数据
        - A 股和港股相关经营数据

        ========= Task =========
        你的目标：从候选指标中挑出 **最能回答用户 Query 的指标**。  
        务必在脑中完成推理，不得泄露思考过程，只给最终答案。  
        - 若能找到 **可直接回答问题** 的指标，请 **只保留这些直接指标**；  
        - 若找不到直接指标，则保留所有“相关或可能相关”的指标；  
        - 若完全无关，则返回空列表 `[]`。  

        输出格式 **仅** 包含两行：  
        1. 一句话概括筛选理由；  
        2. 合法 Python 列表（如 `[0,2,5]`）给出保留指标序号；  
           无符合指标则输出 `[]`。  
        **禁止** 输出指标名称或其他文字。

        ========= Condition =========
        【用户 Query】  
        {query}
        
        【query意图解读】
        {query_desc}

        【候选指标列表】（共 {len(chunk)} 条，序号自 0 起）：  
        {formatted_chunk}

        筛选规则  
        1. **相关指标**（满足其一即可视为相关）  
           - 名称/路径/描述含与 Query 匹配或高度近似的主题、地域、行业、频率、单位；  
           - 虽无法直接回答，但与其他数据组合后可能满足需求；  
           - 与用户明确强调条件（如“名义金额”“中国”“全部行业”“月频”等）相符或近似。  

        2. **不相关指标**  
           - 与 Query 意图无关，且与其他指标组合也难以回答问题。  

        3. **用户需求注意事项**  
        {filter_rules}

        4. **保留原则**（若进入“相关”集合后同时适用）  
           a. 优先保留综合性总指标（宏观总量、总指数等）；  
           b. 优先保留与“中国 / 全国 / 全部行业”相关指标；  
           c. 若 Query 未注明日期，优先保留频率更高者（日 > 周 > 月 > 季 > 年）。 
           d. 如果在候选指标中，**能找到可以直接回答或完美匹配用户问题的指标**（即用户Query中提到的核心内容可以通过该指标直接得到答案），那么**只保留这些直接匹配指标**； **其余同类或相似度较低的指标一律不再保留**。

        ========= Example =========
        候选指标示例（5 条）：  
        0. 中国:出口金额:美元(月)  
        1. 中国:GDP:环比:季调(季)  
        2. 中国:GDP:不变价:同比(季)  
        3. 中国:美国:出口金额(年)  
        4. 中国:美国:进出口金额(月)  

        示例1  
        【用户Query】“中国出口美国的GDP占比”

        - 用户想要“对美国出口”与“中国GDP”指标。  
        - #0 虽是中国出口，但并未限定美国；若用户希望更精确，可以选择删除，也可酌情保留。  
        - #1、#2 均是中国GDP指标，但都不是名义量；若用户严格要求名义金额，则意义不大，可删。  
        - #3 （中国:美国:出口金额(年)）明确是对美国的出口金额（名义值），与需求紧密匹配，宜保留；  
        - #4 （中国:美国:进出口金额(月)）含有进出口总额，无法单独得出“对美国出口”金额；可删或酌情保留。  


        筛选理由：保留了与中国对美出口及GDP相关的指标，用于占比计算。
        ```python
        [3]
        ```

        示例2
        【用户Query】“我只要中国进出口美国的月频数据”
        - 用户仅关心“对美国出口”+“月频”。
        - #4（中国:美国:进出口金额(月)）与需求完全匹配，保留；
        - 其他指标要么非月频，要么与美国出口无关。
        筛选理由：仅保留了中国对美出口的月频指标。
        ```python
        [4]
        ```

        若全都不符合用户需求，则直接输出：
        筛选理由：无相关指标。
        ```python
        []
        ```

        """
    return prompt



def format_tuples_as_table(tuple_list):
    """
    将元组列表格式化为简化的文本表格，相同DATA_TABLE的条目分组显示。

    参数:
        tuple_list: List[Tuple], 例如:
            [('id1', 'table1', '指标1', '%', '年'),
             ('id2', 'table2', '指标2', '元', '季'),
             ('id3', 'table1', '指标3', '%', '月')]

    返回:
        str: 格式化后的简化的文本表格
    """
    if not tuple_list:
        return ""

    # 定义列名（修正了拼写错误）
    headers = ["ind_der_code", "DATA_TABLE", "SHOW_NAME_SHORT", "UNIT", "FREQ", "source"]

    # 计算每列的最大宽度
    col_widths = [len(header) for header in headers]
    for row in tuple_list:
        for i in range(len(row)):
            col_widths[i] = max(col_widths[i], len(str(row[i])))

    # 生成表头
    header = " | ".join([f"{headers[i]:<{col_widths[i]}}" for i in range(len(headers))])
    separator = "-" * (sum(col_widths) + 3 * (len(headers) - 1))  # 修正了变量名

    # 按DATA_TABLE分组
    groups = {}
    for row in tuple_list:
        data_table = row[1]
        if data_table not in groups:
            groups[data_table] = []
        groups[data_table].append(row)

    # 生成分组表格
    result = []
    for data_table, rows in sorted(groups.items()):
        # 添加分组标题
        result.append(f"\nDATA_TABLE: {data_table}")
        result.append(separator)
        result.append(header)
        result.append(separator)

        # 添加数据行
        for row in rows:
            data_row = " | ".join([f"{str(row[i]):<{col_widths[i]}}" for i in range(len(row))])
            result.append(data_row)

    # 组合输出，跳过第一个空行
    return "\n".join(result[1:])


import re
import ast
from typing import List, Tuple, Any

def extract_list_and_text(input_str: str) :
    """
    提取列表（支持 ``` 代码块或普通行内）和解释文字：
    - 若找到多个列表，仅返回 **首个** 能成功解析为 Python list 的结果；
    - 解释文字会移除所有已匹配的列表及代码块定界符。
    """
    # 1) 代码块中的列表（```python / ```json / ``` 等）
    code_block_pattern = re.compile(
        r"```(?:\w+)?\s*?(\[[\s\S]*?\])\s*?```",  # 捕获 [...] 内容
        re.IGNORECASE
    )
    candidates: List[str] = code_block_pattern.findall(input_str)

    # 2) 行内裸列表（未包裹在 ``` 中）
    inline_pattern = re.compile(r"(\[[^\[\]]+\])")  # 简单匹配一层括号
    candidates.extend(inline_pattern.findall(input_str))

    python_list = None
    for cand in candidates:
        cleaned = re.sub(r"np\.float64\(([^)]+)\)", r"\1", cand)  # 去掉 np.float64 包装
        try:
            parsed = ast.literal_eval(cleaned)
            if isinstance(parsed, list):
                python_list = parsed
                break
        except Exception:
            continue  # 解析失败就看下一个候选

    # 3) 构造解释文字：先去掉全部列表，再去掉残留的 ``` 块
    text_without_lists = input_str
    for cand in candidates:
        text_without_lists = text_without_lists.replace(cand, "")
    # 去掉空的 ``` 代码块（可能还有换行）
    explanation = re.sub(r"```[\s\S]*?```", "", text_without_lists).strip()

    return python_list, explanation

async def process_filtered_data(
    filtered_top_230,
    query: str,
    boundaries_query,
    top_230,
    query_desc,
    max_retries: int = 2,
    token_tracker: Optional["TokenTracker"] = None,
):
    retry = 0
    while retry < max_retries:
        try:
            # ---- Step-1: LLM 并行过滤 ----
            raw_responses = await run_prompts_parallel(filtered_top_230, query, query_desc, token_tracker=token_tracker)
            merged_indices, explain_reason = merge_llm_outputs(raw_responses)

            # ---- Step-2: 转为最终数据结构 ----
            final_filtered = [
                item[:6] for i, item in enumerate(top_230) if i in merged_indices
            ]
            md_table = format_tuples_as_table(final_filtered)

            return final_filtered, md_table, explain_reason, merged_indices

        except Exception as e:
            retry += 1
            logging.warning("第 %d 次重试: %s", retry, e)

    # 失败兜底
    logging.error("达到最大重试次数，返回空结果")
    return [], "", "处理失败：达到最大重试次数", []



async def run_prompts_parallel(chunk, query, query_desc, token_tracker: Optional["TokenTracker"] = None):
    """
    对同一 chunk → 运行 PromptA×2 + PromptB×2，并返回 4 份原始响应
    """
    filter_rules = await fetch_EDB_knowledge('EDB_FILTER')

    prompt_a = loosely_filter_indicators(chunk, query, filter_rules, query_desc)
    prompt_b = strictly_filter_indicators(chunk, query, filter_rules, query_desc)
    logging.info(f'prompt_a:{prompt_a}')
    logging.info(f'prompt_b:{prompt_b}')

    async def _call(prompt):
        return await call_llm(prompt=prompt, model="gpt-4.1", token_tracker=token_tracker)   # 如有多端点可传 api_base

    tasks = [
        _call(prompt_a), #_call(prompt_a),
        _call(prompt_b), #_call(prompt_b)
    ]
    return await asyncio.gather(*tasks, return_exceptions=True)

def merge_llm_outputs(raw_list):
    """
    raw_list: [resp1, resp2, resp3, resp4]
    返回:
      merged_indices:  去重后的指标序号列表
      merged_reason:   把每份理由拼接，可选保留来源标签
    """
    merged_set = set()
    reasons = []
    for idx, raw in enumerate(raw_list, 1):
        if isinstance(raw, Exception):      # 捕获异常调用
            reasons.append(f"#Call{idx} 错误: {raw}")
            continue
        lst, why = extract_list_and_text(raw)
        if lst:
            logging.info(f'合并过滤列表:{lst}')
            merged_set.update(lst)
        reasons.append(f"#Call{idx}: {why}")
    return sorted(merged_set), "\n".join(reasons)



async def call_llm(
    prompt: str,
    model: str,
    reasoning_effort: Optional[float] = None,
    temperature: Optional[float] = None,
    SYSTEM_PROMPT: Optional[str] = None,
    timeout: int = 6000,
    token_tracker: Optional["TokenTracker"] = None
) -> str:
    """
    通过与大模型 API 交互获取响应。

    参数:
    prompt (str): 发送给模型的提示语。
    model (str): 模型类型，例如 "gpt-4o", "claude-3-opus-20240229", etc.
    reasoning_effort (float | None): 可选参数，用于控制模型的推理强度 (仅适用于部分模型)。
    temperature (float | None): 可选参数，用于控制生成文本的随机性 (仅适用于部分模型)。
    timeout (int): 请求超时时间（秒）。

    返回:
    str: 模型的响应内容。
    """
    max_retries = 3
    base_delay = 2  # Initial delay in seconds

    for attempt in range(max_retries + 1):
        try:
            API_URL = "https://llm.rabyte.cn/chat/completions"
            headers = {'Content-Type': 'application/json',
                       'Authorization': 'Bearer sk-_A6o-hsX-MSHh-z3I2HUAQ'}

            # ---------- 1) 构造 messages ----------
            messages = []
            if SYSTEM_PROMPT:  # 只有非空时才写入
                messages.append({"role": "developer", "content": SYSTEM_PROMPT})
            messages.append({"role": "user", "content": prompt})

            # Construct payload based on the new API requirements
            payload = {
                "model": model,
                "messages": messages,
            }
            # Add optional parameters if provided
            if reasoning_effort is not None:
                payload["reasoning_effort"] = reasoning_effort
            if temperature is not None:
                payload["temperature"] = temperature
            if timeout is not None:
                payload["timeout"] = timeout


            logging.info(f"开始调用模型 {model.upper()} via {API_URL} (Attempt {attempt + 1}/{max_retries + 1}) with payload: {payload}")

            # Use aiohttp for async request with the specified timeout
            async with aiohttp.ClientSession() as session:
                async with session.post(API_URL, json=payload, headers=headers, timeout=timeout) as response:
                    # 获取响应内容
                    response_text = await response.text()

                    # 检查请求状态
                    if response.status >= 400:
                        # 尝试解析错误响应
                        try:
                            error_data = json.loads(response_text)
                            # 将整个错误响应转换为字符串
                            error_message = json.dumps(error_data, ensure_ascii=False)
                        except json.JSONDecodeError:
                            # 响应不是JSON格式
                            error_message = response_text

                        error_msg = f"API错误 (状态码: {response.status}): {error_message}"
                        logging.error(error_msg)
                        raise Exception(error_msg)

                    # 解析成功响应
                    try:
                        response_data = json.loads(response_text)
                        logging.info("请求成功，收到响应")

                        # Extract content
                        if "choices" in response_data and len(response_data["choices"]) > 0:
                            content = response_data["choices"][0]["message"]["content"]
                            # 记录 token usage
                            if token_tracker is not None:
                                token_tracker.record_from_response(model, response_data)
                            logging.info(f"{model.upper()} call successful.")
                            return content
                        else:
                            error_msg = f"请求成功但响应格式不符合预期: {response_data}"
                            logging.error(error_msg)
                            raise Exception(error_msg) # Raise exception to trigger retry
                    except json.JSONDecodeError:
                        error_msg = f"响应不是有效的JSON格式: {response_text}"
                        logging.error(error_msg)
                        raise Exception(error_msg)
        except Exception as e:
            # Log with the new parameter name
            logging.error(f"调用{model.upper()}模型失败 (Attempt {attempt + 1}/{max_retries + 1}): {str(e)}")
            if attempt < max_retries:
                delay = base_delay + attempt # Increase delay
                logging.info(f"将在 {delay} 秒后重试...")
                await asyncio.sleep(delay)
            else:
                 # Log with the new parameter name
                logging.error(f"模型 {model.upper()} 调用失败，已达到最大重试次数。")
                raise # Re-raise the last exception if all retries fail

# async def main():
#     # 测试提示语
#     prompt = "请帮我查询2022年华胜天成的净利润。"
#
#     try:
#         # 调用 get_query_by_chat 函数
#         response = await get_query_by_chat(prompt)
#         print("GPT-4 的响应内容：")
#         print(response)
#     except Exception as e:
#         print(f"调用 OpenAI API 时出错: {e}")
#
#
# # 运行主函数
if __name__ == "__main__":
    # asyncio.run(get_query_by_chat_o1_low("上海旅游规划"))
    print(asyncio.run(get_query_by_chat_o1("上海旅游规划")))