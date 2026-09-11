from dashvector import Client
from util.rag_helpers import text_to_vectors_http, text_to_vectors_http_numpy,get_bgeM3embeddings
from dashvector import DashVectorCode
from loguru import logger
from dashvector import VectorQuery
from config.nacos.nacos_service import config


## 向量库连接
ali_vector_config = {
    'api_key': 'sk-HC9LFYoft9p9cIA3BtzV87d64rTqeB9B6DA2868F111EFB1FA8A7F64CD0414',
    'endpoint': 'vrs-cn-zim3wd1650002l.dashvector.cn-beijing.aliyuncs.com'
}
ali_vector_config = config.get("ali_vector_config")

ali_client = Client(api_key=ali_vector_config["api_key"], endpoint=ali_vector_config["endpoint"])

# 判断client是否创建成功
if ali_client:
    print('create ali_client success!')

collection_name = config['ali_vector_config']['collection']
print(f"{collection_name=}")
# 连接向量collection
edb_collection = ali_client.get(collection_name)



def search(query_vector:None, collection_name, output_fields, top_k=5, expr: str = None) -> list[dict]:
    # 6 向量搜索，进行搜索之前要先将 collection加载到内存
    collection = ali_client.get(collection_name)
    raw_results = collection.query(
        vector=query_vector,  # 向量检索，也可设置主键检索
        topk=top_k if top_k < 1024 else 1024,
        # filter=expr,
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
    for rank, hit in enumerate(hits, start=1):  # 使用 enumerate 增加序号
        field = hit.fields
        field_value = {
            "rank": rank,  # 新增序号字段
            "id": hit.id,
            "distance": hit.score
        }
        for output_field in output_fields:
            field_value[output_field] = field.get(output_field)
        result_list.append(field_value)
    return result_list

if __name__ == '__main__':
    outputFields = [
    "IND_DER_CODE", "INDIC_ID", "SEARCH", "SEARCH_IND_NAME","IND_DER_NAME", "DATA_TABLE", "SECURITY", "SECURITY_CODE",
    "AUTO_SRH_WORD", "CALIB", "UNIT", "FREQUENCY_CN",
    "INDUSTRY", "CONTENT_TYPE", "SOURCE", "DATASET_ID"
]
    query_emb = get_bgeM3embeddings(['阿里巴巴'])[0]
    emb_vec = VectorQuery(query_emb, ef=15000,is_linear=True)

    collection_name = "edb_market_similarity_query"

    result = search(emb_vec, collection_name, outputFields, top_k=10)
    print(f'edb召回相似字段：{result}')

