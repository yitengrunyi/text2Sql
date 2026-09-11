#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对指定 Gold Set 全量 gold SQL 做机械核验(独立重执行,不信出题过程)。

检查: 状态200/非空/数值题 gold_value 与执行结果一致(0.5%容差+单位换算)/实体在场。
输出: evals/gold_verify_report.json; 退出码 = 失败题数>0 ? 1 : 0。
"""
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dbx import run_sql  # noqa: E402  (自带环境初始化 import 副作用)

NUM = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def numeric_cells(rows):
    out = []
    for row in rows or []:
        for v in row:
            if isinstance(v, (int, float)):
                out.append(float(v))
            elif isinstance(v, str):
                m = NUM.fullmatch(v.strip().replace(",", ""))
                if m:
                    out.append(float(v.replace(",", "")))
    return out


def value_hit(gold_value, rows):
    try:
        base = float(gold_value)
    except (TypeError, ValueError):
        return False
    cells = numeric_cells(rows)
    text = " ".join(str(v) for row in rows or [] for v in row)
    for scale in (1.0, 1e-2, 1e-4, 1e-6, 1e-8, 1e2, 1e4, 1e6, 1e8):
        target = base * scale
        tol = max(abs(target) * 0.005, 0.005) if scale == 1.0 else max(abs(target) * 0.005, 1e-12)
        if any(abs(c - target) <= tol for c in cells):
            return True
    # 容差内字符串包含(日期/代码类)
    return str(gold_value) in text


async def main(set_path: Path, report_path: Path) -> int:
    spec = json.loads(set_path.read_text(encoding="utf-8"))
    from common.middleware.db_utils import async_pools, initialize_all_pools

    await initialize_all_pools()
    report = []
    failures = 0
    sem = asyncio.Semaphore(4)

    async def check(round_spec, idx, turn):
        nonlocal failures
        rid = round_spec["round_id"]
        label = f"r{rid}.t{idx}"
        if turn.get("judge") == "nonquery" or not turn.get("gold_sql"):
            report.append({"turn": label, "status": "skip", "reason": "nonquery/无SQL"})
            return
        async with sem:
            try:
                res = await asyncio.wait_for(run_sql(round_spec["source"], turn["gold_sql"], limit=50), timeout=90)
            except asyncio.TimeoutError:
                res = {"error": "timeout"}
            except Exception as exc:
                res = {"error": f"{type(exc).__name__}: {exc}"}
        entry = {"turn": label, "question": turn["question"][:60], "source": round_spec["source"]}
        if "error" in res:
            entry.update(status="fail", reason=res["error"][:200])
            failures += 1
        elif not res.get("rows"):
            entry.update(status="fail", reason="空结果")
            failures += 1
        else:
            problems = []
            if turn.get("gold_value") and turn.get("judge") in ("numeric", "entity", "list") and not value_hit(turn["gold_value"], res["rows"]):
                problems.append(f"gold_value={turn['gold_value']} 不在执行结果中")
            ents = turn.get("gold_verify_entities") or turn.get("gold_entities") or []
            if ents and turn.get("judge") in ("entity", "list"):
                text = " ".join(str(v) for row in res["rows"] for v in row)
                hits = [e for e in ents if e in text]
                if turn.get("judge") == "entity" and not hits:
                    problems.append(f"标准实体均未命中: {ents}")
                if turn.get("judge") == "list" and len(hits) < max(1, int(len(ents) * 0.8 + 0.999)):
                    problems.append(f"名单实体命中不足: {len(hits)}/{len(ents)}")
            entry.update(status="ok" if not problems else "warn", problems=problems,
                         preview=" | ".join(str(res["rows"][0])[:120] for _ in [0]))
            if problems:
                failures += 1
        report.append(entry)
        print(entry["turn"], entry.get("status"), entry.get("problems", ""), flush=True)

    await asyncio.gather(*(
        check(r, i, t)
        for r in spec["rounds"]
        for i, t in enumerate([r["initial"]] + r["feedbacks"])
    ))
    for pool in async_pools.values():
        pool.close()
    await asyncio.gather(*(pool.wait_closed() for pool in async_pools.values()))
    report_path.write_text(
        json.dumps({"set": str(set_path), "failures": failures, "total": len(report), "report": report}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"核验完成: 失败/可疑 {failures} / {len(report)} → {report_path}")
    return 1 if failures else 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="独立重执行 Gold SQL 并核对答案")
    parser.add_argument("--set", default="evals/gold_set_180.json", dest="set_path")
    parser.add_argument("--report", default="evals/gold_verify_report.json", dest="report_path")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(Path(args.set_path), Path(args.report_path))))
