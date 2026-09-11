#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build and audit a local schema_metadata database.

The builder clones the test metadata database, then reconciles the metadata
rows of the three physical MySQL sources used by local-remote mode against
each instance's current information_schema:

- MYSQL-2 ``juling``   (prod Nacos mysql2_config, read-only)
- MYSQL-1 ``FUND_INFO`` (test Nacos mysql1_config, read-only)
- MYSQL-4 ``fiu``      (local docker instance)

Remote databases are always opened without write permissions by this script.

Examples:
    ./venv/bin/python local_sim/build_schema_metadata.py build
    ./venv/bin/python local_sim/build_schema_metadata.py audit
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import pymysql
from pymysql.cursors import DictCursor, SSCursor


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))
SYNC_ACTOR = "LOCAL_SCHEMA_SYNC"
AUTO_DESCRIPTION = "自动发现，待补充语义"
SYNC_STATE_TABLE = "_TEXT2SQL_LOCAL_SCHEMA_SYNC_STATE"
OVERLAY_PATH = Path(__file__).resolve().parent / "semantic_overlay.json"
SOURCE_VOLATILE_COLUMNS = {"CREATE_BY", "UPDATE_BY", "HCREATETIME", "HUPDATETIME"}
SOURCE_DYNAMIC_TABLES = {"TEST_HISTORY_LOG"}
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_]+$")

# 本地远程模式实际查询的三个物理 MySQL 源。config 决定 physical_configs()
# 返回的连接；hcode 前缀互不相同，避免新增表记录的 TABLE_HCODE 冲突。
PHYSICAL_TARGETS = (
    {"db_name": "juling", "source_tag": "JULING", "hcode_prefix": "LOCALJ"},
    {"db_name": "FUND_INFO", "source_tag": "JULING", "hcode_prefix": "LOCALF"},
    {"db_name": "fiu", "source_tag": "FIU", "hcode_prefix": "LOCALU"},
)


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value else default


def local_config(args: argparse.Namespace, database: str | None = None) -> dict[str, Any]:
    config: dict[str, Any] = {
        "host": args.local_host,
        "port": args.local_port,
        "user": args.local_user,
        "password": args.local_password,
        "charset": "utf8mb4",
        "connect_timeout": args.connect_timeout,
        "read_timeout": args.read_timeout,
        "write_timeout": args.read_timeout,
        "autocommit": False,
    }
    if database:
        config["database"] = database
    return config


def _nacos_configs() -> tuple[dict[str, Any], dict[str, Any]]:
    # Reading Nacos configuration must never register this local process as a service.
    os.environ.setdefault("TEXT2SQL_NACOS_REGISTER", "0")
    from config.nacos.nacos_service import TEST_SERVER, config, fetch_nacos_config

    test_config = fetch_nacos_config(TEST_SERVER)
    # nacos 客户端在服务器不可用时会静默回退到本地快照，而快照按
    # dataId+group 共享、不区分环境——快照内容可能指向生产主机(clusterd59)，
    # 白名单拦截后表现为难以定位的连接超时。测试环境的库必须在私网段。
    for key in ("source_db_config", "mysql1_config", "mysql3_config"):
        host = str(test_config.get(key, {}).get("host", ""))
        if host and not host.startswith("192.168."):
            raise RuntimeError(
                f"测试 Nacos({TEST_SERVER}) 配置异常: {key}.host={host} 不在私网段，"
                "疑似 nacos 服务器不可用时回退到了指向生产的本地快照。"
                "请检查 VPN/测试 Nacos 可达性后重试。"
            )
    return test_config, config


def source_config(args: argparse.Namespace) -> dict[str, Any]:
    test_config, _ = _nacos_configs()
    item = dict(test_config["source_db_config"])
    item["database"] = item.pop("db")
    item.update(
        charset="utf8mb4",
        connect_timeout=args.connect_timeout,
        read_timeout=args.read_timeout,
        write_timeout=args.read_timeout,
        autocommit=False,
    )
    return item


def physical_configs(args: argparse.Namespace) -> dict[str, dict[str, Any]]:
    """每个待校准 DB_NAME 对应一台物理 MySQL 的只读连接配置。"""
    test_config, prod_config = _nacos_configs()

    def tune(raw: dict[str, Any]) -> dict[str, Any]:
        item = dict(raw)
        item["database"] = item.pop("db")
        item.update(
            charset="utf8mb4",
            connect_timeout=args.connect_timeout,
            read_timeout=args.read_timeout,
            write_timeout=args.read_timeout,
            autocommit=False,
        )
        return item

    return {
        "juling": tune(prod_config["mysql2_config"]),
        "FUND_INFO": tune(test_config["mysql1_config"]),
        "fiu": local_config(
            args, os.environ.get("TEXT2SQL_LOCAL_FIU_DB", "fiu")
        ),
    }


def set_read_only(conn: pymysql.Connection) -> None:
    with conn.cursor() as cursor:
        cursor.execute("SET SESSION TRANSACTION READ ONLY")


def quote_identifier(value: str) -> str:
    if not IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"不安全的数据库标识符: {value!r}")
    return f"`{value}`"


def bit_value(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return int.from_bytes(value, "big")
    return int(value)


def fetch_catalog(conn: pymysql.Connection, schema: str) -> dict[str, Any]:
    with conn.cursor(DictCursor) as cursor:
        cursor.execute(
            """
            SELECT TABLE_NAME, TABLE_TYPE, ENGINE, TABLE_COLLATION, TABLE_COMMENT
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = %s
            ORDER BY TABLE_NAME
            """,
            (schema,),
        )
        table_rows = cursor.fetchall()
        cursor.execute(
            """
            SELECT TABLE_NAME, COLUMN_NAME, ORDINAL_POSITION, IS_NULLABLE,
                   DATA_TYPE, COLUMN_TYPE, COLUMN_KEY, EXTRA, COLUMN_COMMENT
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s
            ORDER BY TABLE_NAME, ORDINAL_POSITION
            """,
            (schema,),
        )
        column_rows = cursor.fetchall()

    tables = {row["TABLE_NAME"].upper(): row for row in table_rows}
    columns: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in column_rows:
        columns[row["TABLE_NAME"].upper()][row["COLUMN_NAME"].upper()] = row
    return {"tables": tables, "columns": dict(columns)}


def source_base_tables(conn: pymysql.Connection, schema: str) -> list[str]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT TABLE_NAME
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE'
            ORDER BY TABLE_NAME
            """,
            (schema,),
        )
        return [row[0] for row in cursor.fetchall()]


def database_exists(conn: pymysql.Connection, database: str) -> bool:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = %s",
            (database,),
        )
        return cursor.fetchone() is not None


def create_database(conn: pymysql.Connection, database: str) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            f"CREATE DATABASE {quote_identifier(database)} "
            "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
    conn.commit()


def clone_table(
    source_conn: pymysql.Connection,
    target_conn: pymysql.Connection,
    source_schema: str,
    target_schema: str,
    table: str,
    batch_size: int,
) -> int:
    quoted_table = quote_identifier(table)
    with source_conn.cursor() as cursor:
        cursor.execute(f"SHOW CREATE TABLE {quoted_table}")
        create_sql = cursor.fetchone()[1]
        cursor.execute(
            """
            SELECT COLUMN_NAME
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
              AND EXTRA NOT LIKE '%%VIRTUAL GENERATED%%'
              AND EXTRA NOT LIKE '%%STORED GENERATED%%'
            ORDER BY ORDINAL_POSITION
            """,
            (source_schema, table),
        )
        columns = [row[0] for row in cursor.fetchall()]

    with target_conn.cursor() as cursor:
        cursor.execute(f"USE {quote_identifier(target_schema)}")
        cursor.execute(create_sql)

    quoted_columns = ", ".join(quote_identifier(column) for column in columns)
    insert_sql = f"INSERT INTO {quoted_table} ({quoted_columns}) VALUES ({', '.join(['%s'] * len(columns))})"
    copied = 0
    stream = source_conn.cursor(SSCursor)
    try:
        stream.execute(f"SELECT {quoted_columns} FROM {quoted_table}")
        while True:
            rows = stream.fetchmany(batch_size)
            if not rows:
                break
            with target_conn.cursor() as cursor:
                cursor.executemany(insert_sql, rows)
            target_conn.commit()
            copied += len(rows)
    finally:
        stream.close()
    return copied


def json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    if hasattr(value, "isoformat"):
        return {"iso": value.isoformat()}
    return {"str": str(value), "type": type(value).__name__}


def hash_row(row: tuple[Any, ...]) -> bytes:
    payload = json.dumps(
        [json_value(value) for value in row],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).digest()


def combine_row_hashes(row_hashes: list[bytes]) -> str:
    digest = hashlib.sha256()
    for row_hash in sorted(row_hashes):
        digest.update(row_hash)
    return digest.hexdigest()


def fingerprint_table(
    conn: pymysql.Connection,
    schema: str,
    table: str,
    batch_size: int,
) -> dict[str, Any]:
    with conn.cursor() as metadata_cursor:
        metadata_cursor.execute(
            """
            SELECT COLUMN_NAME
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
              AND EXTRA NOT LIKE '%%VIRTUAL GENERATED%%'
              AND EXTRA NOT LIKE '%%STORED GENERATED%%'
            ORDER BY ORDINAL_POSITION
            """,
            (schema, table),
        )
        columns = [
            row[0]
            for row in metadata_cursor.fetchall()
            if row[0].upper() not in SOURCE_VOLATILE_COLUMNS
        ]

    row_hashes: list[bytes] = []
    row_count = 0
    cursor = conn.cursor(SSCursor)
    try:
        quoted_columns = ", ".join(quote_identifier(column) for column in columns)
        cursor.execute(f"SELECT {quoted_columns} FROM {quote_identifier(table)}")
        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                break
            row_hashes.extend(hash_row(row) for row in rows)
            row_count += len(rows)
    finally:
        cursor.close()
    return {"row_count": row_count, "content_sha256": combine_row_hashes(row_hashes)}


def fingerprint_source_metadata(
    conn: pymysql.Connection,
    schema: str,
    batch_size: int,
) -> dict[str, dict[str, Any]]:
    conn.select_db(schema)
    return {
        table: fingerprint_table(conn, schema, table, batch_size)
        for table in source_base_tables(conn, schema)
        if table != SYNC_STATE_TABLE
    }


def create_sync_state(
    conn: pymysql.Connection,
    fingerprints: dict[str, dict[str, Any]],
) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            CREATE TABLE {quote_identifier(SYNC_STATE_TABLE)} (
                SOURCE_TABLE varchar(128) NOT NULL PRIMARY KEY,
                ROW_COUNT bigint NOT NULL,
                CONTENT_SHA256 char(64) NOT NULL,
                CAPTURED_AT datetime NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        captured_at = datetime.now()
        cursor.executemany(
            f"""
            INSERT INTO {quote_identifier(SYNC_STATE_TABLE)}
                (SOURCE_TABLE, ROW_COUNT, CONTENT_SHA256, CAPTURED_AT)
            VALUES (%s, %s, %s, %s)
            """,
            [
                (table, values["row_count"], values["content_sha256"], captured_at)
                for table, values in sorted(fingerprints.items())
            ],
        )
    conn.commit()


def load_source_baseline(conn: pymysql.Connection) -> dict[str, dict[str, Any]]:
    with conn.cursor(DictCursor) as cursor:
        cursor.execute(
            f"""
            SELECT SOURCE_TABLE, ROW_COUNT, CONTENT_SHA256, CAPTURED_AT
            FROM {quote_identifier(SYNC_STATE_TABLE)}
            ORDER BY SOURCE_TABLE
            """
        )
        return {
            row["SOURCE_TABLE"]: {
                "row_count": row["ROW_COUNT"],
                "content_sha256": row["CONTENT_SHA256"],
                "captured_at": row["CAPTURED_AT"],
            }
            for row in cursor.fetchall()
        }


def source_metadata_audit(
    baseline: dict[str, dict[str, Any]],
    current: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    baseline_tables = set(baseline)
    current_tables = set(current)
    changed = []
    ignored_dynamic_changes = []
    for table in sorted(baseline_tables & current_tables):
        before = baseline[table]
        after = current[table]
        has_changed = (
            before["row_count"] != after["row_count"]
            or before["content_sha256"] != after["content_sha256"]
        )
        if has_changed and table in SOURCE_DYNAMIC_TABLES:
            ignored_dynamic_changes.append(table)
        elif has_changed:
            changed.append(
                {
                    "table": table,
                    "baseline_rows": before["row_count"],
                    "current_rows": after["row_count"],
                }
            )
    result = {
        "baseline_tables": len(baseline_tables),
        "current_tables": len(current_tables),
        "new_tables": sorted(current_tables - baseline_tables),
        "missing_tables": sorted(baseline_tables - current_tables),
        "changed_tables": changed,
        "ignored_dynamic_changes": ignored_dynamic_changes,
    }
    result["consistent"] = not (
        result["new_tables"] or result["missing_tables"] or result["changed_tables"]
    )
    return result


def allocate_hcode(
    used_hcodes: set[str], sequence: int, prefix: str
) -> tuple[str, int]:
    while True:
        hcode = f"{prefix}{sequence:08d}"
        sequence += 1
        if hcode not in used_hcodes:
            used_hcodes.add(hcode)
            return hcode, sequence


def _norm_name(value: Any) -> str:
    """元数据里的名称可能带尾随空格（PAD SPACE 唯一键下与规范名等价），统一成裸名。"""
    return (value or "").strip().upper()


def _collation_equal(raw: Any, canonical: str) -> bool:
    """utf8mb3_general_ci（PAD SPACE、大小写不敏感）下的名称等价判断。

    把排序规则等价的行选作胜者改名，只会原地占据它已有的唯一键槽位，不会撞键。
    """
    if not isinstance(raw, str):
        return False
    return raw.rstrip(" ").upper() == canonical.rstrip(" ").upper()


def reconcile_database(
    target_conn: pymysql.Connection,
    db_name: str,
    source_tag: str,
    hcode_prefix: str,
    physical_catalog: dict[str, Any],
) -> dict[str, Any]:
    """按物理目录校准单个 DB_NAME 的 MDB_TABLE/MDB_COLUMN_JULING 等记录。"""
    physical_tables = physical_catalog["tables"]
    physical_columns = physical_catalog["columns"]

    with target_conn.cursor(DictCursor) as cursor:
        cursor.execute(
            """
            SELECT ID, TABLE_HCODE, TABLE_ENAME, HISVALID, CREATE_BY
            FROM MDB_TABLE
            WHERE LOWER(DB_NAME) = %s
            ORDER BY ID
            """,
            (db_name.lower(),),
        )
        metadata_tables = cursor.fetchall()

    tables_by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    tables_by_hcode: dict[str, dict[str, Any]] = {}
    used_hcodes: set[str] = set()
    for row in metadata_tables:
        name = _norm_name(row["TABLE_ENAME"])
        tables_by_name[name].append(row)
        tables_by_hcode[str(row["TABLE_HCODE"])] = row
        used_hcodes.add(str(row["TABLE_HCODE"]))
    # TABLE_HCODE 在 MDB_TABLE 上是全局唯一键；新增 hcode 不得与任何库的既有值冲突。
    with target_conn.cursor() as cursor:
        cursor.execute("SELECT TABLE_HCODE FROM MDB_TABLE")
        used_hcodes.update(str(row[0]) for row in cursor.fetchall())

    existing_table_names = set(tables_by_name)
    physical_table_names = set(physical_tables)
    missing_physical_tables = sorted(existing_table_names - physical_table_names)
    newly_discovered_tables = sorted(physical_table_names - existing_table_names)
    matched_tables = sorted(existing_table_names & physical_table_names)

    stats: dict[str, Any] = {
        "db_name": db_name,
        "metadata_table_records_before": len(metadata_tables),
        "physical_tables": len(physical_table_names),
        "matched_tables": len(matched_tables),
        "metadata_tables_missing_in_physical": missing_physical_tables,
        "newly_discovered_tables": newly_discovered_tables,
        "table_records_deactivated": 0,
        "table_records_added": 0,
        "column_records_updated": 0,
        "column_records_deactivated": 0,
        "column_records_added": 0,
        "domain_mappings_deactivated": 0,
        "table_rules_deactivated": 0,
    }

    with target_conn.cursor() as cursor:
        if missing_physical_tables:
            missing_hcodes = [
                str(row["TABLE_HCODE"])
                for name in missing_physical_tables
                for row in tables_by_name[name]
            ]
            placeholders = ",".join(["%s"] * len(missing_hcodes))
            cursor.execute(
                f"""
                UPDATE MDB_TABLE
                SET HISVALID = 0, UPDATE_BY = %s
                WHERE TABLE_HCODE IN ({placeholders}) AND HISVALID = 1
                """,
                (SYNC_ACTOR, *missing_hcodes),
            )
            stats["table_records_deactivated"] = cursor.rowcount
            cursor.execute(
                f"""
                UPDATE MDB_COLUMN_JULING
                SET HISVALID = 0, UPDATE_BY = %s
                WHERE TABLE_HCODE IN ({placeholders}) AND HISVALID = 1
                """,
                (SYNC_ACTOR, *missing_hcodes),
            )
            stats["column_records_deactivated"] += cursor.rowcount
            cursor.execute(
                f"""
                UPDATE MDB_DOMN_TB_JULING
                SET HISVALID = 0, UPDATE_BY = %s
                WHERE TABLE_HCODE IN ({placeholders}) AND HISVALID = 1
                """,
                (SYNC_ACTOR, *missing_hcodes),
            )
            stats["domain_mappings_deactivated"] = cursor.rowcount
            cursor.execute(
                f"""
                UPDATE MDB_EXPERT_KNOWLEDGE_JULING
                SET HISVALID = 0, UPDATE_BY = %s
                WHERE KNOW_TYPE = 'TABLE'
                  AND OBJECT_HCODE IN ({placeholders})
                  AND HISVALID = 1
                """,
                (SYNC_ACTOR, *missing_hcodes),
            )
            stats["table_rules_deactivated"] = cursor.rowcount

        for table_name in matched_tables:
            canonical_name = physical_tables[table_name]["TABLE_NAME"]
            for row in tables_by_name[table_name]:
                cursor.execute(
                    """
                    UPDATE MDB_TABLE
                    SET TABLE_ENAME = %s, UPDATE_BY = %s
                    WHERE ID = %s
                    """,
                    (canonical_name, SYNC_ACTOR, row["ID"]),
                )

        sequence = 1
        for table_name in newly_discovered_tables:
            physical = physical_tables[table_name]
            hcode, sequence = allocate_hcode(used_hcodes, sequence, hcode_prefix)
            comment = (physical["TABLE_COMMENT"] or "").strip()
            description = f"{AUTO_DESCRIPTION}。{comment}" if comment else AUTO_DESCRIPTION
            cursor.execute(
                """
                INSERT INTO MDB_TABLE (
                    SRC, DB_TABLE, DB_NAME, TABLE_HCODE, TABLE_CNAME, TABLE_ENAME,
                    TABLE_DESC, TABLE_DESC_GENERATED, IS_SHOW, HISVALID,
                    CREATE_BY, UPDATE_BY
                ) VALUES (
                    %s, 'MYSQL', %s, %s, %s, %s,
                    %s, %s, 0, 0, %s, %s
                )
                """,
                (
                    source_tag,
                    db_name,
                    hcode,
                    comment or physical["TABLE_NAME"],
                    physical["TABLE_NAME"],
                    description,
                    description,
                    SYNC_ACTOR,
                    SYNC_ACTOR,
                ),
            )
            new_row = {
                "ID": cursor.lastrowid,
                "TABLE_HCODE": hcode,
                "TABLE_ENAME": physical["TABLE_NAME"],
                "HISVALID": 0,
                "CREATE_BY": SYNC_ACTOR,
            }
            tables_by_name[table_name].append(new_row)
            tables_by_hcode[hcode] = new_row
            stats["table_records_added"] += 1

        # 表定位按 MDB_DOMN_TB_JULING(HISVALID=1) 直接取候选表名，不回查表记录
        # 状态；活动映射指向停用表会把停用表泄漏进候选集。源头元数据存在这种
        # 悬挂映射（含本来就停用的表），一并停用。
        cursor.execute(
            """
            UPDATE MDB_DOMN_TB_JULING d
            JOIN MDB_TABLE t ON t.TABLE_HCODE = d.TABLE_HCODE
            SET d.HISVALID = 0, d.UPDATE_BY = %s
            WHERE LOWER(t.DB_NAME) = %s AND d.HISVALID = 1 AND t.HISVALID + 0 <> 1
            """,
            (SYNC_ACTOR, db_name.lower()),
        )
        stats["domain_mappings_deactivated"] += cursor.rowcount
        cursor.execute(
            """
            UPDATE MDB_EXPERT_KNOWLEDGE_JULING k
            JOIN MDB_TABLE t ON t.TABLE_HCODE = k.OBJECT_HCODE
            SET k.HISVALID = 0, k.UPDATE_BY = %s
            WHERE LOWER(t.DB_NAME) = %s AND k.KNOW_TYPE = 'TABLE'
              AND k.HISVALID = 1 AND t.HISVALID + 0 <> 1
            """,
            (SYNC_ACTOR, db_name.lower()),
        )
        stats["table_rules_deactivated"] += cursor.rowcount

    target_conn.commit()

    relevant_hcodes = sorted(tables_by_hcode)
    with target_conn.cursor(DictCursor) as cursor:
        metadata_columns: list[dict[str, Any]] = []
        for hcode_batch in batches(relevant_hcodes, 500):
            placeholders = ",".join(["%s"] * len(hcode_batch))
            cursor.execute(
                f"""
                SELECT ID, TABLE_HCODE, TABLE_ENAME, COLUMN_ENAME, HISVALID, CREATE_BY
                FROM MDB_COLUMN_JULING
                WHERE TABLE_HCODE IN ({placeholders})
                ORDER BY ID
                """,
                tuple(hcode_batch),
            )
            metadata_columns.extend(cursor.fetchall())

    columns_by_table_and_name: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in metadata_columns:
        table_row = tables_by_hcode.get(str(row["TABLE_HCODE"]))
        if not table_row:
            continue
        key = (
            _norm_name(table_row["TABLE_ENAME"]),
            _norm_name(row["COLUMN_ENAME"]),
        )
        columns_by_table_and_name[key].append(row)

    with target_conn.cursor() as cursor:
        for table_name in sorted(physical_table_names):
            table_rows = tables_by_name[table_name]
            physical_for_table = physical_columns.get(table_name, {})
            physical_column_names = set(physical_for_table)

            for table_row in table_rows:
                hcode = str(table_row["TABLE_HCODE"])
                metadata_for_hcode = [
                    row for row in metadata_columns if str(row["TABLE_HCODE"]) == hcode
                ]
                metadata_names = {
                    _norm_name(row["COLUMN_ENAME"]) for row in metadata_for_hcode
                }

                for column_name in sorted(metadata_names - physical_column_names):
                    for row in columns_by_table_and_name.get((table_name, column_name), []):
                        if str(row["TABLE_HCODE"]) != hcode:
                            continue
                        cursor.execute(
                            """
                            UPDATE MDB_COLUMN_JULING
                            SET HISVALID = 0, UPDATE_BY = %s
                            WHERE ID = %s AND HISVALID = 1
                            """,
                            (SYNC_ACTOR, row["ID"]),
                        )
                        stats["column_records_deactivated"] += cursor.rowcount

                for column_name in sorted(metadata_names & physical_column_names):
                    physical = physical_for_table[column_name]
                    candidates = [
                        row
                        for row in columns_by_table_and_name.get(
                            (table_name, column_name), []
                        )
                        if str(row["TABLE_HCODE"]) == hcode
                    ]
                    if not candidates:
                        continue
                    # 同一 (表,列) 规范键可能对应多行（如 COMUNIC 与 COMUNIC\xa0）：
                    # 全部改名会产生字面重复撞唯一键 MDB_COLUMN_UN。挑一行作胜者更新，
                    # 其余停用。胜者优先级：字面等于物理名 > 排序规则等于物理名
                    # （改名原地占位，不可能撞键）> 最小 ID（此时组内无任何行与物理名
                    # 排序规则相等，改名也不会撞键）。
                    winner = next(
                        (
                            row
                            for row in candidates
                            if (row["COLUMN_ENAME"] or "")
                            == physical["COLUMN_NAME"]
                        ),
                        None,
                    )
                    if winner is None:
                        winner = next(
                            (
                                row
                                for row in candidates
                                if _collation_equal(
                                    row["COLUMN_ENAME"], physical["COLUMN_NAME"]
                                )
                            ),
                            None,
                        )
                    if winner is None:
                        winner = min(candidates, key=lambda row: row["ID"])
                    cursor.execute(
                        """
                        UPDATE MDB_COLUMN_JULING
                        SET TABLE_ENAME = %s, COLUMN_ENAME = %s,
                            COLUMN_TYPE = %s, COLUMN_NULLABLE = %s,
                            UPDATE_BY = %s
                        WHERE ID = %s
                        """,
                        (
                            physical["TABLE_NAME"],
                            physical["COLUMN_NAME"],
                            physical["COLUMN_TYPE"],
                            "是" if physical["IS_NULLABLE"] == "YES" else "否",
                            SYNC_ACTOR,
                            winner["ID"],
                        ),
                    )
                    stats["column_records_updated"] += 1
                    for row in candidates:
                        if row["ID"] == winner["ID"]:
                            continue
                        cursor.execute(
                            """
                            UPDATE MDB_COLUMN_JULING
                            SET HISVALID = 0, UPDATE_BY = %s
                            WHERE ID = %s AND HISVALID = 1
                            """,
                            (SYNC_ACTOR, row["ID"]),
                        )
                        stats["column_records_deactivated"] += cursor.rowcount

                for column_name in sorted(physical_column_names - metadata_names):
                    physical = physical_for_table[column_name]
                    comment = (physical["COLUMN_COMMENT"] or "").strip()
                    description = f"{AUTO_DESCRIPTION}。{comment}" if comment else AUTO_DESCRIPTION
                    cursor.execute(
                        """
                        INSERT INTO MDB_COLUMN_JULING (
                            TABLE_HCODE, TABLE_ENAME, IS_DISPLAY, COLUMN_ENAME,
                            COLUMN_CNAME, COLUMN_TYPE, COLUMN_NULLABLE, COLUMN_DESC,
                            HISVALID, CREATE_BY, UPDATE_BY
                        ) VALUES (%s, %s, 1, %s, %s, %s, %s, %s, 0, %s, %s)
                        """,
                        (
                            hcode,
                            physical["TABLE_NAME"],
                            physical["COLUMN_NAME"],
                            comment or physical["COLUMN_NAME"],
                            physical["COLUMN_TYPE"],
                            "是" if physical["IS_NULLABLE"] == "YES" else "否",
                            description,
                            SYNC_ACTOR,
                            SYNC_ACTOR,
                        ),
                    )
                    stats["column_records_added"] += 1

    target_conn.commit()
    return stats


def batches(values: list[str], size: int) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def move_database_tables(
    conn: pymysql.Connection,
    source_database: str,
    target_database: str,
) -> None:
    tables = source_base_tables(conn, source_database)
    if not tables:
        return
    clauses = [
        f"{quote_identifier(source_database)}.{quote_identifier(table)} TO "
        f"{quote_identifier(target_database)}.{quote_identifier(table)}"
        for table in tables
    ]
    with conn.cursor() as cursor:
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
        cursor.execute("RENAME TABLE " + ", ".join(clauses))
        cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
    conn.commit()


def load_local_metadata(conn: pymysql.Connection, db_name: str) -> dict[str, Any]:
    with conn.cursor(DictCursor) as cursor:
        cursor.execute(
            """
            SELECT TABLE_HCODE, TABLE_ENAME, HISVALID, CREATE_BY
            FROM MDB_TABLE
            WHERE LOWER(DB_NAME) = %s
            """,
            (db_name.lower(),),
        )
        table_rows = cursor.fetchall()

        hcodes = [str(row["TABLE_HCODE"]) for row in table_rows]
        column_rows: list[dict[str, Any]] = []
        for hcode_batch in batches(hcodes, 500):
            placeholders = ",".join(["%s"] * len(hcode_batch))
            cursor.execute(
                f"""
                SELECT TABLE_HCODE, TABLE_ENAME, COLUMN_ENAME, COLUMN_TYPE,
                       COLUMN_NULLABLE, HISVALID, CREATE_BY
                FROM MDB_COLUMN_JULING
                WHERE TABLE_HCODE IN ({placeholders})
                """,
                tuple(hcode_batch),
            )
            column_rows.extend(cursor.fetchall())

        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM MDB_DOMN_TB_JULING d
            JOIN MDB_TABLE t ON t.TABLE_HCODE = d.TABLE_HCODE
            WHERE LOWER(t.DB_NAME) = %s AND d.HISVALID = 1
            """,
            (db_name.lower(),),
        )
        active_mappings = cursor.fetchone()["total"]
        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM MDB_EXPERT_KNOWLEDGE_JULING k
            JOIN MDB_TABLE t ON t.TABLE_HCODE = k.OBJECT_HCODE
            WHERE LOWER(t.DB_NAME) = %s
              AND k.KNOW_TYPE = 'TABLE' AND k.HISVALID = 1
            """,
            (db_name.lower(),),
        )
        active_table_rules = cursor.fetchone()["total"]
        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM MDB_DOMN_TB_JULING d
            JOIN MDB_TABLE t ON t.TABLE_HCODE = d.TABLE_HCODE
            WHERE LOWER(t.DB_NAME) = %s
              AND d.HISVALID = 1 AND t.HISVALID + 0 <> 1
            """,
            (db_name.lower(),),
        )
        dangling_domain_mappings = cursor.fetchone()["total"]
        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM MDB_EXPERT_KNOWLEDGE_JULING k
            JOIN MDB_TABLE t ON t.TABLE_HCODE = k.OBJECT_HCODE
            WHERE LOWER(t.DB_NAME) = %s AND k.KNOW_TYPE = 'TABLE'
              AND k.HISVALID = 1 AND t.HISVALID + 0 <> 1
            """,
            (db_name.lower(),),
        )
        dangling_table_rules = cursor.fetchone()["total"]

    return {
        "tables": table_rows,
        "columns": column_rows,
        "active_domain_mappings": active_mappings,
        "active_table_rules": active_table_rules,
        "dangling_domain_mappings": dangling_domain_mappings,
        "dangling_table_rules": dangling_table_rules,
    }


def build_audit_report(
    local_metadata: dict[str, Any],
    physical_catalog: dict[str, Any],
) -> dict[str, Any]:
    physical_tables = physical_catalog["tables"]
    physical_columns = physical_catalog["columns"]
    local_tables = local_metadata["tables"]
    local_columns = local_metadata["columns"]

    tables_by_hcode = {str(row["TABLE_HCODE"]): row for row in local_tables}
    metadata_table_names = {_norm_name(row["TABLE_ENAME"]) for row in local_tables}
    active_table_names = {
        _norm_name(row["TABLE_ENAME"])
        for row in local_tables
        if bit_value(row["HISVALID"]) == 1
    }
    reviewed_table_names = {
        _norm_name(row["TABLE_ENAME"])
        for row in local_tables
        if row["CREATE_BY"] != SYNC_ACTOR
    }

    metadata_columns: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    active_column_keys: set[tuple[str, str]] = set()
    reviewed_column_keys: set[tuple[str, str]] = set()
    for row in local_columns:
        table = tables_by_hcode.get(str(row["TABLE_HCODE"]))
        if not table:
            continue
        key = (
            _norm_name(table["TABLE_ENAME"]),
            _norm_name(row["COLUMN_ENAME"]),
        )
        metadata_columns[key].append(row)
        if bit_value(row["HISVALID"]) == 1:
            active_column_keys.add(key)
        if row["CREATE_BY"] != SYNC_ACTOR:
            reviewed_column_keys.add(key)

    physical_column_keys = {
        (table_name, column_name)
        for table_name, columns in physical_columns.items()
        for column_name in columns
    }
    metadata_column_keys = set(metadata_columns)
    physical_table_names = set(physical_tables)

    type_mismatches = []
    nullable_mismatches = []
    for key in sorted(physical_column_keys & metadata_column_keys):
        physical = physical_columns[key[0]][key[1]]
        for metadata in metadata_columns[key]:
            if bit_value(metadata["HISVALID"]) != 1:
                # 停用行是历史记录（含同一列的重复规范名），不参与比对。
                continue
            if (metadata["COLUMN_TYPE"] or "").lower() != physical["COLUMN_TYPE"].lower():
                type_mismatches.append(
                    {
                        "table": physical["TABLE_NAME"],
                        "column": physical["COLUMN_NAME"],
                        "metadata": metadata["COLUMN_TYPE"],
                        "physical": physical["COLUMN_TYPE"],
                    }
                )
            expected_nullable = "是" if physical["IS_NULLABLE"] == "YES" else "否"
            if metadata["COLUMN_NULLABLE"] != expected_nullable:
                nullable_mismatches.append(
                    {
                        "table": physical["TABLE_NAME"],
                        "column": physical["COLUMN_NAME"],
                        "metadata": metadata["COLUMN_NULLABLE"],
                        "physical": expected_nullable,
                    }
                )

    physical_table_count = len(physical_table_names)
    physical_column_count = len(physical_column_keys)
    report = {
        "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "physical": {
            "tables": physical_table_count,
            "columns": physical_column_count,
        },
        "metadata": {
            "table_records": len(local_tables),
            "column_records": len(local_columns),
            "active_tables": len(active_table_names & physical_table_names),
            "active_columns": len(active_column_keys & physical_column_keys),
            "active_domain_mappings": local_metadata["active_domain_mappings"],
            "active_table_rules": local_metadata["active_table_rules"],
        },
        "semantic_coverage": {
            "reviewed_tables": len(reviewed_table_names & physical_table_names),
            "reviewed_tables_denominator": physical_table_count,
            "reviewed_columns": len(reviewed_column_keys & physical_column_keys),
            "reviewed_columns_denominator": physical_column_count,
        },
        "drift": {
            "physical_tables_without_metadata": sorted(physical_table_names - metadata_table_names),
            "active_metadata_tables_missing_in_physical": sorted(active_table_names - physical_table_names),
            "physical_columns_without_metadata": [
                {"table": table, "column": column}
                for table, column in sorted(physical_column_keys - metadata_column_keys)
            ],
            "active_metadata_columns_missing_in_physical": [
                {"table": table, "column": column}
                for table, column in sorted(active_column_keys - physical_column_keys)
            ],
            "column_type_mismatches": type_mismatches,
            "column_nullable_mismatches": nullable_mismatches,
            "active_domain_mappings_to_inactive_tables": local_metadata[
                "dangling_domain_mappings"
            ],
            "active_table_rules_to_inactive_tables": local_metadata[
                "dangling_table_rules"
            ],
        },
    }
    report["consistent"] = not any(report["drift"].values())
    return report


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def print_audit_summary(reports: dict[str, dict[str, Any]]) -> None:
    for db_name, report in reports.items():
        physical = report["physical"]
        metadata = report["metadata"]
        coverage = report["semantic_coverage"]
        drift = report["drift"]
        print(
            f"[{db_name}] 一致性: {'通过' if report['consistent'] else '发现漂移'}；"
            f"物理结构: {physical['tables']} 张表、{physical['columns']} 个字段；"
            f"元数据结构记录: {metadata['table_records']} 张表、{metadata['column_records']} 个字段"
        )
        print(
            f"[{db_name}] 已审核语义覆盖: "
            f"{coverage['reviewed_tables']}/{coverage['reviewed_tables_denominator']} 张表，"
            f"{coverage['reviewed_columns']}/{coverage['reviewed_columns_denominator']} 个字段"
        )
        for key, values in drift.items():
            if values:
                print(f"[{db_name}] {key}: {len(values)}")
    first = next(iter(reports.values()))
    source = first.get("source_metadata")
    if source:
        print(
            f"测试元数据快照: {source['current_tables']}/{source['baseline_tables']} 张表；"
            f"内容变化 {len(source['changed_tables'])} 张"
        )


def orphan_reference_counts(conn: pymysql.Connection) -> dict[str, int]:
    """统计孤儿引用（活动域映射/表规则指向无 MDB_TABLE 记录的 hcode）。"""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) FROM MDB_DOMN_TB_JULING
            WHERE HISVALID = 1
              AND TABLE_HCODE NOT IN (SELECT TABLE_HCODE FROM MDB_TABLE)
            """
        )
        mappings = cursor.fetchone()[0]
        cursor.execute(
            """
            SELECT COUNT(*) FROM MDB_EXPERT_KNOWLEDGE_JULING
            WHERE KNOW_TYPE = 'TABLE' AND HISVALID = 1
              AND OBJECT_HCODE NOT IN (SELECT TABLE_HCODE FROM MDB_TABLE)
              AND CREATE_BY <> %s
            """,
            (SYNC_ACTOR,),
        )
        knowledge = cursor.fetchone()[0]
    return {
        "orphan_domain_mappings": mappings,
        "orphan_table_rules": knowledge,
    }


def deactivate_orphan_mappings(conn: pymysql.Connection) -> dict[str, int]:
    """停用 TABLE_HCODE 无任何 MDB_TABLE 记录的活动域映射。

    域映射的 hcode 与表记录的 hcode 可能错位（如 VIEW_STK_CASH_GENERIC 映射指向
    20253 而表记录是 30253），INNER JOIN 的悬挂清理看不见这类孤儿；表定位直读
    MDB_DOMN_TB_JULING(HISVALID=1)，孤儿会把幽灵表泄漏进候选集。孤儿 TABLE 型
    专家知识只计数不停用——RAG 召回路径可能仍引用，改动会越出三源对账范围。
    """
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE MDB_DOMN_TB_JULING
            SET HISVALID = 0, UPDATE_BY = %s
            WHERE HISVALID = 1
              AND TABLE_HCODE NOT IN (SELECT TABLE_HCODE FROM MDB_TABLE)
            """,
            (SYNC_ACTOR,),
        )
        mappings = cursor.rowcount
        cursor.execute(
            """
            SELECT COUNT(*) FROM MDB_EXPERT_KNOWLEDGE_JULING
            WHERE KNOW_TYPE = 'TABLE' AND HISVALID = 1
              AND OBJECT_HCODE NOT IN (SELECT TABLE_HCODE FROM MDB_TABLE)
              AND CREATE_BY <> %s
            """,
            (SYNC_ACTOR,),
        )
        orphan_knowledge = cursor.fetchone()[0]
    conn.commit()
    return {
        "orphan_domain_mappings_deactivated": mappings,
        "orphan_table_rules_reported": orphan_knowledge,
    }


def activate_physical_records(
    conn: pymysql.Connection,
    db_name: str,
    physical_catalog: dict[str, Any],
) -> dict[str, int]:
    """--activate：把该 DB_NAME 下物理存在的表/列记录全部置为 HISVALID=1。

    列沿用对账的胜者规则（字面等于物理名 > 排序规则等于 > 最小 ID），重复规范名
    的其余行保持停用，避免 TableFetcher 返回重复列。表激活后，原本因"指向停用表"
    被停用的域映射一并恢复（幽灵表的映射保持停用）。
    """
    physical_tables = physical_catalog["tables"]
    physical_columns = physical_catalog["columns"]
    stats = {
        "tables_activated": 0,
        "columns_activated": 0,
        "columns_deactivated": 0,
        "domain_mappings_activated": 0,
    }

    with conn.cursor(DictCursor) as cursor:
        cursor.execute(
            """
            SELECT ID, TABLE_HCODE, TABLE_ENAME, HISVALID
            FROM MDB_TABLE
            WHERE LOWER(DB_NAME) = %s
            ORDER BY ID
            """,
            (db_name.lower(),),
        )
        table_rows = cursor.fetchall()

    tables_by_hcode: dict[str, dict[str, Any]] = {}
    physical_table_hcodes: set[str] = set()
    with conn.cursor() as cursor:
        for row in table_rows:
            hcode = str(row["TABLE_HCODE"])
            tables_by_hcode[hcode] = row
            table_name = _norm_name(row["TABLE_ENAME"])
            if table_name not in physical_tables:
                continue
            if bit_value(row["HISVALID"]) != 1:
                cursor.execute(
                    "UPDATE MDB_TABLE SET HISVALID = 1, UPDATE_BY = %s WHERE ID = %s",
                    (SYNC_ACTOR, row["ID"]),
                )
                stats["tables_activated"] += cursor.rowcount
            physical_table_hcodes.add(hcode)

    hcodes = sorted(tables_by_hcode)
    with conn.cursor(DictCursor) as cursor:
        column_rows: list[dict[str, Any]] = []
        for hcode_batch in batches(hcodes, 500):
            placeholders = ",".join(["%s"] * len(hcode_batch))
            cursor.execute(
                f"""
                SELECT ID, TABLE_HCODE, COLUMN_ENAME, HISVALID
                FROM MDB_COLUMN_JULING
                WHERE TABLE_HCODE IN ({placeholders})
                ORDER BY ID
                """,
                tuple(hcode_batch),
            )
            column_rows.extend(cursor.fetchall())

    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in column_rows:
        table_row = tables_by_hcode.get(str(row["TABLE_HCODE"]))
        if not table_row:
            continue
        groups[(str(row["TABLE_HCODE"]), _norm_name(row["COLUMN_ENAME"]))].append(row)

    with conn.cursor() as cursor:
        for (hcode, column_name), rows in groups.items():
            table_row = tables_by_hcode[hcode]
            table_name = _norm_name(table_row["TABLE_ENAME"])
            physical = physical_columns.get(table_name, {}).get(column_name)
            if physical is None:
                for row in rows:
                    if bit_value(row["HISVALID"]) == 1:
                        cursor.execute(
                            """
                            UPDATE MDB_COLUMN_JULING
                            SET HISVALID = 0, UPDATE_BY = %s
                            WHERE ID = %s
                            """,
                            (SYNC_ACTOR, row["ID"]),
                        )
                        stats["columns_deactivated"] += cursor.rowcount
                continue
            canonical = physical["COLUMN_NAME"]
            winner = next(
                (r for r in rows if (r["COLUMN_ENAME"] or "") == canonical), None
            )
            if winner is None:
                winner = next(
                    (
                        r
                        for r in rows
                        if _collation_equal(r["COLUMN_ENAME"], canonical)
                    ),
                    None,
                )
            if winner is None:
                winner = min(rows, key=lambda r: r["ID"])
            for row in rows:
                want = 1 if row["ID"] == winner["ID"] else 0
                if bit_value(row["HISVALID"]) != want:
                    cursor.execute(
                        """
                        UPDATE MDB_COLUMN_JULING
                        SET HISVALID = %s, UPDATE_BY = %s
                        WHERE ID = %s
                        """,
                        (want, SYNC_ACTOR, row["ID"]),
                    )
                    if want:
                        stats["columns_activated"] += cursor.rowcount
                    else:
                        stats["columns_deactivated"] += cursor.rowcount

        # 恢复"指向已激活表"的域映射；物理不存在的表（幽灵）保持停用。
        if physical_table_hcodes:
            placeholders = ",".join(["%s"] * len(physical_table_hcodes))
            cursor.execute(
                f"""
                UPDATE MDB_DOMN_TB_JULING
                SET HISVALID = 1, UPDATE_BY = %s
                WHERE HISVALID = 0 AND TABLE_HCODE IN ({placeholders})
                """,
                (SYNC_ACTOR, *sorted(physical_table_hcodes)),
            )
            stats["domain_mappings_activated"] += cursor.rowcount

    conn.commit()
    return stats


def apply_semantic_overlay(conn: pymysql.Connection) -> dict[str, int]:
    """应用 local_sim/semantic_overlay.json 的语义覆盖层（幂等）。

    结构对账只解决"物理上有没有"，评测暴露的错因多在语义层：正确表缺域映射
    进不了候选池、代码列的后缀格式无说明、同义表缺权威源标注。覆盖层补三样：
    域映射(MDB_DOMN_TB_JULING)、表级专家知识(MDB_EXPERT_KNOWLEDGE_JULING)、
    列描述补丁(MDB_COLUMN_JULING)。每次 build 自动重放，重建不丢。
    """
    if not OVERLAY_PATH.exists():
        return {}
    overlay = json.loads(OVERLAY_PATH.read_text(encoding="utf-8"))
    stats = {
        "domain_mappings_added": 0,
        "domain_mappings_activated": 0,
        "expert_knowledge_upserted": 0,
        "column_descs_patched": 0,
    }

    with conn.cursor(DictCursor) as cursor:
        cursor.execute(
            """
            SELECT TABLE_HCODE, TABLE_ENAME, TABLE_CNAME
            FROM MDB_TABLE
            WHERE UPPER(DB_NAME) = %s
            """,
            ("FUND_INFO",),
        )
        tables_by_ename = {
            (row["TABLE_ENAME"] or "").upper(): row for row in cursor.fetchall()
        }
        cursor.execute("SELECT DOMAIN_HCODE, DOMAIN_CNAME FROM MDB_DOMAIN_JULING")
        domains = {row["DOMAIN_CNAME"]: str(row["DOMAIN_HCODE"]) for row in cursor.fetchall()}

    def _table(item: dict[str, Any]) -> dict[str, Any] | None:
        row = tables_by_ename.get(item["table"].upper())
        if row is None:
            print(f"覆盖层跳过（元数据无此表）: {item['table']}")
        return row

    with conn.cursor() as cursor:
        for item in overlay.get("domain_mappings", []):
            table = _table(item)
            if table is None:
                continue
            hcode = str(table["TABLE_HCODE"])
            for domain in item["domains"]:
                if domain not in domains:
                    print(f"覆盖层跳过（无此域）: {domain}")
                    continue
                cursor.execute(
                    """
                    SELECT ID, HISVALID + 0 FROM MDB_DOMN_TB_JULING
                    WHERE TABLE_HCODE = %s AND DOMAIN_CNAME = %s
                    """,
                    (hcode, domain),
                )
                existing = cursor.fetchone()
                if existing:
                    if existing[1] != 1:
                        cursor.execute(
                            """
                            UPDATE MDB_DOMN_TB_JULING
                            SET HISVALID = 1, UPDATE_BY = %s WHERE ID = %s
                            """,
                            (SYNC_ACTOR, existing[0]),
                        )
                        stats["domain_mappings_activated"] += cursor.rowcount
                else:
                    cursor.execute(
                        """
                        INSERT INTO MDB_DOMN_TB_JULING (
                            DOMAIN_HCODE, DOMAIN_CNAME, TABLE_HCODE, TABLE_ENAME,
                            HISVALID, CREATE_BY
                        ) VALUES (%s, %s, %s, %s, 1, %s)
                        """,
                        (
                            domains[domain],
                            domain,
                            hcode,
                            table["TABLE_ENAME"],
                            SYNC_ACTOR,
                        ),
                    )
                    stats["domain_mappings_added"] += cursor.rowcount

        for know_index, item in enumerate(overlay.get("expert_knowledge", [])):
            table = _table(item)
            if table is None:
                continue
            hcode = str(table["TABLE_HCODE"])
            ename = table["TABLE_ENAME"]
            object_cname = (table["TABLE_CNAME"] or ename or "")[:30]
            # fetch_table_knowledge 用表名列表匹配 OBJECT_HCODE（见
            # fetch_knowledge.py:215 WHERE OBJECT_HCODE IN final_table_list），
            # TABLE 型知识必须以表名为键才会被注入 prompt；以 hcode 为键的
            # 历史行（如 pledge-gov 系列）从未生效过。源库已有的表名键知识
            # （如 FUND_NETVALUE.KNOW_ID=22）保留共存，覆盖层行用 901+ 编号
            # 避开唯一键 (KNOW_TYPE, OBJECT_HCODE, KNOW_ID)。
            cursor.execute(
                """
                DELETE FROM MDB_EXPERT_KNOWLEDGE_JULING
                WHERE KNOW_TYPE = 'TABLE' AND CREATE_BY = %s AND OBJECT_HCODE = %s
                """,
                (SYNC_ACTOR, ename),
            )
            cursor.execute(
                """
                INSERT INTO MDB_EXPERT_KNOWLEDGE_JULING (
                    KNOW_TYPE, OBJECT_HCODE, OBJECT_CNAME, KNOW_ID, KNOW_DESC,
                    KNOW_KEYWORD, HISVALID, CREATE_BY, UPDATE_BY
                ) VALUES ('TABLE', %s, %s, %s, %s, %s, 1, %s, %s)
                """,
                (
                    ename,
                    object_cname,
                    901 + know_index,
                    item["desc"],
                    item.get("keywords", ""),
                    SYNC_ACTOR,
                    SYNC_ACTOR,
                ),
            )
            stats["expert_knowledge_upserted"] += cursor.rowcount

        for item in overlay.get("expert_knowledge_deactivate", []):
            table = _table(item)
            if table is None:
                continue
            cursor.execute(
                """
                UPDATE MDB_EXPERT_KNOWLEDGE_JULING
                SET HISVALID = 0, UPDATE_BY = %s
                WHERE KNOW_TYPE = 'TABLE' AND OBJECT_HCODE = %s AND KNOW_ID = %s
                  AND HISVALID = 1
                """,
                (SYNC_ACTOR, table["TABLE_ENAME"], item["know_id"]),
            )
            stats.setdefault("expert_knowledge_deactivated", 0)
            stats["expert_knowledge_deactivated"] += cursor.rowcount

        for item in overlay.get("column_desc_patches", []):
            table = _table(item)
            if table is None:
                continue
            hcode = str(table["TABLE_HCODE"])
            cursor.execute(
                """
                SELECT ID, COLUMN_DESC FROM MDB_COLUMN_JULING
                WHERE TABLE_HCODE = %s AND UPPER(COLUMN_ENAME) = %s
                ORDER BY ID LIMIT 1
                """,
                (hcode, item["column"].upper()),
            )
            existing = cursor.fetchone()
            if not existing:
                print(f"覆盖层跳过（无此列）: {item['table']}.{item['column']}")
                continue
            if item.get("mode") == "append" and existing[1]:
                new_desc = f"{existing[1]} {item['text']}"
            else:
                new_desc = item["text"]
            cursor.execute(
                """
                UPDATE MDB_COLUMN_JULING
                SET COLUMN_DESC = LEFT(%s, 5000), UPDATE_BY = %s
                WHERE ID = %s
                """,
                (new_desc[:5000], SYNC_ACTOR, existing[0]),
            )
            stats["column_descs_patched"] += cursor.rowcount

    conn.commit()
    return stats


def reconcile_all_targets(
    local_server: pymysql.Connection,
    target_conns: dict[str, pymysql.Connection],
    target_configs: dict[str, dict[str, Any]],
    activate: bool = False,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, int]]:
    """依次校准每个物理源，返回 (对账统计, 审计报告, 孤儿引用统计)，按 db_name 键控。"""
    reconcile_stats: dict[str, dict[str, Any]] = {}
    audit_reports: dict[str, dict[str, Any]] = {}
    activation_stats: dict[str, dict[str, Any]] = {}
    physical_catalogs: dict[str, dict[str, Any]] = {}
    for target in PHYSICAL_TARGETS:
        db_name = target["db_name"]
        physical_catalog = fetch_catalog(
            target_conns[db_name], target_configs[db_name]["database"]
        )
        physical_catalogs[db_name] = physical_catalog
        reconcile_stats[db_name] = reconcile_database(
            local_server,
            db_name,
            target["source_tag"],
            target["hcode_prefix"],
            physical_catalog,
        )
        if activate:
            activation_stats[db_name] = activate_physical_records(
                local_server, db_name, physical_catalog
            )
    if activation_stats:
        reconcile_stats["activation"] = activation_stats
    if activate:
        # 覆盖层在激活之后应用，审计在覆盖层之后重算，报告反映最终状态
        reconcile_stats["semantic_overlay"] = apply_semantic_overlay(local_server)
    for db_name in physical_catalogs:
        local_metadata = load_local_metadata(local_server, db_name)
        audit_reports[db_name] = build_audit_report(local_metadata, physical_catalogs[db_name])
    orphan_stats = deactivate_orphan_mappings(local_server)
    return reconcile_stats, audit_reports, orphan_stats


def build(args: argparse.Namespace) -> int:
    source_cfg = source_config(args)
    target_configs = physical_configs(args)
    source_schema = source_cfg["database"]

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    staging_database = f"{args.database}_build_{timestamp}"
    backup_database = f"{args.database}_backup_{timestamp}"

    with closing(pymysql.connect(**source_cfg)) as source_conn, closing(
        pymysql.connect(**local_config(args))
    ) as local_server:
        target_conns = {
            db_name: pymysql.connect(**cfg)
            for db_name, cfg in target_configs.items()
        }
        try:
            set_read_only(source_conn)
            for conn in target_conns.values():
                set_read_only(conn)
            if database_exists(local_server, args.database) and not args.replace:
                raise RuntimeError(
                    f"本地数据库 {args.database!r} 已存在。默认拒绝覆盖；"
                    "如需重建，请显式使用 --replace，原库会先改名备份。"
                )
            if database_exists(local_server, staging_database):
                raise RuntimeError(f"临时数据库意外存在: {staging_database}")

            source_tables = source_base_tables(source_conn, source_schema)
            create_database(local_server, staging_database)
            copied_rows: dict[str, int] = {}
            source_fingerprints: dict[str, dict[str, Any]] = {}
            try:
                for index, table in enumerate(source_tables, 1):
                    rows = clone_table(
                        source_conn,
                        local_server,
                        source_schema,
                        staging_database,
                        table,
                        args.batch_size,
                    )
                    copied_rows[table] = rows
                    source_fingerprints[table] = fingerprint_table(
                        source_conn,
                        source_schema,
                        table,
                        args.batch_size,
                    )
                    print(f"[{index}/{len(source_tables)}] {table}: {rows} 行")

                local_server.select_db(staging_database)
                create_sync_state(local_server, source_fingerprints)
                reconcile_stats, audit_reports, orphan_stats = reconcile_all_targets(
                    local_server,
                    target_conns,
                    target_configs,
                    activate=args.activate,
                )
                source_audit = source_metadata_audit(
                    load_source_baseline(local_server), source_fingerprints
                )
                consistent = source_audit["consistent"] and all(
                    report["consistent"] for report in audit_reports.values()
                )
                if not consistent:
                    raise RuntimeError("校准后仍存在结构漂移，拒绝发布临时数据库")
            except Exception:
                with local_server.cursor() as cursor:
                    cursor.execute(
                        f"DROP DATABASE IF EXISTS {quote_identifier(staging_database)}"
                    )
                local_server.commit()
                raise

            # 发布分四步各自提交：备份空库 → 旧库改名进备份 → staging 改名发布 →
            # 删 staging。中途失败时保留 staging（唯一已校验副本），并尽力把备份
            # 库改回原名，避免发布库悬空为空库。
            previous_database = None
            try:
                if database_exists(local_server, args.database):
                    create_database(local_server, backup_database)
                    move_database_tables(local_server, args.database, backup_database)
                    previous_database = backup_database
                else:
                    create_database(local_server, args.database)
                move_database_tables(local_server, staging_database, args.database)
            except Exception:
                if previous_database and database_exists(local_server, args.database):
                    try:
                        if not source_base_tables(local_server, args.database):
                            move_database_tables(
                                local_server, previous_database, args.database
                            )
                    except Exception:
                        pass
                raise
            with local_server.cursor() as cursor:
                cursor.execute(f"DROP DATABASE {quote_identifier(staging_database)}")
            local_server.commit()

            for report in audit_reports.values():
                report["source_metadata"] = source_audit
            report = {
                "mode": "build",
                "source_metadata": {
                    "schema": source_schema,
                    "tables_copied": len(source_tables),
                    "rows_copied": sum(copied_rows.values()),
                    "rows_by_table": copied_rows,
                },
                "target": {
                    "host": args.local_host,
                    "port": args.local_port,
                    "database": args.database,
                    "previous_database_backup": previous_database,
                },
                "reconcile": reconcile_stats,
                "orphan_references": orphan_stats,
                "audit": audit_reports,
            }
            write_report(args.report, report)
            print_audit_summary(audit_reports)
            print(f"报告: {args.report}")
            return 0
        finally:
            for conn in target_conns.values():
                conn.close()


def audit(args: argparse.Namespace) -> int:
    source_cfg = source_config(args)
    target_configs = physical_configs(args)
    source_schema = source_cfg["database"]
    with closing(pymysql.connect(**source_cfg)) as source_conn, closing(
        pymysql.connect(**local_config(args, args.database))
    ) as local_conn:
        set_read_only(source_conn)
        target_conns = {
            db_name: pymysql.connect(**cfg)
            for db_name, cfg in target_configs.items()
        }
        try:
            for conn in target_conns.values():
                set_read_only(conn)
            reconcile_stats, audit_reports = {}, {}
            for target in PHYSICAL_TARGETS:
                db_name = target["db_name"]
                physical_catalog = fetch_catalog(
                    target_conns[db_name], target_configs[db_name]["database"]
                )
                local_metadata = load_local_metadata(local_conn, db_name)
                audit_reports[db_name] = build_audit_report(
                    local_metadata, physical_catalog
                )
            orphan_stats = orphan_reference_counts(local_conn)
            source_audit = source_metadata_audit(
                load_source_baseline(local_conn),
                fingerprint_source_metadata(source_conn, source_schema, args.batch_size),
            )
            for report in audit_reports.values():
                report["source_metadata"] = source_audit
            consistent = (
                source_audit["consistent"]
                and orphan_stats["orphan_domain_mappings"] == 0
                and all(report["consistent"] for report in audit_reports.values())
            )
            report = {
                "mode": "audit",
                "target": {
                    "host": args.local_host,
                    "port": args.local_port,
                    "database": args.database,
                },
                "orphan_references": orphan_stats,
                "audit": audit_reports,
            }
            write_report(args.report, report)
            print_audit_summary(audit_reports)
            print(f"报告: {args.report}")
            return 0 if consistent else 2
        finally:
            for conn in target_conns.values():
                conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成或审计本地 schema_metadata")
    parser.add_argument("mode", choices=("build", "audit"))
    parser.add_argument(
        "--activate",
        action="store_true",
        help="build 时把三个物理源中真实存在的表/列记录全部置为 HISVALID=1",
    )
    parser.add_argument(
        "--database",
        default=os.environ.get("TEXT2SQL_LOCAL_METADATA_DB", "schema_metadata"),
    )
    parser.add_argument("--replace", action="store_true", help="重建时先备份现有本地库")
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--local-host",
        default=os.environ.get("TEXT2SQL_LOCAL_METADATA_HOST", "127.0.0.1"),
    )
    parser.add_argument(
        "--local-port",
        type=int,
        default=env_int("TEXT2SQL_LOCAL_METADATA_PORT", 3307),
    )
    parser.add_argument(
        "--local-user",
        default=os.environ.get("TEXT2SQL_LOCAL_METADATA_USER", "root"),
    )
    parser.add_argument(
        "--local-password",
        default=os.environ.get("TEXT2SQL_LOCAL_METADATA_PASSWORD", "123QWEasd!*"),
    )
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument(
        "--connect-timeout",
        type=int,
        default=env_int("TEXT2SQL_DB_CONNECT_TIMEOUT", 10),
    )
    parser.add_argument("--read-timeout", type=int, default=120)
    args = parser.parse_args()
    if args.report is None:
        args.report = PROJECT_DIR / "artifacts" / f"schema_metadata_{args.mode}_report.json"
    quote_identifier(args.database)
    return args


def main() -> int:
    args = parse_args()
    try:
        return build(args) if args.mode == "build" else audit(args)
    except Exception as exc:
        print(f"失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
