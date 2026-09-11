from dashvector import VectorQuery
from edb_vector import search
from util.rag_helpers import text_to_vectors_http, text_to_vectors_http_numpy,get_bgeM3embeddings, get_top_k_similar
import time
import asyncio
import logging
from typing import List, Dict, Any, Tuple
from config.nacos.nacos_service import config


# EDB关键指标召回
def retrieve_and_merge_indicators(query_text, original_top50, embedding_list, final_topN):
    """处理流程：
    1. 加载embedding数据（列表格式）
    2. 用您的函数召回Top30相似指标
    3. 与原始top50合并去重
    """
    # 2. 转换为get_top_k_similar需要的输入格式：{ind_der_code: embedding}
    table_embeddings = {
        item["ind_der_code"]: item["embedding"]
        for item in embedding_list
        if "ind_der_code" in item and "embedding" in item
    }

    # 3. 获取query embedding（需替换为您的实际函数）
    query_embedding = get_bgeM3embeddings([query_text])[0]

    # 4. 复用您的函数获取Top30相似项
    top_30_pairs = get_top_k_similar(query_embedding, table_embeddings, 30)  # 返回[(ind_der_code, sim), ...]

    # 5. 转换为目标格式并去重
    seen_codes = set()
    final_results = []

    # 优先添加召回结果
    logging.info('核心指标召回######')
    for idx, (ind_der_code, sim) in enumerate(top_30_pairs, 1):
        if ind_der_code in seen_codes or sim < 0.4:
            continue

        matched_item = next(
            (item for item in embedding_list if item.get("ind_der_code") == ind_der_code),
            None
        )
        if matched_item:
            seen_codes.add(ind_der_code)
            final_results.append((
                ind_der_code,
                matched_item["data_table"],
                matched_item["show_name_short"],
                matched_item["unit"],
                matched_item["freq"],
                matched_item["source"],
                1 - sim,
                matched_item["search_ind_name"]
            ))
            logging.info(
                f"{idx}.核心指标ID: {ind_der_code}.. | "
                f"名称: {matched_item['show_name_short']}.. | "
                f"来源: {matched_item['source']} | "
                f"相似度: {sim:.4f} | "
                f"表: {matched_item['data_table']} | "
                f"频率: {matched_item['freq']}"
            )

    # 补充original_top50中不重复的项
    for item in original_top50:
        if item[0] not in seen_codes:  # ind_der_code是第一个元素
            seen_codes.add(item[0])
            # 如果original_top50的项没有distance，默认设为1（优先级最低）
            distance = item[6] if len(item) > 6 else 1.0
            final_results.append((
                item[0], item[1], item[2], item[3], item[4], item[5], distance, item[7]
            ))

    # 按distance升序排序后返回
    return sorted(final_results, key=lambda x: x[6])[:final_topN]


def _search_with_name(vq: VectorQuery,
                      collection_name: str,
                      output_fields: List[str],
                      top_k: int,
                      name: str) -> Tuple[str, List[Dict[str, Any]]]:
    """
    同步包装：调用 search() 并给结果加 _source_embedding 字段，
    返回 (name, results) 方便并发后识别。
    """
    results = search(vq, collection_name, output_fields, top_k, name)
    for r in results:
        r["_source_embedding"] = name
    return name, results


async def do_vector_recall(
    query: str,
    embeddings_config: List[Dict[str, Any]],
    embedding_list: List[Dict[str, Any]],
    collection_name: str = config['ali_vector_config']['collection'],
    output_fields: List[str] = None,
    global_threshold: float = 0.4,
    final_topN: int = 300
):
    """
    通用的向量召回逻辑：
    1) 遍历 embeddings_config，每个 {name, embedding_vec, top_k} 做检索
    2) 将所有结果合并
    3) 过滤、去重、排序
    4) 可再调用 retrieve_and_merge_indicators 做附加处理
    5) 返回最终结果
    """
    if output_fields is None:
        output_fields = [
            "SHOW_NAME_SHORT",
            "SEARCH_IND_NAME",
            "INDIC_ID",
            "IND_DER_CODE",
            "FREQ",
            "UNIT",
            "REGION",
            "COUNTRY",
            "SOURCE",
            "DATA_TABLE",
        ]

    normalized_collection_name = (collection_name or "").strip()
    if normalized_collection_name != collection_name:
        logging.warning(
            "[do_vector_recall] collection_name has extra whitespace, normalized: %r -> %r",
            collection_name,
            normalized_collection_name,
        )
    collection_name = normalized_collection_name

    t_start = time.time()
    logging.info("[do_vector_recall] 开始向量召回...")

    # ========== 1) 并发收集搜索请求 ==========
    tasks = []
    for cfg in embeddings_config:
        name = cfg["name"]
        emb = cfg["embedding_vec"]
        top_k = cfg["top_k"]

        if emb is None:
            logging.warning(f"[{name}] embedding is None => skip.")
            continue

        vq = VectorQuery(emb, ef=10000)
        tasks.append(
            asyncio.to_thread(
                _search_with_name,
                vq,
                collection_name,
                output_fields,
                top_k,
                name,
            )
        )

    # ========== 2) 并发获取结果 ==========
    search_results_list = await asyncio.gather(*tasks, return_exceptions=False)

    # ========== 3) 合并所有结果 ==========
    all_results: List[Dict[str, Any]] = []
    total_raw = 0
    for name, res_list in search_results_list:
        logging.info(f"[{name}] => got {len(res_list)} results")
        brief_list = [
            {
                "ind_der_code": item.get("IND_DER_CODE"),
                "show_name_short": item.get("SHOW_NAME_SHORT"),
                "search_ind_name": item.get("SEARCH_IND_NAME"),
            }
            for item in res_list[:20]
        ]
        logging.info(f"[{name}] preview: {brief_list}")
        total_raw += len(res_list)
        all_results.extend(res_list)

    logging.info(f"[do_vector_recall] 共检索到 {total_raw} 条(含多embedding)")

    # 2.1 根据distance 过滤
    filtered = []
    for item in all_results:
        if item["distance"] >= global_threshold:
            ind_der_code = item.get("IND_DER_CODE")
            if not ind_der_code:
                continue
            row = (
                ind_der_code,
                item.get("DATA_TABLE"),
                item.get("SHOW_NAME_SHORT"),
                item.get("UNIT"),
                item.get("FREQ"),
                item.get("SOURCE"),
                item["distance"],
                item.get("SEARCH_IND_NAME"),
                item["_source_embedding"],
            )
            filtered.append(row)

    # 2.2 对 ind_der_code 去重
    seen_ids = set()
    deduped = []
    for row in filtered:
        code = row[0]
        if code not in seen_ids:
            seen_ids.add(code)
            deduped.append(row)

    # 2.3 按distance升序
    sorted_res = sorted(deduped, key=lambda x: x[6])

    # 3) 截取 final_topN
    final_res = sorted_res[:final_topN]

    # 4) 进一步合并/补充
    merged_res = retrieve_and_merge_indicators(query, final_res, embedding_list, final_topN)

    cost = time.time() - t_start
    logging.info(f"[do_vector_recall] total {len(all_results)} raw hits, final {len(merged_res)} after merge, cost: {cost:.2f}s")
    return merged_res
