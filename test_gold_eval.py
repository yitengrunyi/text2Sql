#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""10轮×6问 gold 评测（生产链路版）。

初始问题走 handler.text2sql_handler.handle_query_demo_for_mq，追问走
handler.feedback_handler.handle_user_feedback（生产反馈入口，含意图分析/
SQL生成/新查询分发），全程 MockWebSocket 捕获回答。判分规则：
- numeric：数值命中（相对容差0.5%；识别 亿/百万/万 单位换算与裸值）；
  给定 gold_entities/asked_date 时必须同时命中。
- entity：实体必须命中，数值/日期为软校验（记录不计错）。
- list：实体名单重叠率≥80%。
"""

import os

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
import math
import re
import statistics
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path

from common.middleware.db_utils import initialize_all_pools
from handler.text2sql_handler import handle_query_demo_for_mq
from handler.feedback_handler import handle_user_feedback

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("gold_eval")

NUM_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
DATE_TIME_RE = re.compile(
    r"(?<!\d)\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:\s+\d{1,2}:\d{1,2}:\d{1,2})?"
)


class MockWebSocket:
    """捕获生产链路通过 websocket 下发的消息。"""

    def __init__(self):
        self.sent_messages = []

    async def send_json(self, data):
        self.sent_messages.append(data)

    async def send_text(self, data):
        self.sent_messages.append(data)

    async def accept(self):
        pass

    async def receive_text(self):
        return "{}"


def _collect_answers(node, texts: list, sqls: list):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "answer" and isinstance(value, str) and value.strip():
                texts.append(value)
            elif key in ("sql", "executed_sql") and isinstance(value, str) and value.strip():
                sqls.append(value)
            else:
                _collect_answers(value, texts, sqls)
    elif isinstance(node, list):
        for item in node:
            _collect_answers(item, texts, sqls)


def harvest(websocket: MockWebSocket, ret) -> tuple[str, str]:
    texts: list[str] = []
    sqls: list[str] = []
    for message in websocket.sent_messages:
        if isinstance(message, str):
            try:
                message = json.loads(message)
            except json.JSONDecodeError:
                texts.append(message)
                continue
        _collect_answers(message, texts, sqls)
    if isinstance(ret, dict):
        for key in ("查询结果", "处理结果", "融合后查询"):
            if ret.get(key):
                texts.append(str(ret[key]))
    answer_text = "\n".join(texts)
    sql_text = next((s for s in reversed(sqls) if s.strip().upper().startswith("SELECT")), "")
    return answer_text, sql_text


def extract_number_candidates(text: str) -> list[float]:
    """提取文本数值候选：裸值恒收录；数值旁紧邻 亿/百万/万 时附换算值。

    表头单位（如『归母净利润(万)』列下的裸数值）由 gold 侧降尺度覆盖。
    """
    candidates: list[float] = []
    # 先移除完整日期/时间，避免 2026-01-05 00:00:00 被拆成 -1、-5、0。
    text = DATE_TIME_RE.sub(" ", text or "")
    for match in NUM_RE.finditer(text):
        raw = match.group(0)
        tail = text[match.end(): match.end() + 3]
        if tail.startswith("年") or re.match(r"^[/-]", tail):
            # 日期片段（2026年 / 2026-08-31）不参与数值比对
            continue
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            continue
        candidates.append(value)
        for keyword, scale in (("亿", 1e8), ("百万", 1e6), ("万", 1e4)):
            if keyword in tail:
                candidates.append(value * scale)
                break
    return candidates


# gold 侧降尺度：元→亿(1e-8)、元→百万(1e-6)、元→万(1e-4)、百万→亿(1e-2)
GOLD_SCALES = (1e-8, 1e-6, 1e-4, 1e-2, 1.0)


def numeric_hit(answer: str, gold: str) -> bool:
    gold_base = float(gold)
    candidates = extract_number_candidates(answer)
    for scale in GOLD_SCALES:
        target = gold_base * scale
        # 0.005 的绝对容差只用于原始单位下的两位小数舍入。若对单位换算后的
        # 极小目标继续使用该下限，时间戳中的 0 会误命中任意小额数值。
        tolerance = max(abs(target) * 0.005, 0.005) if scale == 1.0 else max(abs(target) * 0.005, 1e-12)
        if any(abs(candidate - target) <= tolerance for candidate in candidates):
            return True
    return False


def date_hit(answer: str, gold_date: str) -> bool:
    normalized = re.sub(r"[年月]", "-", (answer or "")).replace("日", "")
    year, month, day = gold_date.split("-")
    variants = {gold_date, f"{year}-{int(month)}-{int(day)}"}
    return any(variant in normalized for variant in variants)


def entity_hit(answer: str, entities: list[str]) -> bool:
    text = re.sub(r"[\s()（）]", "", answer or "")
    for entity in entities:
        normalized = re.sub(r"[\s()（）]", "", entity)
        if normalized and normalized in text:
            return True
    return False


def judge(
    gold: dict,
    answer: str | None,
    had_error: bool,
    row_count: int | None = None,
    gold_row_count: int | None = None,
) -> tuple[bool, list[str]]:
    if had_error:
        return False, ["执行异常/无结果"]
    if not answer or not str(answer).strip():
        return False, ["答案为空"]
    answer = str(answer)
    kind = gold.get("judge", "numeric")
    if (
        row_count is not None
        and gold_row_count is not None
        and gold_row_count > 0
        and row_count > max(5, gold_row_count * 2)
    ):
        return False, [f"结果范围过大({row_count}行, Gold为{gold_row_count}行)"]

    soft = {}
    if gold.get("gold_value"):
        try:
            soft["数值"] = numeric_hit(answer, gold["gold_value"])
        except (TypeError, ValueError):
            # 实体、名单和日期题可把文本答案放在 gold_value；它不参与数值判分。
            pass
    if gold.get("gold_date"):
        soft["日期"] = date_hit(answer, gold["gold_date"])
    entities = gold.get("gold_entities") or []
    if entities:
        soft["实体"] = entity_hit(answer, entities)

    numeric_value = False
    try:
        float(gold.get("gold_value"))
        numeric_value = bool(gold.get("gold_value"))
    except (TypeError, ValueError):
        pass
    if entities and numeric_value:
        soft["实体数值同行"] = any(
            entity_hit(line, entities) and numeric_hit(line, gold["gold_value"])
            for line in answer.splitlines()
        )

    if kind == "numeric":
        checks = [("数值", soft.get("实体数值同行", soft.get("数值", True)))]
        if gold.get("gold_entities"):
            checks.append(("实体", soft.get("实体", True)))
        if gold.get("asked_date"):
            checks.append(("日期", soft.get("日期", True)))
    elif kind == "entity":
        checks = [("实体", soft.get("实体", True))]
        if numeric_value:
            checks.append(("数值", soft.get("实体数值同行", soft.get("数值", True))))
        if gold.get("gold_date"):
            checks.append(("日期", soft.get("日期", False)))
    else:  # list
        overlap = sum(1 for e in entities if e in answer)
        soft["名单命中"] = f"{overlap}/{len(entities)}"
        required = max(1, math.ceil(0.8 * len(entities))) if entities else 1
        checks = [("名单", overlap >= required)]
        if numeric_value:
            checks.append(("数值", soft.get("数值", False)))

    ok = all(value for _, value in checks)
    reasons = [name for name, value in checks if not value] or ["全项通过"]
    if kind == "entity":
        reasons.append(f"(软校验:{ {k: v for k, v in soft.items() if k != '实体'} })")
    return ok, reasons


def summarize(results: list[dict], wall_seconds: float) -> dict:
    completed = [r for r in results if not r["had_error"]]
    times = [r["elapsed_seconds"] for r in results if r["elapsed_seconds"] is not None]
    correct = [r for r in results if r["correct"]]
    by_source: dict[str, dict[str, int]] = {}
    for r in results:
        bucket = by_source.setdefault(r["source"], {"total": 0, "correct": 0})
        bucket["total"] += 1
        if r["correct"]:
            bucket["correct"] += 1
    return {
        "wall_seconds": round(wall_seconds, 1),
        "question_count": len(results),
        "completed_count": len(completed),
        "correct_count": len(correct),
        "accuracy": round(len(correct) / len(results), 4) if results else None,
        "timing": {
            "mean_seconds": round(statistics.mean(times), 2) if times else None,
            "median_seconds": round(statistics.median(times), 2) if times else None,
            "p90_seconds": round(sorted(times)[int(0.9 * (len(times) - 1))], 2)
            if times
            else None,
            "min_seconds": min(times) if times else None,
            "max_seconds": max(times) if times else None,
        },
        "by_source": by_source,
    }


def render_report(summary: dict, results: list[dict]) -> str:
    lines = [
        "# Gold 10轮×6问 评测报告（生产链路）",
        "",
        f"运行时间：{datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"题量：{summary['question_count']}，完成：{summary['completed_count']}，"
        f"答对：{summary['correct_count']}，正确率：{summary['accuracy']:.1%}",
        f"总墙钟：{summary['wall_seconds']}s；单题耗时 "
        f"均值 {summary['timing']['mean_seconds']}s / 中位 {summary['timing']['median_seconds']}s / "
        f"P90 {summary['timing']['p90_seconds']}s / 最快 {summary['timing']['min_seconds']}s / "
        f"最慢 {summary['timing']['max_seconds']}s",
        "",
        "| 数据源 | 题数 | 答对 | 正确率 |",
        "|---|---:|---:|---:|",
    ]
    for source, bucket in summary["by_source"].items():
        lines.append(
            f"| {source} | {bucket['total']} | {bucket['correct']} | "
            f"{bucket['correct'] / bucket['total']:.1%} |"
        )
    lines += ["", "| 轮 | # | 问题 | 判定 | 耗时(s) | 标准答案 | 回答(截断) | 失败项 |",
              "|---:|---:|---|---|---:|---|---|---|"]
    for r in results:
        answer = (r["answer"] or "").replace("\n", " ")[:80]
        gold = (r["gold_display"] or "").replace("\n", " ")
        reasons = "、".join(r["reasons"])[:60]
        lines.append(
            f"| {r['round']} | {r['index']} | {r['question'][:36]} | "
            f"{'对' if r['correct'] else '错'} | {r['elapsed_seconds']} | "
            f"{gold[:44]} | {answer} | {reasons} |"
        )
    return "\n".join(lines) + "\n"


async def run_question(
    question: str, index: int, session: dict, is_initial: bool, timeout: float = 600
) -> dict:
    started = time.perf_counter()
    websocket = MockWebSocket()
    error = None
    ret = None
    if is_initial:
        query_info = {
            "question": question,
            "questionId": session["question_id"],
            "userId": session["user_id"],
            "userName": session["user_name"],
            "feedbackNum": 0,
            "sessionId": session["session_id"],
            "messageId": f"{session['question_id']}_0",
            "system": "test",
        }
        coroutine = handle_query_demo_for_mq(query_info, websocket)
    else:
        query_info_req = {
            "question": question,
            "feedbackQuestion": question,
            "questionId": session["question_id"],
            "feedbackQuestionId": f"{session['question_id']}_f{index}",
            "userId": session["user_id"],
            "userName": session["user_name"],
            "feedbackNum": index,
            "sessionId": session["session_id"],
            "messageId": f"{session['question_id']}_{index}",
            "system": "test",
        }
        coroutine = handle_user_feedback(query_info_req, websocket)
    try:
        # 不取消协程：wait_for 超时会 CancelledError 直穿 except Exception，
        # 跳过会话落库导致后续追问全部"未找到会话历史记录"。超时仅记警告，
        # 继续等自然结束（生产 WS 链路同样没有外部取消）。
        task = asyncio.create_task(coroutine)
        try:
            ret = await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("问题超时 %.0fs，等待自然结束(不取消): %s", timeout, question)
            ret = await task
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        logger.error("问题处理失败 [%s] %s: %s", session["session_id"], question, error)
    elapsed = round(time.perf_counter() - started, 1)
    answer, sql = harvest(websocket, ret)
    if isinstance(ret, dict) and ret.get("错误类型"):
        error = f"{ret.get('错误类型')}: {ret.get('错误信息')}"
    return {
        "answer": answer,
        "sql": sql,
        "elapsed_seconds": elapsed,
        "error": error,
        "had_error": error is not None or not answer.strip(),
    }


async def run_round(round_spec: dict) -> list[dict]:
    golds = [round_spec["initial"]] + round_spec["feedbacks"]
    unique = uuid.uuid4().hex[:8]
    session = {
        "question_id": f"gold_{round_spec['round_id']}_{unique}",
        "user_id": f"gold_user_{round_spec['round_id']}",
        "user_name": f"gold评测_{round_spec['round_id']}",
        "session_id": f"gold_session_{round_spec['round_id']}_{unique}",
    }
    judged = []
    for index, gold in enumerate(golds):
        logger.info(
            "[round%s/%s] %s", round_spec["round_id"], index, gold["question"]
        )
        outcome = await run_question(
            gold["question"], index, session, is_initial=(index == 0)
        )
        correct, reasons = judge(gold, outcome["answer"], outcome["had_error"])
        judged.append(
            {
                "round": round_spec["round_id"],
                "index": index,
                "source": round_spec["source"],
                "theme": round_spec.get("theme"),
                "question": gold["question"],
                "judge_type": gold.get("judge", "numeric"),
                "gold_display": gold.get("gold_display"),
                "gold_sql": gold.get("gold_sql"),
                "answer": outcome["answer"][:4000],
                "sql": outcome["sql"][:4000],
                "elapsed_seconds": outcome["elapsed_seconds"],
                "had_error": outcome["had_error"],
                "error": outcome["error"],
                "correct": correct,
                "reasons": reasons,
            }
        )
    return judged


async def main() -> int:
    parser = argparse.ArgumentParser(description="gold 10轮×6问评测（生产链路）")
    parser.add_argument("--json", default="gold_set_10r.json")
    parser.add_argument("--out", default="artifacts/gold_eval_10r")
    parser.add_argument("--rounds", type=int, default=10)
    args = parser.parse_args()

    spec = json.loads(Path(args.json).read_text(encoding="utf-8"))
    rounds = spec["rounds"][: args.rounds]

    await initialize_all_pools()
    print(f"开始评测：{len(rounds)} 轮 × 6 问，轮间并发", flush=True)
    started = time.perf_counter()
    raw_results = await asyncio.gather(
        *(run_round(round_spec) for round_spec in rounds), return_exceptions=True
    )
    wall_seconds = time.perf_counter() - started

    results: list[dict] = []
    for round_spec, outcome in zip(rounds, raw_results):
        if isinstance(outcome, Exception):
            traceback.print_exc()
            for index, gold in enumerate(
                [round_spec["initial"]] + round_spec["feedbacks"]
            ):
                results.append(
                    {
                        "round": round_spec["round_id"],
                        "index": index,
                        "source": round_spec["source"],
                        "theme": round_spec.get("theme"),
                        "question": gold["question"],
                        "answer": None,
                        "sql": None,
                        "elapsed_seconds": None,
                        "had_error": True,
                        "error": f"{type(outcome).__name__}: {outcome}",
                        "correct": False,
                        "reasons": ["轮级异常"],
                    }
                )
        else:
            results.extend(outcome)

    summary = summarize(results, wall_seconds)
    out_json = Path(f"{args.out}_raw.json")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(
        json.dumps(
            {"summary": summary, "results": results},
            ensure_ascii=False,
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    Path(f"{args.out}_report.md").write_text(
        render_report(summary, results), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    print(f"原始结果: {out_json}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
