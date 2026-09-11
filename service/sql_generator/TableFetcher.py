import collections
from typing import List, Tuple, Dict, Any, Optional
import abc
import ast
import collections


import pickle
from typing import List, Tuple, Optional

from util.db_helpers import query_from_db
from util.fix_fields import FIX_FIELDS, DYNAMIC_TABLES, recall_tables
from util.rag_helpers import fetch_topk_rag_result, search, llm_field_filter
from util.model_helpers import get_query_by_chat


# from FAISS_ANN import EmbeddingIndexManager


class BaseTableFetcher(abc.ABC):
    """
    基类：定义通用的查询与处理逻辑
    """

    def __init__(self, embedding_dict: dict):
        self.embedding_dict = embedding_dict

    # async def query_table_columns(self, table_names: Tuple[str, ...], hisvalid: int = 1) -> List[Tuple]:
    #     # table_names_str = table_names if isinstance(table_names, str) else tuple(table_names)
    #     # 确保 table_names 是一个元组
    #     if isinstance(table_names, str):
    #         table_names = (table_names,)
    #
    #     # 处理单元素元组的情况
    #     if len(table_names) == 1:
    #         table_names_str = f"('{table_names[0]}')"
    #     else:
    #         table_names_str = tuple(table_names)
    #     sql_query = f"""
    #     SELECT TABLE_ENAME, COLUMN_ENAME, COLUMN_CNAME, COLUMN_TYPE, COLUMN_CATEGORY, COLUMN_DESC
    #     FROM MDB_COLUMN_JULING
    #     WHERE TABLE_ENAME IN {table_names_str}  AND HISVALID={hisvalid}
    #     """
    #     return await query_from_db(sql_query)

    async def query_table_columns(
        self,
        table_names: Tuple[str, ...],
        hisvalid: int = 1,
        columns: Optional[List[str]] = None,
        order_by: Optional[str] = None
    ) -> List[Tuple]:
        """
        查询表的列信息，并可选地根据列名进行筛选和排序。

        参数:
        - table_names (Tuple[str, ...]): 表名元组。
        - hisvalid (int): 有效性标志。
        - columns (Optional[List[str]]): 需要筛选的列名列表。
        - order_by (Optional[str]): 排序逻辑。

        返回:
        - List[Tuple]: 查询结果。
        """
        if isinstance(table_names, str):
            table_names = (table_names,)

        if len(table_names) == 1:
            table_names_str = f"('{table_names[0]}')"
        else:
            table_names_str = tuple(table_names)

        # 构建筛选条件
        column_condition = ""
        if columns and len(columns) > 0:
            # col_tuple = tuple(columns)
            # 使用 ast.literal_eval 转换为元组
            col_tuple = ast.literal_eval(columns)
            if len(col_tuple) == 1:
                column_condition = f" AND COLUMN_ENAME IN ('{col_tuple[0]}')"
            else:
                cols_str = ', '.join([f"'{c}'" for c in col_tuple])
                column_condition = f" AND COLUMN_ENAME IN ({cols_str})"

        # 构建排序条件
        order_condition = f" ORDER BY {order_by}" if order_by else ""

        sql_query = f"""
        SELECT TABLE_ENAME, COLUMN_ENAME, COLUMN_CNAME, COLUMN_TYPE, COLUMN_CATEGORY, COLUMN_DESC
        FROM MDB_COLUMN_JULING
        WHERE TABLE_ENAME IN {table_names_str} AND HISVALID={hisvalid}{column_condition}
        {order_condition}
        """
        return await query_from_db(sql_query)

    def build_in_condition(self, fields: List[str]) -> Tuple[str, str]:
        field_tuple = tuple(fields)
        if len(field_tuple) == 1:
            field_tuple_str = f"('{field_tuple[0]}')"
            field_order_by = f"FIELD(COLUMN_ENAME, '{field_tuple[0]}')"
        else:
            combine_str = ', '.join([f"'{f}'" for f in field_tuple])
            field_tuple_str = f"({combine_str})"
            field_order_by = f"FIELD(COLUMN_ENAME, {combine_str})"
        return field_tuple_str, field_order_by

    @abc.abstractmethod
    async def fetch_table_info(self, table_res: List[str], **kwargs) -> Tuple[List[Tuple], Optional[Dict]]:
        """
        抽象方法，不同子类根据需求实现。
        返回值应为 (final_table_res, top3_candidates_dict)
        """
        pass


class DynamicTableFetcher(BaseTableFetcher):
    """
    专门处理动态表的类
    """

    def __init__(self, embedding_dict: dict, query_embedding: Any, K: int = 50):
        super().__init__(embedding_dict)
        self.query_embedding = query_embedding
        self.K = K

    async def fetch_table_info(self, table_res: List[str], **kwargs) -> Tuple[List[Tuple], Optional[Dict]]:
        final_table_list = tuple(table_res)
        dynamic_tables = [table_name.upper() for table_name in final_table_list if table_name.upper() in DYNAMIC_TABLES]
        final_table_res = []
        table_field_map = collections.defaultdict(list)

        for table_name in dynamic_tables:
            table_field_map[table_name].extend(FIX_FIELDS.get(table_name, []))
            filtered_res = fetch_topk_rag_result(table_name, self.query_embedding, self.embedding_dict, self.K)

            for item, _ in filtered_res:
                if item not in table_field_map[table_name]:
                    table_field_map[table_name].append(item)

            field_tuple_str, field_order_by = self.build_in_condition(table_field_map[table_name])
            # sql_query = f"""
            # SELECT TABLE_ENAME, COLUMN_ENAME, COLUMN_CNAME, COLUMN_TYPE, COLUMN_CATEGORY, COLUMN_DESC
            # FROM MDB_COLUMN_JULING
            # WHERE TABLE_ENAME = '{table_name}' AND COLUMN_ENAME IN {field_tuple_str} AND HISVALID=1
            # ORDER BY {field_order_by}
            # """
            # 使用 query_table_columns 方法进行查询
            # query_res = await self.query_table_columns((table_name,), hisvalid=1, field_tuple_str, field_order_by)
            # query_res = await query_from_db(sql_query)
            # 调用 query_table_columns 并传递 columns 和 order_by 参数
            query_res = await self.query_table_columns(
                table_names=(table_name,),
                hisvalid=1,
                columns=field_tuple_str,
                order_by=field_order_by
            )
            final_table_res.extend(query_res)

        return final_table_res, None  # DynamicTableFetcher 不需要返回 top3_candidates_dict


class FixTableFetcher(BaseTableFetcher):
    """
    专门处理固定表的类，可选添加top3候选值逻辑
    """

    def __init__(self, embedding_dict: dict, entity_embedding: Any = None, embedding_dict_field: dict = None,
                 need_top30_candidates: bool = False, K: int = 3):
        super().__init__(embedding_dict)
        self.entity_embedding = entity_embedding
        self.embedding_dict_field = embedding_dict_field
        self.need_top30_candidates = need_top30_candidates
        self.K = K  # top3

    async def fetch_table_info(self, us_stock_codes:List[str], table_res: List[str],query, companies, **kwargs) -> Tuple[List[Tuple], Optional[Dict]]:
        fix_tables = [table_name.upper() for table_name in table_res if table_name.upper() not in DYNAMIC_TABLES]
        final_table_res = []
        top30_candidates_dict = {} if self.need_top30_candidates else None

        if len(fix_tables) == 0:
            return final_table_res, top30_candidates_dict

        if len(fix_tables) == 1:
            fix_tables_str = f'{fix_tables[0]}'
        else:
            fix_tables_str = tuple(fix_tables)

        query_res = await self.query_table_columns(fix_tables_str, hisvalid=1)

        if (not self.need_top30_candidates) or (self.entity_embedding is None) :
            # 不需要top3候选值，直接返回结果
            final_table_res.extend(query_res)
            return final_table_res, top30_candidates_dict

        # 需要top30候选值逻辑
        for table_name in fix_tables:
            table_fields = [row for row in query_res if row[0].upper() == table_name.upper()]
            field_names = [row[1] for row in table_fields]



            # if table_name not in self.embedding_dict_field:
            #     # 没有该表的字段嵌入
            #     for record in table_fields:
            #         final_table_res.append(tuple(record) + (None,))
            #     continue

            # table_field_embeddings = self.embedding_dict_field[table_name]
            # manager = EmbeddingIndexManager(self.embedding_dict_field, use_inner_product=True)

            # for field in field_names:
            #     field_records = [r for r in table_fields if r[1] == field]
            #
            #     if field in table_field_embeddings:
            #         field_values_embeddings = table_field_embeddings[field]
            #         topk_field_values = fetch_topk_rag_fix_result(table_name, self.entity_embedding,
            #                                                       field_values_embeddings, K=self.K)
            #         # FAISS-ANN
            #         topk_field_values = manager.get_top_k_similar_ann(self.entity_embedding, K=3)
            #
            #         matched_values = [candidate_value for candidate_value, _ in topk_field_values]
            #
            #         # 检查 matched_values 是否为空
            #         if len(matched_values) > 0:
            #             top3_candidates_dict[(table_name, field)] = matched_values
            #
            #             for record in field_records:
            #                 final_table_res.append(tuple(record) + ('该字段的候选值是：' + str(matched_values),))
            #         else:
            #             for record in field_records:
            #                 final_table_res.append(tuple(record) + (None,))
            #     else:
            #         for record in field_records:
            #             final_table_res.append(tuple(record) + (None,))
            for field in field_names:
                field_records = [r for r in table_fields if r[1] == field]
                # 不再使用 self.embedding_dict_field，直接通过 search 获取结果
                # for recall_table_name in table_res:
                if table_name.upper() in recall_tables and field in {v[0] for v in recall_tables.values()}:
            # if table_name.upper() == 'STK_SHR_CLS_DTL' and field == 'NAME' :
                # 根据 table_name 和 field_name 在向量引擎中搜索对应的 top K 候选值
                    # expr = f"table_name = 'STK_SHR_CLS_DTL'"
                    # expr = f"table_name = '{table_name}' AND field_name = '{recall_tables[table_name.upper()][0]}'"
                    # collection_name = "text2sql_domain_fields_data"
                    # outputFields = ['table_name', 'field_name', 'field_value']
                    outputFields = ['field_value']
                    if not companies:
                        collection_name = "text2sql_domain_fields_data"
                        expr = (f"table_name = '{table_name}' AND field_name = '{recall_tables[table_name.upper()][0]}'")
                    # 获取top120
                        result = search(self.entity_embedding, collection_name, outputFields, top_k=120, expr=expr)
                        # 提取 field_value 并去重
                        result = list(set(item['field_value'] for item in result))
                        import logging
                        logging.info(f'未过滤top120{result}')
                    elif table_name.upper() == 'GET_STK_SHR_CLS_DTL':
                        collection_name = "text2sql_domain_fields_data"
                        expr = (f"table_name = '{table_name}' AND field_name = '{recall_tables[table_name.upper()][0]}'")
                        # 获取top120
                        result = search(self.entity_embedding, collection_name, outputFields, top_k=120, expr=expr)
                        # 提取 field_value 并去重
                        result = list(set(item['field_value'] for item in result))
                        import logging
                        logging.info(f'股东未过滤top120{result}')
                    else:
                        collection_name = "text2sql_sec_domain_fields_data"
                        companies_tuple = "(" + ", ".join(f"'{company}'" for company in companies) + ")"
                        us_stock_codes_tuple = "(" + ", ".join(f"'{us_stock_code}'" for us_stock_code in us_stock_codes) + ")"
                        expr = (f"table_name = '{table_name}' AND field_name = '{recall_tables[table_name.upper()][0]}' "
                                f"AND sec_name IN {companies_tuple} OR sec_name IN {us_stock_codes_tuple}")
                        # 获取top30
                        result = search(self.entity_embedding, collection_name, outputFields, top_k=30, expr=expr)
                        # 提取 field_value 并去重
                        result = list(set(item['field_value'] for item in result))
                        import logging
                        logging.info(f'未过滤top30{result}')
                        logging.info(f'expr:{expr}')
                    if len(result) > 0:
                        #llm过滤选出top10
                        result = await llm_field_filter(query, result)
                        logging.info(f'过滤后的top30{result}')
                        # 从检索结果中获取 field_value
                        matched_values = [r for r in result]
                        top30_candidates_dict[(table_name, field)] = matched_values

                        for record in field_records:
                            final_table_res.append(tuple(record) + ('该字段的候选值是：' + str(matched_values),))
                    else:
                        # 没有查到对应候选值
                        for record in field_records:
                            final_table_res.append(tuple(record) + (None,))
                else:
                    for record in field_records:
                        final_table_res.append(tuple(record) + (None,))

        return final_table_res, top30_candidates_dict


class TableInfoService:
    """
    使用组合的方式，从而根据需求灵活选择 fetcher 来获取结果。
    """

    def __init__(self, dynamic_fetcher: DynamicTableFetcher = None, fix_fetcher: FixTableFetcher = None):
        self.dynamic_fetcher = dynamic_fetcher
        self.fix_fetcher = fix_fetcher

    async def fetch_table_info(self, table_res: List[str], query) -> Tuple[List[Tuple], Dict]:
        final_table_res = []
        top30_candidates_dict = {}

        # 动态表信息获取
        if self.dynamic_fetcher:
            dynamic_res, _ = await self.dynamic_fetcher.fetch_table_info(table_res)
            final_table_res.extend(dynamic_res)

        # 固定表信息获取
        if self.fix_fetcher:
            fix_res, fix_candidates = await self.fix_fetcher.fetch_table_info(table_res, query)
            final_table_res.extend(fix_res)
            if fix_candidates:
                top30_candidates_dict.update(fix_candidates)

        return final_table_res, top30_candidates_dict



class TableInfoService:
    """
    使用组合的方式，从而根据需求灵活选择 fetcher 来获取结果。
    """

    def __init__(self, dynamic_fetcher: DynamicTableFetcher=None, fix_fetcher: FixTableFetcher=None):
        self.dynamic_fetcher = dynamic_fetcher
        self.fix_fetcher = fix_fetcher

    async def fetch_table_info(self, us_stock_codes:List[str], table_res: List[str], query, companies: Optional[List[str]] ) -> Tuple[List[Tuple], Dict]:
        final_table_res = []
        top30_candidates_dict = {}

        # 动态表信息获取
        if self.dynamic_fetcher:
            dynamic_res, _ = await self.dynamic_fetcher.fetch_table_info(table_res)
            final_table_res.extend(dynamic_res)

        # 固定表信息获取
        if self.fix_fetcher:
            fix_res, fix_candidates = await self.fix_fetcher.fetch_table_info(us_stock_codes, table_res, query, companies)
            final_table_res.extend(fix_res)
            if fix_candidates:
                top30_candidates_dict.update(fix_candidates)

        return final_table_res, top30_candidates_dict


# 使用示例
# 初始化不同的fetcher
# dynamic_fetcher = DynamicTableFetcher(embedding_dict=embedding_dict, query_embedding=query_embedding)
# fix_fetcher = FixTableFetcher(embedding_dict=embedding_dict, entity_embedding=entity_embedding, embedding_dict_field=embedding_dict_field, need_top3_candidates=True)
# service = TableInfoService(dynamic_fetcher=dynamic_fetcher, fix_fetcher=fix_fetcher)
# result, top3_candidates_dict = await service.fetch_table_info(table_res)