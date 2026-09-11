#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评测插桩：LLM 调用计时/计数、表候选与选中捕获、列召回捕获、消融开关。

设计要点：
- 以 contextvar 绑定当前轮次(TurnTelemetry)，并发轮次互不串扰；
- 只 patch 各模块的 import 名(不动生产代码文件)；
- 全部幂等，重复 install 自动跳过。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import contextvars
import time

_telemetry_ctx: contextvars.ContextVar = contextvars.ContextVar("eval_telemetry", default=None)

_installed = set()


class TurnTelemetry:
    def __init__(self, key: str):
        self.key = key
        self.started = time.perf_counter()
        self.llm_calls: list[dict] = []          # {model, seconds}
        self.selected_tables: list[str] | None = None
        self.candidate_tables: list[str] | None = None
        self.prompt_columns_raw = None            # TableInfoService.fetch_table_info 原始返回
        self.sql_prompt_chars: list[int] = []     # SQL 生成 prompt 长度

    def snapshot(self) -> dict:
        calls = self.llm_calls
        seconds = [c["seconds"] for c in calls]
        return {
            "key": self.key,
            "llm_call_count": len(calls),
            "llm_models": sorted({c["model"] for c in calls}),
            "llm_seconds_total": round(sum(seconds), 2),
            "llm_seconds_max": round(max(seconds), 2) if seconds else None,
            "selected_tables": self.selected_tables,
            "candidate_tables": self.candidate_tables,
            "sql_prompt_chars": self.sql_prompt_chars,
            "prompt_columns_raw_len": (
                len(str(self.prompt_columns_raw)) if self.prompt_columns_raw is not None else None
            ),
        }


def begin_turn(key: str) -> TurnTelemetry:
    tel = TurnTelemetry(key)
    _telemetry_ctx.set(tel)
    return tel


def end_turn() -> None:
    _telemetry_ctx.set(None)


def _current() -> TurnTelemetry | None:
    return _telemetry_ctx.get()


# ---------------------------------------------------------------- LLM 计时

_LLM_MODULES = (
    "handler.text2sql_handler",
    "handler.feedback_handler",
    "service.locator.table_locator",
    "service.locator.domain_locator",
    "service.locator.question_locator",
    "service.analysis.question_analysis",
    "service.self_reflection.diagnose",
    "service.self_reflection.sql_explanation_info",
    "service.sql_generator.text_to_sql_generator",
    "util.rag_helpers",
    "util.data_formater_helpers",
    "service.feedback_intent.feedback_intent",
)


def install_llm_timer() -> None:
    if "llm_timer" in _installed:
        return
    import importlib

    import util.model_helpers as mh

    orig = mh.call_llm

    async def timed_call_llm(prompt, model, *args, **kwargs):
        t0 = time.perf_counter()
        try:
            return await orig(prompt, model, *args, **kwargs)
        finally:
            tel = _current()
            if tel is not None:
                tel.llm_calls.append({"model": str(model), "seconds": round(time.perf_counter() - t0, 2)})

    for mod_name in _LLM_MODULES:
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue
        if getattr(mod, "call_llm", None) is orig:
            mod.call_llm = timed_call_llm
    _installed.add("llm_timer")


# ---------------------------------------------------------------- 表定位捕获 / 随机消融

_existing_tables_cache: dict[str, set] = {}


async def _existing_tables(db_type: str) -> set:
    if db_type in _existing_tables_cache:
        return _existing_tables_cache[db_type]
    from common.middleware.db_utils import get_pool

    pool_name = {"MYSQL-1": "mysql1", "MYSQL-2": "mysql2", "MYSQL-4": "mysql4"}.get(db_type)
    if pool_name is None:
        return set()
    conn = await get_pool(pool_name).acquire()
    try:
        async with conn.cursor() as cursor:
            await cursor.execute("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE()")
            rows = await cursor.fetchall()
    finally:
        get_pool(pool_name).release(conn)
    names = {r[0].upper() for r in rows}
    _existing_tables_cache[db_type] = names
    return names


def install_table_capture(random_ablation: bool = False, seed_base: str = "eval") -> None:
    key = f"table_capture:{random_ablation}"
    if key in _installed:
        return
    import random

    from util.fix_fields import DEFAULT_TABLES

    import handler.text2sql_handler as th

    orig = th.fetch_and_process_tables

    async def wrapped_tables(query, domain_res, background_info, domain_one, industry_str, concepts, db_type, token_tracker=None):
        tables, table_define = await orig(
            query, domain_res, background_info, domain_one, industry_str, concepts, db_type, token_tracker=token_tracker
        )
        pool = [row[0] for row in (table_define or []) if row and row[0]]
        pool = [t for t in pool if t.upper() not in DEFAULT_TABLES]
        tel = _current()
        if tel is not None:
            tel.selected_tables = [t.upper() for t in (tables or [])]
            tel.candidate_tables = [t.upper() for t in pool]
        if random_ablation:
            try:
                existing = await _existing_tables(db_type)
            except Exception:
                existing = set()
            usable = [t for t in dict.fromkeys(pool) if not existing or t.upper() in existing]
            k = len(tables or [])
            if usable and k:
                rng = random.Random(f"{seed_base}|{query}|{domain_res}")
                tables = rng.sample(usable, min(k, len(usable)))
        return tables, table_define

    th.fetch_and_process_tables = wrapped_tables
    _installed.add(key)


# ---------------------------------------------------------------- 列召回捕获 / 列RAG消融

def install_column_capture(no_column_rag: bool = False) -> None:
    key = f"column_capture:{no_column_rag}"
    if key in _installed:
        return
    import service.sql_generator.TableFetcher as TF

    if no_column_rag:
        orig_rag = TF.fetch_topk_rag_result

        def all_columns(table_name, query_embedding, embedding_dict, K):
            table_embeddings = embedding_dict.get(table_name, {})
            return list(table_embeddings.items())

        TF.fetch_topk_rag_result = all_columns

    orig_dyn = TF.DynamicTableFetcher.fetch_table_info
    orig_fix = TF.FixTableFetcher.fetch_table_info

    async def wrapped_dyn(self, table_res, **kwargs):
        res = await orig_dyn(self, table_res, **kwargs)
        tel = _current()
        if tel is not None and tel.prompt_columns_raw is None:
            tel.prompt_columns_raw = {"kind": "dynamic", "tables": [str(t) for t in table_res], "res": str(res)[:20000]}
        return res

    async def wrapped_fix(self, us_stock_codes, table_res, query, companies, **kwargs):
        res = await orig_fix(self, us_stock_codes, table_res, query, companies, **kwargs)
        tel = _current()
        if tel is not None:
            tel.prompt_columns_raw = {"kind": "fix", "tables": [str(t) for t in table_res], "res": str(res)[:20000]}
        return res

    TF.DynamicTableFetcher.fetch_table_info = wrapped_dyn
    TF.FixTableFetcher.fetch_table_info = wrapped_fix
    _installed.add(key)


# ---------------------------------------------------------------- Reflection 消融

def install_no_reflection() -> None:
    if "no_reflection" in _installed:
        return
    import handler.text2sql_handler as th
    import handler.feedback_handler as fh

    for mod in (th, fh):
        orig = mod.execute_sql

        async def always_ok(sql, dbtype, _orig=orig):
            code, result = await _orig(sql, dbtype)
            return 200, result

        mod.execute_sql = always_ok
    _installed.add("no_reflection")


# ---------------------------------------------------------------- SQL 生成 prompt 长度

def install_prompt_size_capture() -> None:
    if "prompt_size" in _installed:
        return
    import service.sql_generator.text_to_sql_generator as gen

    for fname in ("construct_output_text", "construct_sql_correction_prompt"):
        orig = getattr(gen, fname, None)
        if orig is None:
            continue

        def wrapped(*args, _orig=orig, **kwargs):
            prompt = _orig(*args, **kwargs)
            tel = _current()
            if tel is not None and isinstance(prompt, str):
                tel.sql_prompt_chars.append(len(prompt))
            return prompt

        setattr(gen, fname, wrapped)
    _installed.add("prompt_size")


def install_all(ablation: str = "full", seed_base: str = "eval") -> None:
    """按消融名安装插桩。ablation: full | norefl | norag | base"""
    install_llm_timer()
    install_prompt_size_capture()
    random_ablation = ablation in ("norag", "base")
    install_table_capture(random_ablation=random_ablation, seed_base=seed_base)
    install_column_capture(no_column_rag=random_ablation)
    if ablation in ("norefl", "base"):
        install_no_reflection()
