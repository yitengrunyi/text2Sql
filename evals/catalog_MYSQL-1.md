# MYSQL-1: 266 tables

| table | cols | rows~ | comment |
|---|---:|---:|---|
| ANALYST_ATTENT_INDUSTRY_LIST_CALENDARDAY | 15 | 281143 | 分析师关注行业列表 |
| ANALYST_ATTENT_INDUSTRY_LIST_FREQUENCY | 14 | 142936 | 分析师关注行业列表 |
| BROKER_OPINION | 29 | 29180 | 从券商行业周报中提取核心观点，行业事件，推荐股票等。 |
| BROKER_OPINION_SE | 13 | 251184 | 从表 存标准化的股票代码 |
| BROKER_OPINION_SUMMARY | 17 | 980 | 按周度，汇总观点 |
| CK_QT_DAILYQUOTE | 6 | 3789 | 聚源行情表的时间监控 |
| CODE_MAPPING | 16 | 60152 | 代码和自己基金主数据的关联表  |
| CONCEPT_TIMES | 19 | 0 | 记录概念每天在研报、路演、微信群、星球里面的出现次数，以及滚动7天的次数。 |
| CONCEPT_TIMES_HOUR | 23 | 3477807 |  |
| CSI_INDEX_QUOTE | 21 | 22821331 | 中证指数行情 |
| ERR_LOG | 34 | 23 |  |
| ETF_CNAME_USA | 13 | 3416 |  |
| ETF_DAILY_QUOTE | 34 | 2261993 | ETF行情，来自聚源行情表 |
| ETF_DAILY_QUOTE_USA | 20 | 6039259 | 美股ETF行情 |
| ETF_INFO_DETAIL | 28 | 10622 | ETF信息 |
| ETF_LABEL_INFO_CHINA | 37 | 1820 |  |
| ETF_LABEL_INFO_USA | 30 | 3420 | ETF标签信息，实际使用的宽表 |
| ETF_LABEL_POPULAR_TOPICS | 15 | 5002 | 常用基金标签 |
| ETF_LABEL_POPULAR_TOPICS_LIST | 13 | 57 | 常用基金标签 |
| ETF_LABEL_SUMMARY | 11 | 2407 | 给煜东用的，etf标签的竖表 |
| ETF_PERFORMANCE_DETAIL | 40 | 669444 | ETF表现 |
| ETF_SHARES_CHANGE_ROLL | 21 | 4584820 | ETF基金份额变动（5日滚动）情况 |
| ETF_STATISTICS_ROLL | 29 | 8131521 | ETF基金，滚动收益率，近一年，一个月，3年啥的 只保留最新一期的截面值 |
| ETF_STATISTICS_YEAR | 28 | 10934 | ETF基金产品超额收益统计表(年统计） 计算每年（12个月），基金与指数超额的胜率与盈亏比，超额等值         |
| ETL_DATA_ERR_LOG | 30 | 106 |  |
| ETL_JOB_LOG | 17 | 0 |  |
| EXCHANGE_INDEX_QUOTE | 20 | 4644019 | 交易所的指数行情， 成长，风格指数这些 |
| FOBE_GJZQ_CATERING_BRAND_YEAR | 16 | 0 |  |
| FOF_PORTFOLIO_DETAIL | 22 | 41776 | FOF基金持仓情况 |
| FUND_AND_COMPANY_MAPPING | 17 | 27871 | 基金和基金公司的对应关系 |
| FUND_AND_COMPANY_MAPPING_bak_20251114 | 17 | 29583 |  |
| FUND_AND_MANAGER_MAPPING | 18 | 63265 | 基金和基金经理的对应关系 |
| FUND_ASSET_ALLOCATION | 19 | 484564 | 基金资产情况 |
| FUND_BENCHMARK | 35 | 0 | VIEW |
| FUND_COMB_DETAIL | 14 | 66 | fof基金上传的组合的基金列表信息  |
| FUND_COMB_INFO | 15 | 10 | fof基金上传的组合  |
| FUND_COMPANY_ASSET_ALLOCATION | 18 | 8113 | 基金公司持有基金资产净值和资产总值，根据基金公司和基金关系表FUND_AND_COMPANY_MAPPING，聚合FUN |
| FUND_COMPANY_INDUSTRY_HOLDING_MV_DETAIL_HY | 23 | 2546817 | 基金公司持有行业市值具体情况（半年度） |
| FUND_COMPANY_INDUSTRY_HOLDING_MV_DETAIL_Q | 23 | 2827237 | 基金公司持有行业市值具体情况（季度） |
| FUND_CORR_PARTNER | 18 | 0 | 基金之间的相互相关性  |
| FUND_CORR_PARTNER_ROLL | 19 | 1457534 | 基金滚动相关性  |
| FUND_DISCLOSURE_STATISTICS | 13 | 183 | 基金季报披露统计信息 存时间序列值 |
| FUND_FRONT_CONTROL | 10 | 1 | 基金日期控制表， 用来控制前端应该取什么报告期的日期 该表只有一行记录 |
| FUND_HOLD_STATISTICS | 23 | 3500565 | 基金产品持仓统计（最新）表 只存基金产品最新报告期的数据，REPORT_DATE不是主键之一 每 |
| FUND_INDUSTRY_ASSET_RATIO_ALL | 24 | 61741998 | 基金产品净值与所有行业指数的回归结果 |
| FUND_INDUSTRY_CHANGE_HY | 25 | 33159113 | 基金行业持仓变化情况_半年度 |
| FUND_INDUSTRY_CHANGE_Q | 25 | 21010926 | 基金行业持仓变化情况_季度 |
| FUND_INDUSTRY_DIVERGENCE | 21 | 0 | 基金经理行业分歧度 用“市值加权的持仓股数变化”的标准差和均值来测量行业分歧度 |
| FUND_INDUSTRY_HOLDING_MV_DETAIL_HY | 22 | 52661502 | 基金持有行业市值具体情况（半年度） |
| FUND_INDUSTRY_HOLDING_MV_DETAIL_Q | 22 | 28025154 | 基金持有行业市值具体情况（季度） |
| FUND_INDUSTRY_HOLDING_MV_DETAIL_QDII | 27 | 46468 | QDII 基金持有行业市值具体情况（QDII的不分季度还是年度） |
| FUND_INDUSTRY_HOLDING_MV_HY | 22 | 49173 | 基金持有行业市值情况（半年度） |
| FUND_INDUSTRY_HOLDING_MV_Q | 22 | 92519 | 基金持有行业市值情况（季度） |
| FUND_INVEST_ADVISOR_REL | 15 | 21712 | 基金和管理人关联关系表 |
| FUND_LABEL_INFO | 16 | 41 | 基金（基金经理）标签信息表 |
| FUND_LABEL_VALUE_SECTION | 17 | 42179 | 基金标签值表（截面） |
| FUND_LABEL_VALUE_SERIES | 18 | 429764 | 基金标签值表（时间序列） |
| FUND_LIST_FREQUENCY | 14 | 667048 | 基金列表，用来计算的基金，每个报告期统计一次 |
| FUND_MANAGER_ABNORMAL_INDUSTRY_ASSET_RATIO | 22 | 761670 | 基金经理净值有异动的时候， 用相关联的那些指数回归，这些是离散的点，一截一截的 |
| FUND_MANAGER_ABNORMAL_YIELD | 17 | 31441 | 记录基金经理收益特别高或者特别低的天数及对应三级行业指数收益 |
| FUND_MANAGER_ASSET_ALLOCATION | 18 | 97347 | 基金经理持有基金资产净值和资产总值，根据基金经理和基金关系表FUND_AND_MANAGER_MAPPING，聚合FUN |
| FUND_MANAGER_ASSET_RATIO | 21 | 5896993 | 基金经理（合成）净值与，与大类资产的回归结果  中证全指（000985.CSI） 中 |
| FUND_MANAGER_DERIVED_YIELD | 16 | 912732 | 基金经理净值表 衍生，不同频率 |
| FUND_MANAGER_HEAVILY_HOLD_INDUSTRY_HY | 23 | 70307 |  |
| FUND_MANAGER_HEAVILY_HOLD_INDUSTRY_Q | 23 | 157200 |  |
| FUND_MANAGER_HOLD_CONCEPT_HY | 22 | 1842571 | 基金经理持有的概念，包含概念内包含的个股数量 |
| FUND_MANAGER_HOLD_CONCEPT_Q | 22 | 898286 | 基金经理持有的概念，包含概念内包含的个股数量 |
| FUND_MANAGER_HOLD_STATISTICS | 22 | 9088569 | 基金经理持仓统计（最新）表 只存基金经理最新报告期的数据，REPORT_DATE不是主键之一 每 |
| FUND_MANAGER_HOLD_STOCK_FEATURE | 17 | 2668909 | 基金经持股特征 存每个报告期，基金经理的持股特征。 TYPE： 1：独门股。仅仅被这 |
| FUND_MANAGER_HOLD_STOCK_FEATURE_Q | 16 | 0 | 基金经持股特征 存每个报告期，基金经理的持股特征。 TYPE： 1：独门股。仅仅被这 |
| FUND_MANAGER_INDUSTRY_ASSET_RATIO_ALL | 23 | 39522553 | 基金经理（合成）净值与所有行业指数的回归结果 |
| FUND_MANAGER_INDUSTRY_ASSET_RATIO_HY | 23 | 20771664 | 基金经理（合成）净值与全部行业指数的回归结果 |
| FUND_MANAGER_INDUSTRY_ASSET_RATIO_Q | 23 | 19279772 | 基金经理（合成）净值与重仓行业指数的回归结果 |
| FUND_MANAGER_INDUSTRY_CHANGE_HY | 24 | 22365917 | 基金经理行业持仓变化情况_半年度 |
| FUND_MANAGER_INDUSTRY_CHANGE_Q | 24 | 15978357 | 基金经理行业持仓变化情况_季度 |
| FUND_MANAGER_INDUSTRY_CONCERTRATION_HY | 17 | 238821 | 基金经理全部股持股集中度 |
| FUND_MANAGER_INDUSTRY_CONCERTRATION_Q | 17 | 502585 | 基金经理重仓股持股集中度 |
| FUND_MANAGER_INDUSTRY_CORR_HY | 19 | 0 | 基金经理净值曲线与季度重仓指数的相关性 这里不区分TOP_N，所有的指数一起计算相关性，包括债基的 |
| FUND_MANAGER_INDUSTRY_CORR_Q | 19 | 10828251 | 基金经理净值曲线与季度重仓指数的相关性 这里不区分TOP_N，所有的指数一起计算相关性，包括债基的 |
| FUND_MANAGER_INDUSTRY_DIVERGENCE_HY | 22 | 1008 | 基金经理行业分歧度 用“市值加权的持仓股数变化”的标准差和均值来测量行业分歧度 |
| FUND_MANAGER_INDUSTRY_DIVERGENCE_Q | 22 | 974 | 基金经理行业分歧度 用“市值加权的持仓股数变化”的标准差和均值来测量行业分歧度 |
| FUND_MANAGER_INDUSTRY_HOLDING_MV_HY | 24 | 22383142 | 基金经理持有行业市值情况（半年度） |
| FUND_MANAGER_INDUSTRY_HOLDING_MV_Q | 24 | 13059587 | 基金经理持有行业市值情况（季度） |
| FUND_MANAGER_INDUSTRY_HOLDING_MV_RANK_HY | 21 | 2267536 | 基金经理持有股票市值的行业内排名  |
| FUND_MANAGER_INDUSTRY_HOLDING_MV_RANK_Q | 21 | 1933649 | 基金经理持有股票市值的行业内排名  |
| FUND_MANAGER_INDUSTRY_WEIGHTED_YIELD_HY | 16 | 1252423 | 基金经理前N重仓行业加权涨跌幅 |
| FUND_MANAGER_INDUSTRY_WEIGHTED_YIELD_Q | 16 | 2538369 | 基金经理前N重仓行业加权涨跌幅 |
| FUND_MANAGER_INFO | 29 | 6286 | 基金经理概况 |
| FUND_MANAGER_NET_VALUE | 15 | 2564289 | 基金经理净值表 |
| FUND_MANAGER_NET_VALUE_SIMULATE | 15 | 2363110 | 基金经理净值表(虚拟) |
| FUND_MANAGER_OPER_HINT_ASSET | 23 | 191972 | 基金经理操作提示 根据“势”，判断增持或者减持的强度  |
| FUND_MANAGER_OPER_HINT_INDUSTRY | 24 | 1200222 | 基金经理操作提示 根据“势”，判断增持或者减持的强度  |
| FUND_MANAGER_OPINION | 33 | 84420 | 基金经理一句话观点 |
| FUND_MANAGER_PARAS_MOMENTUM_ASSET | 48 | 1703873 | 回归参数统计，包括beta的“势”之类  |
| FUND_MANAGER_PARAS_MOMENTUM_INDUSTRY | 49 | 48861994 | 回归参数的“势”  |
| FUND_MANAGER_REPORT_LIST | 12 | 137728 |  |
| FUND_MANAGER_STATISTICS_YEAR | 21 | 87466 | 基金经理收益统计表(年统计） 计算每年（12个月），基金与指数超额的胜率与盈亏比，超额等值  |
| FUND_MANAGER_STOCK_ALLOCATION_HY | 14 | 27450 | 基金经理持有股票资产具体情况，根据FUND_MANAGER_STOCK_PORTFOLIO_HY聚合得到，得到港股和全部 |
| FUND_MANAGER_STOCK_ALLOCATION_Q | 14 | 56206 | 基金经理持有股票资产具体情况，根据FUND_MANAGER_STOCK_PORTFOLIO_Q聚合得到，得到港股和全部股 |
| FUND_MANAGER_STOCK_CHANGE_HY | 31 | 9512520 | 基金经理股票持仓变化情况_半年度 |
| FUND_MANAGER_STOCK_CHANGE_Q | 31 | 2485813 | 基金经理股票持仓变化情况_季度 |
| FUND_MANAGER_STOCK_PORTFOLIO_HY | 23 | 6516189 | 半年报、年报基金经理持仓明细 |
| FUND_MANAGER_STOCK_PORTFOLIO_Q | 23 | 2123681 | 季报基金经理持仓明细 |
| FUND_MANAGER_STYLE_ASSET_RATIO | 23 | 10781543 | 基金经理（合成）净值与大中小盘风格指数的回归结果  |
| FUND_MANAGER_TOP10_STOCK_CHANGE_HY | 16 | 472576 | 基金经理前10大股票变化情况-半年度 |
| FUND_MANAGER_TOP10_STOCK_CHANGE_Q | 16 | 1029834 | 基金经理前10大股票变化情况-季度 |
| FUND_MANAGER_TRACK_ASSET_RATIO | 21 | 33078 | 基金经理（合成）净值与，与赛道指数的回归结果  |
| FUND_MANAGER_TRACK_HOLDING | 19 | 177149 | 基金经理持有赛道市值情况 |
| FUND_MANAGER_TURNOVER_RATE | 12 | 35272 | 基金经理换手率 |
| FUND_MANAGER_WEIGHTED_INDUSTRY_HY | 23 | 287418 | 基金经理持有的行业加权比例(季度) 如果在某个行业上只只有一个股票，则 市值加权 和 对数市值加权 的持仓变 |
| FUND_MANAGER_WEIGHTED_INDUSTRY_Q | 23 | 142931 | 基金经理持有的行业加权比例(季度) 如果在某个行业上只只有一个股票，则 市值加权 和 对数市值加权 的持仓变 |
| FUND_NETVALUE | 17 | 27734134 |  |
| FUND_NETVALUE_SIMULATE | 16 | 16971156 | 基金拟合收益 |
| FUND_OPER_HINT | 26 | 5032516 | 基金产品操作提示 根据“势”，判断增持或者减持的强度  |
| FUND_ORIGINAL_NETVALUE | 13 | 26790 | 原始净值表 |
| FUND_PARAS_MOMENTUM | 50 | 32447385 | 回归参数统计，包括beta的“势”之类 基金产品的 |
| FUND_PERFORMANCE_ATTRIBUTION_DAILY | 16 | 204313 | 基金组合业绩归因（日频） |
| FUND_PORTFOLIO_DETAIL | 25 | 24192128 | 基金持股明细 包含上市公司季报披露的十大股东信息 |
| FUND_PORTFOLIO_DETAIL_COMPANY_LIST | 23 | 6510 | 基金持股明细 包含上市公司季报披露的十大股东信息 把被删除的纯3的移过来 |
| FUND_PORTFOLIO_DETAIL_QDII | 31 | 161590 | 基金持股明细  |
| FUND_PORTFOLIO_MIN_REPORT_DATE | 12 | 3216928 | 基金持仓股票最小报告日期 |
| FUND_POSITION_RATIO_DALIY_BY_RATIO | 19 | 20469640 | 基金的股票持仓占比（日频）-根据市值占比计算 |
| FUND_POSITION_RATIO_DALIY_BY_SHARES | 20 | 0 | 基金的股票持仓占比（日频）-根据股数计算 |
| FUND_REPORT_LIST | 13 | 413028 | 聚合表，放基金报告期 |
| FUND_SHARES_CHANGE | 37 | 4199608 | 基金份额变动  交易所上市基金（如ETF、LOF）日更新，其他基金季更新 |
| FUND_STATISTICS_FREQ | 29 | 7569806 | 基金产品收益统计表(不同频率的，季度，月频）  |
| FUND_STATISTICS_RANGE | 29 | 2216302 | 基金产品在区间段内的收益统计  |
| FUND_STATISTICS_ROLL | 29 | 48641 | ETF基金，滚动收益率，近一年，一个月，3年啥的 只保留最新一期的截面值 |
| FUND_STATISTICS_YEAR | 28 | 160751 | 基金产品超额收益统计表(年统计） 计算每年（12个月），基金与指数超额的胜率与盈亏比，超额等值  |
| FUND_STOCK_CHANGE_HY | 25 | 18333629 | 基金股票持仓_半年报 |
| FUND_STOCK_CHANGE_Q | 25 | 3459427 | 基金股票持仓_季报 |
| FUND_STOCK_INTERVAL_CONTRIBUTION | 22 | 33690 | 基金持有个股的区间贡献 |
| FUND_STOCK_INTERVAL_CONTRIBUTION_ALL | 22 | 533807 | 基金持有个股的区间贡献 |
| FUND_STOCK_SIMULATE_PORTFOLIO | 24 | 6636468 | 基金季报拼接的全持仓 有3种方式： 1.半年报往后推到下个季度 2.相邻2期半年报平 |
| FUND_TABLE_CAL_TIME_LOG | 17 | 109173 | 计算表数据的执行时间 |
| FUND_TABLE_UPDATE_INFO | 12 | 13 | 记录计算过程中，上次取到原始表的最大时间戳 应该在每次计算函数结束后，执行统一的函数更新该值 |
| FUND_TOP10_STOCK_CHANGE_HY | 17 | 769345 | 基金前10大股票变化情况-半年度 |
| FUND_TOP10_STOCK_CHANGE_Q | 17 | 3847985 | 基金前10大股票变化情况-季度 |
| FUND_TRACK_HOLDING | 20 | 683377 | 基金持有赛道市值情况 |
| FUND_TURNOVER_RATE | 13 | 21971 | 基金换手率 |
| HK_INDEX_QUOTE | 12 | 19225 | 港交所的指数行情 |
| HOT_TOPICS_CONTROL | 18 | 886 | 记录每天批次更新每一步的完成情况。  |
| HOT_TOPICS_DAILY_REPORT | 17 | 1107 | 日报 |
| HOT_TOPICS_DAILY_REPORT_US | 15 | 54 | 美股日报生成表 |
| HOT_TOPICS_MAIN | 23 | 23416 | 蓝宝书主表。存每天3个批次的热门题材。 |
| HOT_TOPICS_MAIN_20250818_bak | 21 | 176 |  |
| HOT_TOPICS_MAIN_20250819_bak | 21 | 22 |  |
| HOT_TOPICS_MAIN_20260827 | 23 | 302 | 蓝宝书主表。存每天3个批次的热门题材。 |
| HOT_TOPICS_MAIN_20260827_copy1 | 23 | 326 | 蓝宝书主表。存每天3个批次的热门题材。 |
| HOT_TOPICS_MAIN_2026_08_12 | 23 | 0 | 蓝宝书主表。存每天3个批次的热门题材。 |
| HOT_TOPICS_RELA | 14 | 285167 | 热门题材表，关系表 |
| HOT_TOPICS_RELATED_STOCK | 18 | 59269 | 热门题材关联的股票代码 |
| HOT_TOPICS_SEQ_MAP | 15 | 10378 | 热门题材的名字会变，这里把历史上的映射到同一个名称上。 映射有几种： 1. 标准名称映射。例如“ |
| HOT_TOPICS_SEQ_NO_MAP | 12 | 862 | 匹配不上标准名的 |
| HOT_TOPICS_STANDARD_NAME | 13 | 307 | 热门题材的标准名称 想了下，还是要维护一个主表，不然后面的变化控制不到，也监控不到 |
| HOT_TOPICS_US_MAIN | 17 | 3325 | 美股蓝宝书主表 |
| HOT_TOPICS_US_MAIN_20260827 | 17 | 205 | 美股蓝宝书主表 |
| HOT_TOPICS_US_MAIN_20260827_copy1 | 17 | 235 | 美股蓝宝书主表 |
| HOT_TOPICS_US_MAIN_20260827_copy2 | 17 | 236 | 美股蓝宝书主表 |
| HOT_TOPICS_US_MAIN_2026_08_18 | 17 | 232 | 美股蓝宝书主表 |
| HOT_TOPICS_US_MAIN_copy1 | 16 | 40 | 美股蓝宝书主表 |
| HOT_TOPICS_US_RELATED_STOCK | 15 | 0 | 热门美股题材关联的股票代码 |
| HOT_TOPICS_VIOLATION | 19 | 2 | 生成音频时候，校验不通过的原因，存下来。 |
| INDEX_CAPITAL_ROLL | 17 | 27477 | 指数（ETF）资金净流入统计 |
| INDEX_INDUSTRY_MAPPING | 21 | 0 | VIEW |
| INDEX_QUOTE_ALL | 32 | 37312150 | 把所有的指数行情放在一起，不然好麻烦。。。还是逃不开这一步 |
| INDEX_STATISTICS_FREQ | 31 | 1374181 | 指数频率 |
| INDEX_STATISTICS_ROLL | 29 | 37424 | etf业绩基准，指数的滚动收益率 |
| INDEX_STATISTICS_YEAR | 30 | 59585 | 指数年收益率 |
| INDUSTRY_INDEX_STATISTICS_FREQ | 27 | 1106958 | 讯兔行业指数，频率统计 周线，月线啥的  |
| INDUSTRY_INDEX_STATISTICS_RANGE | 31 | 5309 | 讯兔行业指数，范围统计的表  |
| INDUSTRY_INDEX_STATISTICS_ROLL | 30 | 16039 | 讯兔行业指数，滚动收益率 |
| INDUSTRY_INDEX_STATISTICS_YEAR | 29 | 9183 | 讯兔行业指数年收益统计表  |
| INDUSTRY_REPORT_LIST | 13 | 76464 |  |
| JY_CT_SYSTEMCONST | 18 | 827860 | 聚源的系统常量表 |
| JY_JYDB_DELETEREC | 5 | 201825 | 聚源JYDB库的删除表 |
| JY_MF_FundArchives | 70 | 14065 | 公募基金主表 |
| JY_QT_DAILYQUOTE | 13 | 4314936 |  |
| JY_QT_INDEXQUOTE | 15 | 4664973 | 聚源指数行情表 |
| JY_QT_TRADINGDAYNEW | 10 | 3006 |  |
| JY_SECUMAIN | 20 | 393558 | 聚源证券主表 |
| LABEL_INFO | 22 | 9130 | 标签信息 |
| LANBAOSHU_CUSTOMER_CONFIG | 9 | 1 | 客户配置表 |
| LANBAOSHU_SYNC_RECORD | 7 | 0 | 蓝宝书同步记录表 |
| MDB_ENTITY_INDUSTRY | 21 | 0 | VIEW |
| MF_AssetAllocation | 12 | 960082 |  |
| MF_FUND_NAV | 25 | 3490405 | 公募基金净值表 |
| MF_FundType | 16 | 453 |  |
| MF_InvestTargetCriterion | 16 | 0 |  |
| MF_JYFundType | 15 | 19926 |  |
| MF_StockPortfolioDetail | 13 | 2598740 |  |
| MUTUAL_FUND_SECTOR | 24 | 372257 | 基金分类 |
| MUTUAL_FUND_SECTOR_DETAIL | 19 | 19377 | 实际使用到的基金标签，为了查询的时候更快出结果，单独做了一张表 |
| OS_INDEX_QUOTE | 13 | 1036677 | 境外指数行情(含香港)     |
| SECU_LABEL_INFO | 19 | 226695 | 股票标签信息 |
| SECU_LABEL_INFO_FREQUENCY | 19 | 3151584 | 股票标签信息。根据频率和SECU_LABEL_INFO表的开始结束时间，把数据拉成时间序列 |
| SECU_LABEL_MARKET_VALUE | 18 | 47654 | 股票标签对应的市值 |
| STK_COMPETE_HISTORY | 17 | 0 | 记录可比公司AH股的可比公司 |
| STK_TIMES_HOUR | 24 | 7306346 |  |
| STOCK_CHANGE_DETAIL_HY | 15 | 95776 | 股票变化明细， 包含清仓的股票（没有被市场上任何一个基金经理持有） |
| STOCK_CHANGE_DETAIL_Q | 15 | 18733 | 股票变化明细， 包含清仓的股票（没有被市场上任何一个基金经理持有） |
| STOCK_DAILY_QUOTE | 21 | 0 |  |
| STOCK_FACTOR_VALUE | 15 | 0 | VIEW |
| STOCK_HOLD_STATISTICS_HY | 41 | 154248 | 个股持有统计  |
| STOCK_HOLD_STATISTICS_Q | 43 | 168959 | 个股持有统计  |
| STOCK_MIN_HOLD | 12 | 5452 | 个股在  FUND_PORTFOLIO_DETAIL 中被主动型基金持有的最小日期  |
| STOCK_PERFORMANCE | 19 | 522319 | 股票行情表现（非日频） |
| STOCK_REPORT_LIST | 13 | 250246 | 聚合表，放基金报告期 |
| STOCK_STATISTICS_RANGE | 30 | 23860 | 股票，范围统计的表 日期不是索引列，YTD，QTD，WTD，只会保留最新一期的数据。 |
| STOCK_STATISTICS_ROLL | 29 | 48138 | 个股滚动收益率 注意，这个表日期不是主键，每个类型的滚动收益率只保留最新一期的 |
| SYWG_INDEX_QUOTE | 22 | 3392699 | 申万指数行情 |
| TMP_FUND_AND_COMPANY_MAPPING_DUPLICATE | 7 | 56 |  |
| TMP_FUND_AND_COMPANY_MAPPING_DUPLICATE_NULL | 6 | 205 |  |
| TMP_FUND_DETAIL_TYPE | 11 | 19046 |  |
| TMP_FUND_DETAIL_TYPE_20220606 | 8 | 19208 |  |
| TMP_FUND_INDEX_WEIGHT | 10 | 421414 |  |
| TMP_FUND_MANAGER_STATISTICS_YEAR | 14 | 31174 |  |
| TMP_FUND_MANAGER_STOCK_PORTFOLIO | 23 | 2642024 |  |
| TMP_JS_HOLD | 12 | 2219 |  |
| TMP_JS_SECU_INDUSTRY | 8 | 91533 |  |
| TMP_JS_YZP_WEIGHT | 9 | 756 |  |
| TMP_SECU_INDEX_INDUSTRY | 18 | 4781 |  |
| TMP_SECU_INDEX_WEIGHT | 8 | 351587 |  |
| TMP_STOCK1_REGRESSION_WEIGHT | 8 | 46536 |  |
| TMP_WEIGHT_DIFF | 17 | 6206 |  |
| USER_BEHAVIOR_STOCK_ORG_STATISTICS_SNAP | 24 | 539 | 用户行为数据滚动统计 最终结果表 |
| USER_BEHAVIOR_STOCK_ORG_STATISTICS_SNAP_SEQ | 26 | 121095 | 用户行为数据滚动统计 最终结果表，SNAP表只记录当天最新的一条，SNAP_SEQ表记录每天一个界面的值。 |
| USER_HIGH_FREQ_QUESTION_POOL | 20 | 0 | 高频用户个性化推荐问题池表 |
| USER_INTEREST_ENTITY | 33 | 2462595 | 用户实体兴趣表 股票，题材等。 |
| USER_INTEREST_ENTITY_REPORT | 16 | 13579 | 用户的兴趣报告 只存那个大模型返回的文本报告 |
| USER_INTEREST_ENTITY_REPORT_DETAIL | 21 | 495834 | 用户的兴趣报告-详情 |
| USER_QUESTION_POOL | 19 | 0 | 统一推荐问题池表 |
| VW_API_BROKER_OPINION | 17 | 0 | VIEW |
| VW_API_BROKER_OPINION_STOCK | 10 | 0 | VIEW |
| VW_API_BROKER_OPINION_STOCK1 | 10 | 0 | VIEW |
| VW_API_BROKER_OPINION_SUMMARY | 10 | 0 | VIEW |
| VW_API_INDUSTRY_CROWD_INDICATOR_SEQ | 23 | 0 | VIEW |
| VW_CROWD_INDICATOR_HOT_TRACK | 19 | 0 | VIEW |
| VW_ETF_HOLDING_DETAIL_USA | 6 | 0 | VIEW |
| VW_FUND_AND_MANAGER_MAPPING_ALL | 2 | 0 | VIEW |
| VW_FUND_INDUSTRY_HOLDING_MV_DETAIL_HY | 25 | 0 | VIEW |
| VW_FUND_INDUSTRY_HOLDING_MV_DETAIL_Q | 25 | 0 | VIEW |
| VW_FUND_LABEL_SERIES | 13 | 0 | VIEW |
| VW_FUND_LABEL_SERIES_PAIPAI | 13 | 0 | VIEW |
| VW_FUND_MANAGER_INDUSTRY_CHANGE_HY | 28 | 0 | VIEW |
| VW_FUND_MANAGER_INDUSTRY_CHANGE_Q | 28 | 0 | VIEW |
| VW_FUND_QUARTER_YIELD | 16 | 0 | VIEW |
| VW_INDEX_ALL | 5 | 0 | VIEW |
| VW_INDEX_STATISTICS_ROLL | 10 | 0 | VIEW |
| VW_INDUSTRY_CROWD_INDICATOR | 19 | 0 | VIEW |
| VW_INDUSTRY_CROWD_INDICATOR_SEQ | 25 | 0 | VIEW |
| VW_SAME_COMPANY | 8 | 0 | VIEW |
| VW_SAME_COMPANY_US | 3 | 0 | VIEW |
| VW_SECU_INDUSTRY_123 | 9 | 0 | VIEW |
| VW_STOCK_HOLDING_MARKET_VALUE_SNAP_Q | 9 | 0 | VIEW |
| VW_STOCK_HOLDING_NEGOTIABLE_RATIO_Q | 5 | 0 | VIEW |
| VW_STOCK_LABEL | 15 | 0 | VIEW |
| VW_STOCK_LABEL_FREQUENCY | 13 | 0 | VIEW |
| VW_XT_INDEX_ALL | 4 | 0 | VIEW |
| VW_XT_INDUSTRY_DAILY_QUOTE | 5 | 0 | VIEW |
| sys_user | 31 | 15219 | 用户信息 |
| tmp_STOCK_HOLD_STATISTICS_Q | 39 | 2169 |  |
| tmp_change_invest | 23 | 12381 |  |
| tmp_fund_manager_data | 5 | 17268 |  |
| tmp_hy_asset | 7 | 72965 |  |
| tmp_js_trade_seq | 8 | 1218 |  |
