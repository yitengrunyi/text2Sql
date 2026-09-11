#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线重判：对已完成 run 的全部轮次重执行 pred/gold SQL 并按当前判分器重算 EX。

用途：判分口径升级后统一重判（运行记录里只存了结果预览，需重执行拿全量结果）。
"""
import asyncio
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dbx import run_sql  # noqa: E402

from run_eval import render_result, exec_sql_real, answer_judge  # noqa: E402


async def rescore_turn(turn: dict, spec_rounds: dict) -> dict:
    rid = turn["round_id"]
    round_spec = spec_rounds[rid]
    golds = [round_spec["initial"]] + round_spec["feedbacks"]
    gold = golds[turn["index"]]
    if turn.get("judge_type") == "nonquery":
        return {"changed": False}
    source = round_spec["source"]

    g = await exec_sql_real(gold.get("gold_sql"), source)
    if g is None or g[0] != 200:
        return {"changed": False, "note": "gold_failed"}
    _, gold_render, gold_rows = render_result(g)

    out = {}
    executions = {}
    for tag, sql in (("first", turn.get("first_sql")), ("final", turn.get("final_sql"))):
        if not sql:
            out[f"ex_{tag}"] = False
            continue
        if sql not in executions:
            r = await exec_sql_real(sql, source)
            executions[sql] = render_result(r) if r is not None else (None, "", 0)
        status, text, rows = executions[sql]
        ok, reasons = answer_judge(
            gold,
            text,
            had_error=(status != 200),
            row_count=rows,
            gold_row_count=gold_rows,
        )
        out[f"ex_{tag}"] = ok
        if tag == "final":
            out["ex_reasons"] = reasons
    # 答案级重判
    ok, reasons = answer_judge(gold, turn.get("answer") or "", had_error=not (turn.get("answer") or "").strip())
    out["answer_ok"] = ok
    out["answer_reasons"] = reasons
    changed = any(turn.get(k) != v for k, v in out.items())
    turn.update(out)
    return {"changed": changed}


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tags", nargs="*", default=["full"])
    parser.add_argument(
        "--turns",
        default=None,
        help="逗号分隔的精确题号；可写 rag/r20_t0 或 r20_t0（后者应用于所有指定 run）",
    )
    args = parser.parse_args()
    tags = args.tags or ["full"]
    selected = set(filter(None, (args.turns or "").split(",")))
    spec = json.loads(Path("evals/gold_set_180.json").read_text(encoding="utf-8"))
    spec_rounds = {r["round_id"]: r for r in spec["rounds"]}
    from common.middleware.db_utils import initialize_all_pools

    await initialize_all_pools()
    sem = asyncio.Semaphore(6)

    async def guard(coro):
        async with sem:
            return await coro

    for tag in tags:
        turns_dir = Path(f"evals/runs/{tag}/turns")
        if not turns_dir.exists():
            print(f"[WARN] {tag} 不存在")
            continue
        paths = []
        for path in sorted(turns_dir.glob("r*_t*.json")):
            if selected and path.stem not in selected and f"{tag}/{path.stem}" not in selected:
                continue
            paths.append(path)

        async def process(path):
            turn = json.loads(path.read_text(encoding="utf-8"))
            try:
                res = await guard(rescore_turn(turn, spec_rounds))
            except Exception as exc:
                print(f"[ERR] {path.name}: {type(exc).__name__}: {exc}")
                return False
            if res.get("changed"):
                path.write_text(json.dumps(turn, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
                return True
            return False

        results = await asyncio.gather(*(process(path) for path in paths))
        print(f"[{tag}] 重判完成, 处理 {len(paths)} 轮, 变更 {sum(results)} 轮")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
