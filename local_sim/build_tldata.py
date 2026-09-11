# -*- coding: utf-8 -*-
"""
本机模拟宏观 Doris 库(TLDATA), 用本地 MySQL 8 替身(Doris 走 MySQL 协议, pipeline
用 pymysql 连接, 查询行为一致)。

结构来源: text_to_sql_generator.generate_edb_field_descriptions —— 每张 ECO_DATA_*
表固定 5 列(ind_der_code/DATA_VALUE/PERIOD_DATE/UPDATE_TIME/PUBLISH_DATE),
另有元数据表 EDB_INDIC_DATA(ind_der_code/DATA_TABLE/SHOW_NAME_SHORT/UNIT/FREQ/SOURCE)。
数据来源: important_indic_emb.pkl 的 402 个真实宏观指标(ind_der_code/名称/频率/单位/
所属表), 指标值时间序列为算法生成(量级按指标类型+单位估计)。

用法: ./venv/bin/python local_sim/build_tldata.py   (幂等, 先 DROP 再建)
"""
import pickle
import re
import sys
import zlib
from datetime import date, datetime, timedelta

import numpy as np
import pymysql

HOST, PORT, USER, PASSWORD = "127.0.0.1", 3307, "root", "123QWEasd!*"

REPLACE_LIST = [
    "ECO_DATA_CHINA_REGION", "ECO_DATA_CHINA", "ECO_DATA_IND_ELECTRONIC",
    "ECO_DATA_IND_REALESTATE", "ECO_DATA_IND_TEXTILECLOTHING", "ECO_DATA_IND_STEEL",
    "ECO_DATA_IND_UTILITYINDUSTRY", "ECO_DATA_GLOBE_REST", "ECO_DATA_IND_CHEMICAL",
    "ECO_DATA_IND_MACHINERYEQUIP_18", "ECO_DATA_IND_BUILDINGMATERIALS",
    "ECO_DATA_IND_TRAFFICTRANSPORT", "ECO_DATA_IND_FINANCIALSERVICES",
    "ECO_DATA_IND_CATERINGTOURISM", "ECO_DATA_GLOBE_USA", "ECO_DATA_IND_ENERGY",
    "ECO_DATA_IND_ARICULTURAL", "ECO_DATA_GLOBE_EU", "ECO_DATA_IND_COMMERCIALTRADE",
    "ECO_DATA_IND_AUTOMOBILE", "ECO_DATA_IND_LIGHTMANUFACTUE",
    "ECO_DATA_IND_FOODBEVERAGE", "ECO_DATA_IND_CULTURE", "ECO_DATA_IND_INFOSERVICE",
    "ECO_DATA_IND_BIOLOGICALMEDI_21", "ECO_DATA_IND_NONFERROUSMETALS",
    "ECO_DATA_IND_OTHERS",
]

# 指标名 -> 基准值(按关键词), 未命中时按单位兜底
NAME_LEVELS = [
    (r"GDP.*(增速|同比)", 5.5), (r"GDP", 900000), (r"CPI", 2.3), (r"PPI", 0.5),
    (r"PMI", 50.4), (r"失业率", 5.2), (r"就业", 1300), (r"利率", 3.0),
    (r"汇率", 6.9), (r"房价", 10000), (r"社融", 45000), (r"M[012]", 2000000),
    (r"进出口|出口|进口", 3000), (r"贸易", 4000), (r"消费", 40000),
    (r"零售|销售额", 41000), (r"收入|利润", 60000), (r"投资", 50000),
    (r"工业增加值", 5.8), (r"发电量", 7000), (r"产量", 6000), (r"库存", 50000),
    (r"指数", 1100), (r"信心|预期|景气", 100), (r"人数|人口", 80000),
    (r"原油|石油", 75), (r"天然气", 3.0), (r"煤炭", 900), (r"钢铁|钢材", 10000),
    (r"水泥", 20000), (r"汽车", 250000), (r"货运|客运", 150000),
    (r"税收", 12000), (r"财政", 20000), (r"外汇储备", 32000), (r"房价", 9500),
    (r"通胀|物价", 2.0), (r"工资", 8000), (r"养老金|保险", 50000),
]
UNIT_HINTS = {  # 兜底量级(对数10)
    "%": (0.0, 1.2), "亿元": (3.0, 5.5), "亿美元": (2.5, 4.5), "万亿元": (0.5, 2.2),
    "点": (2.0, 4.0), "人": (4.0, 6.5), "辆": (4.0, 6.5), "吨": (4.0, 7.0),
    "万吨": (2.0, 4.5), "亿吨": (0.5, 2.0), "万桶": (2.5, 4.0), "千桶": (3.0, 4.5),
    "元": (3.0, 5.0), "亿美元/年": (2.5, 4.0), "%(可比价)": (0.0, 1.2),
}


def level_for(name, unit, rng):
    for pat, lv in NAME_LEVELS:
        if re.search(pat, name):
            if unit == "%" and lv > 100:
                lv = 3.0
            return lv
    lo, hi = UNIT_HINTS.get(unit, (2.0, 5.0))
    return 10 ** float(rng.uniform(lo, hi))


def dates_for(freq, start=date(2005, 1, 1), end=date(2026, 7, 31)):
    out = []
    if freq == "周":
        d = start
        while d <= end:
            if d.weekday() == 4:            # 周五
                out.append(d)
            d += timedelta(days=1)
    else:
        step = {"月": 1, "季": 3, "年": 12}.get(freq, 1)
        y, m = start.year, start.month
        while date(y, m, 1) <= end:
            # 月: 月末; 季: 季末; 不定期: 月末但随机缺测
            mm = m + (2 if freq == "季" else 0)
            last = date(y + (mm // 12), (mm % 12) + 1, 1) - timedelta(days=1)
            if last > end:
                break
            if freq == "不定期":
                if np.random.default_rng(abs(hash((y, m))) % 2**32).random() > 0.35:
                    out.append(last)
            else:
                out.append(last)
            y, m = (y + (m - 1 + step) // 12, (m - 1 + step) % 12 + 1)
    return out


def series(ind):
    """按指标生成随机游走+均值回归序列。确定性: 以 ind_der_code 做 seed。
    PMI 单独收敛(真实值域 30~70); '%' 类整体收紧并按基准裁剪。"""
    seed = zlib.crc32(ind["ind_der_code"].encode())
    rng = np.random.default_rng(seed)
    name = ind["search_ind_name"]
    base = level_for(name, ind["unit"], rng)
    is_pmi = re.search(r"PMI", name)
    if ind["unit"] == "%":
        sigma = max(abs(base) * 0.12, 0.25)
    else:
        sigma = base * 0.06
    ds = dates_for(ind["freq"])
    vals, v = [], base
    for _ in ds:
        v = v + rng.normal(0, sigma) + (base - v) * (0.25 if is_pmi else 0.12)
        vals.append(round(float(v), 2))
    if is_pmi:
        vals = [min(max(x, 30.0), 70.0) for x in vals]
    elif ind["unit"] == "%":
        vals = [min(max(x, max(-15.0, base - 6)), min(30.0, base + 6)) for x in vals]
    return ds, vals


def main():
    with open("important_indic_emb.pkl", "rb") as f:
        inds = pickle.load(f)
    conn = pymysql.connect(host=HOST, port=PORT, user=USER, password=PASSWORD,
                           charset="utf8mb4")
    cur = conn.cursor()
    cur.execute("DROP DATABASE IF EXISTS TLDATA")
    cur.execute("CREATE DATABASE TLDATA DEFAULT CHARACTER SET utf8mb4")
    cur.execute("USE TLDATA")
    cur.execute("""CREATE TABLE EDB_INDIC_DATA (
        ind_der_code VARCHAR(100) PRIMARY KEY,
        DATA_TABLE VARCHAR(100),
        SHOW_NAME_SHORT VARCHAR(255),
        UNIT VARCHAR(50),
        FREQ VARCHAR(20),
        SOURCE VARCHAR(255))""")
    for t in sorted(set(REPLACE_LIST)):
        cur.execute(f"""CREATE TABLE `{t}` (
          ind_der_code VARCHAR(100),
          DATA_VALUE DOUBLE,
          PERIOD_DATE DATE,
          UPDATE_TIME DATETIME,
          PUBLISH_DATE DATETIME,
          PRIMARY KEY (ind_der_code, PERIOD_DATE))""")

    meta_rows, total = [], 0
    for ind in inds:
        tbl = ind["data_table"]
        if tbl not in REPLACE_LIST:
            tbl = "ECO_DATA_CHINA"
        meta_rows.append((ind["ind_der_code"], tbl, ind["show_name_short"],
                          ind["unit"], ind["freq"], ind.get("source")))
        ds, vals = series(ind)
        rows = [(ind["ind_der_code"], vals[i], d,
                 datetime(2026, 8, 20, 6, 0, 0), datetime(d.year, d.month, d.day, 9, 30, 0))
                for i, d in enumerate(ds)]
        cur.executemany(
            f"INSERT INTO `{tbl}` (ind_der_code, DATA_VALUE, PERIOD_DATE, UPDATE_TIME, "
            f"PUBLISH_DATE) VALUES (%s,%s,%s,%s,%s)", rows)
        total += len(rows)
    cur.executemany("INSERT INTO EDB_INDIC_DATA (ind_der_code, DATA_TABLE, "
                    "SHOW_NAME_SHORT, UNIT, FREQ, SOURCE) VALUES (%s,%s,%s,%s,%s,%s)",
                    meta_rows)
    conn.commit()

    print(f"EDB_INDIC_DATA: {len(meta_rows)} 指标, 数据行合计 {total}")
    for t in ["ECO_DATA_CHINA", "ECO_DATA_GLOBE_USA", "ECO_DATA_GLOBE_REST",
              "ECO_DATA_GLOBE_EU", "ECO_DATA_IND_ENERGY", "ECO_DATA_IND_STEEL"]:
        cur.execute(f"SELECT COUNT(*) FROM `{t}`")
        print(f"{t}: {cur.fetchone()[0]} 行")
    cur.execute("""SELECT i.SHOW_NAME_SHORT, i.UNIT, i.FREQ, d.PERIOD_DATE, d.DATA_VALUE
        FROM EDB_INDIC_DATA i JOIN ECO_DATA_GLOBE_USA d USING (ind_der_code)
        WHERE i.SHOW_NAME_SHORT LIKE '美国%%CPI%%' ORDER BY d.PERIOD_DATE DESC LIMIT 3""")
    print("美国CPI样例:", cur.fetchall())
    cur.execute("""SELECT DATE_FORMAT(t1.PERIOD_DATE, '%Y-%m') AS 月份,
        MAX(CASE WHEN t2.SHOW_NAME_SHORT LIKE '美国%%失业率%%' THEN ROUND(t1.DATA_VALUE,2) END) AS 失业率
        FROM ECO_DATA_GLOBE_USA t1 JOIN EDB_INDIC_DATA t2 USING (ind_der_code)
        WHERE t1.PERIOD_DATE >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)
          AND t1.DATA_VALUE IS NOT NULL
        GROUP BY DATE_FORMAT(t1.PERIOD_DATE, '%Y-%m') ORDER BY 1 DESC LIMIT 3""")
    print("EDB 典型 SQL 冒烟:", cur.fetchall())
    conn.close()
    print("== TLDATA 模拟库建库完成 ==")


if __name__ == "__main__":
    sys.exit(main())
