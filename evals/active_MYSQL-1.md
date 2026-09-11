# MYSQL-1: 67 active tables

| db | table | cname | desc |
|---|---|---|---|
| FUND_PUBLIC | CT_TRACK_DEFINE | 赛道和申万一级行业映射关系 | )[:80] |
| FUND_INFO | ETF_DAILY_QUOTE | ETF行情表 | 本表格是ETF基金的收盘行情，包括开盘价，收盘价，最高价，最低价，成交量，成交额等行情信息。)[:80] |
| FUND_INFO | ETF_INFO_DETAIL | ETF信息 | 自动发现，待补充语义。ETF信息)[:80] |
| FUND_INFO | ETF_LABEL_INFO_CHINA | A股ETF标签信息表 | 记录中国市场上市交易的ETF的标签信息)[:80] |
| FUND_INFO | ETF_LABEL_INFO_USA | 美股ETF标签信息表 | 记录美国市场上市交易的ETF的标签信息)[:80] |
| FUND_INFO | ETF_PERFORMANCE_DETAIL | ETF表现 | 自动发现，待补充语义。ETF表现)[:80] |
| FUND_INFO | ETF_SHARES_CHANGE_ROLL | ETF基金份额变动表 | ETF基金日频的份额变动，以及资金净流入情况)[:80] |
| FUND_INFO | FUND_AND_COMPANY_MAPPING | 基金产品和基金公司的对应关系 | 记录基金所属基金公司)[:80] |
| FUND_INFO | FUND_AND_MANAGER_MAPPING | 基金产品和基金经理的对应关系 | 记录基金由哪个基金经理管理)[:80] |
| FUND_INFO | FUND_ASSET_ALLOCATION | 基金产品对应的基金规模情况 | )[:80] |
| FUND_INFO | FUND_BENCHMARK | 基金基本信息表 | 该表主要存储基金的各类基础信息（包括代码、名称、成立日期、运作方式、投资类型等）、详细的业绩比较基准与投资目标文本、相关费用（管理费、托管费等），并包含了主动管理基金及ETF跟踪指数的标准化数据。)[:80] |
| FUND_PUBLIC | FUND_BENCHMARK | 基金业绩基准表 | 基金业绩基准表记录基金和指数相关的信息，包括主动型和ETF基金跟踪的指数，当需要寻找某一类指数时，使用该表，得到的指数都有基金跟踪，属于比较常用的指数。)[:80] |
| FUND_INFO | FUND_COMPANY_ASSET_ALLOCATION | 基金公司持有主动型基金规模情况 | )[:80] |
| FUND_INFO | FUND_COMPANY_INDUSTRY_HOLDING_MV_DETAIL_HY | 基金公司持有行业市值具体情况(半年报、年报) | )[:80] |
| FUND_INFO | FUND_COMPANY_INDUSTRY_HOLDING_MV_DETAIL_Q | 基金公司持有行业市值具体情况(季报) | )[:80] |
| FUND_INFO | FUND_FRONT_CONTROL | 基金产品最新报告期 | 记录最新报告期，所有涉及基金持仓、基金经理持仓、基金公司持仓的表，没有相关日期说明，默认取最新报告期的值，从FUND_FRONT_CONTROL获取。)[:80] |
| FUND_INFO | FUND_INDUSTRY_ASSET_RATIO_ALL | 基金申万行业回归权重表 | 存基金与31个申万一级行业的回归权重)[:80] |
| FUND_INFO | FUND_INDUSTRY_CHANGE_HY | 基金产品对应的行业和题材持仓变化情况(半年报、年报) | )[:80] |
| FUND_INFO | FUND_INDUSTRY_CHANGE_Q | 基金产品对应的行业和题材持仓变化情况(季报) | )[:80] |
| FUND_INFO | FUND_INDUSTRY_HOLDING_MV_DETAIL_HY | 基金产品持有行业和题材市值具体情况(半年报、年报) | )[:80] |
| FUND_INFO | FUND_INDUSTRY_HOLDING_MV_DETAIL_QDII | QDII基金产品持有行业市值具体情况（QDII的不分季度还是年度） | )[:80] |
| FUND_INFO | FUND_INDUSTRY_HOLDING_MV_HY | 基金产品持有行业和题材市值情况(半年报、年报) | )[:80] |
| FUND_INFO | FUND_INDUSTRY_HOLDING_MV_Q | 基金产品持有行业和题材市值情况(季报) | )[:80] |
| FUND_INFO | FUND_LABEL_INFO | 基金、基金经理标签信息表 | )[:80] |
| FUND_INFO | FUND_LABEL_VALUE_SECTION | 基金标签值表(截面) | )[:80] |
| FUND_INFO | FUND_LABEL_VALUE_SERIES | 基金标签值表(时间序列) | )[:80] |
| FUND_INFO | FUND_LIST_FREQUENCY | 基金列表，用来计算的主动型基金，每个报告期统计一次 | )[:80] |
| FUND_INFO | FUND_MANAGER_ASSET_ALLOCATION | 基金经理持有主动型基金规模情况 | )[:80] |
| FUND_INFO | FUND_MANAGER_INDUSTRY_HOLDING_MV_HY | 基金经理行业和题材持仓(半年报、年报) | 收录基金经理持有行业、题材的情况，表中为半年报、年报全持仓信息，即每个半年末最后一天的数据，包括：持股市值、持仓占比、超配低配等信息)[:80] |
| FUND_INFO | FUND_MANAGER_INDUSTRY_HOLDING_MV_Q | 基金经理行业和题材持仓_季报 | 收录基金经理持有行业、题材的情况，表中为季报重仓信息，即每个季度末最后一天的数据，包括：持股市值、持仓占比、超配低配等信息)[:80] |
| FUND_INFO | FUND_MANAGER_INFO | 基金经理基本信息表 | 收录基金经理的基本情况，包括：从业机构、性别、出生年份、最高学历、管理年限、管理基金数量、换手率、管理规模等)[:80] |
| FUND_INFO | FUND_MANAGER_NET_VALUE | 基金经理净值表 | 将基金经理管理的权益类产品净值，根据规模加权计算为一根表征基金经理整体业绩表现的虚拟净值曲线。)[:80] |
| FUND_INFO | FUND_MANAGER_OPINION | 基金经理观点 | 对基金经理定期报告中观点的总结)[:80] |
| FUND_INFO | FUND_MANAGER_STATISTICS_YEAR | 基金经理净值年统计表 | 当查询基金经理个人的收益表现时，参照此表中的内容。表中存的是表征基金经理权益产品综合收益净值曲线的分年度统计的结果，包含最大回撤，夏普比，波动率，胜率，标准差，下行标准差等统计指标。)[:80] |
| FUND_INFO | FUND_MANAGER_STOCK_CHANGE_HY | 基金经理股票持仓变化情况(半年报、年报) | )[:80] |
| FUND_INFO | FUND_MANAGER_STOCK_CHANGE_Q | 基金经理股票持仓变化情况(季报) | )[:80] |
| FUND_INFO | FUND_MANAGER_STOCK_PORTFOLIO_HY | 半年报、年报基金经理持仓明细 | )[:80] |
| FUND_INFO | FUND_MANAGER_STOCK_PORTFOLIO_Q | 季报基金经理持仓明细 | )[:80] |
| FUND_INFO | FUND_MANAGER_TOP10_STOCK_CHANGE_HY | 基金经理前10大股票变化情况(半年报、年报) | )[:80] |
| FUND_INFO | FUND_MANAGER_TOP10_STOCK_CHANGE_Q | 基金经理前10大股票变化情况(季报) | )[:80] |
| FUND_INFO | FUND_MANAGER_TRACK_HOLDING | 基金经理持有赛道市值情况 | )[:80] |
| FUND_INFO | FUND_MANAGER_TURNOVER_RATE | 基金经理换手率 | )[:80] |
| FUND_INFO | FUND_NETVALUE | 基金净值表 | )[:80] |
| FUND_INFO | FUND_NETVALUE_SIMULATE | 基金模拟收益率表 | 用拟合的全持仓计算的基金模拟收益率)[:80] |
| FUND_INFO | FUND_PORTFOLIO_DETAIL | 基金产品的持股明细 | 包含基金季报、半年报、年报披露的持仓信息以及上市公司季报披露的十大股东信息)[:80] |
| FUND_INFO | FUND_PORTFOLIO_DETAIL_QDII | QDII基金产品的持股明细 | )[:80] |
| FUND_INFO | FUND_SHARES_CHANGE | 基金份额变动 | 记录基金份额相关数据，交易所上市基金（如ETF、LOF）日更新，其他基金季更新)[:80] |
| FUND_INFO | FUND_STATISTICS_YEAR | 基金产品超额收益统计表(年统计）
计算每年（12个月），基金与指数超额的胜率与盈亏比，超额等值 | 自动发现，待补充语义。基金产品超额收益统计表(年统计）
计算每年（12个月），基金与指数超额的胜率与盈亏比，超额等值)[:80] |
| FUND_INFO | FUND_STOCK_CHANGE_HY | 基金产品的股票持仓(半年报、年报) | 收录基金持有股票情况，表中为半年报、年报全持仓信息，即每个半年末最后一天的数据，包括：持股数量、持股市值、占基金持有净资产比例、增减持标签等)[:80] |
| FUND_INFO | FUND_STOCK_CHANGE_Q | 基金产品的股票持仓(季报) | 收录基金持有股票情况，表中为季报重仓信息，即每个季度末最后一天的数据，包括：持股数量、持股市值、占基金持有净资产比例、增减持标签等)[:80] |
| FUND_INFO | FUND_TOP10_STOCK_CHANGE_HY | 基金前10大股票变化情况(半年报、年报) | )[:80] |
| FUND_INFO | FUND_TOP10_STOCK_CHANGE_Q | 基金前10大股票变化情况(季报) | )[:80] |
| FUND_INFO | FUND_TRACK_HOLDING | 基金持有赛道市值情况 | )[:80] |
| FUND_INFO | FUND_TURNOVER_RATE | 基金换手率 | )[:80] |
| FUND_INFO | INDEX_QUOTE_ALL | 指数行情表 | 表格INDEX_QUOTE_ALL-指数行情表: 表格“INDEX_QUOTE_ALL”是一个用于记录指数行情的详细数据表。该表格包含多个字段，涵盖了指数在交易日的各类重要信息。具体字段包括：

- **ID**：自增列，用于唯一标识每条记录。
- **交易日**：记录数据对应的交易日期。
- **指数代码**和**指数简称**：分别记录指数的代码和简称。
- **收盘价**、**最高价**、**最低价**：记录指数在交易日内的收盘价、最高价和最低价。
- **涨跌幅**：记录指数的涨跌幅度。
- **成交量**和**成交额**：记录指数的成交量和成交金额。
- **指数类型**：标识指数类型，1表示普通指数，2表示利率指数。
- **是否QA**、**是否人工修改**、**是否有效**：分别标识数据是否经过质量保证、是否被人工修改以及数据是否有效。
- **数据插入时间**和**数据修改时间**：记录数据的插入和最后修改时间。
- **指数市盈率（PE）**、**指数市净率（PB）**、**指数股息率**：记录指数的市盈率、市净率和股息率。
- **总市值**和**流通市值**：记录指数的总市值和流通市值。

该表格通过详细记录这些字段的数据，提供了全面的指数行情信息，便于分析和研究指数的市场表现。)[:80] |
| FUND_INFO | INDEX_STATISTICS_YEAR | 指数收益年统计表 | 收录指数在每个自然年的年收益率，最大回撤等绩效指标)[:80] |
| FUND_INFO | LABEL_INFO | 标签信息表 | 包含申万行业、题材等标签)[:80] |
| FUND_INFO | MUTUAL_FUND_SECTOR | 基金分类表(Wind) | Wind的基金分类信息表)[:80] |
| FUND_INFO | SECU_LABEL_INFO | 股票标签信息表 | 记录股票所属标签信息)[:80] |
| FUND_INFO | STOCK_FACTOR_VALUE | VIEW | 自动发现，待补充语义。VIEW)[:80] |
| FUND_PUBLIC | STOCK_FACTOR_VALUE | 股票因子表 | 当查询与基金有关的个股因子时，参照此表中的内容。
表中不同FACTOR_ID代表不同的股票因子，映射关系如下：
FACTOR_ID：
52，PB（市净率）
53，PB_TTM（市盈率）
61，PSTTM（市现率）
26，自由流通股本
37，总股本)[:80] |
| FUND_INFO | STOCK_HOLD_STATISTICS_HY | 基金持有个股情况统计(半年报、年报) | 统计股票被所有主动型基金持有情况)[:80] |
| FUND_INFO | STOCK_HOLD_STATISTICS_Q | 基金持有个股情况统计(季报) | 统计股票被所有主动型基金持有情况)[:80] |
| FUND_INFO | VW_FUND_INDUSTRY_HOLDING_MV_DETAIL_Q | 基金产品持有行业和题材市值具体情况(季报) | 表格VW_FUND_INDUSTRY_HOLDING_MV_DETAIL_Q -基金产品持有行业和题材市值具体情况(季报): 表格“基金持有行业和题材市值具体情况(季报)”（VW_FUND_INDUSTRY_HOLDING_MV_DETAIL_Q）用于记录和分析基金在不同报告期内持有的行业和题材的市值情况。该表格包含多个字段，详细记录了基金的基本信息、标签信息、持股市值及其变动情况、占净资产比例、备注信息以及数据的历史记录和有效性。

具体字段包括：自增列（ID）、基金内部代码（FUND_HCODE）、基金代码（FUND_SYMBOL）、基金简称（FUND_NAME）、标签类型（LABEL_TYPE）、标签代码（LABEL_CODE）、标签名称（LABEL_NAME）、标签对应指数标准代码（INDEX_HCODE）、标签对应指数代码（INDEX_CODE）、报告期（REPORT_DATE）、持股市值（MARKET_VALUE）、持股市值变动（MARKET_VALUE_CHANGE）、持股市值变动比例（MARKET_VALUE_CHANGE_RATIO）、占基金经理持有净资产比例（RATIO_IN_NV）、备注（REMARK）、是否QA（HISQA）、是否人工修改（HISMAN）、是否有效（HISVALID）、数据插入时间（HCREATETIME）和数据修改时间（HUPDATETIME）。

通过这些字段，用户可以详细了解基金在不同时间点持有的行业和题材的市值变化情况，以及这些变化对基金净资产的影响，从而为投资决策提供数据支持。)[:80] |
| FUND_INFO | VW_FUND_LABEL_SERIES | 基金产品及基金经理标签表（风格，赛道，大小盘等） | **表格“基金产品及基金经理标签表（风格，赛道，大小盘等）”（VW_FUND_LABEL_SERIES）**用于记录和分析公募基金产品及基金经理在06月30日、12月31日两大持仓报告期的多维标签信息。表格涵盖大中小盘、价值/成长以及赛道（金融、周期、制造、科技、医药等），便于快速筛选和风格分析。

主要字段包括：
1）ID（自增列）
2）END_DATE（报告期日期）
3）PSN_NAME/PSN_HCODE（基金经理姓名及内码）
4）FUND_SYMBOL/FUND_NAME/FUND_HCODE（基金代码、名称及内码）
5）LABEL_NAME/LABEL_SUB_NAME（标签大类与小类，如规模标签、单/双赛道细分等）
6）LABEL_VALUE_NAME（标签具体值，如“大盘”“价值”“科技”等）

查询示例：筛选科技赛道时可用 LABEL_NAME='单/双赛道细分' AND LABEL_VALUE_NAME LIKE '%科技%'；如问价值/成长偏好可用 LABEL_VALUE_NAME IN ('价值','成长','平衡')；如问大中小盘可用 LABEL_VALUE_NAME IN ('大盘','中盘','小盘')。通过该表可快速定位基金产品或基金经理的风格变动与赛道偏好，支持多维度投研分析与决策。)[:80] |
| FUND_INFO | VW_FUND_MANAGER_INDUSTRY_CHANGE_HY | 基金经理行业持仓变化情况(半年报、年报) | )[:80] |
| FUND_INFO | VW_FUND_MANAGER_INDUSTRY_CHANGE_Q | 基金经理行业持仓变化情况(季报) | )[:80] |
