# -*- coding: utf-8 -*-
"""12 条 EDB 方言验证 SQL，直打本地模拟 Doris(MySQL) TLDATA 库。
方言约束来自 text_to_sql_generator.generate_doris_specs / generate_edb_field_descriptions:
末尾无分号、DATE_FORMAT 非 TO_CHAR、IFNULL 非 NVL、PERIOD_DATE 字符串比较、
DATE_SUB(CURDATE(), INTERVAL n ...)、GROUP BY 完整、CASE WHEN 中文别名、禁 LIKE。"""
import pymysql, json

conn = pymysql.connect(host='127.0.0.1', port=3307, user='root', password='123QWEasd!*',
                       database='TLDATA', charset='utf8mb4')
cur = conn.cursor()
cur.execute("SELECT @@sql_mode, @@version")
m, v = cur.fetchone()
print("sql_mode:", m, "| version:", v)

QUERIES = [
    # ---- Q1 指标目录 EDB_INDIC_DATA 查 SHOW_NAME_SHORT/UNIT/FREQ (ind_der_code IN 精确匹配, 禁LIKE) ----
    ("Q1 指标目录",
     "SELECT SHOW_NAME_SHORT AS `指标名称`, UNIT AS `单位`, FREQ AS `频率` "
     "FROM EDB_INDIC_DATA "
     "WHERE ind_der_code IN ('1012dskwe36i8uq1h1o2khx9j3am','201mcbxe1p6uoemumvdlijlle6u','20146gv9dv5t5ev7k2pzfnvbslt0')"),

    # ---- Q2 两表 JOIN + MAX(CASE WHEN) 透视, 近10年中国GDP类指标 ----
    ("Q2 JOIN透视-GDP近10年",
     "SELECT DATE_FORMAT(t1.PERIOD_DATE, '%Y-%m-%d') AS `日期`, "
     "MAX(CASE WHEN t2.ind_der_code = '1012dskwe36i8uq1h1o2khx9j3am' THEN ROUND(t1.DATA_VALUE, 2) END) AS `中国GDP不变价同比(%)`, "
     "MAX(CASE WHEN t2.ind_der_code = '1012dhd93dzojvrn0oshoec7uwen' THEN ROUND(t1.DATA_VALUE, 2) END) AS `中国GDP环比季调(%)` "
     "FROM ECO_DATA_CHINA t1 "
     "JOIN EDB_INDIC_DATA t2 ON t2.DATA_TABLE = 'ECO_DATA_CHINA' AND t1.ind_der_code = t2.ind_der_code "
     "WHERE t2.ind_der_code IN ('1012dskwe36i8uq1h1o2khx9j3am','1012dhd93dzojvrn0oshoec7uwen') "
     "AND t1.PERIOD_DATE >= DATE_SUB(CURDATE(), INTERVAL 10 YEAR) "
     "AND t1.DATA_VALUE IS NOT NULL "
     "GROUP BY DATE_FORMAT(t1.PERIOD_DATE, '%Y-%m-%d') "
     "ORDER BY DATE_FORMAT(t1.PERIOD_DATE, '%Y-%m-%d') DESC"),

    # ---- Q3 PERIOD_DATE >= '2015-01-01' 字符串比较 + 按年 DATE_FORMAT 分组 + 倒序 ----
    ("Q3 年度分组-2015以来",
     "SELECT DATE_FORMAT(t1.PERIOD_DATE, '%Y') AS `年份`, "
     "ROUND(AVG(t1.DATA_VALUE), 2) AS `GDP不变价同比均值(%)` "
     "FROM ECO_DATA_CHINA t1 "
     "WHERE t1.ind_der_code = '1012dskwe36i8uq1h1o2khx9j3am' "
     "AND t1.PERIOD_DATE >= '2015-01-01' "
     "AND t1.DATA_VALUE IS NOT NULL "
     "GROUP BY DATE_FORMAT(t1.PERIOD_DATE, '%Y') "
     "ORDER BY `年份` DESC"),

    # ---- Q4 DATE_SUB(CURDATE(), INTERVAL 6 MONTH) 近期数据 ----
    ("Q4 近6个月美国CPI同比",
     "SELECT DATE_FORMAT(t1.PERIOD_DATE, '%Y-%m') AS `月份`, "
     "ROUND(t1.DATA_VALUE, 2) AS `美国CPI同比(%)` "
     "FROM ECO_DATA_GLOBE_USA t1 "
     "WHERE t1.ind_der_code = '201mcbxe1p6uoemumvdlijlle6u' "
     "AND t1.PERIOD_DATE >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH) "
     "AND t1.DATA_VALUE IS NOT NULL "
     "ORDER BY t1.PERIOD_DATE DESC"),

    # ---- Q5 美国库 失业率/CPI 透视 ----
    ("Q5 美国失业率CPI透视",
     "SELECT DATE_FORMAT(t1.PERIOD_DATE, '%Y-%m') AS `月份`, "
     "MAX(CASE WHEN t2.ind_der_code = '201b29bogrrwk2ki8wvtb5xyvy46' THEN ROUND(t1.DATA_VALUE, 2) END) AS `美国U3失业率(%)`, "
     "MAX(CASE WHEN t2.ind_der_code = '201mcbxe1p6uoemumvdlijlle6u' THEN ROUND(t1.DATA_VALUE, 2) END) AS `美国CPI同比(%)`, "
     "MAX(CASE WHEN t2.ind_der_code = '2018z4wosz6czk0db6zcj6ickykg' THEN ROUND(t1.DATA_VALUE, 2) END) AS `美国核心CPI同比(%)` "
     "FROM ECO_DATA_GLOBE_USA t1 "
     "JOIN EDB_INDIC_DATA t2 ON t2.DATA_TABLE = 'ECO_DATA_GLOBE_USA' AND t1.ind_der_code = t2.ind_der_code "
     "WHERE t2.ind_der_code IN ('201b29bogrrwk2ki8wvtb5xyvy46','201mcbxe1p6uoemumvdlijlle6u','2018z4wosz6czk0db6zcj6ickykg') "
     "AND t1.PERIOD_DATE >= DATE_SUB(CURDATE(), INTERVAL 1 YEAR) "
     "AND t1.DATA_VALUE IS NOT NULL "
     "GROUP BY DATE_FORMAT(t1.PERIOD_DATE, '%Y-%m') "
     "ORDER BY DATE_FORMAT(t1.PERIOD_DATE, '%Y-%m') DESC "
     "LIMIT 6"),

    # ---- Q6 欧盟库 GLOBE_EU ----
    ("Q6 欧元区PMI",
     "SELECT DATE_FORMAT(t1.PERIOD_DATE, '%Y-%m') AS `月份`, "
     "ROUND(t1.DATA_VALUE, 2) AS `欧元区综合PMI(%)` "
     "FROM ECO_DATA_GLOBE_EU t1 "
     "WHERE t1.ind_der_code = '2012l22m4iiprtg38tpaqeehiktr' "
     "AND t1.PERIOD_DATE >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH) "
     "AND t1.DATA_VALUE IS NOT NULL "
     "ORDER BY t1.PERIOD_DATE DESC"),

    # ---- Q7 日本库 GLOBE_REST ----
    ("Q7 日本GDP环比折年率",
     "SELECT DATE_FORMAT(t1.PERIOD_DATE, '%Y-%m-%d') AS `日期`, "
     "ROUND(t1.DATA_VALUE, 2) AS `日本GDP环比折年率(%)` "
     "FROM ECO_DATA_GLOBE_REST t1 "
     "WHERE t1.ind_der_code = '2011fulppl44714v4wp36fcqa2db' "
     "AND t1.PERIOD_DATE >= '2024-01-01' "
     "AND t1.DATA_VALUE IS NOT NULL "
     "ORDER BY t1.PERIOD_DATE DESC"),

    # ---- Q8 空表 ECO_DATA_IND_AUTOMOBILE: 期望 0 行且不报错 ----
    ("Q8 空表查询",
     "SELECT DATE_FORMAT(t1.PERIOD_DATE, '%Y-%m-%d') AS `日期`, "
     "ROUND(t1.DATA_VALUE, 2) AS `数值` "
     "FROM ECO_DATA_IND_AUTOMOBILE t1 "
     "WHERE t1.PERIOD_DATE >= '2024-01-01' "
     "AND t1.DATA_VALUE IS NOT NULL "
     "ORDER BY t1.PERIOD_DATE DESC"),

    # ---- Q9 周频连续性: 美国初请失业金人数(周) 按年计数 ----
    ("Q9 周频连续性",
     "SELECT DATE_FORMAT(t1.PERIOD_DATE, '%Y') AS `年份`, "
     "COUNT(t1.DATA_VALUE) AS `周数`, "
     "ROUND(AVG(t1.DATA_VALUE), 1) AS `均值(千人)` "
     "FROM ECO_DATA_GLOBE_USA t1 "
     "WHERE t1.ind_der_code = '2016cl8x9ei68rp7ytbd16b3l3em' "
     "AND t1.PERIOD_DATE >= '2023-01-01' "
     "AND t1.DATA_VALUE IS NOT NULL "
     "GROUP BY DATE_FORMAT(t1.PERIOD_DATE, '%Y') "
     "ORDER BY `年份` DESC"),

    # ---- Q10 季频连续性: 中国GDP不变价同比 每年期数 ----
    ("Q10 季频连续性",
     "SELECT DATE_FORMAT(t1.PERIOD_DATE, '%Y') AS `年份`, "
     "COUNT(t1.DATA_VALUE) AS `季度数` "
     "FROM ECO_DATA_CHINA t1 "
     "WHERE t1.ind_der_code = '1012dskwe36i8uq1h1o2khx9j3am' "
     "AND t1.PERIOD_DATE >= '2022-01-01' "
     "AND t1.DATA_VALUE IS NOT NULL "
     "GROUP BY DATE_FORMAT(t1.PERIOD_DATE, '%Y') "
     "ORDER BY `年份` DESC"),

    # ---- Q11 IS NOT NULL + ROUND + IFNULL(非NVL) + 单位换算展示 ----
    ("Q11 IFNULL+ROUND",
     "SELECT DATE_FORMAT(t1.PERIOD_DATE, '%Y-%m-%d') AS `日期`, "
     "IFNULL(ROUND(t1.DATA_VALUE, 2), 0) AS `欧元区消费者信心指数`, "
     "IFNULL(ROUND(t1.DATA_VALUE * 1.0, 2), 0) AS ` Sentix信心指数` "
     "FROM ECO_DATA_GLOBE_EU t1 "
     "WHERE t1.ind_der_code IN ('2013y7ux2pub47nyjxdia8dvycfv','2012yryn7et0dx2t4oz03k2cs4cn') "
     "AND t1.PERIOD_DATE >= '2026-01-01' "
     "AND t1.DATA_VALUE IS NOT NULL "
     "ORDER BY t1.PERIOD_DATE DESC"),

    # ---- Q12 无可用数据兜底 (generate_edb_field_descriptions 规定写法) ----
    ("Q12 无数据兜底",
     "SELECT '无可用数据' AS `提示`"),
]

results = []
for name, sql in QUERIES:
    try:
        cur.execute(sql)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        results.append({
            "name": name, "sql": sql, "ok": True, "rowcount": len(rows),
            "columns": cols, "first3": [tuple(str(v) for v in r) for r in rows[:3]],
        })
    except Exception as e:
        conn.ping(reconnect=True)
        results.append({"name": name, "sql": sql, "ok": False, "error": f"{type(e).__name__}: {e}"})

for r in results:
    print("=" * 100)
    print(r["name"], "| OK" if r["ok"] else "| FAIL")
    print("SQL:", r["sql"])
    if r["ok"]:
        print("rows:", r["rowcount"], "| columns:", r["columns"])
        for row in r["first3"]:
            print("  ", row)
    else:
        print("ERROR:", r["error"])

with open('/Users/mdb/project/text2sql_renew/artifacts/edb_sim_validation_results.json', 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print("\nsaved to artifacts/edb_sim_validation_results.json")
conn.close()
