import pandas as pd
from collections import Counter
from pathlib import Path
import asyncio
import json
import traceback
from tqdm import tqdm
import os
from util.model_helpers import call_llm
from util.common import extract_json
import json_repair


def build_evaluation_prompt(turn_data):
    """构建评估提示词
    
    Args:
        turn_data: 包含所有评估所需信息的字典
    
    Returns:
        构建好的提示词
    """
    # 从turn_data中获取所有需要的信息
    user_input = turn_data.get("用户输入", "")
    intent_type = turn_data.get("意图分类", "未知意图")
    executed_sql = turn_data.get("执行SQL", "")
    table_fields_description = turn_data.get("表字段描述", "")
    ground_truth_sql = turn_data.get("基准SQL", "")
    ground_truth_input = turn_data.get("首轮用户问题", "")
    
    # 处理历史记录
    try:
        history = turn_data.get("历史记录", [])
        if isinstance(history, str):
            history = json.loads(history.replace("'", "\""))
        elif not isinstance(history, list):
            history = []
    except:
        history = []
    
    history_text = "\n".join([f"- {i}: {h}" for i, h in enumerate(history)])
    
    # 处理之前轮次的用户问题和SQL
    previous_turns = turn_data.get("之前轮次", [])
    previous_turns_text = ""
    for turn in previous_turns:
        turn_num = turn.get("轮次", "未知")
        turn_input = turn.get("用户输入", "")
        turn_sql = turn.get("执行SQL", "")
        
        if turn_input and turn_sql:
            previous_turns_text += f"\n### 轮次 {turn_num}\n"
            previous_turns_text += f"用户问题: \"{turn_input}\"\n"
            previous_turns_text += f"执行SQL:\n```sql\n{turn_sql}\n```\n"
    
    return f"""# 多轮对话Text2SQL评估任务

你是一位专业的SQL和多轮对话专家，需要评估用户追问后的意图分类和SQL生成结果是否正确。请采用灵活的评估标准，只要SQL能在逻辑上满足用户需求即可。

## 背景信息
- 首轮用户问题: "{ground_truth_input}"
- 上一轮查询生成的SQL (视为基准): 
```sql
{ground_truth_sql}
```

## 数据库表结构信息
{table_fields_description}

## 完整对话历史
以下是该对话的所有历史轮次，包括用户问题和对应生成的SQL:
{previous_turns_text}

## 历史对话记录:
{history_text}

## 当前用户追问:
"{user_input}"

## 当前追问的系统处理:
- 系统识别的意图类型: {intent_type}
- 追问对应生成的SQL: 
```sql
{executed_sql if executed_sql else "未生成SQL"}
```

## 评估任务
1. 意图分类评估：
   - 判断系统识别的意图类型（{intent_type}）是否正确
   - 意图类型说明：
     * NON_QUERY: 闲聊类无关反馈，如"谢谢"、"你做得很好"等
     * SQL_GENERATION: 需要构建新的SQL查询，或修改当前SQL
     * NEW_QUERY: 需要基于历史对话生成完全新的问题，或需要新的表结构

2. SQL生成评估（仅当意图为SQL_GENERATION时）：
   A. 业务逻辑正确性（采用灵活标准）：
      - SQL查询是否能在逻辑上满足用户的需求（不要过于严格，即使实现方式不同）
      - 查询可以包含额外的字段，只要包含了用户需要的核心信息即可
      - 排序、分组、筛选条件只要基本符合用户请求的意图即可
      - 查询结构虽与预期不同，但能实现相同结果的也视为正确
      - 是否与历史对话上下文保持基本一致性
   
   B. 语法和结构基本正确性：
      - SQL是否能正常执行（无明显语法错误）
      - SQL是否引用了存在的表和字段
      - 表关联基本合理
      - 函数和操作符使用基本合适

## 重要评估原则
- 采用灵活宽松的评估标准，只要SQL能实现用户需求的核心功能即可判定为正确
- 不要因为SQL风格不同、多选了一些列、使用了不同的但等效的函数或表达式而判定为错误
- 即使SQL的写法与预期不同，只要查询结果能满足用户需求，也应判定为正确
- 对于有多种合理实现方式的需求，应该接受不同的SQL实现

## 请严格按照以下JSON格式输出评估结果:
```json
{{
  "intent_analysis": "详细分析系统识别的意图类型是否正确，说明理由",
  "intent_correct": true或false(表示意图分类是否正确),
  "sql_analysis": "详细分析SQL的正确性（仅当意图为SQL_GENERATION时）",
  "sql_correct": true或false(表示SQL是否正确，仅当意图为SQL_GENERATION时),
  "is_correct": true或false(整体评估结果：意图分类正确且SQL正确（如果适用）)
}}
```

注意:
- 评估必须同时考虑意图分类的准确性和SQL的正确性（如果适用）
- 对于NON_QUERY和NEW_QUERY意图，只需评估意图分类是否正确
- 对于SQL_GENERATION意图，需要同时评估意图分类和SQL的正确性
- 分析必须详细说明为什么系统的处理是正确或错误的，无论结果如何都要给出充分理由
- 只返回JSON格式的结果，不要有其他文本
"""

async def evaluate_chat_turn(turn_data):
    """评估单轮对话
    
    Args:
        turn_data: 包含所有评估所需信息的字典
    
    Returns:
        评估结果字典
    """
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # 构建提示词
            prompt = build_evaluation_prompt(turn_data)
            
            # 调用大模型
            response = await call_llm(prompt=prompt, model="nulls-gemini-2.5-pro-preview-03-25")
            
            # 解析JSON结果
            evaluation_result = json_repair.loads(response)
            
            if not evaluation_result:
                raise ValueError("JSON解析失败，未能获取有效评估结果")
                
            return {
                "意图分析": evaluation_result.get("intent_analysis", "未提供分析"),
                "意图正确": evaluation_result.get("intent_correct", False),
                "SQL分析": evaluation_result.get("sql_analysis", "未提供分析"),
                "SQL正确": evaluation_result.get("sql_correct", False),
                "评估结果": evaluation_result.get("is_correct", False)
            }
        except Exception as e:
            print(f"评估轮次数据时出错 (尝试 {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                print(f"等待2秒后重试...")
                await asyncio.sleep(2)
            else:
                print(f"已达到最大重试次数，放弃重试")
                return {
                    "意图分析": f"评估出错: {str(e)}",
                    "意图正确": False,
                    "SQL分析": f"评估出错: {str(e)}",
                    "SQL正确": False,
                    "评估结果": False
                }

async def evaluate_test_case(test_data, df):
    """评估单个测试用例的所有轮次
    
    Args:
        test_data: 包含单个测试用例所有轮次数据的DataFrame
        df: 主DataFrame，用于更新评估结果
    
    Returns:
        更新后的DataFrame
    """
    try:
        test_id = test_data["测试ID"].iloc[0]
        print(f"\n开始评估测试ID: {test_id}")
        
        # 获取第0轮(ground truth)的SQL和用户输入
        ground_truth_data = test_data[test_data["轮次"] == 0]
        if len(ground_truth_data) == 0:
            print(f"警告：测试ID {test_id} 没有轮次为0的数据")
            return df
            
        # 验证ground truth数据的完整性
        first_sql = ground_truth_data.iloc[0].get("执行SQL")
        ground_truth_input = ground_truth_data.iloc[0].get("用户输入")
        
        if not first_sql or not ground_truth_input:
            print(f"警告：测试ID {test_id} 的基准数据不完整")
            return df
        
        # 获取需要评估的轮次数据
        evaluation_data = test_data[test_data["轮次"] > 0].copy()
        if len(evaluation_data) == 0:
            print(f"警告：测试ID {test_id} 没有需要评估的轮次")
            return df
            
        print(f"测试ID {test_id} 共有 {len(evaluation_data)} 轮需要评估")
        
        # 保存所有轮次数据以便引用
        turn_data_map = {}
        # 首先存储首轮数据
        turn_data_map[0] = {
            "轮次": 0,
            "用户输入": ground_truth_input,
            "执行SQL": first_sql
        }
        
        # 然后保存其他轮次数据
        for idx, row in test_data.iterrows():
            turn = row['轮次']
            if turn > 0:
                turn_data_map[turn] = {
                    "轮次": turn,
                    "用户输入": row.get("用户输入", ""),
                    "执行SQL": row.get("执行SQL", ""),
                    "意图分类": row.get("意图分类", "")
                }
        
        # 评估轮次>0的对话
        for idx, row in evaluation_data.iterrows():
            try:
                current_turn = row['轮次']
                intent_type = row.get("意图分类", "")
                
                # 跳过NON_QUERY和NEW_QUERY类型的轮次
                if intent_type in ["NON_QUERY", "NEW_QUERY","INITIAL_QUERY"]:
                    print(f"跳过测试ID {test_id} 的第 {current_turn} 轮，因为意图类型为 {intent_type}")
                    # 对于NON_QUERY和NEW_QUERY类型，直接设置为正确
                    df.at[idx, "意图正确"] = True
                    df.at[idx, "SQL正确"] = True
                    df.at[idx, "评估结果"] = True
                    df.at[idx, "意图分析"] = f"意图类型为{intent_type}，默认设置为正确"
                    df.at[idx, "SQL分析"] = f"意图类型为{intent_type}，默认设置为正确"
                    continue
                
                # idx是迭代序号，而row.name是该行在原始DataFrame中的索引值
                original_index = row.name
                print(f"正在评估测试ID {test_id} 的第 {current_turn} 轮 (DataFrame索引: {original_index})...")
                
                # 收集当前轮次之前的所有用户问题和SQL作为对话历史
                previous_turns = []
                for i in range(current_turn):
                    if i in turn_data_map:
                        previous_turns.append(turn_data_map[i])
                
                # 获取当前轮次的所有数据
                turn_data = row.to_dict()
                
                # 添加之前所有轮次的用户输入和SQL
                turn_data["之前轮次"] = previous_turns
                
                # 获取前一轮SQL作为基准SQL（如果存在）
                ground_truth_sql = first_sql  # 默认使用首轮SQL
                if current_turn - 1 in turn_data_map and turn_data_map[current_turn - 1].get("执行SQL"):
                    ground_truth_sql = turn_data_map[current_turn - 1].get("执行SQL")
                
                turn_data["基准SQL"] = ground_truth_sql
                turn_data["首轮用户问题"] = ground_truth_input
                
                # 评估当前轮次
                evaluation_result = await evaluate_chat_turn(turn_data)
                
                # 验证评估结果的完整性
                required_fields = ["意图分析", "意图正确", "SQL分析", "SQL正确", "评估结果"]
                if not all(field in evaluation_result for field in required_fields):
                    print(f"警告：测试ID {test_id} 轮次 {current_turn} 的评估结果不完整")
                    continue
                
                # 确认原始索引存在于主DataFrame中
                if original_index not in df.index:
                    print(f"警告：测试ID {test_id} 轮次 {current_turn} 的索引 {original_index} 在主DataFrame中不存在")
                    continue
                
                # 使用原始DataFrame的索引更新数据
                df.at[original_index, "意图分析"] = evaluation_result["意图分析"]
                df.at[original_index, "意图正确"] = evaluation_result["意图正确"]
                df.at[original_index, "SQL分析"] = evaluation_result["SQL分析"]
                df.at[original_index, "SQL正确"] = evaluation_result["SQL正确"]
                df.at[original_index, "评估结果"] = evaluation_result["评估结果"]
                
                print(f"测试ID {test_id} 的第 {current_turn} 轮评估完成")
                
            except Exception as e:
                print(f"评估测试ID {test_id} 轮次 {row['轮次']} 时出错: {str(e)}")
                continue
        
        print(f"测试ID {test_id} 的所有轮次评估完成")
        return df
        
    except Exception as e:
        print(f"处理测试ID {test_id} 时出错: {str(e)}")
        return df

async def evaluate_multi_turn_results(excel_path, output_path=None):
    """评估多轮对话结果
    
    Args:
        excel_path: Excel文件路径
        output_path: 输出Excel文件路径，默认为None(自动生成)
    """
    try:
        print(f"开始读取Excel文件: {excel_path}")
        df = pd.read_excel(excel_path)
        
        # 确认必要的列是否存在
        required_columns = ["测试ID", "轮次", "用户输入", "执行SQL", "历史记录", "意图分类"]
        for col in required_columns:
            if col not in df.columns:
                print(f"警告：Excel文件中没有'{col}'列，这可能影响评估准确性")
                if col == "测试ID" or col == "轮次" or col == "用户输入":
                    print(f"错误：必需列'{col}'不存在，无法继续评估")
                    return
                
        # 初始化新列
        df["意图分析"] = ""
        df["意图正确"] = False
        df["SQL分析"] = ""
        df["SQL正确"] = False
        df["评估结果"] = False
        
        # 按测试ID分组处理
        test_ids = df["测试ID"].unique()
        print(f"共有{len(test_ids)}个测试会话需要评估")
        
        # 创建测试用例任务列表
        tasks = []
        for test_id in test_ids:
            test_data = df[df["测试ID"] == test_id].sort_values("轮次")
            tasks.append(evaluate_test_case(test_data, df))
        
        # 并发执行所有测试用例的评估
        print("开始并发评估所有测试用例...")
        await asyncio.gather(*tasks)
        
        # 确定输出路径
        if not output_path:
            file_path = Path(excel_path)
            output_path = file_path.parent / f"{file_path.stem}_evaluated{file_path.suffix}"
            
        # 保存结果
        print(f"保存评估结果到: {output_path}")
        df.to_excel(output_path, index=False)
        print("评估完成！")
        
        # 输出评估统计
        eval_df = df[(df["轮次"] > 0) & (~df["意图分类"].isin(["NON_QUERY", "NEW_QUERY"]))]
        total_evaluated = len(eval_df)
        
        if total_evaluated > 0:
            intent_correct = eval_df["意图正确"].sum()
            sql_correct = eval_df["SQL正确"].sum()
            overall_correct = eval_df["评估结果"].sum()
            
            # 计算SQL生成类型的正确率
            sql_gen_df = eval_df[eval_df["意图分类"] == "SQL_GENERATION"]
            sql_gen_count = len(sql_gen_df)
            sql_gen_correct = sql_gen_df["SQL正确"].sum() if sql_gen_count > 0 else 0
            
            print(f"\n评估统计结果:")
            print("-" * 40)
            print(f"总评估轮次: {total_evaluated}轮 (不包括NON_QUERY和NEW_QUERY类型)")
            print(f"意图分类正确: {intent_correct}轮 ({intent_correct/total_evaluated*100:.2f}%)")
            
            if sql_gen_count > 0:
                print(f"SQL生成正确: {sql_gen_correct}轮 / {sql_gen_count}轮 SQL生成类型 ({sql_gen_correct/sql_gen_count*100:.2f}%)")
            else:
                print("没有SQL_GENERATION类型的轮次")
                
            print(f"整体评估正确: {overall_correct}轮 ({overall_correct/total_evaluated*100:.2f}%)")
            print("-" * 40)
        else:
            print("\n没有可评估的轮次 (所有轮次都是NON_QUERY/NEW_QUERY或轮次为0)")
        
    except Exception as e:
        print(f"评估过程出错: {e}")
        traceback.print_exc()

async def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="多轮对话Text2SQL评测工具")
    parser.add_argument("--file", "-f", help="要分析的Excel文件路径", default="test_results_202505071542_filtering_off.xlsx")
    parser.add_argument("--output", "-o", help="评估结果输出路径")
    
    args = parser.parse_args()
    
    excel_file = args.file
    
    if not os.path.exists(excel_file):
        print(f"错误：找不到Excel文件 '{excel_file}'")
        return
        
    # 执行评估
    await evaluate_multi_turn_results(excel_file, args.output)

if __name__ == "__main__":
    asyncio.run(main())
