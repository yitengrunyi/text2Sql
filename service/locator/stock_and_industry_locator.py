import os

import aiohttp

from service.locator.question_locator import fetch_and_process_industries
from util.http_helpers import stock_matcher_url, fetch, us_stock_matcher_url

print("Current working directory:", os.getcwd())
script_dir = os.path.dirname(os.path.abspath(__file__))

# 构建文件的绝对路径
a_stock_map = os.path.join(script_dir, 'a_stock_map.csv')
hk_stock_map = os.path.join(script_dir, 'hk_stock_map.csv')
us_stock_map = os.path.join(script_dir, 'us_stock_map.csv')
industry_csv_file = os.path.join(script_dir, '申万行业-新.csv')
async def fetch_stock_industry_topics(query):
    stock_info, companies, us_stock_codes = await get_stock_info(query)

    if stock_info:
        return stock_info, companies, us_stock_codes

    #industry_res = await fetch_and_process_industries(query, industry_csv_file)
    # topic_info = fetch_and_process_concepts(query)

    # industry_res = industry_res + topic_info

    return None, companies, None

async def fetch_industry_topics(query, res_str):


    industry_res = await fetch_and_process_industries(query, industry_csv_file, res_str)
    # topic_info = fetch_and_process_concepts(query)

    # industry_res = industry_res + topic_info

    return industry_res

async def get_stock_info(query):
    import pandas as pd
    cn_stock_industry_map = pd.read_csv(a_stock_map)
    hk_stock_industry_map = pd.read_csv(hk_stock_map)
    us_stock_industry_map = pd.read_csv(us_stock_map)


    async with aiohttp.ClientSession() as session:
        data = {"is_keep_vague": "1", "scope": "prd",
         "content": query}
        resp_stock_baichuan = await fetch(session, us_stock_matcher_url, data)
        entities_stock_baichuan = resp_stock_baichuan['pattern_res']

    final_combine_res = ""
    us_stock_codes = []  # 用于存储美股股票代码

    entities_stock_baichuan = filter_and_deduplicate(entities_stock_baichuan)

    def extract_company_names(entities_stock_baichuan):
        companies = []  # 用于存储提取的公司名称

        for item in entities_stock_baichuan:
            # 假设每个 item 的格式为 "SECxxxxxx-公司名-股票代码-市场"
            parts = item.split('-')  # 按 '-' 分割字符串
            if len(parts) >= 2:  # 确保分割后的部分至少包含公司名
                company_name = parts[1]  # 公司名是分割后的第二部分
                companies.append(company_name)  # 将公司名添加到列表中

        return companies

    companies = extract_company_names(entities_stock_baichuan)

    for item in entities_stock_baichuan:
        if item.endswith('SH') or item.endswith('SZ'):
            company = item.split('-')[1]
            stock_code = item.split('-')[2]
            if stock_code.startswith('688'):
                final_combine_res += f"该问题可能涉及A股-'{company}'，并且该股票为A股【科创板公司】，该股票为A股【科创板公司】！！！"
            elif stock_code.startswith('300') or stock_code.startswith('301'):
                final_combine_res += f"该问题可能涉及A股-'{company}'，并且该股票为A股主板的创业板公司，该股票为A股主板的创业板公司！！！"
            else:
                final_combine_res += f"该问题可能涉及A股-'{company}'，并且该股票为A股主板公司，该股票为A股主板公司！！！"

            # 获取对应的行业名称
            industry_name = cn_stock_industry_map[cn_stock_industry_map['stockName'] == company]['industryName'].head(1)
            if not industry_name.empty:
                final_combine_res += f'对应的一级行业名称为-{industry_name.iloc[0]}。'
            else:
                final_combine_res += '未找到对应的行业名称。'

        elif item.endswith('HK'):
            company = item.split('-')[1]
            final_combine_res += f"该问题可能涉及港股-'{company}',"

            # 获取对应的行业名称
            industry_name = hk_stock_industry_map[hk_stock_industry_map['stockName'] == company]['industryName'].head(1)
            if not industry_name.empty:
                final_combine_res += f'对应的港股行业名称为-{industry_name.iloc[0]}。'
            else:
                final_combine_res += '未找到对应的行业名称。'

        elif item.endswith('US'):
            company = item.split('-')[1]
            final_combine_res += f"该问题可能涉及美股-'{company}', 它的美股股票代码为：{item.split('-')[2]}，请注意美股筛选的时候使用股票代码进行关联。"
            # 将美股股票代码添加到列表中
            us_stock_codes.append(item.split('-')[2])

            # 获取对应的行业名称
            industry_name = us_stock_industry_map[us_stock_industry_map['stockName'] == company]['industryName'].head(1)
            if not industry_name.empty:
                final_combine_res += f'对应的美股行业名称为-{industry_name.iloc[0]}。'
            else:
                final_combine_res += '未找到对应的行业名称。'

    return final_combine_res, companies, us_stock_codes


def filter_and_deduplicate(pattern_res):
    # 创建一个字典来存储每个名称的优选结果和对应的优先级
    result_dict = {}

    for item in pattern_res:
        parts = item.split("-")
        name = parts[1]
        market_code = parts[-1]

        # # 定义市场代码的优先级，数字越小优先级越高
        # if market_code in ["SH", "SZ"]:
        #     priority = 1  # 最高优先级
        # elif market_code == "HK":
        #     priority = 2  # 次高优先级
        # else:
        #     priority = 3  # 其他市场，最低优先级


        # 定义市场代码的优先级，数字越小优先级越高
        if market_code in ["SH", "SZ"]:
            priority = 1  # 最高优先级
        elif market_code == "US":
            priority = 2  # 次高优先级（US 优先于 HK）
        elif market_code == "HK":
            priority = 3  # 次低优先级
        else:
            priority = 4  # 其他市场，最低优先级

        if name in result_dict:
            # 比较当前条目与已存储条目的优先级
            stored_item, stored_priority = result_dict[name]
            if priority < stored_priority:
                result_dict[name] = (item, priority)
        else:
            result_dict[name] = (item, priority)

    # 从结果字典中提取最终的条目
    return [item for item, priority in result_dict.values()]