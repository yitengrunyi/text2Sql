#!/usr/bin/env python3
"""Run a repeatable MYSQL-2 end-to-end benchmark through the local WebSocket."""

import argparse
import asyncio
import json
import statistics
import time
import uuid
from datetime import datetime
from pathlib import Path

import websockets


QUESTIONS = [
    "贵州茅台2025年归属于母公司股东的净利润是多少？",
    "贵州茅台2025年基本每股收益是多少？",
    "五粮液2025年归属于母公司股东的净利润是多少？",
    "比亚迪2025年归属于母公司股东的净利润是多少？",
    "贵州茅台最新一个交易日的收盘价是多少？请同时给出交易日期。",
    "五粮液最新一个交易日的收盘价是多少？请同时给出交易日期。",
    "比亚迪最新一个交易日的收盘价是多少？请同时给出交易日期。",
    "沪深300指数最新一个交易日的收盘点位是多少？请同时给出交易日期。",
    "上证指数最新一个交易日的收盘点位是多少？请同时给出交易日期。",
    "2026年8月贵州茅台收盘价最高的是哪一天？最高收盘价是多少？",
]


async def run_question(uri: str, question: str, number: int, timeout: float) -> dict:
    request = {
        "question": question,
        "sessionId": f"mysql2-benchmark-{number}-{uuid.uuid4().hex[:8]}",
        "userId": "mysql2-benchmark",
        "userName": "MYSQL-2基准测试",
    }
    started = time.perf_counter()
    events = []
    error = None

    try:
        async with websockets.connect(uri, open_timeout=10) as websocket:
            await websocket.send(json.dumps(request, ensure_ascii=False))
            while True:
                raw = await asyncio.wait_for(websocket.recv(), timeout=timeout)
                event = json.loads(raw)
                event["elapsed_seconds"] = round(time.perf_counter() - started, 3)
                events.append(event)
                if event.get("data", {}).get("isEnd") is True:
                    break
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    elapsed = round(time.perf_counter() - started, 3)
    by_type = {}
    for event in events:
        event_type = str(event.get("data", {}).get("type"))
        by_type.setdefault(event_type, []).append(event.get("data", {}).get("answer"))

    return {
        "number": number,
        "question": question,
        "elapsed_seconds": elapsed,
        "error": error,
        "event_count": len(events),
        "by_type": by_type,
        "events": events,
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--uri", default="ws://127.0.0.1:5903/ws")
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/mysql2_benchmark_raw.json"),
    )
    args = parser.parse_args()

    results = []
    for number, question in enumerate(QUESTIONS, start=1):
        print(f"[{number}/{len(QUESTIONS)}] {question}", flush=True)
        result = await run_question(args.uri, question, number, args.timeout)
        results.append(result)
        print(
            f"  {result['elapsed_seconds']:.3f}s, "
            f"events={result['event_count']}, error={result['error']}",
            flush=True,
        )

    completed_times = [
        result["elapsed_seconds"] for result in results if result["error"] is None
    ]
    report = {
        "run_at": datetime.now().astimezone().isoformat(),
        "uri": args.uri,
        "question_count": len(QUESTIONS),
        "completed_count": len(completed_times),
        "timing": {
            "average_seconds": round(statistics.mean(completed_times), 3)
            if completed_times
            else None,
            "median_seconds": round(statistics.median(completed_times), 3)
            if completed_times
            else None,
            "min_seconds": min(completed_times) if completed_times else None,
            "max_seconds": max(completed_times) if completed_times else None,
        },
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report["timing"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
