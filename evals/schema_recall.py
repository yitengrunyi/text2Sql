#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用指定运行产物重放字段 RAG，计算 Column Recall@K。"""
import argparse
import ast
import json
import os
import pickle
import sys
from collections import defaultdict
from pathlib import Path

import pymysql
from sqlglot import exp, parse_one

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def pct(n: int, d: int):
    return round(100.0 * n / d, 1) if d else None


def load_metadata() -> dict[str, set[str]]:
    conn = pymysql.connect(
        host=os.environ.get("TEXT2SQL_LOCAL_METADATA_HOST", "127.0.0.1"),
        port=int(os.environ.get("TEXT2SQL_LOCAL_METADATA_PORT", "3307")),
        user=os.environ.get("TEXT2SQL_LOCAL_METADATA_USER", "root"),
        password=os.environ.get("TEXT2SQL_LOCAL_METADATA_PASSWORD", "123QWEasd!*"),
        database=os.environ.get("TEXT2SQL_LOCAL_METADATA_DB", "schema_metadata"),
        connect_timeout=5,
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT TABLE_ENAME, COLUMN_ENAME FROM MDB_COLUMN_JULING "
                "WHERE HISVALID=1 AND TABLE_ENAME IS NOT NULL AND COLUMN_ENAME IS NOT NULL"
            )
            rows = cursor.fetchall()
    finally:
        conn.close()
    result = defaultdict(set)
    for table, column in rows:
        result[str(table).upper()].add(str(column).upper())
    return dict(result)


def extract_keywords(answer: str) -> list[str] | None:
    for line in (answer or "").splitlines():
        text = line.strip()
        if not (text.startswith("[") and text.endswith("]")):
            continue
        try:
            value = ast.literal_eval(text)
        except (SyntaxError, ValueError):
            continue
        if isinstance(value, list) and value and all(isinstance(item, str) for item in value):
            return value
    return None


def gold_column_names(sql: str, gold_tables: list[str], metadata: dict[str, set[str]]) -> set[str]:
    available = set().union(*(metadata.get(table.upper(), set()) for table in gold_tables))
    if not available:
        return set()
    try:
        tree = parse_one(sql, read="mysql")
    except Exception:
        return set()
    return {
        str(column.name).upper()
        for column in tree.find_all(exp.Column)
        if column.name != "*" and str(column.name).upper() in available
    }


def explicit_gold_columns(gold: dict) -> set[str]:
    value = gold.get("gold_columns")
    if not isinstance(value, dict):
        return set()
    return {
        str(column).upper()
        for columns in value.values()
        for column in columns
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="重放本地字段向量召回并计算 Column Recall@K")
    parser.add_argument("--set", default="evals/gold_set_180.json", dest="set_path")
    parser.add_argument("--run-dir", default="evals/runs/full/turns")
    parser.add_argument("--output", default="evals/runs/schema_recall.json")
    parser.add_argument("--k", default="10,20,50", help="逗号分隔的 K 值")
    args = parser.parse_args()
    ks = sorted({int(value) for value in args.k.split(",") if value.strip()})
    if not ks or any(value <= 0 for value in ks):
        parser.error("--k 必须包含正整数")

    os.environ.setdefault("text2sql_env", "prod")
    os.environ.setdefault("TEXT2SQL_NACOS_REGISTER", "0")
    spec = json.loads((ROOT / args.set_path).read_text(encoding="utf-8"))
    gold_by_key = {}
    for round_spec in spec["rounds"]:
        for index, gold in enumerate([round_spec["initial"], *round_spec["feedbacks"]]):
            gold_by_key[(round_spec["round_id"], index)] = gold

    records = []
    for path in sorted((ROOT / args.run_dir).glob("r*_t*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        selected = (record.get("telemetry") or {}).get("selected_tables") or []
        keywords = extract_keywords(record.get("answer") or "")
        if selected and keywords:
            unique_selected = list(dict.fromkeys(str(table).upper() for table in selected))
            records.append((record, unique_selected, keywords))

    metadata = load_metadata()
    with (ROOT / "service/sql_generator/embedding_dict_update_juling_0216.pkl").open("rb") as handle:
        embedding_dict = pickle.load(handle)
    from util.fix_fields import DYNAMIC_TABLES, FIX_FIELDS
    from util.rag_helpers import get_bgeM3embeddings, fetch_topk_rag_result

    embedding_inputs = ["".join(keywords) for _, _, keywords in records]
    embeddings = get_bgeM3embeddings(embedding_inputs)
    if len(embeddings) != len(records):
        raise RuntimeError(f"BGE-M3 返回 {len(embeddings)} 个向量，预期 {len(records)} 个")

    details = []
    totals = {k: {"gold": 0, "hit": 0, "full_turns": 0} for k in ks}
    all_columns = rag_columns = 0
    for (record, selected, _), query_embedding in zip(records, embeddings):
        key = (record["round_id"], record["index"])
        gold = gold_by_key[key]
        gold_tables = [str(table).upper() for table in gold.get("gold_tables") or []]
        gold_columns = explicit_gold_columns(gold) or gold_column_names(
            gold.get("gold_sql") or "", gold_tables, metadata
        )
        if not gold_columns:
            continue
        recall_at_k = {}
        for k in ks:
            prompt_pairs = set()
            for table in selected:
                table_columns = metadata.get(table, set())
                if k == max(ks):
                    all_columns += len(table_columns)
                if table in DYNAMIC_TABLES:
                    names = list(FIX_FIELDS.get(table, []))
                    names.extend(name for name, _ in fetch_topk_rag_result(table, query_embedding, embedding_dict, k))
                    selected_columns = {str(name).upper() for name in names} & table_columns
                else:
                    selected_columns = table_columns
                if k == max(ks):
                    rag_columns += len(selected_columns)
                prompt_pairs.update((table, column) for column in selected_columns)

            prompt_names = {column for _, column in prompt_pairs}
            hit_columns = gold_columns & prompt_names
            totals[k]["gold"] += len(gold_columns)
            totals[k]["hit"] += len(hit_columns)
            totals[k]["full_turns"] += int(not (gold_columns - prompt_names))
            recall_at_k[str(k)] = {
                "hit_columns": sorted(hit_columns),
                "missed_columns": sorted(gold_columns - prompt_names),
                "recall": pct(len(hit_columns), len(gold_columns)),
            }
        details.append({
            "round_id": record["round_id"],
            "index": record["index"],
            "question": record["question"],
            "gold_tables": gold_tables,
            "selected_tables": selected,
            "gold_columns": sorted(gold_columns),
            "recall_at_k": recall_at_k,
        })

    max_k = max(ks)
    summary = {
        "run_dir": args.run_dir,
        "set": args.set_path,
        "dynamic_top_k": ks,
        "selection_turns": len(records),
        "evaluated_turns": len(details),
        "column_recall_at_k": {
            str(k): {
                "hit": totals[k]["hit"],
                "total": totals[k]["gold"],
                "recall": pct(totals[k]["hit"], totals[k]["gold"]),
                "turn_all_columns_recalled": pct(totals[k]["full_turns"], len(details)),
            }
            for k in ks
        },
        "schema_columns_with_rag": rag_columns,
        "schema_columns_without_column_rag": all_columns,
        "schema_column_count_reduction": pct(all_columns - rag_columns, all_columns),
        "schema_column_count_reduction_at_k": max_k,
    }
    output = {"summary": summary, "details": details}
    path = ROOT / args.output
    path.write_text(json.dumps(output, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"详情: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
