from test_gold_eval import extract_number_candidates, judge, numeric_hit


def test_dates_and_times_are_not_numeric_candidates():
    values = extract_number_candidates("2026-01-05 00:00:00 收盘 57.29")

    assert values == [57.29]


def test_zero_does_not_match_a_scaled_nonzero_value():
    assert not numeric_hit("2026-01-05 00:00:00 57.29", "-17.58")


def test_yuan_to_hundred_million_conversion_still_matches():
    assert numeric_hit("市值 722.01 亿元", "72201282000")


def test_million_dollars_to_hundred_million_conversion_still_matches():
    assert numeric_hit("营业收入 5393.14 亿美元", "539314")


def test_original_unit_keeps_two_decimal_rounding_tolerance():
    assert numeric_hit("涨跌幅 0.42%", "0.417")


def test_numeric_value_must_be_on_the_entity_row():
    gold = {"judge": "numeric", "gold_value": "4.01", "gold_entities": ["中国神华"]}
    answer = "荣晟环保 4.01\n中国神华 2.14"

    assert judge(gold, answer, False)[0] is False


def test_entity_question_requires_its_gold_date():
    gold = {
        "judge": "entity",
        "gold_entities": ["中国神华"],
        "gold_date": "2026-07-13",
    }

    assert judge(gold, "中国神华 2026-10-23", False)[0] is False


def test_excessive_result_rows_fail_execution_judgement():
    gold = {"judge": "numeric", "gold_value": "1.1483", "gold_entities": ["目标基金"]}

    ok, reasons = judge(
        gold,
        "目标基金 1.1483",
        False,
        row_count=1000,
        gold_row_count=1,
    )

    assert ok is False
    assert reasons == ["结果范围过大(1000行, Gold为1行)"]


def test_list_question_with_count_requires_both_entities_and_count():
    gold = {"judge": "list", "gold_entities": ["单宽之", "董瑾"], "gold_value": "21"}

    assert judge(gold, "单宽之、董瑾，均为21只", False)[0] is True
    assert judge(gold, "单宽之、董瑾", False)[0] is False
