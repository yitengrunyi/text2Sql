#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""装配 gold_set_180.json：既有 10 轮 + 草稿 20 轮。

- 既有轮次: gold_set_10r.json(1-4,8-10) + artifacts/gold_set_fund_3r.json(5-7,修正版)
- 草稿轮次: evals/drafts/round_*.json
- gold_tables 从 gold_sql 的 FROM/JOIN 提取
- route_gold 机械口径(对齐生产 3 意图 prompt 定义):
    NON_QUERY  非查询闲聊
    SQL_GENERATION  当前二级域表上下文可解(指代/条件/时间漂移/同域实体替换)
    NEW_QUERY  需要跨二级域的新表结构
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

import pymysql

ROOT = Path(__file__).resolve().parent.parent
DOMAIN_OF_TABLE_SQL = """
SELECT DISTINCT m.TABLE_ENAME, m.DOMAIN_CNAME
FROM MDB_DOMN_TB_JULING m
JOIN MDB_DOMAIN_JULING d ON m.DOMAIN_HCODE = d.DOMAIN_HCODE
WHERE m.HISVALID = 1 AND d.HISVALID = 1
"""

# 既有 60 问手工标签: (round, idx) -> (followup_type, difficulty, time_sensitivity)
HAND = {
    # R1 个股年报财务·宁德时代
    (1, 0): (None, "单表", "absolute"), (1, 1): ("指代继承", "单表", "absolute"),
    (1, 2): ("指代继承", "单表", "absolute"), (1, 3): ("指代继承", "单表", "absolute"),
    (1, 4): ("条件追加", "单表", "absolute"), (1, 5): ("条件修改", "单表", "absolute"),
    # R2 个股年报·中国平安
    (2, 0): (None, "单表", "absolute"), (2, 1): ("普通追问", "单表", "absolute"),
    (2, 2): ("条件修改", "单表", "absolute"), (2, 3): ("条件修改", "单表", "absolute"),
    (2, 4): ("条件追加", "聚合", "absolute"), (2, 5): ("普通追问", "单表", "absolute"),
    # R3 个股行情
    (3, 0): (None, "时间窗口", "absolute"), (3, 1): ("指代继承", "单表", "absolute"),
    (3, 2): ("条件追加", "单表", "absolute"), (3, 3): ("条件修改", "聚合", "absolute"),
    (3, 4): ("条件修改", "单表", "absolute"), (3, 5): ("条件修改", "聚合", "absolute"),
    # R4 指数
    (4, 0): (None, "单表", "absolute"), (4, 1): ("指代继承", "单表", "absolute"),
    (4, 2): ("条件修改", "单表", "absolute"), (4, 3): ("条件修改", "单表", "absolute"),
    (4, 4): ("话题切换", "单表", "absolute"), (4, 5): ("条件修改", "单表", "absolute"),
    # R5 基金净值
    (5, 0): (None, "单表", "absolute"), (5, 1): ("指代继承", "单表", "absolute"),
    (5, 2): ("条件修改", "单表", "absolute"), (5, 3): ("普通追问", "子查询", "absolute"),
    (5, 4): ("条件追加", "子查询", "absolute"), (5, 5): ("话题切换", "单表", "relative"),
    # R6 基金持仓/经理
    (6, 0): (None, "聚合", "absolute"), (6, 1): ("话题切换", "单表", "relative"),
    (6, 2): ("话题切换", "单表", "relative"), (6, 3): ("条件追加", "聚合", "absolute"),
    (6, 4): ("话题切换", "单表", "relative"), (6, 5): ("条件追加", "聚合", "relative"),
    # R7 ETF
    (7, 0): (None, "单表", "absolute"), (7, 1): ("指代继承", "单表", "absolute"),
    (7, 2): ("指代继承", "多表join", "absolute"), (7, 3): ("条件修改", "子查询", "relative"),
    (7, 4): ("话题切换", "聚合", "absolute"), (7, 5): ("指代继承", "聚合", "absolute"),
    # R8 美股行情
    (8, 0): (None, "单表", "relative"), (8, 1): ("条件修改", "单表", "relative"),
    (8, 2): ("条件修改", "单表", "relative"), (8, 3): ("条件追加", "聚合", "relative"),
    (8, 4): ("条件修改", "单表", "relative"), (8, 5): ("条件修改", "单表", "relative"),
    # R9 美股财年财务
    (9, 0): (None, "单表", "absolute"), (9, 1): ("普通追问", "单表", "absolute"),
    (9, 2): ("条件修改", "单表", "absolute"), (9, 3): ("条件修改", "单表", "absolute"),
    (9, 4): ("条件追加", "多表join", "absolute"), (9, 5): ("话题切换", "聚合", "absolute"),
    # R10 美股全库
    (10, 0): (None, "聚合", "relative"), (10, 1): ("指代继承", "单表", "relative"),
    (10, 2): ("条件追加", "多表join", "relative"), (10, 3): ("条件修改", "单表", "relative"),
    (10, 4): ("条件追加", "聚合", "relative"), (10, 5): ("条件追加", "聚合", "relative"),
}

ROUND_DOMAIN = {1: "个股", 2: "个股", 3: "个股", 4: "指数", 5: "基金", 6: "基金", 7: "基金", 8: "美股", 9: "美股", 10: "美股"}

AUX_TABLES = {"GET_A_INDUSTRY", "GET_A_SEC_CODE", "HK_COMBINFO", "HK_STKCODE", "HK_INDCHCOM", "PUB_INDU_REF", "GET_INDX_GEN_INFO"}


def apply_overrides(overrides: dict, rid: int, idx: int, turn: dict) -> None:
    patch = overrides.get((rid, idx))
    if not patch:
        return
    for key, value in patch.items():
        if key == "labels":
            turn["labels"].update(value)
        else:
            turn[key] = value

FROM_JOIN = re.compile(r"(?is)\b(?:from|join)\s+`?([a-z_][a-z0-9_]*)`?")


def tables_from_sql(sql: str) -> list:
    if not sql:
        return []
    seen = []
    for name in FROM_JOIN.findall(sql):
        name = name.upper()
        if name not in ("SELECT",) and name not in seen:
            seen.append(name)
    return seen


def load_domain_map() -> dict:
    conn = pymysql.connect(host="127.0.0.1", port=3307, user="root", password="123QWEasd!*",
                           database="schema_metadata", charset="utf8mb4")
    try:
        with conn.cursor() as cur:
            cur.execute(DOMAIN_OF_TABLE_SQL)
            mapping: dict[str, set] = {}
            for table, domain in cur.fetchall():
                mapping.setdefault(table.upper(), set()).add(domain)
            return mapping
    finally:
        conn.close()


def domains_of(tables, domain_map):
    result = set()
    for t in tables or []:
        if t in AUX_TABLES:
            continue
        result |= domain_map.get(t, set())
    return result


def compute_routes(turns, domain_map, log):
    """按二级域表上下文机械计算追问 route_gold。

    未知域的表(如注入表 VIEW_US_EOD_EXPR 不在域映射)保守判 SQL_GENERATION。
    """
    initialized = False
    prev_domains = set()
    for turn in turns:
        labels = turn.setdefault("labels", {})
        if turn.get("judge") == "nonquery":
            labels["route_gold"] = "NON_QUERY"
            continue  # 闲聊轮上下文保持
        d_now = domains_of(turn.get("gold_tables"), domain_map)
        if not initialized:
            labels["route_gold"] = None  # initial
            prev_domains = d_now
            initialized = True
        else:
            labels["route_gold"] = (
                "NEW_QUERY" if (d_now and prev_domains and d_now.isdisjoint(prev_domains)) else "SQL_GENERATION"
            )
            if d_now:
                prev_domains = d_now
    return turns


def normalize_turn(turn, round_domain):
    t = dict(turn)
    t.setdefault("gold_entities", [])
    t.setdefault("gold_date", None)
    t["gold_tables"] = [x.upper() for x in (t.get("gold_tables") or tables_from_sql(t.get("gold_sql")))]
    labels = t.setdefault("labels", {})
    labels.setdefault("followup_type", None)
    labels.setdefault("difficulty", "单表")
    labels.setdefault("route_gold", None)
    labels.setdefault("time_sensitivity", "absolute")
    return t


def build():
    domain_map = load_domain_map()
    rounds = []

    # 定向修正(对抗校验 verdict warn + 机械核验发现):
    OVERRIDES = {
        (20, 2): {"labels": {"time_sensitivity": "absolute"}},
        (20, 4): {"gold_entities": ["中证医疗"]},
        (24, 1): {"labels": {"time_sensitivity": "relative"}},
        (26, 0): {"gold_entities": ["华安黄金易"]},
        # r7.t2 测试库隔夜刷新了 2026-09-02 行的 FUND_SIZE → 用当前实测值
        (7, 2): {"gold_value": "19579514570", "gold_display": "195.80亿元(2026-09-02)"},
        # r9.t4 原 gold SQL 只返回两年营收原值,未计算增速,EX 判分会失真 → 改为计算增速
        (9, 4): {
            "gold_sql": (
                "SELECT ROUND(100*(MAX(CASE WHEN c.F056N=2025 THEN c.F048N END)"
                "/MAX(CASE WHEN c.F056N=2024 THEN c.F048N END)-1),2) AS growth_pct "
                "FROM COM3103 c JOIN AMERICAN_STOCK_MAIN m ON m.FIU_ID=c.FIU_ID "
                "WHERE m.SYMBOL='AAPL' AND c.F003V='FY' AND c.F056N IN (2024,2025)"
            )
        },
    }

    base10 = json.loads((ROOT / "gold_set_10r.json").read_text(encoding="utf-8"))["rounds"]
    fund3 = json.loads((ROOT / "artifacts/gold_set_fund_3r.json").read_text(encoding="utf-8"))["rounds"]
    by_id = {r["round_id"]: r for r in base10}
    by_id.update({r["round_id"]: r for r in fund3})

    for rid in sorted(by_id):
        r = by_id[rid]
        turns = [normalize_turn(t, ROUND_DOMAIN[rid]) for t in [r["initial"]] + r["feedbacks"]]
        for idx, turn in enumerate(turns):
            followup, difficulty, sens = HAND[(rid, idx)]
            turn["labels"]["followup_type"] = followup
            turn["labels"]["difficulty"] = difficulty
            turn["labels"]["time_sensitivity"] = sens
            apply_overrides(OVERRIDES, rid, idx, turn)
        compute_routes(turns, domain_map, print)
        rounds.append({
            "round_id": rid, "source": r["source"], "domain": ROUND_DOMAIN[rid],
            "theme": r.get("theme"), "initial": turns[0], "feedbacks": turns[1:],
        })

    drafts = sorted((ROOT / "evals/drafts").glob("round_*.json"))
    route_overrides = []
    for path in drafts:
        r = json.loads(path.read_text(encoding="utf-8"))
        rid = r["round_id"]
        if any(x["round_id"] == rid for x in rounds):
            print(f"[WARN] 草稿轮次 {rid} 与已有轮次冲突，跳过")
            continue
        turns = [normalize_turn(t, r.get("domain")) for t in [r["initial"]] + r["feedbacks"]]
        for idx, turn in enumerate(turns):
            if turn.get("judge") == "nonquery":
                turn["labels"]["difficulty"] = None
                turn["labels"]["followup_type"] = "非查询"
            apply_overrides(OVERRIDES, rid, idx, turn)
        compute_routes(turns, domain_map, print)
        for turn in turns:
            if turn["judge"] != "nonquery" and turn["labels"]["followup_type"] == "话题切换" and turn["labels"]["route_gold"] != "NEW_QUERY":
                route_overrides.append((rid, turn["question"][:30], turn["labels"]["route_gold"]))
        rounds.append({
            "round_id": rid, "source": r["source"], "domain": r.get("domain"), "theme": r.get("theme"),
            "initial": turns[0], "feedbacks": turns[1:], "_draft": path.name,
        })

    rounds.sort(key=lambda x: x["round_id"])
    if [r["round_id"] for r in rounds] != list(range(1, len(rounds) + 1)):
        print("[WARN] 轮次编号不连续:", [r["round_id"] for r in rounds])

    # 统计
    all_turns = [(r, t) for r in rounds for t in [r["initial"]] + r["feedbacks"]]
    stats = {
        "rounds": len(rounds),
        "turns": len(all_turns),
        "by_source": Counter(r["source"] for r, _ in all_turns),
        "by_domain": Counter(r["domain"] for r, _ in all_turns),
        "by_difficulty": Counter(t["labels"]["difficulty"] for _, t in all_turns),
        "by_followup": Counter(t["labels"]["followup_type"] or "initial" for _, t in all_turns),
        "by_route": Counter(t["labels"]["route_gold"] or "initial" for _, t in all_turns),
        "by_judge": Counter(t.get("judge", "numeric") for _, t in all_turns),
        "time_relative": sum(1 for _, t in all_turns if t["labels"]["time_sensitivity"] == "relative"),
    }
    out = {
        "meta": {
            "name": "gold_set_180",
            "created": "2026-09-03",
            "structure": "30轮×6问(1初始+5追问)；不含宏观/EDB主题、不依赖DashVector",
            "route_rule": "route_gold 按二级域表上下文机械计算: 同域可解=SQL_GENERATION, 跨域新表=NEW_QUERY, 闲聊=NON_QUERY(对齐 common/prompt/prompt_template.py 三分类定义)",
            "sources": {
                "MYSQL-2": "生产 juling（真实数据，只读）",
                "MYSQL-1": "测试 Nacos FUND_INFO（测试数据）",
                "MYSQL-4": "本地 fiu（43只美股样本，合成数值，gold以库内值为准）",
            },
            "judge_types": {
                "numeric": "数值命中(相对容差0.5%,亿/百万/万换算)；gold_date/gold_entities 给出则必须命中",
                "entity": "实体命中；数值/日期软校验",
                "list": "名单重叠率≥80%",
                "nonquery": "仅判路由",
            },
        },
        "rounds": rounds,
    }
    dest = ROOT / "evals/gold_set_180.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=1, default=dict))
    if route_overrides:
        print("[INFO] 话题切换轮被域规则改判为 SQL_GENERATION(同域表可解):", route_overrides)
    print(f"写出: {dest}")


if __name__ == "__main__":
    build()
