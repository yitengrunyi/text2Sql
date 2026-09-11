import requests
import numpy as np
import json
import asyncio
import logging
from typing import List, Optional, Tuple, Dict
import os
import time
from util.rag_helpers import get_bgeM3embeddings

def find_similar_items(
    query: str, 
    top_k: int = 50, 
    embeddings_type: str = None
) -> List[str]:
    """
    同步版本：根据输入的查询找到最相似的项目。

    :param query: 查询文本
    :param top_k: 返回的相似项目数量
    :param embeddings_type: 嵌入向量类别，可选值：'概念', '二级行业', '三级行业'
    :return: 返回最相似的项目列表
    """
    try:
        start_time = time.time()
        
        # 定义embeddings_type到文件名的映射
        embeddings_file_map = {
            "概念": "concept_embeddings.json",
            "二级行业": "industry_level2_embeddings.json",
            "三级行业": "industry_level3_embeddings.json"
        }
        
        if not embeddings_type or embeddings_type not in embeddings_file_map:
            logging.error(f"无效的embeddings_type: {embeddings_type}，可选值为：{list(embeddings_file_map.keys())}")
            return []
            
        # 构建文件路径
        current_dir = os.path.dirname(os.path.abspath(__file__))
        data_file_path = os.path.join(current_dir, embeddings_file_map[embeddings_type])
        
        # 检查文件是否存在
        if not os.path.exists(data_file_path):
            logging.error(f"嵌入向量文件 {data_file_path} 不存在")
            return []
        
        # 加载嵌入向量
        load_start = time.time()
        with open(data_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        load_end = time.time()
        logging.info(f"加载嵌入向量文件耗时: {load_end - load_start:.4f} 秒")
        
        items = data["name"]
        item_embeddings = np.array(data["embedding"])
        
        # 获取查询文本的嵌入向量
        embed_start = time.time()
        query_embedding = get_bgeM3embeddings([query])
        embed_end = time.time()
        logging.info(f"获取查询嵌入向量耗时: {embed_end - embed_start:.4f} 秒")
        
        if not query_embedding:
            logging.error("无法获取查询文本的嵌入向量")
            return []
        
        query_embedding = np.array(query_embedding[0])
        
        # 计算相似度
        sim_start = time.time()
        # 归一化向量
        query_norm = query_embedding / np.linalg.norm(query_embedding)
        item_norms = item_embeddings / np.linalg.norm(item_embeddings, axis=1)[:, np.newaxis]
        
        # 计算相似度并获取top_k结果
        similarities = np.dot(item_norms, query_norm)
        top_indices = np.argsort(similarities)[::-1][:top_k]
        sim_end = time.time()
        logging.info(f"计算相似度和排序耗时: {sim_end - sim_start:.4f} 秒")
        
        results = [items[idx] for idx in top_indices]
        
        end_time = time.time()
        logging.info(f"总耗时: {end_time - start_time:.4f} 秒")
        
        return results
        
    except Exception as e:
        logging.error(f"查找相似项目时出错: {str(e)}")
        return []

async def find_similar_items_async(
    query: str, 
    top_k: int = 50, 
    embeddings_type: str = None
) -> List[str]:
    """
    异步版本：根据输入的查询找到最相似的项目。

    :param query: 查询文本
    :param top_k: 返回的相似项目数量
    :param embeddings_type: 嵌入向量类别，可选值：'概念', '二级行业', '三级行业'
    :return: 返回最相似的项目列表
    """
    try:
        start_time = time.time()
        
        # 定义embeddings_type到文件名的映射
        embeddings_file_map = {
            "概念": "concept_embeddings.json",
            "二级行业": "industry_level2_embeddings.json",
            "三级行业": "industry_level3_embeddings.json"
        }
        
        if not embeddings_type or embeddings_type not in embeddings_file_map:
            logging.error(f"无效的embeddings_type: {embeddings_type}，可选值为：{list(embeddings_file_map.keys())}")
            return []
            
        # 构建文件路径
        current_dir = os.path.dirname(os.path.abspath(__file__))
        data_file_path = os.path.join(current_dir, embeddings_file_map[embeddings_type])
        
        # 检查文件是否存在
        if not os.path.exists(data_file_path):
            logging.error(f"嵌入向量文件 {data_file_path} 不存在")
            return []
            
        # 加载嵌入向量
        load_start = time.time()
        with open(data_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        load_end = time.time()
        logging.info(f"加载嵌入向量文件耗时: {load_end - load_start:.4f} 秒")
        
        items = data["name"]
        item_embeddings = np.array(data["embedding"])
        
        # 获取查询文本的嵌入向量
        embed_start = time.time()
        query_embedding = get_bgeM3embeddings([query])
        embed_end = time.time()
        logging.info(f"获取查询嵌入向量耗时: {embed_end - embed_start:.4f} 秒")
        
        if not query_embedding:
            logging.error("无法获取查询文本的嵌入向量")
            return []
            
        query_embedding = np.array(query_embedding[0])
        
        # 计算相似度
        sim_start = time.time()
        # 归一化向量
        query_norm = query_embedding / np.linalg.norm(query_embedding)
        item_norms = item_embeddings / np.linalg.norm(item_embeddings, axis=1)[:, np.newaxis]
        
        # 计算相似度并获取top_k结果
        similarities = np.dot(item_norms, query_norm)
        top_indices = np.argsort(similarities)[::-1][:top_k]
        sim_end = time.time()
        logging.info(f"计算相似度和排序耗时: {sim_end - sim_start:.4f} 秒")
        
        results = [items[idx] for idx in top_indices]
        
        end_time = time.time()
        logging.info(f"总耗时: {end_time - start_time:.4f} 秒")
        
        return results
        
    except Exception as e:
        logging.error(f"查找相似项目时出错: {str(e)}")
        return []
