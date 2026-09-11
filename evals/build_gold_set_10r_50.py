#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从已标注评测集构建 10 轮 x 5 问的可复现 Gold Set。"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from sqlglot import exp, parse_one


ROOT = Path(__file__).resolve().parent.parent
SOURCE_SET = ROOT / "evals/gold_set_180.json"
OUTPUT_SET = ROOT / "evals/gold_set_10r_50.json"

# 每轮索引包括首问 t0。第 7 轮跳过会随每日行情重算的 YTD 题。
KEEP_INDICES = {
    1: (0, 1, 2, 3, 4),
    2: (0, 1, 2, 3, 4),
    3: (0, 1, 2, 3, 4),
    4: (0, 1, 2, 3, 4),
    5: (0, 1, 2, 3, 4),
    6: (0, 1, 2, 3, 4),
    7: (0, 1, 2, 4, 5),
    8: (0, 1, 2, 3, 4),
    9: (0, 1, 2, 3, 4),
    10: (0, 1, 2, 3, 4),
}


ROUND_10 = [
    {
        "question": "苹果公司当前样本的总市值是多少？",
        "judge": "numeric",
        "gold_value": "27907200",
        "gold_display": "27,907,200 百万美元（本地样本值）",
        "gold_entities": ["苹果"],
        "gold_sql": "SELECT m.CSNAME, c.F013N FROM COM3101 c JOIN AMERICAN_STOCK_MAIN m ON m.FIU_ID=c.FIU_ID WHERE m.SYMBOL='AAPL'",
        "gold_tables": ["COM3101", "AMERICAN_STOCK_MAIN"],
        "gold_date": None,
        "labels": {"followup_type": None, "difficulty": "多表join", "route_gold": None, "time_sensitivity": "snapshot"},
    },
    {
        "question": "微软的呢？",
        "judge": "numeric",
        "gold_value": "26373600",
        "gold_display": "26,373,600 百万美元（本地样本值）",
        "gold_entities": ["微软"],
        "gold_sql": "SELECT m.CSNAME, c.F013N FROM COM3101 c JOIN AMERICAN_STOCK_MAIN m ON m.FIU_ID=c.FIU_ID WHERE m.SYMBOL='MSFT'",
        "gold_tables": ["COM3101", "AMERICAN_STOCK_MAIN"],
        "gold_date": None,
        "labels": {"followup_type": "指代继承", "difficulty": "多表join", "route_gold": "SQL_GENERATION", "time_sensitivity": "snapshot"},
    },
    {
        "question": "苹果、微软和英伟达中，谁的当前样本总市值最高？",
        "judge": "entity",
        "gold_value": "30870000",
        "gold_display": "英伟达，30,870,000 百万美元（本地样本值）",
        "gold_entities": ["英伟达"],
        "gold_sql": "SELECT m.SYMBOL, m.CSNAME, c.F013N FROM COM3101 c JOIN AMERICAN_STOCK_MAIN m ON m.FIU_ID=c.FIU_ID WHERE m.SYMBOL IN ('AAPL','MSFT','NVDA') ORDER BY c.F013N DESC LIMIT 1",
        "gold_tables": ["COM3101", "AMERICAN_STOCK_MAIN"],
        "gold_date": None,
        "labels": {"followup_type": "条件追加", "difficulty": "多表join", "route_gold": "SQL_GENERATION", "time_sensitivity": "snapshot"},
    },
    {
        "question": "换成特斯拉，它当前样本的市盈率是多少？",
        "judge": "numeric",
        "gold_value": "73.27",
        "gold_display": "73.27 倍（本地样本值）",
        "gold_entities": ["特斯拉"],
        "gold_sql": "SELECT m.CSNAME, c.F021N FROM COM3101 c JOIN AMERICAN_STOCK_MAIN m ON m.FIU_ID=c.FIU_ID WHERE m.SYMBOL='TSLA'",
        "gold_tables": ["COM3101", "AMERICAN_STOCK_MAIN"],
        "gold_date": None,
        "labels": {"followup_type": "条件修改", "difficulty": "多表join", "route_gold": "SQL_GENERATION", "time_sensitivity": "snapshot"},
    },
    {
        "question": "当前本地美股样本中，市盈率最低的是哪只股票？市盈率是多少？",
        "judge": "entity",
        "gold_value": "9.35",
        "gold_display": "京东-W（JD），9.35 倍（本地样本值）",
        "gold_entities": ["京东-W"],
        "gold_sql": "SELECT m.SYMBOL, m.CSNAME, c.F021N FROM COM3101 c JOIN AMERICAN_STOCK_MAIN m ON m.FIU_ID=c.FIU_ID WHERE c.F021N IS NOT NULL ORDER BY c.F021N ASC LIMIT 1",
        "gold_tables": ["COM3101", "AMERICAN_STOCK_MAIN"],
        "gold_date": None,
        "labels": {"followup_type": "条件追加", "difficulty": "多表join", "route_gold": "SQL_GENERATION", "time_sensitivity": "snapshot"},
    },
]


def load_schema(source: str) -> dict:
    path = ROOT / f"evals/schema_{source}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def derive_gold_columns(sql: str, tables: list[str], schema: dict) -> dict[str, list[str]]:
    """按 SQL 表别名将标准字段归属到具体表。"""
    tree = parse_one(sql, read="mysql")
    table_names = [name.upper() for name in tables]
    aliases: dict[str, str] = {}
    for table in tree.find_all(exp.Table):
        name = str(table.name).upper()
        if name not in table_names:
            continue
        aliases[name] = name
        aliases[str(table.alias_or_name).upper()] = name

    result = {table: set() for table in table_names}
    select_aliases = {
        str(item.alias).upper()
        for item in tree.selects
        if getattr(item, "alias", None)
    }
    for column in tree.find_all(exp.Column):
        name = str(column.name).upper()
        if name in select_aliases and not column.table:
            continue
        if column.table:
            owner = aliases.get(str(column.table).upper())
            if owner and name in schema.get(owner, {}).get("columns", {}):
                result[owner].add(name)
            continue
        owners = [
            table for table in table_names
            if name in schema.get(table, {}).get("columns", {})
        ]
        if len(owners) == 1:
            result[owners[0]].add(name)

    return {table: sorted(columns) for table, columns in result.items()}


def fix_round_8(turns: list[dict]) -> None:
    names = ["苹果公司", "特斯拉", "英伟达", None, "微软"]
    symbols = ["AAPL", "TSLA", "NVDA", None, "MSFT"]
    for index, turn in enumerate(turns):
        turn["gold_date"] = "2026-08-25"
        turn["labels"]["time_sensitivity"] = "absolute"
        if index == 3:
            turn["question"] = "2026年8月25日，苹果、特斯拉、英伟达中谁的收盘价最高？"
            continue
        turn["question"] = f"{names[index]}2026年8月25日的收盘价是多少？"
        turn["gold_sql"] = (
            "SELECT SYMBOL, CLOSE_PRICE, TRADE_DATE FROM VIEW_US_EOD_EXPR "
            f"WHERE SYMBOL='{symbols[index]}' AND TRADE_DATE='2026-08-25'"
        )
    turns[3]["gold_verify_entities"] = ["TSLA"]


def make_entity_gold_verifiable(round_id: int, turns: list[dict]) -> None:
    if round_id == 1:
        turns[4]["gold_sql"] = (
            "SELECT A_STOCKSNAME, F110101 FROM VIEW_STK_FIN_IDX "
            "WHERE A_STOCKCODE IN ('300750','600036') AND ENDDATE='2025-12-31' "
            "AND RPT_SRC='年报' AND ISVALID=1 ORDER BY F110101 DESC LIMIT 1"
        )
    elif round_id == 2:
        turns[4]["gold_sql"] = (
            "SELECT A_STOCKSNAME, F110101 FROM VIEW_STK_FIN_IDX "
            "WHERE A_STOCKCODE IN ('601318','601166','600900') AND ENDDATE='2025-12-31' "
            "AND RPT_SRC='年报' AND ISVALID=1 ORDER BY F110101 DESC LIMIT 1"
        )
    elif round_id == 3:
        turns[2]["gold_sql"] = (
            "SELECT STOCKSNAME, SECCODE, TCLOSE FROM STK_MKT "
            "WHERE SECCODE IN ('300750','600036') AND TRADEDATE='2026-08-31' "
            "AND ISVALID=1 ORDER BY TCLOSE DESC LIMIT 1"
        )


def fix_dynamic_snapshot_questions(round_id: int, turns: list[dict]) -> None:
    if round_id != 6:
        return
    turns[3].update({
        "question": "按2026年9月3日评测库快照，并列在管基金数量最多的基金经理都有谁？最多管几只？",
        "judge": "list",
        "gold_entities": ["单宽之", "董瑾"],
        "gold_value": "21",
        "gold_display": "单宽之（华夏基金）、董瑾（汇添富），均为21只",
        "gold_sql": (
            "SELECT PSN_NAME, INST_NAME, FUND_NUM_ACTUAL FROM FUND_MANAGER_INFO "
            "WHERE FUND_NUM_ACTUAL=(SELECT MAX(FUND_NUM_ACTUAL) FROM FUND_MANAGER_INFO) "
            "ORDER BY PSN_NAME"
        ),
    })
    turns[3]["labels"]["time_sensitivity"] = "snapshot"


def build() -> None:
    source = json.loads(SOURCE_SET.read_text(encoding="utf-8"))
    schemas = {name: load_schema(name) for name in ("MYSQL-1", "MYSQL-2", "MYSQL-4")}
    rounds = []
    for original in source["rounds"]:
        round_id = original["round_id"]
        if round_id not in KEEP_INDICES:
            continue
        all_turns = [original["initial"], *original["feedbacks"]]
        turns = [copy.deepcopy(all_turns[index]) for index in KEEP_INDICES[round_id]]
        if round_id == 8:
            fix_round_8(turns)
        if round_id == 10:
            turns = copy.deepcopy(ROUND_10)
        fix_dynamic_snapshot_questions(round_id, turns)
        make_entity_gold_verifiable(round_id, turns)
        for turn in turns:
            if "STK_INCOME_GEN" in turn["gold_tables"]:
                turn["gold_sql"] = turn["gold_sql"].replace(
                    "FROM STK_INCOME_GEN", "FROM VIEW_STK_INCOME_GEN"
                )
                turn["gold_tables"] = [
                    "VIEW_STK_INCOME_GEN" if table == "STK_INCOME_GEN" else table
                    for table in turn["gold_tables"]
                ]
            turn["gold_columns"] = derive_gold_columns(
                turn["gold_sql"], turn["gold_tables"], schemas[original["source"]]
            )
            turn["requires_dashvector"] = False
            turn["uses_macro_db"] = False
        rounds.append({
            "round_id": round_id,
            "source": original["source"],
            "domain": original["domain"],
            "theme": original["theme"] if round_id != 10 else "美股估值与多轮实体切换",
            "initial": turns[0],
            "feedbacks": turns[1:],
        })

    if len(rounds) != 10 or any(len([r["initial"], *r["feedbacks"]]) != 5 for r in rounds):
        raise RuntimeError("Gold Set 必须严格为 10 轮 x 5 问")

    output = {
        "meta": {
            "name": "gold_set_10r_50",
            "created": "2026-09-03",
            "structure": "10轮 x 5问（1首问+4追问），共50问",
            "source_style": "问题风格参考 test_cases.json；答案和 SQL 均来自数据库只读实查",
            "sources": {
                "MYSQL-2": "生产 juling（只读）",
                "MYSQL-1": "测试 FUND_INFO（只读）",
                "MYSQL-4": "本地 fiu（43只美股样本，合成数值，以库内值为准）",
            },
            "exclusions": ["宏观库/EDB", "依赖 DashVector 字段值召回的问题"],
            "schema_recall_k": {"table": [1, 3, 5, 10], "column": [10, 20, 50]},
            "metrics": {
                "sql_first_execution_accuracy": "首次生成 SQL 的执行结果正确题数/有效 SQL 题数",
                "sql_after_reflection_accuracy": "Reflection 后 SQL 的执行结果正确题数/有效 SQL 题数",
                "reflection_repair_rate": "首次错误且实际触发 Reflection 的题中，最终修复正确题数/触发题数",
                "schema_table_recall_at_k": "Top-K 选表中命中的标准表数/该题标准表总数",
                "schema_column_recall_at_k": "Top-K 字段中命中的标准字段数/该题标准字段总数",
                "wrong_table_hallucination_rate": "预测 SQL 中物理库不存在的唯一表名数/预测 SQL 唯一表名总数",
                "wrong_column_hallucination_rate": "预测 SQL 中物理库不存在的唯一字段名数/预测 SQL 唯一字段名总数",
                "followup_execution_accuracy": "40个追问中最终执行正确的题数/有效追问题数",
                "latency_p50_p95": "50问端到端耗时的第50/95百分位",
                "mean_tokens": "50问总 Token 数/有 Token 记录的问题数",
                "mean_llm_calls": "50问 LLM 调用总次数/有调用记录的问题数",
                "overall_accuracy": "最终执行正确题数/有效 SQL 题数",
            },
        },
        "rounds": rounds,
    }
    OUTPUT_SET.write_text(json.dumps(output, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"写出: {OUTPUT_SET}（10轮，50问）")


if __name__ == "__main__":
    build()
