from typing import Dict, Any, List, Tuple, Optional, Union


def extract_json(json_text: str) -> dict:
    """
    从模型返回的文本中提取并解析JSON内容。
    
    处理多种格式：
    1. ```json 标记的代码块（各种变体，如有空格、缩进等）
    2. ```JSON 标记的代码块（大写）
    3. 不带标记的纯JSON字符串
    
    Args:
        json_text: 模型返回的可能包含JSON的文本
        
    Returns:
        解析后的JSON对象，解析失败时返回空字典
    """
    import re
    import json
    
    # 去除前后空白
    json_text = json_text.strip()
    
    # 首先检查是否包含代码块标记
    if "```" in json_text:
        # 尝试提取代码块中的JSON - 处理各种格式
        pattern = r"```(?:json|JSON)?(?:\s|\n)*([\s\S]*?)```"
        match = re.search(pattern, json_text)
        if match:
            json_text = match.group(1).strip()
    
    # 尝试解析JSON字符串
    try:
        return json.loads(json_text)
    except json.JSONDecodeError:
        # 如果解析失败，尝试一些修复操作
        # 例如：处理单引号替换为双引号的情况
        try:
            # 替换单引号为双引号（简单情况）
            fixed_text = re.sub(r"(?<!\\')'([^']*?)'(?!\\')", r'"\1"', json_text)
            # 替换键中的单引号
            fixed_text = re.sub(r"'([^']*?)'(?=\s*:)", r'"\1"', fixed_text)
            return json.loads(fixed_text)
        except json.JSONDecodeError:
            # 如果仍然解析失败，返回空字典
            return {}

def extract_sql(sql_text: str) -> str:
    """
    从模型返回的文本中提取SQL查询语句。
    
    处理多种格式：
    1. ```sql 标记的代码块（各种变体，如有空格、缩进等）
    2. ```SQL 标记的代码块（大写）
    
    Args:
        sql_text: 模型返回的可能包含SQL的文本
        
    Returns:
        提取出的SQL字符串，如果未找到则返回空字符串
    """
    import re
    
    # 如果输入为空，返回空字符串
    if not sql_text:
        return ""
    
    # 去除前后空白
    sql_text = sql_text.strip()
    
    # 检查是否包含代码块标记
    if "```" in sql_text:
        # 提取代码块中的SQL - 处理各种格式
        pattern = r"```(?:sql|SQL)?(?:\s|\n)*([\s\S]*?)```"
        match = re.search(pattern, sql_text)
        if match:
            return match.group(1).strip()
    
    # 如果没有找到SQL代码块，返回空字符串
    return ""

def build_table_fields_description(table_fields_info: List = None, filtered_table_info: List = None) -> str:
    """
    构建表格和字段的详细描述
    
    参数:
        table_fields_info: 表字段详情列表
        filtered_table_info: 过滤后的表定义信息列表
        
    返回:
        表格和字段的格式化描述文本
    """
    if not table_fields_info or not filtered_table_info:
        return ""
    
    # 构建表格信息字典
    table_details = {table[0]: {'name': table[1], 'description': table[2].replace('\n', '')} 
                    for table in filtered_table_info if len(table) >= 3}
    
    # 构建输出文本
    output_text = ""
    for table_name in table_details:
        output_text += f"【表格】：{table_name}，该表为{table_details[table_name]['name']}：{table_details[table_name]['description'][:200]}\n"
        output_text += "该表格中的字段详细信息：\n"
        
        # 添加该表的字段信息
        for field in table_fields_info:
            if field[0].upper() == table_name.upper():
                field_name = field[1]
                field_chinese_name = field[2]
                field_type = field[3] if len(field) > 3 else ""
                parent_category = field[4] if len(field) > 4 else ""
                field_detail = field[5] if len(field) > 5 else ""
                
                field_detail_info = f"这个字段的释义以及可能包含的单位量纲的介绍如下：{field_detail}" if field_detail else ""
                parent_category_info = f"同时该字段和'{parent_category}'这个上级类别有关。" if parent_category else ""
                
                output_text += f"{field_name}: {field_chinese_name}，{field_detail_info[:150]}，该字段的数值类别为：{field_type}, {parent_category_info}\n"
        
        output_text += "\n"
    
    return output_text