#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""180轮多轮评测 runner（生产链路 + 全量插桩）。

消融预设(--ablation):
  full   完整管线（Schema RAG + Memory + Reflection 全开）
  ragmem 仅关 Reflection（= +Memory 阶梯）
  rag    仅开 Schema RAG（Memory/Reflection 关，追问按新问处理）
  base   全关（基础生成：随机表候选 + 无列RAG + 无反思 + 无会话记忆）

每轮产物: <out>/turns/r{round}_t{idx}.json（断点续跑按文件跳过）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 环境必须先于 db_utils/handler 的 import 生效（与 run_local_remote.sh 一致）
os.environ.setdefault("text2sql_env", "prod")
os.environ.setdefault("TEXT2SQL_NACOS_REGISTER", "0")
os.environ.setdefault("TEXT2SQL_DISABLE_RABBITMQ", "1")
os.environ.setdefault("TEXT2SQL_SOURCE_DB_USE_LOCAL", "1")
os.environ.setdefault("TEXT2SQL_MYSQL4_USE_LOCAL", "1")
os.environ.setdefault("TEXT2SQL_MYSQL1_USE_TEST_NACOS", "1")
os.environ.setdefault("TEXT2SQL_MYSQL3_USE_TEST_NACOS", "1")
os.environ.setdefault("TEXT2SQL_SQL_MODEL", "gpt-4.1")
os.environ.setdefault("TEXT2SQL_FILTER_EXISTING_TABLES", "1")
os.environ.setdefault("TEXT2SQL_DB_CONNECT_TIMEOUT", "10")
os.environ.setdefault("TEXT2SQL_REDIS_URL", "redis://127.0.0.1:6380/0")
os.environ.pop("TEXT2SQL_LOCAL_SIM", None)

import argparse
import asyncio
import json
import logging
import re
import time
import traceback
import uuid
from pathlib import Path

from common.middleware.db_utils import initialize_all_pools, async_query_exec_by_saas
from handler.text2sql_handler import handle_query_demo_for_mq
from handler.feedback_handler import handle_user_feedback
from util.token_tracker import TokenTracker

import evals.instrument as instrument
from test_gold_eval import MockWebSocket, harvest, judge as answer_judge

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("run_eval")
logger.setLevel(logging.INFO)

SQL_KW = re.compile(r"(?is)\b(WITH|SELECT)\b.*")


def extract_pred_sql(text: str) -> str | None:
    """从 WS 消息/返回值里宽松提取 SQL（去代码栅栏、去前缀废话）。"""
    if not text or not str(text).strip():
        return None
    s = str(text).strip()
    fence = re.search(r"```(?:sql|SQL)?\s*([\s\S]*?)```", s)
    if fence:
        s = fence.group(1).strip()
    m = SQL_KW.search(s)
    if not m:
        return None
    sql = s[m.start():].strip().rstrip(";").strip()
    return sql or None


WS_TYPE = {
    "table_name": 1006,
    "sql1": 1007,
    "sql1_code": 1008,
    "sql1_res": 1009,
    "diag": 1034,
    "selected_table": 1013,
    "reflected_sql": 1014,
    "reflected_code": 1015,
    "reflected_res": 1016,
    "explain": 1020,
    "reject": 1050,
    "refuse": 1055,
    "unreachable": 1037,
}


def parse_ws(messages: list) -> dict:
    events = {k: [] for k in WS_TYPE}
    usage = None
    for message in messages:
        if isinstance(message, str):
            try:
                message = json.loads(message)
            except json.JSONDecodeError:
                continue
        if not isinstance(message, dict):
            continue
        if message.get("usage"):
            usage = message["usage"]
        data = message.get("data") or {}
        t = data.get("type") or data.get("TYPE")
        answer = data.get("answer") or data.get("ANSWER")
        for name, code in WS_TYPE.items():
            if t == code:
                events[name].append(answer if answer is not None else "")
    return {"events": events, "usage": usage}


def render_result(result) -> tuple[int, str, int]:
    """execute_sql 结果 → (status, 文本渲染, 行数)。"""
    import pandas as pd

    status, payload = result
    if status != 200 or not isinstance(payload, pd.DataFrame):
        return status, str(payload or "")[:500], 0
    if payload.empty:
        return 500, "No rows fetched", 0
    parts = []
    for _, row in payload.iterrows():
        parts.append(" ".join("" if v is None else str(v) for v in row.tolist()))
    return 200, "\n".join(parts), len(payload)


async def exec_with_timeout(coro_factory, seconds: float):
    try:
        return await asyncio.wait_for(coro_factory(), timeout=seconds)
    except asyncio.TimeoutError:
        return 500, "harness exec timeout"


async def exec_sql_real(sql: str, dbtype: str):
    from service.sql_executor.text_to_sql_exec import execute_sql

    if not sql:
        return None
    return await exec_with_timeout(lambda: execute_sql(sql, dbtype), 150)


def classify_exec(status, text: str) -> str:
    if status == 200:
        return "ok"
    if status == 403:
        return "blocked"
    if "No rows fetched" in (text or ""):
        return "empty"
    if "timed out" in (text or "") or "timeout" in (text or "").lower():
        return "timeout"
    return "error"


async def check_persisted(question_id: str) -> dict:
    try:
        rows = await exec_with_timeout(
            lambda: async_query_exec_by_saas(
                "SELECT question_id, intent, reflected_sql, formatted_output FROM saas.text_to_sql_middle_records WHERE question_id=:qid",
                {"qid": question_id},
            ),
            30,
        )
        if rows:
            row = rows[0]
            mapping = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
            return {"persisted": True, "intent": mapping.get("intent"), "has_sql": bool(mapping.get("reflected_sql"))}
        return {"persisted": False}
    except Exception as exc:
        return {"persisted": None, "error": f"{type(exc).__name__}: {exc}"}


class Runner:
    def __init__(self, args):
        self.args = args
        self.ablation = args.ablation
        flags = {
            "full": dict(rag=True, memory=True, reflection=True),
            "ragmem": dict(rag=True, memory=True, reflection=False),
            "rag": dict(rag=True, memory=False, reflection=False),
            "base": dict(rag=False, memory=False, reflection=False),
        }[self.ablation]
        self.flags = flags
        self.only_turns = args.only_turns or {}
        self.turns_dir = Path(args.out) / "turns"
        self.turns_dir.mkdir(parents=True, exist_ok=True)

    def setup_instrumentation(self):
        # instrument 层的开关粒度: full=全开 / norefl=仅关Reflection / base=随机表+关列RAG+关Reflection
        install_map = {"full": "full", "ragmem": "norefl", "rag": "norefl", "base": "base"}
        instrument.install_all(ablation=install_map[self.ablation], seed_base=f"{self.args.tag}|{self.ablation}")

    def turn_path(self, round_id, index) -> Path:
        return self.turns_dir / f"r{round_id}_t{index}.json"

    async def run_round(self, round_spec: dict, sem: asyncio.Semaphore) -> None:
        golds = [round_spec["initial"]] + round_spec["feedbacks"]
        round_id = round_spec["round_id"]
        target_indices = self.only_turns.get(round_id)
        async with sem:
            unique = uuid.uuid4().hex[:8]
            base = {
                "question_id": f"ev_{self.args.tag}_{round_id}_{unique}",
                "user_id": f"ev_user_{round_id}",
                "user_name": f"评测_{self.args.tag}_{round_id}",
                "session_id": f"ev_sess_{round_id}_{unique}",
            }
            for index, gold in enumerate(golds):
                is_target = target_indices is None or index in target_indices
                needs_memory_warmup = (
                    target_indices is not None
                    and self.flags["memory"]
                    and any(target > index for target in target_indices)
                )
                if not is_target and not needs_memory_warmup:
                    continue
                if is_target and self.turn_path(round_id, index).exists() and not self.args.force:
                    continue
                try:
                    record = await self.run_turn(round_spec, gold, base, index)
                except Exception as exc:
                    traceback.print_exc()
                    record = self.skeleton_record(round_spec, gold, index)
                    record["error"] = f"{type(exc).__name__}: {exc}"
                if not is_target:
                    logger.info("[%s r%s.%s] Memory 回放完成，不覆盖原记录", self.ablation, round_id, index)
                    continue
                self.turn_path(round_id, index).write_text(
                    json.dumps(record, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
                )
                logger.info(
                    "[%s r%s.%s] %s ex_final=%s %.1fs",
                    self.ablation, round_id, index, gold["question"][:24],
                    record.get("ex_final"), record.get("elapsed_seconds"),
                )

    def skeleton_record(self, round_spec, gold, index) -> dict:
        return {
            "round_id": round_spec["round_id"], "index": index, "source": round_spec["source"],
            "domain": round_spec.get("domain"), "theme": round_spec.get("theme"),
            "question": gold["question"], "labels": gold.get("labels", {}),
            "judge_type": gold.get("judge", "numeric"), "ablation": self.ablation,
            "had_error": True,
        }

    async def run_turn(self, round_spec: dict, gold: dict, base: dict, index: int) -> dict:
        record = self.skeleton_record(round_spec, gold, index)
        record["had_error"] = False
        question = gold["question"]
        labels = gold.get("labels", {})
        route_gold = labels.get("route_gold")
        source = round_spec["source"]

        use_memory = self.flags["memory"] and index > 0
        tel = instrument.begin_turn(f"{self.args.tag}:{base['question_id']}.{index}")
        tracker = TokenTracker()
        websocket = MockWebSocket()
        started = time.perf_counter()
        ret = None
        error = None
        try:
            if index == 0 or not self.flags["memory"]:
                turn_ids = dict(base)
                if index > 0:  # 无记忆模式：每问独立新会话
                    suffix = f"m{index}"
                    turn_ids = {
                        "question_id": f"{base['question_id']}_{suffix}",
                        "user_id": base["user_id"],
                        "user_name": base["user_name"],
                        "session_id": f"{base['session_id']}_{suffix}",
                    }
                query_info = {
                    "question": question,
                    "questionId": turn_ids["question_id"],
                    "userId": turn_ids["user_id"],
                    "userName": turn_ids["user_name"],
                    "feedbackNum": 0,
                    "sessionId": turn_ids["session_id"],
                    "messageId": f"{turn_ids['question_id']}_0",
                    "system": "test",
                }
                coroutine = handle_query_demo_for_mq(query_info, websocket, tracker)
            else:
                query_info_req = {
                    "question": question,
                    "feedbackQuestion": question,
                    "questionId": base["question_id"],
                    "feedbackQuestionId": f"{base['question_id']}_f{index}",
                    "userId": base["user_id"],
                    "userName": base["user_name"],
                    "feedbackNum": index,
                    "sessionId": base["session_id"],
                    "messageId": f"{base['question_id']}_{index}",
                    "system": "test",
                }
                coroutine = handle_user_feedback(query_info_req, websocket, tracker)
            task = asyncio.create_task(coroutine)
            try:
                ret = await asyncio.wait_for(asyncio.shield(task), timeout=self.args.timeout)
            except asyncio.TimeoutError:
                logger.warning("问题超时 %.0fs，等待自然结束: %s", self.args.timeout, question)
                ret = await task
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            logger.error("问题处理失败 [%s] %s: %s", base["session_id"], question, error)
        elapsed = round(time.perf_counter() - started, 1)
        instrument.end_turn()

        parsed = parse_ws(websocket.sent_messages)
        events = parsed["events"]
        answer_text, _ = harvest(websocket, ret)
        record["answer"] = (answer_text or "")[:2000]
        if isinstance(ret, dict) and ret.get("错误类型") and not error:
            error = f"{ret.get('错误类型')}: {ret.get('错误信息')}"

        # 路由捕获
        route_pred = None
        if index > 0 and self.flags["memory"]:
            if isinstance(ret, dict):
                route_pred = ret.get("意图分类") or None
        record["route_gold"] = route_gold
        record["route_pred"] = route_pred
        record["route_ok"] = None if route_gold is None else (route_pred == route_gold)

        # SQL 捕获与执行
        first_sql = extract_pred_sql(events["sql1"][0]) if events["sql1"] else None
        reflected_sql = extract_pred_sql(events["reflected_sql"][0]) if events["reflected_sql"] else None
        final_sql = reflected_sql or first_sql
        record["first_sql"] = first_sql
        record["final_sql"] = final_sql
        record["reflection_triggered"] = bool(reflected_sql and reflected_sql != first_sql)

        is_sql_turn = gold.get("judge") != "nonquery"
        gold_exec_status, gold_render, gold_rows = None, None, None
        if is_sql_turn and gold.get("gold_sql"):
            g = await exec_sql_real(gold["gold_sql"], source)
            if g is not None:
                gold_exec_status, gold_render, gold_rows = render_result(g)
                record["gold_exec"] = {
                    "status": gold_exec_status, "rows": gold_rows,
                    "preview": gold_render[:200],
                }

        for tagname, sql in (("first", first_sql), ("final", final_sql)):
            if not is_sql_turn:
                record[f"exec_{tagname}"] = None
                record[f"ex_{tagname}"] = None
                continue
            if not sql:
                record[f"exec_{tagname}"] = {"status": None, "kind": "no_sql"}
                record[f"ex_{tagname}"] = False
                if tagname == "first":
                    record["ex_reasons"] = ["未生成SQL"]
                continue
            # 未生成新的反思 SQL 时，first/final 是同一条查询。复用首次判分，
            # 避免重复执行引入超时或数据库刷新造成的随机差异。
            if tagname == "final" and sql == first_sql:
                record["exec_final"] = dict(record["exec_first"])
                record["ex_final"] = record["ex_first"]
                continue
            r = await exec_sql_real(sql, source)
            status, text, rows = render_result(r) if r is not None else (None, "", 0)
            record[f"exec_{tagname}"] = {"status": status, "kind": classify_exec(status, text), "rows": rows}
            if tagname == "first":
                record["first_result_preview"] = text[:200]
            # EX：以预测 SQL 的执行结果比对 gold（数值容差/实体/名单口径复用 answer 判分器）
            if gold_exec_status != 200:
                ok, reasons = False, [f"gold_sql_failed:{(gold_render or '')[:60]}"]
            else:
                ok, reasons = answer_judge(
                    gold,
                    text,
                    had_error=(status != 200),
                    row_count=rows,
                    gold_row_count=gold_rows,
                )
            record[f"ex_{tagname}"] = ok
            if tagname == "first":
                record["ex_reasons"] = reasons

        # nonquery 判定
        if not is_sql_turn:
            if self.flags["memory"]:
                record["ex_final"] = record["route_ok"]
            else:
                record["ex_final"] = bool(events["refuse"])  # 无记忆模式下被首问意图拒答即正确
            record["ex_first"] = None

        # 答案级判分（解释文本）
        if is_sql_turn:
            ok, reasons = answer_judge(gold, answer_text, had_error=bool(error) or not answer_text.strip())
            record["answer_ok"] = ok
            record["answer_reasons"] = reasons
        else:
            record["answer_ok"] = None

        # 遥测
        record["elapsed_seconds"] = elapsed
        record["error"] = error
        record["had_error"] = bool(error)
        record["telemetry"] = tel.snapshot()
        try:
            usage = tracker.get_aggregated_usage()
            record["token_usage"] = usage
            record["token_totals"] = {
                "prompt": sum(int(u.get("prompt_tokens") or 0) for u in usage),
                "completion": sum(int(u.get("completion_tokens") or 0) for u in usage),
                "total": sum(int(u.get("total_tokens") or 0) for u in usage),
            }
        except Exception as exc:
            record["token_usage"] = []
            record["token_totals"] = {"error": str(exc)}
        record["ws_usage"] = parsed["usage"]

        # 表召回
        gold_tables = [t.upper() for t in (gold.get("gold_tables") or [])]
        selected = tel.selected_tables or []
        candidates = tel.candidate_tables or []
        record["gold_tables"] = gold_tables
        record["table_recall"] = {
            "selected": selected,
            "candidate_tables": candidates,
            "selected_hit_all": bool(gold_tables) and all(t in selected for t in gold_tables) if gold_tables else None,
            "selected_hit_any": bool(gold_tables) and any(t in selected for t in gold_tables) if gold_tables else None,
            "candidate_hit_all": bool(gold_tables) and all(t in candidates for t in gold_tables) if gold_tables else None,
        }

        # 落库核验
        persist_key = (
            f"{base['question_id']}_f{index}"
            if (index > 0 and self.flags["memory"])
            else (f"{base['question_id']}_m{index}" if index > 0 else base["question_id"])
        )
        record["persist"] = await check_persisted(persist_key)
        return record


async def main() -> int:
    parser = argparse.ArgumentParser(description="180轮评测 runner")
    parser.add_argument("--set", default="evals/gold_set_180.json")
    parser.add_argument("--out", default=None, help="默认 evals/runs/<ablation>")
    parser.add_argument("--ablation", default="full", choices=["full", "ragmem", "rag", "base"])
    parser.add_argument("--tag", default=None)
    parser.add_argument("--only", default=None, help="轮次 id 逗号分隔")
    parser.add_argument("--only-turns", default=None, help="精确题号，如 12:0,13:1；有记忆时自动回放前文")
    parser.add_argument("--sources", default=None, help="MYSQL-1,MYSQL-2 过滤")
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--limit-rounds", type=int, default=None)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    only_turns = {}
    if args.only_turns:
        for item in args.only_turns.split(","):
            round_text, index_text = item.strip().split(":", 1)
            only_turns.setdefault(int(round_text), set()).add(int(index_text))
    args.only_turns = only_turns

    args.tag = args.tag or args.ablation
    args.out = args.out or f"evals/runs/{args.tag}"

    spec = json.loads(Path(args.set).read_text(encoding="utf-8"))
    rounds = spec["rounds"]
    if args.only_turns:
        keep = set(args.only_turns)
        rounds = [r for r in rounds if r["round_id"] in keep]
    elif args.only:
        keep = {int(x) for x in args.only.split(",") if x.strip()}
        rounds = [r for r in rounds if r["round_id"] in keep]
    if args.sources:
        keep = {x.strip() for x in args.sources.split(",")}
        rounds = [r for r in rounds if r["source"] in keep]
    if args.limit_rounds:
        rounds = rounds[: args.limit_rounds]

    runner = Runner(args)
    runner.setup_instrumentation()
    await initialize_all_pools()

    logger.info(
        "评测开始: ablation=%s flags=%s rounds=%d turns=%d out=%s",
        args.ablation, runner.flags, len(rounds), sum(1 + len(r["feedbacks"]) for r in rounds), args.out,
    )
    started = time.perf_counter()
    sem = asyncio.Semaphore(args.concurrency)
    await asyncio.gather(*(runner.run_round(r, sem) for r in rounds))
    logger.info("评测完成: %.1fs → %s", time.perf_counter() - started, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
