from ast import literal_eval
from datetime import datetime
import logging
from decimal import Decimal
import asyncio
import pandas
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from util.token_tracker import TokenTracker

from common.middleware.redis_util import redis_client
from util.model_helpers import get_query_by_chat_gpt_4_1, call_llm
from textwrap import dedent
data_limit_num = 100
data_all_num = 1000

data_list = ['CURRENCY', 'BASE_DATE_TYPE', 'SUB_POST', 'SEC_TYPE', 'FRZ_TYPE', 'SEC_CODE', 'REFCTGDIVDST', 'FRZCOM_CODE', 'GUAR_IF_CON', 'REFMED', 'GUARD_REL', 'FST_COURT', 'REFCCLUBAPCTSHG', 'P_SEQ', 'LIST_EXCHANGE_CODE', 'GUARD_CODE', 'ORGCODE', 'REFCINTRTSTY', 'GUAR_IF_OVE', 'CMNT_HCODE', 'ComCode', 'RARC_CODE', 'IS_FIRST_HOLDER', 'COMCODE', 'STKUNICODE', 'RELA_ITEM', 'IMPAWN_TYPE', 'INDU_CODE', 'RELA_COM_CODE', 'IF_EXECUTE_DIR', 'TOPCODE', 'REFCLEAOFCRSN', 'STATIS_CLS', 'DIST_CLS_CODE', 'IS_SHORT_TRADE', 'ADD_SUB_TYPE', 'IDVUNIC', 'MNG_POST_CODE', 'IS_DELIST', 'FUND_HCODE', 'CAL_TYPE', 'LITI_CODE', 'STK_CLS_CODE', 'REFCITYTY', 'BUY_CODE', 'CSRC_RESULT', 'LIST_EXCHANGE', 'REFCSHHNTU', 'GUAR_CODE', 'FLAGDPSN', 'ITEM_ID', 'RWXACC_CODE', 'RELA_CODE', 'REFCCHSTUDDPL', 'DIR_POST_CODE', 'ISAUCTION', 'APPINS_CODE', 'FIXED_ID', 'CURNCY', 'FRZ_ADM_CODE', 'INST_HCODE', 'PT_POST_CODE', 'CHNG_TYPE_CODE', 'INDEX_CODE', 'IMPAWN_SHR_TYPE', 'ADD_SUB_CLS', 'NTUREFCINTRTS', 'CONCEPT_HCODE', 'FRZCOMCD', 'ISIMPAWN', 'SEC_INNER_CODE', 'MON_TYPE_ONE', 'IS_RWD', 'OBJ_INNER_CODE', 'SEC_COURT', 'SW2_IND_HCODE', 'UNICDIVCUR', 'IVST_TYPE_CODE', 'LITI_TYPE', 'SHR_TYPE', 'INDI_ID', 'BASE_DATE_CODE', 'P_SEQ_PLAN', 'ISS_TYPE_CODE', 'STK_CLS', 'PRG', 'IS_OVER_FIVE', 'PSNREFC', 'POST_CODE', 'LEAVE_RSN_CODD', 'REFCSELRTSTYDCS', 'CURUNICINTRTS', 'CHNG_TYPE', 'SW1_IND_HCODE', 'OTH_RWD', 'SEC_HCODE', 'COMP_HCODE', 'ISS_CLS_CODE', 'RPT_SRC', 'REFCINFOSOU', 'CURNCY_CLS_ID', 'BUY_CODE_MARK', 'GUAR_CURTYPE', 'ORG_CODE', 'comcode', 'RELA_ORG_CODE', 'INDX_CODE', 'LAW_TYPE', 'IVST_OBJ_CODE', 'COMUNIC', 'ADD_OBJ_TYPE', 'Party_Sort', 'IMPAWN_CODE', 'COMPANY_CODE', 'ISALL', 'CURUNICBSCVS', 'P_SEQ_INTRO', 'PSN_HCODE', 'INDUSTRY_HCODE', 'SW3_IND_HCODE', 'GUAR_REL', 'CURTYPE', 'REFCDIVTY', 'ON_DUTY', 'REPORT_CODE', 'FRZSHR_SROT', 'REFCINTOBJ', 'PRG_CODE', 'ADD_CODE', 'ORG_CODE_MARK', 'INNER_CODE', 'SEC_ACCUSER', 'INVSG_HCODE', 'ParentCode', 'INDEX_HCODE', 'INCT_TYPE_CODE', 'IS_CTRL', 'HOLDER_CODE', 'Party_Code', 'REPU_TYPE']
del_columns = ['内部公司代码' , '内部参考代码']
# @staticmethod
def format_number(value):
    # 新增：统一处理所有缺失值（包括 NaN、NaT、None 等）
    if pandas.isna(value):  # 使用 pandas 的缺失值检测
        return "-"
    # 处理时间类型（兼容 pandas.Timestamp 和原生 datetime）
    elif isinstance(value, (datetime, pandas.Timestamp)):
        return value.strftime("%Y-%m-%d")
    # 处理数值类型（int/float/Decimal）
    elif isinstance(value, (int, float, Decimal)):
        if isinstance(value, int):
            return "{:,}".format(value)
        else:
            return "{:,.2f}".format(value)
    # 处理字符串类型
    elif isinstance(value, str):
        try:
            # 尝试解析日期字符串（如果字符串符合格式）
            date_obj = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
            return date_obj.strftime("%Y-%m-%d")
        except ValueError:
            return str(value)
    # 其他类型转为字符串
    else:
        return str(value)



def df_to_table(question_id, columns_to_drop ,table: pandas.DataFrame) -> str:
    if table is None or table.empty:
        return ""

    # 固定删除 COMCODE1 和 COMCODE2 列（如果存在）
    merged_list = columns_to_drop + del_columns
    existing_cols = [col for col in merged_list if col in table.columns]
    if existing_cols:
        table = table.drop(columns=existing_cols)
        # 删列后检查是否为空
        if table.empty:
            return ""

    # 后续原有处理逻辑
    arr = table.values.tolist()
    for ar in arr:
        for i in range(0, len(ar)):
            if ar[i] is None:
                ar[i] = "-"
            else:
                ar[i] = format_number(ar[i])

    arr.insert(0, table.columns)

    if len(arr) > data_limit_num + 1:
        # 保存全量最多1000数组到缓存
        arr = arr[:data_all_num + 1]

    key = "text_to_sql_data_" + str(question_id)
    logging.info(f'redis缓存数据结果的key={key}')
    redis_client.set(key, str([list(t) for t in arr]), ex=60*60*24*7)
    if not key.endswith("_0"):
        key = key[:-2] + "_0"
        redis_client.set(key, str([list(t) for t in arr]), ex=60 * 60 * 24 * 7)
    # 开始截取
    arr = arr[:data_limit_num + 1]

    return "{table:" + str([list(t) for t in arr]) + "}"



def format_to_4_decimal_places(value):
    # 判断是否是整数或浮点数
    if isinstance(value, (int, float)):
        return "{:.4f}".format(value)
    else:
        return str(value)

def format_and_filter_tuples(data_str, valid_columns):
    # 使用 literal_eval 安全解析字符串
    data = literal_eval(data_str)
    # 筛选符合条件的元组
    filtered_data = [item[1] for item in data if item[0].upper() in valid_columns]
    return filtered_data

async def get_filter_colunms_name(sql_str, token_tracker: Optional["TokenTracker"] = None):
    try:
        prompt = f"""
            {sql_str}\n
            请抽取sql里的SELECT的字段以及别名，用二元组列表的形式给我（字段名，别名），注意如果有二次计算的指标，则只给我那个指标里的字段以及指标对应的别名,还有字段不要带表前缀
        注意！！！光给我二元组列表，不要有其他任何的输出
            """
        alias_res = await call_llm(prompt=prompt, model="gpt-4.1", token_tracker=token_tracker)
        data_str = dedent(alias_res).strip()
        # 格式化并过滤数据
        result = format_and_filter_tuples(data_str, data_list)
    except Exception as e:
        return []
    return result