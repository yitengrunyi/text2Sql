from util.query_intent import (
    has_explicit_forecast_intent,
    has_market_price_intent,
    is_forecast_domain,
    is_forecast_table,
)


def test_year_alone_is_not_forecast_intent():
    assert not has_explicit_forecast_intent("贵州茅台2025年归母净利润是多少")


def test_explicit_forecast_terms_are_detected():
    assert has_explicit_forecast_intent("贵州茅台2025年预期归母净利润是多少")
    assert has_explicit_forecast_intent("贵州茅台业绩预告")


def test_forecast_domain_and_table_are_detected():
    assert is_forecast_domain("主板业绩预告")
    assert is_forecast_table("VIEW_STK_CONSENSUS_FORECAST")
    assert is_forecast_table("CON_FCST_STK_FIN")
    assert not is_forecast_table("VIEW_STK_FIN_IDX")


def test_market_price_intent_is_detected():
    assert has_market_price_intent("美股苹果AAPL最新收盘价是多少")
    assert not has_market_price_intent("苹果公司最新净利润是多少")
