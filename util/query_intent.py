"""Deterministic intent checks used to constrain metadata-driven routing."""

FORECAST_INTENT_TERMS = (
    "预期",
    "预测",
    "预计",
    "业绩预告",
    "一致预期",
    "盈利预测",
    "未来业绩",
    "forecast",
)

FORECAST_DOMAIN_MARKERS = ("业绩预告", "预测", "预期")
FORECAST_TABLE_MARKERS = ("FORECAST", "FCST")
MARKET_PRICE_INTENT_TERMS = (
    "收盘",
    "开盘",
    "最高价",
    "最低价",
    "最新价",
    "股价",
    "行情",
    "涨跌",
    "成交",
    "换手",
)


def has_explicit_forecast_intent(query: str) -> bool:
    normalized = (query or "").lower()
    return any(term.lower() in normalized for term in FORECAST_INTENT_TERMS)


def is_forecast_domain(domain_name: str) -> bool:
    return any(marker in (domain_name or "") for marker in FORECAST_DOMAIN_MARKERS)


def is_forecast_table(table_name: str) -> bool:
    normalized = (table_name or "").upper()
    return any(marker in normalized for marker in FORECAST_TABLE_MARKERS)


def has_market_price_intent(query: str) -> bool:
    return any(term in (query or "") for term in MARKET_PRICE_INTENT_TERMS)
