#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""聚合 runs/<tag>/turns/*.json → 指标 JSON + Markdown 报告。

用法: ./venv/bin/python evals/aggregate.py --runs full,ragmem,rag,base [--set evals/gold_set_180.json]
"""
import argparse
import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from sqlglot import exp, parse_one

ROOT = Path(__file__).resolve().parent.parent
ROUTE_CLASSES = ["SQL_GENERATION", "NEW_QUERY", "NON_QUERY"]
DEFAULT_TABLES = {
    "GET_A_INDUSTRY", "GET_A_SEC_CODE", "HK_COMBINFO", "HK_STKCODE",
    "HK_INDCHCOM", "PUB_INDU_REF", "GET_INDX_GEN_INFO",
}


def load_current_gold_drift(report_path: Path | None = None) -> set[tuple[int, int]]:
    """读取最近一次 Gold 复核中已随实时库变化的题号。"""
    path = report_path or (ROOT / "evals/gold_verify_report.json")
    if not path.exists():
        return set()
    try:
        report = json.loads(path.read_text(encoding="utf-8")).get("report", [])
    except (OSError, json.JSONDecodeError):
        return set()
    drift = set()
    for row in report:
        if row.get("status") not in ("warn", "fail"):
            continue
        match = re.fullmatch(r"r(\d+)\.t(\d+)", str(row.get("turn") or ""))
        if match:
            drift.add((int(match.group(1)), int(match.group(2))))
    return drift


def pct(n, d):
    return round(100.0 * n / d, 1) if d else None


def quantile(values, q):
    if not values:
        return None
    s = sorted(values)
    return round(s[min(len(s) - 1, int(q * (len(s) - 1)))], 2)


def load_turns(run_dir: Path) -> list[dict]:
    turns = []
    for path in sorted((run_dir / "turns").glob("r*_t*.json")):
        try:
            turns.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception as exc:
            turns.append({"_path": path.name, "had_error": True, "error": f"parse: {exc}"})
    return turns


def load_physical_schemas() -> dict[str, dict]:
    schemas = {}
    for source in ("MYSQL-1", "MYSQL-2", "MYSQL-4"):
        path = ROOT / f"evals/schema_{source}.json"
        if path.exists():
            schemas[source] = json.loads(path.read_text(encoding="utf-8"))
    return schemas


def sql_identifier_audit(sql: str, source: str, schemas: dict[str, dict]) -> dict:
    """按物理 schema 检查预测 SQL 的错误表名和字段名。"""
    if not sql or source not in schemas:
        return {"parse_error": False, "tables": set(), "bad_tables": set(), "columns": set(), "bad_columns": set()}
    try:
        tree = parse_one(sql, read="mysql")
    except Exception:
        return {"parse_error": True, "tables": set(), "bad_tables": set(), "columns": set(), "bad_columns": set()}

    schema = schemas[source]
    cte_names = {str(cte.alias_or_name).upper() for cte in tree.find_all(exp.CTE)}
    virtual_columns: dict[str, set[str]] = {}
    for cte in tree.find_all(exp.CTE):
        names = set()
        for item in cte.this.selects:
            name = item.alias_or_name
            if name and name != "*":
                names.add(str(name).upper())
        virtual_columns[str(cte.alias_or_name).upper()] = names
    for subquery in tree.find_all(exp.Subquery):
        alias = str(subquery.alias_or_name).upper()
        if not alias:
            continue
        virtual_columns[alias] = {
            str(item.alias_or_name).upper()
            for select in subquery.find_all(exp.Select)
            for item in select.selects
            if item.alias_or_name and item.alias_or_name != "*"
        }
    virtual_column_names = set().union(*virtual_columns.values()) if virtual_columns else set()

    real_tables = set()
    bad_tables = set()
    relation_columns: dict[str, set[str]] = dict(virtual_columns)
    for table in tree.find_all(exp.Table):
        name = str(table.name).upper()
        alias = str(table.alias_or_name).upper()
        if name in cte_names:
            relation_columns[alias] = virtual_columns.get(name, set())
            continue
        real_tables.add(name)
        columns = set(schema.get(name, {}).get("columns", {}))
        relation_columns[name] = columns
        relation_columns[alias] = columns
        if name not in schema:
            bad_tables.add(name)

    select_aliases = {
        str(item.alias).upper()
        for select in tree.find_all(exp.Select)
        for item in select.selects
        if getattr(item, "alias", None)
    }
    columns = set()
    bad_columns = set()
    for column in tree.find_all(exp.Column):
        name = str(column.name).upper()
        if name == "*" or (not column.table and name in select_aliases):
            continue
        qualifier = str(column.table).upper() if column.table else ""
        key = f"{qualifier}.{name}" if qualifier else name
        columns.add(key)
        if qualifier:
            available = relation_columns.get(qualifier)
            if available is not None and name not in available and name not in virtual_column_names:
                bad_columns.add(key)
            elif available is None and name not in virtual_column_names and not any(
                name in relation for relation in relation_columns.values()
            ):
                bad_columns.add(key)
        elif not any(name in available for available in relation_columns.values()):
            bad_columns.add(key)
    return {
        "parse_error": False,
        "tables": real_tables,
        "bad_tables": bad_tables,
        "columns": columns,
        "bad_columns": bad_columns,
    }


def summarize_hallucinations(turns: list[dict], sql_key: str, schemas: dict[str, dict]) -> dict:
    audits = [sql_identifier_audit(t.get(sql_key), t.get("source"), schemas) for t in turns if t.get(sql_key)]
    table_total = sum(len(row["tables"]) for row in audits)
    table_bad = sum(len(row["bad_tables"]) for row in audits)
    column_total = sum(len(row["columns"]) for row in audits)
    column_bad = sum(len(row["bad_columns"]) for row in audits)
    return {
        "sql_n": len(audits),
        "parse_error_n": sum(1 for row in audits if row["parse_error"]),
        "wrong_table_identifiers": table_bad,
        "table_identifiers": table_total,
        "wrong_table_rate": pct(table_bad, table_total),
        "wrong_column_identifiers": column_bad,
        "column_identifiers": column_total,
        "wrong_column_rate": pct(column_bad, column_total),
        "turns_with_wrong_table": sum(bool(row["bad_tables"]) for row in audits),
        "turns_with_wrong_column": sum(bool(row["bad_columns"]) for row in audits),
    }


def macro_f1(records: list[dict]) -> dict:
    """records: (gold, pred) 对；pred 可能为 None/UNKNOWN。"""
    labels = ROUTE_CLASSES
    per = {}
    for lab in labels:
        tp = sum(1 for g, p in records if g == lab and p == lab)
        fp = sum(1 for g, p in records if g != lab and p == lab)
        fn = sum(1 for g, p in records if g == lab and p != lab)
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        f1 = (2 * precision * recall / (precision + recall)) if precision and recall else (0.0 if (tp + fp and tp + fn) else None)
        per[lab] = {"tp": tp, "fp": fp, "fn": fn,
                    "precision": round(precision, 4) if precision is not None else None,
                    "recall": round(recall, 4) if recall is not None else None,
                    "f1": round(f1, 4) if f1 is not None else None}
    f1s = [v["f1"] for v in per.values() if v["f1"] is not None]
    confusion = Counter((g, str(p)) for g, p in records)
    return {
        "n": len(records),
        "correct": sum(1 for g, p in records if g == p),
        "accuracy": pct(sum(1 for g, p in records if g == p), len(records)),
        "macro_f1": round(statistics.mean(f1s), 4) if f1s else None,
        "per_class": per,
        "confusion": {f"{g}→{p}": c for (g, p), c in sorted(confusion.items()) if g != p},
        "no_prediction": sum(1 for g, p in records if not p),
    }


def summarize_run(run_dir: Path, verify_report: Path | None = None) -> dict:
    turns = load_turns(run_dir)
    schemas = load_physical_schemas()
    sql_turns = [t for t in turns if t.get("judge_type") != "nonquery"]
    nonquery = [t for t in turns if t.get("judge_type") == "nonquery"]
    current_drift = load_current_gold_drift(verify_report)
    is_current_drift = lambda t: (t.get("round_id"), t.get("index")) in current_drift
    # 只有明确执行失败才算 gold 漂移；缺少 gold_exec 是评测记录无效，不能混为一类。
    gold_failed = [
        t for t in sql_turns
        if (t.get("gold_exec") and t["gold_exec"].get("status") != 200) or is_current_drift(t)
    ]
    invalid = [t for t in sql_turns if not t.get("gold_exec")]
    valid = [
        t for t in sql_turns
        if (t.get("gold_exec") or {}).get("status") == 200 and not is_current_drift(t)
    ]
    reflection_enabled = any(t.get("ablation") == "full" for t in turns)

    def final_ok(turn):
        # 旧运行在没有 Reflection 时仍把同一条 SQL 执行了两次，偶发超时会让
        # first/final 不一致。此时首次执行才是该消融组唯一有效的 EX。
        return turn.get("ex_final") if reflection_enabled else turn.get("ex_first")

    def final_exec(turn):
        return turn.get("exec_final") if reflection_enabled else turn.get("exec_first")

    ex_first = [1 if t.get("ex_first") else 0 for t in valid]
    ex_final = [1 if final_ok(t) else 0 for t in valid]

    # Reflection 有效性
    first_bad = [t for t in valid if not t.get("ex_first")]
    reflected = [t for t in first_bad if reflection_enabled and t.get("reflection_triggered")]
    repaired = [t for t in reflected if final_ok(t)]
    broken_by_reflect = [t for t in valid if reflection_enabled and t.get("ex_first") and not final_ok(t)]
    first_empty = [t for t in valid if (t.get("exec_first") or {}).get("kind") == "empty"]
    first_error = [t for t in valid if (t.get("exec_first") or {}).get("kind") in ("error", "timeout")]

    # 分层
    def rate(subset, key="ex_final"):
        hits = [1 if (final_ok(t) if key == "ex_final" else t.get(key)) else 0 for t in subset]
        return {"n": len(hits), "correct": sum(hits), "acc": pct(sum(hits), len(hits))}

    by = lambda field: {
        k: rate([t for t in valid if (t.get("labels") or {}).get(field) == k])
        for k in sorted({(t.get("labels") or {}).get(field) for t in valid if (t.get("labels") or {}).get(field)}, key=str)
    }

    # 路由（有记忆的 run 才有 route_pred）
    route_records = [(t.get("route_gold"), t.get("route_pred")) for t in turns
                     if t.get("route_gold") and t.get("index", 0) > 0]
    route_records = [(g, p if p in ROUTE_CLASSES else (p or None)) for g, p in route_records]
    routing_enabled = any(p is not None for _, p in route_records)

    # 性能
    elapsed = [t["elapsed_seconds"] for t in turns if isinstance(t.get("elapsed_seconds"), (int, float))]
    llm_calls = [t.get("telemetry", {}).get("llm_call_count") for t in turns if t.get("telemetry")]
    token_totals = [t.get("token_totals", {}) for t in turns if t.get("token_totals")]
    tok_prompt = [x.get("prompt") for x in token_totals if isinstance(x.get("prompt"), (int, float))]
    tok_comp = [x.get("completion") for x in token_totals if isinstance(x.get("completion"), (int, float))]

    # 表召回（表定位实际运行的轮次）
    sel_turns = [
        t for t in valid
        if t.get("ablation") != "base"
        and t.get("table_recall", {}).get("selected") is not None
        and t["table_recall"].get("selected")
    ]
    hit_all = sum(1 for t in sel_turns if t["table_recall"]["selected_hit_all"])
    hit_any = sum(1 for t in sel_turns if t["table_recall"]["selected_hit_any"])
    cand_all = 0
    for turn in sel_turns:
        retrieved_gold = set(turn.get("gold_tables") or []) - DEFAULT_TABLES
        candidates = set(turn["table_recall"].get("candidate_tables") or turn["table_recall"].get("candidates") or [])
        # 旧运行记录把候选表存在 telemetry 中，table_recall 仅存 selected；兼容两种格式。
        if not candidates:
            candidates = set((turn.get("telemetry") or {}).get("candidate_tables") or [])
        cand_all += int(not retrieved_gold or retrieved_gold <= candidates)

    table_recall_at_k = {}
    for k in (1, 3, 5, 10):
        hit = total = 0
        for turn in sel_turns:
            gold = set(turn.get("gold_tables") or []) - DEFAULT_TABLES
            selected = [name for name in turn["table_recall"].get("selected", []) if name not in DEFAULT_TABLES]
            hit += len(gold & set(selected[:k]))
            total += len(gold)
        table_recall_at_k[str(k)] = {"hit": hit, "total": total, "recall": pct(hit, total)}

    exec_ok = sum(1 for t in valid if (final_exec(t) or {}).get("status") == 200)
    persisted = [t for t in turns if (t.get("persist") or {}).get("persisted") is not None]

    answer_turns = [t for t in valid if t.get("answer_ok") is not None]
    prompt_chars = [c for t in turns for c in (t.get("telemetry", {}).get("sql_prompt_chars") or [])]

    return {
        "run_dir": str(run_dir),
        "turns_total": len(turns),
        "sql_turns": len(sql_turns),
        "nonquery_turns": len(nonquery),
        "gold_drift_turns": len(gold_failed),
        "invalid_eval_turns": len(invalid),
        "ex": {
            "ex_first": pct(sum(ex_first), len(ex_first)),
            "ex_final": pct(sum(ex_final), len(ex_final)),
            "first_correct": sum(ex_first),
            "final_correct": sum(ex_final),
            "n": len(valid),
        },
        "reflection": {
            "enabled": reflection_enabled,
            "first_fail_n": len(first_bad),
            "reflected_n": len(reflected),
            "repaired_n": len(repaired),
            "repair_rate": pct(len(repaired), len(reflected)),
            "first_to_final_lift_pp": round(
                (pct(sum(ex_final), len(ex_final)) or 0) - (pct(sum(ex_first), len(ex_first)) or 0), 1),
            "regressed_n": len(broken_by_reflect),
            "empty_result_n": len(first_empty),
            "empty_recovered": sum(1 for t in first_empty if final_ok(t)),
            "error_result_n": len(first_error),
        },
        "by_domain": {
            k: rate([t for t in valid if t.get("domain") == k])
            for k in sorted({t.get("domain") for t in valid if t.get("domain")}, key=str)
        },
        "by_source": {
            k: rate([t for t in valid if t.get("source") == k])
            for k in sorted({t.get("source") for t in valid if t.get("source")}, key=str)
        },
        "by_difficulty": by("difficulty"),
        "by_followup_type": by("followup_type"),
        "by_time": {
            "absolute": rate([t for t in valid if (t.get("labels") or {}).get("time_sensitivity") == "absolute"]),
            "relative": rate([t for t in valid if (t.get("labels") or {}).get("time_sensitivity") == "relative"]),
        },
        "followup_ex": rate([t for t in valid if (t.get("index") or 0) > 0]),
        "initial_ex": rate([t for t in valid if (t.get("index") or 0) == 0]),
        "routing": macro_f1(route_records) if routing_enabled else None,
        "perf": {
            "latency_n": len(elapsed),
            "latency_p50_s": quantile(elapsed, 0.50),
            "latency_p90_s": quantile(elapsed, 0.90),
            "latency_p95_s": quantile(elapsed, 0.95),
            "latency_mean_s": round(statistics.mean(elapsed), 1) if elapsed else None,
            "latency_max_s": max(elapsed) if elapsed else None,
            "llm_calls_mean": round(statistics.mean(llm_calls), 2) if llm_calls else None,
            "llm_calls_n": len(llm_calls),
            "llm_calls_max": max(llm_calls) if llm_calls else None,
            "tokens_prompt_mean": round(statistics.mean(tok_prompt)) if tok_prompt else None,
            "tokens_completion_mean": round(statistics.mean(tok_comp)) if tok_comp else None,
            "tokens_total_mean": round(statistics.mean([a + b for a, b in zip(tok_prompt, tok_comp) if a is not None and b is not None])) if tok_prompt else None,
            "tokens_n": len(tok_prompt),
            "sql_prompt_chars_mean": round(statistics.mean(prompt_chars)) if prompt_chars else None,
            "sql_prompt_n": len(prompt_chars),
        },
        "stability": {
            "sql_exec_success_rate": pct(exec_ok, len(valid)),
            "sql_exec_success_n": exec_ok,
            "persist_rate": pct(sum(1 for t in persisted if t["persist"]["persisted"]), len(persisted)),
            "persisted_n": sum(1 for t in persisted if t["persist"]["persisted"]),
            "persist_total": len(persisted),
            "handler_error_turns": sum(1 for t in turns if t.get("had_error")),
            "timeout_turns": sum(1 for t in turns if (final_exec(t) or {}).get("kind") == "timeout"),
        },
        "table_recall": {
            "n": len(sel_turns),
            "selected_hit_all_n": hit_all,
            "selected_hit_any_n": hit_any,
            "candidate_hit_all_n": cand_all,
            "selected_hit_all": pct(hit_all, len(sel_turns)),
            "selected_hit_any": pct(hit_any, len(sel_turns)),
            "candidate_hit_all": pct(cand_all, len(sel_turns)),
            "recall_at_k": table_recall_at_k,
        },
        "identifier_hallucination": {
            "first": summarize_hallucinations(valid, "first_sql", schemas),
            "final": summarize_hallucinations(valid, "final_sql", schemas),
        },
        "answer_accuracy": pct(sum(1 for t in answer_turns if t["answer_ok"]), len(answer_turns)),
        "answer_correct": sum(1 for t in answer_turns if t["answer_ok"]),
        "answer_n": len(answer_turns),
    }


def render_md(summaries: list[dict]) -> str:
    lines = ["# Text2SQL 评测报告", "", f"生成时间: 2026-09-03", ""]
    for s in summaries:
        tag = Path(s["run_dir"]).name
        lines += [f"## Run: {tag}", ""]
        ex = s["ex"]
        lines += [
            f"- 题量: {s['turns_total']} 问(SQL题 {s['sql_turns']}, 非查询 {s['nonquery_turns']}, "
            f"gold漂移剔除 {s['gold_drift_turns']}, 评测无效 {s['invalid_eval_turns']})",
        ]
        if s["reflection"]["enabled"]:
            lines += [
                f"- **首次EX {ex['first_correct']}/{ex['n']}={ex['ex_first']}% → Reflection后EX {ex['final_correct']}/{ex['n']}={ex['ex_final']}%**",
                f"- Reflection: 首次失败 {s['reflection']['first_fail_n']} 题, 触发修复 {s['reflection']['reflected_n']}, 修复成功 {s['reflection']['repaired_n']}/{s['reflection']['reflected_n']} (**{s['reflection']['repair_rate']}%**), 反而改坏 {s['reflection']['regressed_n']}",
                f"- 空结果 {s['reflection']['empty_result_n']} 题(不触发修复, 恢复 {s['reflection']['empty_recovered']}); 执行报错 {s['reflection']['error_result_n']} 题",
            ]
        else:
            lines += [f"- **EX {ex['first_correct']}/{ex['n']}={ex['ex_first']}%** (Reflection关闭)"]
        if s["routing"]:
            r = s["routing"]
            lines += [
                f"- 路由 Macro-F1 **{r['macro_f1']}** (答对 {r['correct']}/{r['n']}={r['accuracy']}%, 未预测 {r['no_prediction']})",
                f"  - per-class: " + "; ".join(f"{k}: P={v['precision']} R={v['recall']} F1={v['f1']}" for k, v in r["per_class"].items()),
            ]
            if r["confusion"]:
                lines += [f"  - 混淆: {r['confusion']}"]
        p = s["perf"]
        lines += [
            f"- 延迟({p['latency_n']}轮): p50 {p['latency_p50_s']}s / p90 {p['latency_p90_s']}s / **p95 {p['latency_p95_s']}s** / max {p['latency_max_s']}s",
            f"- LLM 调用均值 {p['llm_calls_mean']} 次/轮({p['llm_calls_n']}轮, max {p['llm_calls_max']}); Token 均值 prompt {p['tokens_prompt_mean']} + completion {p['tokens_completion_mean']} ({p['tokens_n']}轮)",
            f"- SQL 生成 Prompt 平均长度 {p['sql_prompt_chars_mean']} 字符({p['sql_prompt_n']}次生成调用)",
            f"- 稳定: SQL执行成功 {s['stability']['sql_exec_success_n']}/{ex['n']}={s['stability']['sql_exec_success_rate']}%, 落库 {s['stability']['persisted_n']}/{s['stability']['persist_total']}={s['stability']['persist_rate']}%, handler异常 {s['stability']['handler_error_turns']}, 超时 {s['stability']['timeout_turns']}",
        ]
        tr = s["table_recall"]
        table_line = (
            f"- 表召回: 选中表全覆盖 {tr['selected_hit_all_n']}/{tr['n']}={tr['selected_hit_all']}% / "
            f"命中任一 {tr['selected_hit_any_n']}/{tr['n']}={tr['selected_hit_any']}% / "
            f"候选池覆盖(排除固定注入表) {tr['candidate_hit_all_n']}/{tr['n']}={tr['candidate_hit_all']}%"
            if tr["n"] else "- 表召回: 未启用"
        )
        lines += [
            table_line,
            "- Table Recall@K: " + "; ".join(
                f"K={k}: {v['hit']}/{v['total']}={v['recall']}%"
                for k, v in tr["recall_at_k"].items()
            ),
            (
                "- 错误表/字段幻觉率（最终SQL）: "
                f"表 {s['identifier_hallucination']['final']['wrong_table_identifiers']}/"
                f"{s['identifier_hallucination']['final']['table_identifiers']}="
                f"{s['identifier_hallucination']['final']['wrong_table_rate']}%；"
                f"字段 {s['identifier_hallucination']['final']['wrong_column_identifiers']}/"
                f"{s['identifier_hallucination']['final']['column_identifiers']}="
                f"{s['identifier_hallucination']['final']['wrong_column_rate']}%"
            ),
            f"- 分层EX: " + "; ".join(f"{k}={v['correct']}/{v['n']}={v['acc']}%" for k, v in s["by_domain"].items()),
            f"- 数据源EX: " + "; ".join(f"{k}={v['correct']}/{v['n']}={v['acc']}%" for k, v in s["by_source"].items()),
            f"- 难度EX: " + "; ".join(f"{k}={v['correct']}/{v['n']}={v['acc']}%" for k, v in s["by_difficulty"].items()),
            f"- 追问类型EX: " + "; ".join(f"{k}={v['correct']}/{v['n']}={v['acc']}%" for k, v in s["by_followup_type"].items()),
            f"- 时间敏感性EX: 绝对 {s['by_time']['absolute']['correct']}/{s['by_time']['absolute']['n']}={s['by_time']['absolute']['acc']}% / 相对 {s['by_time']['relative']['correct']}/{s['by_time']['relative']['n']}={s['by_time']['relative']['acc']}%",
            f"- 首问EX {s['initial_ex']['correct']}/{s['initial_ex']['n']}={s['initial_ex']['acc']}% vs 追问EX {s['followup_ex']['correct']}/{s['followup_ex']['n']}={s['followup_ex']['acc']}%; 答案文本一致 {s['answer_correct']}/{s['answer_n']}={s['answer_accuracy']}%",
            "",
        ]
    if len(summaries) > 1:
        lines += ["## 消融对比", "", "| 指标 | " + " | ".join(Path(s["run_dir"]).name for s in summaries) + " |",
                  "|---|" + "---:|" * len(summaries)]
        def row(name, fn):
            return f"| {name} | " + " | ".join(str(fn(s)) for s in summaries) + " |"
        lines += [
            row("首次EX", lambda s: f"{s['ex']['ex_first']}% ({s['ex']['first_correct']}/{s['ex']['n']})"),
            row("最终EX", lambda s: f"{s['ex']['ex_final']}% ({s['ex']['final_correct']}/{s['ex']['n']})"),
            row("Reflection修复成功率", lambda s: (f"{s['reflection']['repair_rate']}% ({s['reflection']['repaired_n']}/{s['reflection']['reflected_n']})" if s['reflection']['enabled'] else "未启用")),
            row("追问EX", lambda s: f"{s['followup_ex']['acc']}% ({s['followup_ex']['correct']}/{s['followup_ex']['n']})"),
            row("指代继承EX", lambda s: (lambda v: f"{v['acc']}% ({v['correct']}/{v['n']})")((s["by_followup_type"].get("指代继承") or {}))),
            row("时间漂移EX", lambda s: (lambda v: f"{v['acc']}% ({v['correct']}/{v['n']})")((s["by_followup_type"].get("时间漂移") or {}))),
            row("p95延迟s", lambda s: s["perf"]["latency_p95_s"]),
            row("LLM调用均值", lambda s: s["perf"]["llm_calls_mean"]),
            row("Token均值", lambda s: s["perf"]["tokens_total_mean"]),
        ]
        lines += [""]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", default="full")
    parser.add_argument("--set", default="evals/gold_set_180.json")
    parser.add_argument("--verify-report", default=None)
    args = parser.parse_args()

    set_path = ROOT / args.set
    inferred_report = set_path.with_name(f"{set_path.stem}_verify_report.json")
    verify_report = Path(args.verify_report) if args.verify_report else inferred_report
    if not verify_report.is_absolute():
        verify_report = ROOT / verify_report
    if not verify_report.exists():
        verify_report = ROOT / "evals/gold_verify_report.json"

    summaries = []
    for tag in args.runs.split(","):
        run_dir = ROOT / "evals/runs" / tag
        if not run_dir.exists():
            print(f"[WARN] 不存在 {run_dir}, 跳过")
            continue
        summaries.append(summarize_run(run_dir, verify_report))

    out_json = ROOT / "evals/runs" / ("metrics_" + "_".join(t for t in args.runs.split(",")) + ".json")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(summaries, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    md = render_md(summaries)
    out_md = out_json.with_suffix(".md")
    out_md.write_text(md, encoding="utf-8")
    print(md)
    print(f"指标 JSON: {out_json}")


if __name__ == "__main__":
    main()
