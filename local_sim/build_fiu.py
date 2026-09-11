# -*- coding: utf-8 -*-
"""
本机模拟美股库(fiu): 真实表结构(schema_metadata 元数据) + 贴近真实的 mock 数据。

表结构来源: local_sim/fiu_columns_from_metadata.txt (从 192.168.15.57 schema_metadata
的 MDB_TABLE/MDB_COLUMN_JULING 导出, SRC='FIU' 共 20 张表)。
数据: 43 只真实美股(代码/名称/行业/量级真实), 行情与财务数值为算法生成。

用法: ./venv/bin/python local_sim/build_fiu.py   (幂等, 先 DROP 再建)
"""
import re
import sys
from datetime import date, timedelta

import numpy as np
import pymysql

HOST, PORT, USER, PASSWORD = "127.0.0.1", 3307, "root", "123QWEasd!*"

# ---------------------------------------------------------------- 字段明细解析
EXPECTED = {  # HCODE: (表名, 列数, 建成什么)
    "50001": ("AMERICAN_STOCK_MAIN", 10, "table"),
    "50002": ("STK2401", 12, "table"),
    "50003": ("COM3101", 35, "table"),
    "50004": ("COM3102", 70, "table"),
    "50005": ("COM3103", 57, "table"),
    "50006": ("COM3104", 45, "table"),
    "50007": ("COM3105", 14, "table"),
    "50008": ("COM3106", 12, "table"),
    "50009": ("VIEW_COM3105", 14, "table"),      # 真实视图逻辑不可还原, 建成同列结构的表
    "50010": ("VIEW_COM3106", 13, "table"),
    "50011": ("VIEW_COM3102_Q", 70, "view_q:COM3102"),
    "50012": ("VIEW_COM3103_Q", 57, "view_q:COM3103"),
    "50013": ("VIEW_COM3104_Q", 45, "view_q:COM3104"),
    "50014": ("VIEW_COM3102_CUM", 70, "view_cum:COM3102"),
    "50015": ("VIEW_COM3103_CUM", 57, "view_cum:COM3103"),
    "50016": ("VIEW_COM3104_CUM", 45, "view_cum:COM3104"),
    "50032": ("VIEW_ADS_STOCK_US_EOD_DI", 11, "table"),   # 已停用, 建空表
    "50033": ("VIEW_STOCK_US_TURNOUT_SHARES", 7, "table"),
    "50034": ("VIEW_US_EOD_EXPR", 22, "table"),
    "50035": ("VIEW_US_EXPR_IDX", 21, "table"),
}
V50035_COLS = ["FIU_ID", "SYMBOL_NASDAQ", "ISIN", "F002V", "F003V", "F001V", "F004V",
               "F006V", "TRADE_DATE", "SYMBOL", "COMB_SYMBOL", "CLOSE_PRICE",
               "CHG_PCT_DAY", "CHG_PCT_WEEK", "CHG_PCT_MONTH", "CHG_PCT_QUARTER",
               "CHG_PCT_YEAR", "CHG_PCT_WTD", "CHG_PCT_MTD", "CHG_PCT_YTD", "NAME"]


def parse_columns(path):
    sections, cur = {}, None
    for line in open(path, encoding="utf-8"):
        line = line.rstrip("\n")
        if line.startswith("###"):
            cur = line[3:].split("|")[0].strip().split()[0]   # 只取 HCODE
            sections[cur] = []
        elif line.strip() and cur:
            parts = line.split("|")
            if len(parts) >= 3 and parts[0].strip():
                sections[cur].append((parts[0].strip(), parts[2].strip(), parts[1].strip()))
    out = {}
    for hcode, (ename, ncols, _kind) in EXPECTED.items():
        cols = sections.get(hcode, [])
        if hcode == "50035":   # 该段混有 SYM1502 脏数据, 只保留 21 个已知列
            cols = [c for c in cols if c[0] in V50035_COLS]
            cols.sort(key=lambda c: V50035_COLS.index(c[0]))
        if len(cols) != ncols:
            print(f"[warn] {hcode} {ename}: 期望 {ncols} 列, 解析到 {len(cols)} 列")
        out[hcode] = (ename, cols)
    return out


def norm_type(col, sqltype):
    """F###D 一律 DATE (修元数据 bug), F###N 默认 FLOAT, 其余按标注。"""
    if re.fullmatch(r"F\d{3}D", col):
        return "DATE"
    t = sqltype.upper()
    if t in ("VARCHAR", "CHARACTER", ""):
        return "FLOAT" if (t == "" and re.fullmatch(r"F\d{3}N", col)) else "VARCHAR(255)"
    return t


def build_ddl(parsed):
    stmts = ["CREATE DATABASE IF NOT EXISTS fiu DEFAULT CHARACTER SET utf8mb4", "USE fiu"]
    views = []
    for hcode, (ename, cols) in parsed.items():
        kind = EXPECTED[hcode][2]
        if kind.startswith("view_"):
            base = kind.split(":")[1]
            f3v = "('Q1','Q2','Q3','Q4')" if kind.startswith("view_q") else "('T1','FY')"
            views.append(f"CREATE OR REPLACE VIEW {ename} AS "
                         f"SELECT * FROM {base} WHERE F003V IN {f3v}")
            continue
        defs = [f"  `{c}` {norm_type(c, t)} COMMENT '{cn[:200]}'" for c, t, cn in cols]
        if ename == "AMERICAN_STOCK_MAIN":
            defs.append("  PRIMARY KEY (`FIU_ID`), KEY `idx_comb_symbol` (`COMB_SYMBOL`)")
        elif ename in ("VIEW_US_EOD_EXPR", "VIEW_US_EXPR_IDX",
                       "VIEW_ADS_STOCK_US_EOD_DI", "VIEW_STOCK_US_TURNOUT_SHARES"):
            defs.append("  PRIMARY KEY (`SYMBOL`, `TRADE_DATE`)")
        elif ename in ("COM3102", "COM3103", "COM3104", "COM3101"):
            defs.append("  PRIMARY KEY (`FIU_ID`, `F001D`, `F003V`)" if ename != "COM3101"
                        else "  PRIMARY KEY (`FIU_ID`)")
        elif ename in ("COM3105", "COM3106", "VIEW_COM3105", "VIEW_COM3106"):
            defs.append("  PRIMARY KEY (`FIU_ID`, `F001D`, `F002V`, `F003N`)")
        elif ename == "STK2401":
            defs.append("  PRIMARY KEY (`FIU_ID`, `F001D`)")
        stmts.append(f"CREATE TABLE `{ename}` (\n" + ",\n".join(defs) + "\n) ENGINE=InnoDB")
    return stmts + views


# ---------------------------------------------------------------- 股票宇宙
# (SYMBOL, 中文, 英文, 交易所, 申万一级, 中概股, 2023初价, 2026-08价, 总股本亿股,
#  年营收亿美元, 净利率, 毛利率)   # 股本按 px*shares≈真实市值量级校准
STOCKS = [
    ("AAPL", "苹果", "Apple Inc.", "NASDAQ", "电子", 0, 125, 255, 152, 3910, 0.26, 0.44),
    ("MSFT", "微软", "Microsoft Corp.", "NASDAQ", "计算机", 0, 240, 495, 74, 2450, 0.36, 0.69),
    ("NVDA", "英伟达", "NVIDIA Corp.", "NASDAQ", "电子", 0, 145, 175, 245, 1310, 0.55, 0.75),
    ("GOOGL", "谷歌A", "Alphabet Inc. Cl A", "NASDAQ", "传媒", 0, 88, 200, 122, 3500, 0.29, 0.57),
    ("AMZN", "亚马逊", "Amazon.com Inc.", "NASDAQ", "商业贸易", 0, 86, 225, 105, 6380, 0.09, 0.47),
    ("META", "Meta平台", "Meta Platforms Inc.", "NASDAQ", "传媒", 0, 120, 590, 25, 1650, 0.35, 0.81),
    ("TSLA", "特斯拉", "Tesla Inc.", "NASDAQ", "汽车", 0, 118, 340, 32, 990, 0.15, 0.18),
    ("AVGO", "博通", "Broadcom Inc.", "NASDAQ", "电子", 0, 570, 265, 46, 560, 0.39, 0.63),
    ("BRK.B", "伯克希尔B", "Berkshire Hathaway Cl B", "NYSE", "非银金融", 0, 275, 500, 215, 3650, 0.20, 0.0),
    ("JPM", "摩根大通", "JPMorgan Chase & Co.", "NYSE", "银行", 0, 135, 290, 28, 1770, 0.33, 0.0),
    ("V", "Visa", "Visa Inc. Cl A", "NYSE", "非银金融", 0, 208, 345, 19.5, 360, 0.53, 0.98),
    ("XOM", "埃克森美孚", "Exxon Mobil Corp.", "NYSE", "采掘", 0, 108, 122, 43, 3450, 0.10, 0.32),
    ("UNH", "联合健康", "UnitedHealth Group Inc.", "NYSE", "医药生物", 0, 498, 320, 9.1, 4000, 0.06, 0.22),
    ("JNJ", "强生", "Johnson & Johnson", "NYSE", "医药生物", 0, 177, 165, 24, 890, 0.20, 0.68),
    ("WMT", "沃尔玛", "Walmart Inc.", "NYSE", "商业贸易", 0, 142, 100, 80, 6480, 0.03, 0.25),
    ("PG", "宝洁", "Procter & Gamble Co.", "NYSE", "农林牧渔", 0, 140, 152, 23.6, 840, 0.18, 0.51),
    ("HD", "家得宝", "Home Depot Inc.", "NYSE", "商业贸易", 0, 320, 385, 9.9, 1580, 0.09, 0.34),
    ("KO", "可口可乐", "Coca-Cola Co.", "NYSE", "食品饮料", 0, 60, 70, 43, 470, 0.23, 0.61),
    ("MCD", "麦当劳", "McDonald's Corp.", "NYSE", "休闲服务", 0, 268, 305, 7.2, 260, 0.33, 0.57),
    ("CSCO", "思科", "Cisco Systems Inc.", "NASDAQ", "通信", 0, 47, 68, 40, 560, 0.23, 0.65),
    ("ABBV", "艾伯维", "AbbVie Inc.", "NYSE", "医药生物", 0, 163, 195, 17.7, 560, 0.12, 0.60),
    ("MRK", "默沙东", "Merck & Co. Inc.", "NYSE", "医药生物", 0, 108, 82, 25.3, 640, 0.25, 0.76),
    ("CVX", "雪佛龙", "Chevron Corp.", "NYSE", "采掘", 0, 160, 155, 18.6, 2010, 0.10, 0.34),
    ("ACN", "埃森哲", "Accenture plc Cl A", "NYSE", "计算机", 0, 265, 300, 6.3, 670, 0.11, 0.32),
    ("CRM", "赛富时", "Salesforce Inc.", "NYSE", "计算机", 0, 132, 245, 9.6, 380, 0.16, 0.76),
    ("AMD", "超威半导体", "Advanced Micro Devices Inc.", "NASDAQ", "电子", 0, 68, 175, 16.2, 260, 0.08, 0.50),
    ("INTC", "英特尔", "Intel Corp.", "NASDAQ", "电子", 0, 26, 30, 43, 540, 0.02, 0.40),
    ("QCOM", "高通", "QUALCOMM Inc.", "NASDAQ", "电子", 0, 115, 150, 11, 390, 0.25, 0.56),
    ("TXN", "德州仪器", "Texas Instruments Inc.", "NASDAQ", "电子", 0, 172, 200, 9.1, 160, 0.35, 0.63),
    ("ORCL", "甲骨文", "Oracle Corp.", "NYSE", "计算机", 0, 83, 210, 28.3, 530, 0.20, 0.71),
    ("IBM", "IBM", "International Business Machines", "NYSE", "计算机", 0, 141, 275, 9.2, 630, 0.12, 0.56),
    ("DIS", "迪士尼", "Walt Disney Co.", "NYSE", "传媒", 0, 87, 110, 18.2, 940, 0.06, 0.36),
    ("NFLX", "奈飞", "Netflix Inc.", "NASDAQ", "传媒", 0, 295, 1150, 4.3, 400, 0.22, 0.46),
    ("BA", "波音", "Boeing Co.", "NYSE", "国防军工", 0, 205, 225, 5.5, 780, -0.05, 0.11),
    ("CAT", "卡特彼勒", "Caterpillar Inc.", "NYSE", "机械设备", 0, 235, 420, 4.87, 670, 0.17, 0.34),
    ("GS", "高盛", "Goldman Sachs Group Inc.", "NYSE", "非银金融", 0, 340, 660, 2.9, 530, 0.30, 0.0),
    ("BABA", "阿里巴巴", "Alibaba Group Holding Ltd.", "NYSE", "商业贸易", 1, 88, 105, 22, 1350, 0.10, 0.37),
    ("PDD", "拼多多", "PDD Holdings Inc.", "NASDAQ", "商业贸易", 1, 90, 120, 14, 400, 0.28, 0.62),
    ("BIDU", "百度", "Baidu Inc.", "NASDAQ", "计算机", 1, 135, 85, 3.5, 190, 0.15, 0.51),
    ("NTES", "网易", "NetEase Inc.", "NASDAQ", "传媒", 1, 68, 110, 6.4, 160, 0.28, 0.60),
    ("JD", "京东", "JD.com Inc.", "NASDAQ", "商业贸易", 1, 36, 33, 13.6, 1600, 0.03, 0.15),
    ("LI", "理想汽车", "Li Auto Inc.", "NASDAQ", "汽车", 1, 18, 28, 9, 250, 0.07, 0.21),
    ("NIO", "蔚来", "NIO Inc.", "NYSE", "汽车", 1, 9.5, 4.5, 20, 100, -0.35, 0.10),
]
SW1_CODE = {"电子": "801080", "计算机": "801750", "传媒": "801760", "商业贸易": "801200",
            "汽车": "801880", "银行": "801780", "非银金融": "801790", "采掘": "801020",
            "医药生物": "801150", "农林牧渔": "801010", "食品饮料": "801120",
            "休闲服务": "801210", "通信": "801770", "机械设备": "801890",
            "国防军工": "801740", "综合": "801230"}

EOD_START, EOD_END = date(2023, 1, 3), date(2026, 8, 25)
rng = np.random.default_rng(20260825)


def trading_days():
    d, out = EOD_START, []
    while d <= EOD_END:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def price_path(start_px, end_px, n):
    loglen = np.log(end_px / start_px)
    steps = rng.normal(loglen / n, 0.018, n)
    steps += (loglen - steps.sum()) / n
    return start_px * np.exp(np.cumsum(steps))


def quarter_ends():
    """财报期 2019Q1..2026Q2 + FY(到2025): (期末日, F003V, YYYYMM)。"""
    out = []
    for y in range(2019, 2027):
        for qi, (m, dd) in enumerate([(3, 31), (6, 30), (9, 30), (12, 31)], 1):
            if y == 2026 and qi > 2:
                continue
            out.append((date(y, m, dd), f"Q{qi}", y * 100 + m))
        if y <= 2025:
            out.append((date(y, 12, 31), "FY", y * 100 + 12))
    return out


SECTORS = {"AAPL": [("iPhone", "手机", 0.52), ("Services", "服务", 0.24),
                    ("Mac", "电脑", 0.09), ("Wearables", "可穿戴", 0.09), ("iPad", "平板", 0.06)],
           "MSFT": [("Intelligent Cloud", "智能云", 0.43), ("Productivity", "生产力软件", 0.32),
                    ("More Personal Computing", "个人计算", 0.25)],
           "NVDA": [("Data Center", "数据中心", 0.86), ("Gaming", "游戏", 0.09),
                    ("Professional", "专业可视化", 0.05)],
           "BABA": [("Commerce", "中国商业", 0.66), ("Cloud", "云计算", 0.11),
                    ("International", "国际商业", 0.13), ("Others", "其他", 0.10)],
           "TSLA": [("Automotive", "汽车", 0.78), ("Energy", "能源", 0.14), ("Services", "服务", 0.08)]}
REGIONS = [("North America", "北美", 0.58), ("Europe", "欧洲", 0.20),
           ("Greater China", "大中华区", 0.08), ("Asia Pacific", "亚太(除中国)", 0.08),
           ("Others", "其他", 0.06)]
CN_REGIONS = [("Greater China", "大中华区", 0.68), ("North America", "北美", 0.15),
              ("Asia Pacific", "亚太(除中国)", 0.09), ("Europe", "欧洲", 0.05),
              ("Others", "其他", 0.03)]
SIC = {"AAPL": "3571", "MSFT": "7372", "NVDA": "3674", "JPM": "6022", "XOM": "2911",
       "BABA": "5961", "TSLA": "3711"}


def as_row(valmap, cols):
    return [valmap.get(c) for c in cols]


def build(conn, parsed):
    cols = {h: [c for c, _, _ in parsed[h][1]] for h in parsed}
    fiu = {s[0]: f"{i + 1:08d}" for i, s in enumerate(STOCKS)}
    days = trading_days()
    n = len(days)
    eod_by_key = {}

    main_rows, eod_rows, idx_rows, turn_rows, tech_rows, stk_rows = [], [], [], [], [], []
    for (sym, cn, en, exch, sw, cnst, p0, p1, sh_yi, rev_bn, net_m, gro_m) in STOCKS:
        fid = fiu[sym]
        disp = cn + ("-W" if cnst else "")
        isin = "US" + f"{abs(hash(sym)) % 10**9:09d}"[:9] + f"{abs(hash(en)) % 10:01d}"
        main_rows.append(as_row({"FIU_ID": fid, "SYMBOL": sym, "COMB_SYMBOL": f"{sym}.US",
                                 "CSNAME": disp, "IS_CHINESE_STOCK": "中概股" if cnst else None,
                                 "EXCH_HCODE": exch, "SEC_HCODE": f"S{fid[-6:]}",
                                 "IS_IMPORTANT_STOCK": "重要" if rev_bn > 500 else None,
                                 "SW_INDU_CODE_2021_1": sw, "SW1_CODE": SW1_CODE[sw]},
                                cols["50001"]))
        px = price_path(p0, p1, n)
        vol_base = sh_yi * 1e8 * rng.uniform(0.003, 0.012)
        last_close = last_shares = None
        closes = {}
        for i, d in enumerate(days):
            close = round(float(px[i]), 2)
            closes[d] = close
            pre = round(float(px[i - 1]) if i else p0, 2)
            chg = round(close - pre, 2)
            chg_pct = round(chg / pre * 100, 2) if pre else 0.0
            openp = round(pre * (1 + rng.normal(0, 0.004)), 2)
            high = round(max(openp, close) * (1 + abs(rng.normal(0, 0.005))), 2)
            low = round(min(openp, close) * (1 - abs(rng.normal(0, 0.005))), 2)
            vol = int(vol_base * (1 + abs(rng.normal(0, 0.5))))
            amt = round(vol * (openp + high + low + close) / 4, 2)
            shares = round(sh_yi * 1e8 * (1 + 0.008 * i / 252), 0)
            turn = round(vol / shares * 100, 3)
            avgp = round(amt / vol, 2) if vol else None
            row = {"TRADE_DATE": d, "SYMBOL": sym, "COMB_SYMBOL": f"{sym}.US", "FIU_ID": fid,
                   "NAME": disp, "PRE_CLOSE": pre, "OPEN_PRICE": openp, "HIGH_PRICE": high,
                   "LOW_PRICE": low, "CLOSE_PRICE": close, "LAST_PRICE": close, "CHG": chg,
                   "CHG_PCT_DAY": chg_pct, "SWING_DAY": round((high - low) / pre * 100, 2),
                   "AVG_PRICE": avgp, "TRADE_VOLUME": vol, "TRADE_AMOUNT": amt,
                   "TURN_RATIO_PCT": turn, "TOTAL_SHARES": shares, "ISIN": isin,
                   "SEC_TYPE": "STK", "ETF_FLAG": "N"}
            eod_rows.append(as_row(row, cols["50034"]))
            eod_by_key[(sym, d)] = (pre, openp, high, low, close, vol, amt, turn, shares)

            def pct(k):
                j = max(0, i - k)
                return round((px[i] / px[j] - 1) * 100, 2)
            if i >= 252:
                ytd_j = next(j for j, dd in enumerate(days) if dd.year == d.year)
                mtd_j = next(j for j, dd in enumerate(days)
                             if dd.year == d.year and dd.month == d.month)
                wk_j = i - d.weekday() if i - d.weekday() >= 0 else 0
                irow = {"FIU_ID": fid, "SYMBOL_NASDAQ": sym, "ISIN": isin, "F002V": disp,
                        "F003V": en, "F001V": exch, "F004V": "普通股", "F006V": "N",
                        "TRADE_DATE": d, "SYMBOL": sym, "COMB_SYMBOL": f"{sym}.US",
                        "CLOSE_PRICE": close, "CHG_PCT_DAY": chg_pct,
                        "CHG_PCT_WEEK": pct(5), "CHG_PCT_MONTH": pct(21),
                        "CHG_PCT_QUARTER": pct(63), "CHG_PCT_YEAR": pct(252),
                        "CHG_PCT_WTD": round((px[i] / px[wk_j] - 1) * 100, 2),
                        "CHG_PCT_MTD": round((px[i] / px[mtd_j] - 1) * 100, 2),
                        "CHG_PCT_YTD": round((px[i] / px[ytd_j] - 1) * 100, 2), "NAME": disp}
                idx_rows.append(as_row(irow, cols["50035"]))
            if i >= n - 60:
                turn_rows.append(as_row({"FIU_ID": fid, "TURN_RATIO_PCT": turn,
                                         "TOTAL_SHARES": shares, "TRADE_DATE": d,
                                         "SYMBOL": sym, "CSNAME": disp, "ENAME": en},
                                        cols["50033"]))
            last_close, last_shares, last_d = close, shares, d

        eps = rev_bn * net_m * 1e8 / (sh_yi * 1e8)          # 美元
        bvps = max(eps * 8, 0.1)
        rev_ps = rev_bn * 1e8 / (sh_yi * 1e8)
        pe = round(last_close / eps, 2) if eps > 0 else None
        v = {"FIU_ID": fid, "F001D": last_d, "F002V": "USD",
             "F003N": round(sh_yi * 100, 2), "F005N": round(sh_yi * 100 * 0.99, 2),
             "F007N": round(max(eps * rng.uniform(0.2, 0.6), 0.1) / last_close * 100, 3),
             "F011N": round(1 / pe, 5) if pe else None,
             "F013N": round(last_close * sh_yi * 100 * 7.2, 2),
             "F015N": round(last_close / bvps, 3), "F019N": round(rng.uniform(8, 40), 3),
             "F021N": pe, "F025N": round(last_close / max(rev_ps, 0.1), 2),
             "F027N": round(sh_yi * 1e6, 0), "F029N": round(sh_yi * 1e6 * 0.9, 0),
             "F031N": round(max(eps * rng.uniform(1.0, 1.4), 0.3), 3),
             "F033N": round(max(eps * rng.uniform(0.2, 0.6), 0.05), 4)}
        for k in list(v):
            if re.fullmatch(r"F\d{3}N", k):
                v[k.replace("N", "D")] = last_d          # 值列对应的更新日期列
        tech_rows.append(as_row(v, cols["50003"]))

        # ---- 财务三表 (Q/FY 行, 供 _Q/_CUM 视图过滤) ----
        g = 1.08 if rev_bn < 300 else (1.12 if rev_bn < 1500 else 1.06)
        for d, f3v, yyyymm in quarter_ends():
            ann_rev = rev_bn * g ** (d.year - 2019)
            # 季度权重归一化, 保证 Q1+Q2+Q3+Q4 = FY
            w = {"Q1": 1.0, "Q2": 1.02, "Q3": 1.05, "Q4": 1.28}[f3v] / 1.0875 if f3v != "FY" else None
            rev = ann_rev if f3v == "FY" else ann_rev * 0.25 * w
            rev *= rng.uniform(0.97, 1.03)
            net = rev * net_m * rng.uniform(0.9, 1.1)
            gross = rev * gro_m
            shares_then = sh_yi * 1e8                    # 股本恒定, 保证 EPS 全年份自洽
            eps_then = net * 1e8 / shares_then
            common = {"FIU_ID": fid, "F001D": d, "F002D": d, "F003V": f3v,
                      "F004N": 365 if f3v == "FY" else 91, "F005V": "USD", "F006N": yyyymm}

            inc = dict(common)
            inc.update({"F007N": net * 0.02 * 100, "F011N": net * 0.001 * 100,
                        "F012N": net * 1.25 * 100, "F013N": net * 1.25 / shares_then,
                        "F014N": net * 1.3 * 100, "F016N": eps_then,
                        "F017N": eps_then * 0.98, "F018N": eps_then, "F021N": rev * 1.08 * 100,
                        "F022N": gross * 100, "F023N": max(net, 1) * 0.18 * 100,
                        "F032N": net * 100,
                        "F034N": net * 100, "F041N": net * 1.15 * 100,
                        "F044N": net * 1.22 * 100, "F048N": rev * 100,
                        "F049N": rev * 1e8 / shares_then, "F050N": rev * 0.18 * 100,
                        "F052N": net * 0.02 * 100, "F056N": d.year})
            bs = dict(common)
            assets = rev_bn * (3.2 if sw in ("银行", "非银金融") else 1.6) * g ** (d.year - 2019) * 1e2  # 百万美元
            liab = assets * rng.uniform(0.35, 0.75)
            equity = assets - liab
            bs.update({"F008N": assets, "F009N": assets * 0.35,
                       "F014N": equity * 1e6 / shares_then, "F017N": assets * 0.12,
                       "F018N": assets * 0.2, "F020N": equity * 0.7, "F022N": liab * 0.5,
                       "F023N": liab * 0.35, "F025N": liab * 0.1, "F034N": assets * 0.12,
                       "F040N": liab, "F041N": liab * 0.45, "F044N": assets, "F062N": equity,
                       "F069N": d.year})
            cf = dict(common)
            ocf = net * rng.uniform(0.9, 1.3)
            capex = rev * rng.uniform(0.03, 0.09)
            dps = max(eps_then * rng.uniform(0.2, 0.6), 0.01)
            cf.update({"F008N": capex * 100, "F009N": ocf * 0.1 * 100,
                       "F011N": rev * 0.05 * 100,
                       "F015N": dps * shares_then / 1e8 * 100, "F016N": dps,
                       "F020N": -rev * 0.04 * 100, "F022N": (ocf - capex) * 100,
                       "F027N": -capex * 1.3 * 100, "F034N": ocf * 100, "F036N": ocf * 100,
                       "F044N": d.year})
            for kind, valmap, hc in (("is", inc, "50005"), ("bs", bs, "50004"), ("cf", cf, "50006")):
                FIN_BUF[kind].append(as_row(valmap, cols[hc]))

        # ---- 板块/地域分布 (近3个财年) ----
        for y in (2023, 2024, 2025):
            rev_y = rev_bn * (1.1 ** (y - 2023)) * 100   # 百万美元
            segs = SECTORS.get(sym, [("Main Business", "主营业务", 0.62),
                                     ("Secondary", "次主营", 0.24), ("Others", "其他", 0.14)])
            for i, (en_seg, cn_seg, share) in enumerate(segs, 1):
                dd = date(y, 12, 31)
                m = {"FIU_ID": fid, "F001D": dd, "F002V": "SEG", "F003N": i, "F004D": dd,
                     "F005V": "USD", "F006V": en_seg, "SECTOR_CNAME": cn_seg,
                     "F007N": round(rev_y * share, 2), "F008N": round(rev_y * share * 0.3, 2),
                     "F012V": SIC.get(sym, "0000"), "F003V": "FY"}
                SEC_BUF["view5"].append(as_row(m, cols["50009"]))
                SEC_BUF["base5"].append(as_row(m, cols["50007"]))
            regions = CN_REGIONS if cnst else REGIONS
            for i, (en_r, cn_r, share) in enumerate(regions, 1):
                dd = date(y, 12, 31)
                m = {"FIU_ID": fid, "F001D": dd, "F002V": "REG", "F003N": i, "F004D": dd,
                     "F005V": "USD", "F006V": en_r, "REGION_CNAME": cn_r,
                     "F007N": round(rev_y * share, 2), "F008N": round(rev_y * share * 0.3, 2),
                     "F003V": "FY"}
                SEC_BUF["view6"].append(as_row(m, cols["50010"]))
                SEC_BUF["base6"].append(as_row(m, cols["50008"]))
        # ---- STK2401 (已停用表, 近250日 x 前8只) ----
        if sym in [s[0] for s in STOCKS[:8]]:
            for d in days[-250:]:
                r = eod_by_key[(sym, d)]
                stk_rows.append([fid, d, "USD", r[0], r[1], r[2], r[3], r[4], r[5], r[6],
                                 r[7], float(r[8])])
        FIN_FLUSH.append(fiu)  # no-op 占位避免误删
    return dict(main=main_rows, eod=eod_rows, idx=idx_rows, turn=turn_rows,
                tech=tech_rows, stk=stk_rows, fin=FIN_BUF, sec=SEC_BUF)


FIN_BUF = {"is": [], "bs": [], "cf": []}
SEC_BUF = {"view5": [], "base5": [], "view6": [], "base6": []}
FIN_FLUSH = []


def sanitize(v):
    if isinstance(v, (np.floating, np.integer)):
        return v.item()
    return v


def insert_many(cur, table, cols, rows):
    if not rows:
        return
    sql = (f"INSERT INTO `{table}` ({','.join(f'`{c}`' for c in cols)}) "
           f"VALUES ({','.join(['%s'] * len(cols))})")
    cur.executemany(sql, [[sanitize(v) for v in r] for r in rows])


TABLE_OF = {"50001": "AMERICAN_STOCK_MAIN", "50002": "STK2401", "50003": "COM3101",
            "50004": "COM3102", "50005": "COM3103", "50006": "COM3104",
            "50007": "COM3105", "50008": "COM3106", "50009": "VIEW_COM3105",
            "50010": "VIEW_COM3106", "50032": "VIEW_ADS_STOCK_US_EOD_DI",
            "50033": "VIEW_STOCK_US_TURNOUT_SHARES", "50034": "VIEW_US_EOD_EXPR",
            "50035": "VIEW_US_EXPR_IDX"}


def main():
    parsed = parse_columns(__file__.rsplit("/", 1)[0] + "/fiu_columns_from_metadata.txt")
    data = build(None, parsed)
    cols = {h: [c for c, _, _ in parsed[h][1]] for h in parsed}
    conn = pymysql.connect(host=HOST, port=PORT, user=USER, password=PASSWORD,
                           charset="utf8mb4")
    cur = conn.cursor()
    cur.execute("DROP DATABASE IF EXISTS fiu")
    for stmt in build_ddl(parsed):
        cur.execute(stmt)
    cur.execute("USE fiu")
    insert_many(cur, "AMERICAN_STOCK_MAIN", cols["50001"], data["main"])
    insert_many(cur, "VIEW_US_EOD_EXPR", cols["50034"], data["eod"])
    insert_many(cur, "VIEW_US_EXPR_IDX", cols["50035"], data["idx"])
    insert_many(cur, "VIEW_STOCK_US_TURNOUT_SHARES", cols["50033"], data["turn"])
    insert_many(cur, "COM3101", cols["50003"], data["tech"])
    insert_many(cur, "COM3102", cols["50004"], data["fin"]["bs"])
    insert_many(cur, "COM3103", cols["50005"], data["fin"]["is"])
    insert_many(cur, "COM3104", cols["50006"], data["fin"]["cf"])
    insert_many(cur, "VIEW_COM3105", cols["50009"], data["sec"]["view5"])
    insert_many(cur, "COM3105", cols["50007"], data["sec"]["base5"])
    insert_many(cur, "VIEW_COM3106", cols["50010"], data["sec"]["view6"])
    insert_many(cur, "COM3106", cols["50008"], data["sec"]["base6"])
    insert_many(cur, "STK2401", cols["50002"], data["stk"])
    conn.commit()

    for t in ["AMERICAN_STOCK_MAIN", "VIEW_US_EOD_EXPR", "VIEW_US_EXPR_IDX",
              "VIEW_STOCK_US_TURNOUT_SHARES", "COM3101", "COM3102", "COM3103", "COM3104",
              "VIEW_COM3102_Q", "VIEW_COM3102_CUM", "VIEW_COM3103_Q", "VIEW_COM3103_CUM",
              "VIEW_COM3104_Q", "VIEW_COM3104_CUM", "VIEW_COM3105", "VIEW_COM3106",
              "COM3105", "COM3106", "STK2401"]:
        cur.execute(f"SELECT COUNT(*) FROM `{t}`")
        print(f"{t}: {cur.fetchone()[0]} 行")
    cur.execute("SELECT COMB_SYMBOL, CSNAME, SW_INDU_CODE_2021_1, IS_CHINESE_STOCK "
                "FROM AMERICAN_STOCK_MAIN WHERE COMB_SYMBOL IN ('AAPL.US','NVDA.US','BABA.US')")
    print("主表样例:", cur.fetchall())
    cur.execute("SELECT F001D, F003V, ROUND(F048N,1), ROUND(F032N,1), ROUND(F016N,2) "
                "FROM VIEW_COM3103_CUM WHERE FIU_ID=(SELECT FIU_ID FROM "
                "AMERICAN_STOCK_MAIN WHERE COMB_SYMBOL='TSLA.US') ORDER BY F001D DESC LIMIT 3")
    print("特斯拉 FY 营收/净利/EPS:", cur.fetchall())
    conn.close()
    print("== fiu 模拟库建库完成 ==")


if __name__ == "__main__":
    sys.exit(main())
