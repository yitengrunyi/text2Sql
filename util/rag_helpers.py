import asyncio
import json
import os
from collections import defaultdict
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from util.token_tracker import TokenTracker

from dashvector import VectorQuery
from pathlib import Path
import pickle
import requests
from dashvector import DashVectorCode
from requests.adapters import HTTPAdapter
# from text2vec import SentenceModel
from urllib3 import Retry
from loguru import logger
from sklearn.metrics.pairwise import cosine_similarity
from config.nacos.nacos_service import config
from common.enum.EmbedingType import EmbedingType
from FlagEmbedding import BGEM3FlagModel
from util.data_import import ali_client
from util.model_helpers import call_llm
import json_repair

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
bge_m3 = os.path.join(parent_dir, "model", "embedding", "bge-m3")
print(bge_m3)
# model = BGEM3FlagModel(bge_m3, use_fp16=True)
model = None

embedding_url_m3="http://192.168.66.14:8023/embeddings_normalize_query"
http_client_session = requests.Session()
adapter = requests.adapters.HTTPAdapter(pool_connections=100, pool_maxsize=100)
http_client_session.mount("http://", adapter)
http_client_session.mount("https://", adapter)
def get_top_k_similar(query_embedding, table_embeddings, K):
    similarities = []
    for column_name, embedding in table_embeddings.items():
        sim = cosine_similarity([query_embedding], [embedding])[0][0]
        similarities.append((column_name, sim))

    # 排序，按相似度降序排列，获取Top K
    top_k = sorted(similarities, key=lambda x: x[1], reverse=True)[:K]

    return top_k


def fetch_topk_rag_result(table_name, query_embedding, embedding_dict, K):

    # 从字典中获取该表的所有embeddings
    table_embeddings = embedding_dict.get(table_name, {})
    # 获取Top K的相似结果
    top_k_results = get_top_k_similar(query_embedding, table_embeddings, K)

    return top_k_results


def fetch_topk_rag_fix_result(table_name, query_embedding, embedding_dict, K):

    # 从字典中获取该表的所有embeddings
    # table_embeddings = embedding_dict.get(table_name, {})
    # 获取Top K的相似结果
    top_k_results = get_top_k_similar(query_embedding, embedding_dict, K)

    return top_k_results


def text_to_vectors_http(text_data):
    payload = json.dumps({
        "content": [
            text_data
        ],
        "max_length": 510
    })
    headers = {
        'Content-Type': 'application/json'
    }

    # 创建一个 Retry 对象
    retries = Retry(
        total=5,  # 总重试次数
        backoff_factor=0.1,  # 回退因子，用于计算每次重试的延迟时间
        status_forcelist=[500, 502, 503, 504],  # 针对哪些 HTTP 状态码进行重试
    )

    # 创建一个 HTTPAdapter 对象，并将 Retry 对象传入
    adapter = HTTPAdapter(max_retries=retries)

    # 将适配器挂载到 HTTP 会话对象
    http_client_session.mount('http://', adapter)
    http_client_session.mount('https://', adapter)

    # 执行请求
    response = http_client_session.request("POST", embedding_url_m3, headers=headers, data=payload, timeout=30)

    if response.status_code != 200:
        logger.info(
            f"Request failed with status code: {response.status_code}, response: {response},request data: {payload}")
        return text_to_vectors(text_data)
    # return response.json().get("embeddings")[0] 目前这个远程的不是BGE-M3 先使用本地的代替后续部署后再使用远程 todo
    return text_to_vectors(text_data)



def text_to_vectors_http_numpy(text_data):
    # try:
    #     payload = json.dumps({
    #         "content": [
    #             text_data
    #         ],
    #         "max_length": 510
    #     })
    #     headers = {
    #         'Content-Type': 'application/json'
    #     }
    #
    #     # 创建一个 Retry 对象
    #     retries = Retry(
    #         total=5,  # 总重试次数
    #         backoff_factor=0.1,  # 回退因子，用于计算每次重试的延迟时间
    #         status_forcelist=[500, 502, 503, 504],  # 针对哪些 HTTP 状态码进行重试
    #     )
    #
    #     # 创建一个 HTTPAdapter 对象，并将 Retry 对象传入
    #     adapter = HTTPAdapter(max_retries=retries)
    #
    #     # 将适配器挂载到 HTTP 会话对象
    #     http_client_session.mount('http://', adapter)
    #     http_client_session.mount('https://', adapter)
    #
    #     # 执行请求
    #     response = http_client_session.request("POST", embedding_url_m3, headers=headers, data=payload, timeout=30)
    #
    #     if response.status_code != 200:
    #         logger.info(
    #             f"Request failed with status code: {response.status_code}, response: {response},request data: {payload}")
    #         return text_to_vectors_numpy(text_data)
    #     return response.json().get("embeddings")
    # # return text_to_vectors_numpy(text_data)
    # except Exception as e:
    #     logger.error(f"向量化出现异常{str(e)}")
        return text_to_vectors_numpy(text_data)

from typing import List, Optional
def get_bgeM3embeddings(sentences: List[str], max_length: Optional[int] = 256, url: str = config['bge_m3_url']) -> List[List[float]]:
    """
    获取句子的嵌入向量。

    :param sentences: 需要编码的句子列表。
    :param max_length: 句子的最大长度（可选，默认为 256）。
    :param url: FastAPI 接口的 URL（可选，默认为本地服务地址）。
    :return: 返回句子的嵌入向量列表。
    """
    # 构造请求体
    data = {
        "content": sentences,
        "max_length": max_length
    }

    try:
        # 发送 POST 请求
        response = requests.post(url, json=data)
        response.raise_for_status()  # 检查请求是否成功
        result = response.json()  # 解析 JSON 响应
        return result["embeddings"]
    except requests.exceptions.RequestException as e:
        print(f"请求失败: {e}")
        return []
    except KeyError:
        print("响应格式错误，未找到 'embeddings' 字段。")
        return []


def text_to_vectors_http_batch(text_data_list):
    payload = json.dumps({
        "content": text_data_list,
        "max_length": 510
    })
    headers = {
        'Content-Type': 'application/json'
    }

    # 创建一个 Retry 对象
    retries = Retry(
        total=5,  # 总重试次数
        backoff_factor=0.1,  # 回退因子，用于计算每次重试的延迟时间
        status_forcelist=[500, 502, 503, 504],  # 针对哪些 HTTP 状态码进行重试
    )

    # 创建一个 HTTPAdapter 对象，并将 Retry 对象传入
    adapter = HTTPAdapter(max_retries=retries)

    # 将适配器挂载到 HTTP 会话对象
    http_client_session.mount('http://', adapter)
    http_client_session.mount('https://', adapter)

    # 执行请求
    response = http_client_session.request("POST", embedding_url_m3, headers=headers, data=payload, timeout=30)

    if response.status_code != 200:
        logger.error(
            f"Request failed with status code: {response.status_code}, response: {response},request data: {payload}")
        raise Exception()
    return response.json().get("embeddings")



def search_by_group(query_vector, collection_name, output_fields, group_field,group_count ,group_topk, expr: str = None) -> list[dict]:
    # 6 向量搜索，进行搜索之前要先将 collection加载到内存
    collection = ali_client.get(collection_name)
    raw_results = collection.query_group_by(
        vector=query_vector,  # 向量检索，也可设置主键检索
        group_by_field=group_field,
        group_count=group_count,
        group_topk=group_topk,
        filter=expr,
        output_fields=output_fields,
        include_vector=False,
        async_req=True
    ).get()



    if raw_results is None or raw_results.code != DashVectorCode.Success:
        logger.error(f"raw_results is None or raw_results.code != 0, raw_results is {raw_results}")
        # send_feishu_alert("PaiPai", f"AliVectorDB 查询异常，raw_results is {raw_results}")
        return []

    hits = raw_results.output
    # 遍历hits，将hits中的每个hit的content_text取出来，放入一个dict，并且将这个dict放入一个list中，最后返回这个list
    result_list = []
    for group in hits:
        for doc in group.docs:
            field_value = {"id": doc.id, "distance": doc.score}
            for output_field in output_fields:
                value = doc.fields.get(output_field)
                field_value[output_field] = value
            result_list.append(field_value)

    return result_list


def search(query_vector, collection_name, output_fields, top_k=5, expr: str = None) -> list[dict]:
    # 6 向量搜索，进行搜索之前要先将 collection加载到内存
    collection = ali_client.get(collection_name)
    raw_results = collection.query(
        vector=query_vector,  # 向量检索，也可设置主键检索
        topk=top_k if top_k < 1024 else 1024,
        filter=expr,
        output_fields=output_fields,
        include_vector=False,
        async_req=True
    ).get()
    if raw_results is None or raw_results.code != DashVectorCode.Success:
        logger.error(f"raw_results is None or raw_results.code != 0, raw_results is {raw_results}")
        # send_feishu_alert("PaiPai", f"AliVectorDB 查询异常，raw_results is {raw_results}")
        return []

    hits = raw_results.output
    # 遍历hits，将hits中的每个hit的content_text取出来，放入一个dict，并且将这个dict放入一个list中，最后返回这个list
    result_list = []
    for hit in hits:
        field = hit.fields
        field_value = {"id": hit.id, "distance": hit.score}
        for output_field in output_fields:
            value = field.get(output_field)
            field_value[output_field] = value
        result_list.append(field_value)
    return result_list

def text_to_vectors(text_data):
    try:
        query_embedding = model.encode(''.join(text_data),
                                       batch_size=12,
                                       max_length=8192,
                                       )['dense_vecs']
    except Exception as e:
        logger.error("An error occurred during text to vectors use text2vec:", str(e))
        return None
    return query_embedding.tolist()

def text_to_vectors_numpy(text_data):
    try:
        query_embedding = model.encode(''.join(text_data),
                                       batch_size=12,
                                       max_length=8192,
                                       )['dense_vecs']
    except Exception as e:
        logger.error("An error occurred during text to vectors use text2vec:", str(e))
        return None
    return query_embedding


async def llm_field_filter(query: str, candidate_result, token_tracker: Optional["TokenTracker"] = None) -> list:
    """
    使用LLM筛选与查询相关的字段值。

    参数:
    query (str): 用户的查询问题。
    candidate_result (list): 待筛选的候选结果列表。
    token_tracker: TokenTracker 实例用于追踪 token 使用。

    返回:
    list: 筛选后的结果列表。
    """

    # 生成筛选提示信息
    prompt = f"""
    请筛选出与"{query}"相关的值，筛选结果以JSON格式的数组输出。
    注意：
    1. 输出格式必须是有效的JSON数组格式
    2. 即使轻微相关也算可以被筛选
    3. 只输出JSON数组，不要输出其他任何内容
    
    待筛选结果：
    {candidate_result}
    
    以json列表形式输出:
    ```json
    ["值1", "值2", "值3"]
    ```
    """

    try:
        # 调用大模型获取筛选结果
        response = await call_llm(prompt=prompt, model="gpt-4.1", token_tracker=token_tracker)
        
        # 使用 json_repair 解析响应
        field_list = json_repair.loads(response)
        
        if isinstance(field_list, list):
            # 筛选候选结果中包含在field_list中的项目
            filtered_result = [item for item in candidate_result if item in field_list]
            logger.info(f"LLM字段筛选完成，原始数量: {len(candidate_result)}, 筛选后数量: {len(filtered_result)}")
            return filtered_result
        else:
            logger.warning("LLM返回的不是有效的列表格式，返回原始结果")
            return candidate_result
            
    except Exception as e:
        logger.error(f"LLM字段筛选失败: {str(e)}，返回原始结果")
        return candidate_result




if __name__ == '__main__':
    # query_em = text_to_vectors_numpy("上海电气")
    query_em = get_bgeM3embeddings(['中国宏观_货币与银行_社会融资规模增量（月）_社会融资规模增量_累计值'])[0]
    collection_name = "text2sql_domain_fields_data"
    # collection_name = 'text2sql_sec_domain_fields_data'
    outputFields = ['table_name','field_name','field_value']
    # expr = f"field_name='NAME'"
    expr = "table_name = 'GET_STK_SHR_CLS_DTL' AND field_name = 'NAME'"
    # expr = "table_name = 'VIEW_COM3106' AND field_name = 'F006v' AND sec_name IN ('阿帕契')"
    # expr = "table_name = 'VIEW_COM3105' AND field_name = 'F006V' AND sec_name IN ('美国铝业', '阿帕奇') OR sec_name IN ('AA.US', 'APA.US')"
    result = search(query_em, collection_name, outputFields,top_k=120,expr=expr)
    print(result)


