#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""核验 Gold Set 引用的表和字段在本地元数据库中可用。"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path

import pymysql
from pymysql.cursors import DictCursor


SOURCE_DB = {"MYSQL-1": "FUND_INFO", "MYSQL-2": "juling", "MYSQL-4": "fiu"}


def collect_requirements(spec: dict) -> tuple[dict[str, set[str]], dict[tuple[str, str], set[str]]]:
    tables: dict[str, set[str]] = defaultdict(set)
    columns: dict[tuple[str, str], set[str]] = defaultdict(set)
    for round_spec in spec["rounds"]:
        db_name = SOURCE_DB[round_spec["source"]]
        for turn in [round_spec["initial"], *round_spec["feedbacks"]]:
            tables[db_name].update(name.upper() for name in turn.get("gold_tables", []))
            for table, names in turn.get("gold_columns", {}).items():
                columns[(db_name, table.upper())].update(name.upper() for name in names)
    return tables, columns


def audit(set_path: Path, report_path: Path) -> int:
    spec = json.loads(set_path.read_text(encoding="utf-8"))
    required_tables, required_columns = collect_requirements(spec)
    conn = pymysql.connect(
        host=os.environ.get("TEXT2SQL_LOCAL_METADATA_HOST", "127.0.0.1"),
        port=int(os.environ.get("TEXT2SQL_LOCAL_METADATA_PORT", "3307")),
        user=os.environ.get("TEXT2SQL_LOCAL_METADATA_USER", "root"),
        password=os.environ.get("TEXT2SQL_LOCAL_METADATA_PASSWORD", "123QWEasd!*"),
        database=os.environ.get("TEXT2SQL_LOCAL_METADATA_DB", "schema_metadata"),
        charset="utf8mb4",
        cursorclass=DictCursor,
    )
    missing_tables = []
    inactive_tables = []
    missing_columns = []
    inactive_columns = []
    missing_domain_mappings = []
    weak_table_descriptions = []
    weak_column_descriptions = []
    checked_table_rows = 0
    checked_column_rows = 0
    try:
        with conn.cursor() as cursor:
            for db_name, table_names in sorted(required_tables.items()):
                for table_name in sorted(table_names):
                    cursor.execute(
                        """
                        SELECT TABLE_HCODE, TABLE_CNAME, TABLE_DESC, TABLE_DESC_GENERATED,
                               HISVALID + 0 AS ACTIVE
                        FROM MDB_TABLE
                        WHERE LOWER(DB_NAME)=LOWER(%s) AND UPPER(TABLE_ENAME)=%s
                        ORDER BY ACTIVE DESC, ID DESC LIMIT 1
                        """,
                        (db_name, table_name),
                    )
                    table = cursor.fetchone()
                    if not table:
                        missing_tables.append(f"{db_name}.{table_name}")
                        continue
                    checked_table_rows += 1
                    if table["ACTIVE"] != 1:
                        inactive_tables.append(f"{db_name}.{table_name}")
                    description = table["TABLE_DESC_GENERATED"] or table["TABLE_DESC"] or table["TABLE_CNAME"]
                    if not description:
                        weak_table_descriptions.append(f"{db_name}.{table_name}")

                    cursor.execute(
                        """
                        SELECT COUNT(*) AS N
                        FROM MDB_DOMN_TB_JULING
                        WHERE TABLE_HCODE=%s AND HISVALID=1
                        """,
                        (table["TABLE_HCODE"],),
                    )
                    if cursor.fetchone()["N"] == 0:
                        missing_domain_mappings.append(f"{db_name}.{table_name}")

                    for column_name in sorted(required_columns.get((db_name, table_name), set())):
                        cursor.execute(
                            """
                            SELECT COLUMN_CNAME, COLUMN_DESC, HISVALID + 0 AS ACTIVE
                            FROM MDB_COLUMN_JULING
                            WHERE TABLE_HCODE=%s AND UPPER(COLUMN_ENAME)=%s
                            ORDER BY ACTIVE DESC, ID DESC LIMIT 1
                            """,
                            (table["TABLE_HCODE"], column_name),
                        )
                        column = cursor.fetchone()
                        key = f"{db_name}.{table_name}.{column_name}"
                        if not column:
                            missing_columns.append(key)
                            continue
                        checked_column_rows += 1
                        if column["ACTIVE"] != 1:
                            inactive_columns.append(key)
                        if not (column["COLUMN_DESC"] or column["COLUMN_CNAME"]):
                            weak_column_descriptions.append(key)
    finally:
        conn.close()

    question_text = "\n".join(
        turn["question"]
        for round_spec in spec["rounds"]
        for turn in [round_spec["initial"], *round_spec["feedbacks"]]
    ).lower()
    forbidden_hits = [term for term in ("宏观", "doris", "dashvector") if term in question_text]
    blockers = (
        missing_tables + inactive_tables + missing_columns + inactive_columns
        + missing_domain_mappings + weak_table_descriptions + weak_column_descriptions
        + forbidden_hits
    )
    report = {
        "set": str(set_path),
        "passed": not blockers,
        "checked": {
            "unique_tables": checked_table_rows,
            "unique_columns": checked_column_rows,
            "questions": sum(1 + len(row["feedbacks"]) for row in spec["rounds"]),
        },
        "blockers": {
            "missing_tables": missing_tables,
            "inactive_tables": inactive_tables,
            "missing_columns": missing_columns,
            "inactive_columns": inactive_columns,
            "missing_domain_mappings": missing_domain_mappings,
            "weak_table_descriptions": weak_table_descriptions,
            "weak_column_descriptions": weak_column_descriptions,
            "forbidden_question_terms": forbidden_hits,
        },
        "known_non_blocking_limitations": [
            "远程元数据表 MKT_MAX_TRADEDATE 已变化，但本集合的 MYSQL-2 行情题均使用固定日期，不依赖该快照。",
            "MYSQL-4 是 43 只美股的本地合成样本；集合不询问生产库覆盖股票总数，数值按本地库判分。",
        ],
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="核验 Gold Set 与本地元数据库的一致性")
    parser.add_argument("--set", default="evals/gold_set_10r_50.json", dest="set_path")
    parser.add_argument("--report", default="evals/gold_set_10r_50_metadata_report.json", dest="report_path")
    args = parser.parse_args()
    raise SystemExit(audit(Path(args.set_path), Path(args.report_path)))
