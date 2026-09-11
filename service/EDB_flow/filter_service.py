from util.model_helpers import extract_sql, process_filtered_data, format_tuples_as_table
from pprint import pformat
import time
import logging
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from util.token_tracker import TokenTracker

from config.nacos.nacos_service import config


async def do_llm_filter(
    top_230: list,
    query: str,
    query_desc: str,
    token_tracker: Optional["TokenTracker"] = None
):
    """
        如果 cfg.enable_llm_filter = False，则直接把 top_230 原样返回，
        同时构造 format_final_filtered_top_230、table_res，保证下游接口兼容。
        """
    if not config["edb_pipeline"]["enable_llm_filter"]:
        logging.info('############不启动llm过滤#############')
        # 1) final_filtered_top_230 就是原始召回结果
        final_filtered_top_230 = top_230

        # ❶ final_filtered_top_230 保持与原 LLM 流程 **完全一致** → 只保留 0~5 字段
        final_filtered_top_230 = [row[:6] for row in top_230]

        format_final_filtered_top_230 = format_tuples_as_table(final_filtered_top_230)

        # ❸ table_res 去重
        table_res = sorted({row[1] for row in final_filtered_top_230})

        return final_filtered_top_230, format_final_filtered_top_230, table_res

    """
    使用大模型对召回结果进行过滤，并返回过滤后的结果。
    """
    filter_start_time = time.time()
    logging.info(f"▌开始对召回结果进行 LLM 过滤...")

    # 构造用于 process_filtered_data 的初始元组：
    # [(index_in_top_230, search_ind_name), ...]
    filtered_top_230 = [
        (i, row[7]) for i, row in enumerate(top_230)
    ]


    # 并行过滤
    final_filtered_top_230, format_final_filtered_top_230, explain_result, converted_list = \
        await process_filtered_data(
            filtered_top_230=filtered_top_230,
            query=query,
            boundaries_query=None,
            top_230=top_230,
            query_desc = query_desc,
            max_retries=2,
            token_tracker=token_tracker,
        )

    # ===== 直接在此生成 table_res（表名位于索引 1）=====
    seen = set()
    table_res = []
    for r in final_filtered_top_230:
        if len(r) > 1:  # 防御式检查
            tbl = r[1]
            if tbl not in seen:
                seen.add(tbl)
                table_res.append(tbl)

    logging.info(f"▌结果过滤完成，耗时: {time.time() - filter_start_time:.2f}s")
    logging.info(f"整理过滤结果: {converted_list}")
    logging.info(f"原因解释: {explain_result}")
    logging.info(f"回查详细数据: {final_filtered_top_230}")
    logging.info("▌数据处理结果汇总：")
    logging.info(f"▌整理过滤结果（共{len(converted_list)}条）:\n{pformat(converted_list, width=120)}")
    logging.info(f"▌原因解释:\n{explain_result}")
    logging.info(
        f"▌回查数据样本（共{len(final_filtered_top_230)}条）:\n"
        f"{pformat(final_filtered_top_230[:3], width=120)}..."
    )
    logging.info(f"▌去重后的表名列表（共{len(table_res)}张表）：{table_res}")

    return final_filtered_top_230, format_final_filtered_top_230, table_res