
from typing import List, Tuple, Optional
from datetime import datetime
from util.db_helpers import query_from_db


async def fetch_general_knowledge() -> str:
    """
    获取一般知识信息。

    返回:
    str: 一般知识信息。
    """
    sql_query = f"""
    SELECT KNOW_TYPE, KNOW_ID, KNOW_DESC FROM MDB_EXPERT_KNOWLEDGE_JULING
    WHERE KNOW_TYPE = 'GENERAL'
    """
    general_info = await query_from_db(sql_query)
    general_text = ""
    for idx, item in enumerate(general_info):
        if "注意当前的时间" in item[2]:
            date_time_str = datetime.now().strftime('%Y年%m月%d日')
            new_info = f'请注意当前的时间是{date_time_str}，请注意基准的时间。 请特别注意字段的类别，如果字段是datetime类别的，则请不要使用TO_DATE函数。'
            general_text += f"{idx + 1}.{new_info}\n\n"
        #获取最新交易日期
        elif "查询效率优化-最近交易日" in item[2]:

            # ── 1. 取 A 股、港股的最新 TRADEDATE 和 ENDDATE ──────────────────
            sql_A = """
            SELECT 
                TRADEDATE AS trade_A,        -- 最新交易日
                ENDDATE   AS end_A           -- 最新报表截止日
            FROM MKT_MAX_TRADEDATE
            WHERE MKT_TYPE = 'A股';
            """

            sql_HK = """
            SELECT 
                TRADEDATE AS trade_HK,       -- 最新交易日
                ENDDATE   AS end_HK          -- 最新报表截止日
            FROM MKT_MAX_TRADEDATE
            WHERE MKT_TYPE = '港股';
            """
            # 执行查询（各返回一行两列 → (TRADEDATE, ENDDATE)）
            trade_A, end_A = (await query_from_db(sql_A))[0]  # e.g. (2025-06-20, 2025-06-20)
            trade_HK, end_HK = (await query_from_db(sql_HK))[0]


            # ── 2. 把日期格式化成 “YYYY年M月D日” ────────────────────────────
            def fmt(dt):
                if isinstance(dt, str):
                    dt = datetime.strptime(dt[:10], "%Y-%m-%d")
                return f"{dt.year}年{dt.month}月{dt.day}日"

            trade_str = f"A股:{fmt(trade_A)}，港股:{fmt(trade_HK)}"
            enddate_str = f"A股:{fmt(end_A)}，港股:{fmt(end_HK)}"

            # ── 3. 替换占位日期文本并写入 general_text ──────────────────────
            pattern = r"\d{4}年\d{1,2}月\d{1,2}日"

            # 原本 item[2] 里是“最近交易日”提示 —— 先替换它
            updated_trade_notice = re.sub(pattern, trade_str, item[2])
            general_text += f"{idx + 1}.{updated_trade_notice}\n\n"

            # 构造“最新报表截止日”提示（沿用同一段文案，关键词改一下）
            enddate_notice_tpl = item[2].replace("最近交易日", "最新报表截止日") \
                .replace("交易日", "报表截止日")
            updated_enddate_notice = re.sub(pattern, enddate_str, enddate_notice_tpl)
            general_text += f"{idx + 1}.1.{updated_enddate_notice}\n\n"

        else:
            general_text += f"{idx+1}.{item[2]}\n\n"
    return general_text

async def fetch_EDB_knowledge(know_type: str = "EDB_GENERAL") -> str:
    """
    获取一般知识信息。

    返回:
    str: 一般知识信息。
    """
    sql_query = f"""
    SELECT KNOW_TYPE, KNOW_ID, KNOW_DESC FROM MDB_EXPERT_KNOWLEDGE_JULING
    WHERE KNOW_TYPE = '{know_type}' AND HISVALID = 1
    """
    general_info = await query_from_db(sql_query)
    general_text = ""
    for idx, item in enumerate(general_info):
        if "注意当前的时间" in item[2]:
            from datetime import datetime
            date_time_str = datetime.now().strftime('%Y年%m月%d日')
            new_info = f'请注意当前的时间是{date_time_str}，请注意基准的时间。 请特别注意字段的类别，如果字段是datetime类别的，则请不要使用TO_DATE函数。'
            general_text += f"{idx + 1}.{new_info}\n\n"
        elif know_type == "EDB_FILTER":
            general_text += f"   - {item[2]}\n"
        else:
            general_text += f"{idx+1}.{item[2]}\n"
    return general_text


async def fetch_domain_knowledge(concepts:str, domain_res: str, industry_str: str, domian_one: str) -> str:
    """
    获取域知识信息。

    参数:
    domain_res (str): 域分类结果。
    industry_str (str): 行业字符串。
    domain_one (str): 一级域分类结果。
    返回:
    str: 域知识信息。
    """
    domain_str = domain_res.replace('[', '(').replace(']', ')')
    sql_query = f"""
    SELECT KNOW_TYPE, KNOW_ID, KNOW_DESC FROM MDB_EXPERT_KNOWLEDGE_JULING
    WHERE KNOW_TYPE = 'DOMAIN' AND ( OBJECT_CNAME IN {domain_str} OR OBJECT_CNAME = '{domian_one}' )
    """
    domain_info = await query_from_db(sql_query)
    update_domain_info = []
    for line in domain_info:
        content = line[2]
        if '涉及到申万' in content:
            if len(industry_str) > 0:
                industry_str += (' ，请在书写SQL时特别关注本条信息，如果问题中用户说的行业和本条信息冲突，请以本条信息为准！！！如果用户原问题Query中包含”申万XXXX“这样的信息，请必须仍然以本条信息为准！！！')
                update_domain_info.append((None,None,industry_str))
        elif '请优先以当前时间截面' in content:
            from datetime import datetime
            date_time_str = datetime.now().strftime('%Y年%m月%d日')
            date_info = f'如果没有明确约定问题的时间段，请优先以当前时间截面，即{date_time_str}为基准，向前向后推算。'
            update_domain_info.append((None,None,date_info))
        else:
            update_domain_info.append(line)

    if len(concepts) > 1:
        concepts += (' 请在书写SQL时特别关注本条信息，如果问题中用户说的题材和本条信息冲突，请以本条信息为准！！！')
        update_domain_info.append((None,None,concepts))

    domain_text = ""
    for idx, item in enumerate(update_domain_info):
        domain_text += f"{idx+1}.{item[2]}\n\n"
    return domain_text

import re



async def fetch_EDB_tables_knowledges(final_filtered_top_50: list, top30_candidates_dict = None) -> List[str]:
    """
    从数据库中获取表信息，并根据查询生成定位提示。

    参数:
    query (str): 用户的查询问题。
    final_filtered_top_50: list

    """

    # 从 final_filtered_top_50 提取 OBJECT_HCODE 值（每个子列表的第2位）
    # filtered_hcodes = [item[1] for item in final_filtered_top_50]
    filtered_hcodes = list({item[1] for item in final_filtered_top_50})  # 使用集合推导式去重
    if not filtered_hcodes:
        return "没有找到匹配的表信息"

    # 确保 final_table_list 包含这些值（如果需要的话）
    # 这里假设 final_table_list 已经是你要筛选的完整列表
    # 如果需要交集，可以这样：c
    # final_table_list = [hcode for hcode in final_table_list if hcode in filtered_hcodes]

    sql_query = f"""
        SELECT KNOW_TYPE, KNOW_ID, OBJECT_HCODE, OBJECT_CNAME, KNOW_DESC 
        FROM MDB_EXPERT_KNOWLEDGE_JULING
        WHERE KNOW_TYPE = 'TABLE' 
        AND OBJECT_HCODE IN {tuple(filtered_hcodes) if len(filtered_hcodes) > 1 else f"('{filtered_hcodes[0]}')"}
        AND HISVALID = 1
    """
    table_info = await query_from_db(sql_query)
    table_text = ''

    # 如果top30_candidates_dict不为空，则添加字段值信息
    if top30_candidates_dict:
        table_text = "根据query,我们已经预先知道以下字段的值可从如下列表中选取："
        for key, values in top30_candidates_dict.items():
            # table_text += f" {list(key)[0]}表的{list(key)[1]}字段的字段值: {values}\n"
            if len(values) == 1:
                table_text += f"{list(key)[0]}表的{list(key)[1]}字段,请在sql中的WHERE条件中加入{list(key)[1]} = '{values[0]}'!!!\n"
                table_text += f"{list(key)[0]}表的{list(key)[1]}字段,请在sql中的WHERE条件中加入{list(key)[1]} = '{values[0]}'!!!\n"
            else:
                # 使用正则表达式将列表转换为 SQL 合法的 IN 条件
                values_str = re.sub(r"[\[\]]", "", str(values))  # 去掉列表的方括号
                table_text += f"{list(key)[0]}表的{list(key)[1]}字段,请在sql中的WHERE条件中加入{list(key)[1]} in ({values_str})!!!\n"
                table_text += f"{list(key)[0]}表的{list(key)[1]}字段,请在sql中的WHERE条件中加入{list(key)[1]} in ({values_str})!!!\n"
        # table_text += (f"请根据语义判断!!!\n\n"
        #                f"注意字段取值不要使用不在字段值列表里的，也要注意不是所有字段值都需要使用，请你根据需要来选择！！！")
    for idx, item in enumerate(table_info):
        table_text += (f"{idx + 1}.对于【{item[2]}】表格，即{item[3]}表格，{item[4]}；")
        # for key, values in top3_candidates_dict.items():
        #     table_text += f" {list(key)[1]}: {values}\n"
        # table_text += (f"请根据语义判断!!!\n\n"
        #     f"注意不是所有字段的候选值都需要使用，请你根据需要来选择。\n\n")
    return table_text


async def fetch_table_knowledge(top30_candidates_dict:dict, final_table_list: List[str]) -> str:
    """
    获取表格知识信息。

    参数:
    final_table_list (Tuple[str]): 表名列表。

    返回:
    str: 表格知识信息。
    """
    final_table_list = tuple(final_table_list) if len(final_table_list) > 1 else f"('{final_table_list[0]}')"

    sql_query = f"""
    SELECT KNOW_TYPE, KNOW_ID, OBJECT_HCODE, OBJECT_CNAME, KNOW_DESC FROM MDB_EXPERT_KNOWLEDGE_JULING
    WHERE KNOW_TYPE = 'TABLE' AND OBJECT_HCODE IN {final_table_list}
    """
    table_info = await query_from_db(sql_query)
    table_text = ''

    # 如果top30_candidates_dict不为空，则添加字段值信息
    if top30_candidates_dict:
        table_text = "根据query,我们已经预先知道以下字段的值可从如下列表中选取："
        for key, values in top30_candidates_dict.items():
            # table_text += f" {list(key)[0]}表的{list(key)[1]}字段的字段值: {values}\n"
            if len(values) == 1:
                table_text += f"{list(key)[0]}表的{list(key)[1]}字段,请在sql中的WHERE条件中加入{list(key)[1]} = '{values[0]}'!!!\n"
                table_text += f"{list(key)[0]}表的{list(key)[1]}字段,请在sql中的WHERE条件中加入{list(key)[1]} = '{values[0]}'!!!\n"
            else:
                # 使用正则表达式将列表转换为 SQL 合法的 IN 条件
                values_str = re.sub(r"[\[\]]", "", str(values))  # 去掉列表的方括号
                table_text += f"{list(key)[0]}表的{list(key)[1]}字段,请在sql中的WHERE条件中加入{list(key)[1]} in ({values_str})!!!\n"
                table_text += f"{list(key)[0]}表的{list(key)[1]}字段,请在sql中的WHERE条件中加入{list(key)[1]} in ({values_str})!!!\n"
        # table_text += (f"请根据语义判断!!!\n\n"
        #                f"注意字段取值不要使用不在字段值列表里的，也要注意不是所有字段值都需要使用，请你根据需要来选择！！！")
    for idx, item in enumerate(table_info):
        table_text += (f"{idx+1}.对于【{item[2]}】表格，即{item[3]}表格，{item[4]}；")
        # for key, values in top3_candidates_dict.items():
        #     table_text += f" {list(key)[1]}: {values}\n"
        # table_text += (f"请根据语义判断!!!\n\n"
        #     f"注意不是所有字段的候选值都需要使用，请你根据需要来选择。\n\n")
    return table_text