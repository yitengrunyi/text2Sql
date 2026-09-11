from evals.aggregate import load_physical_schemas, sql_identifier_audit


SCHEMAS = load_physical_schemas()


def test_identifier_audit_accepts_existing_table_and_column():
    result = sql_identifier_audit("SELECT TCLOSE FROM STK_MKT", "MYSQL-2", SCHEMAS)

    assert result["bad_tables"] == set()
    assert result["bad_columns"] == set()


def test_identifier_audit_reports_missing_table_and_column():
    result = sql_identifier_audit("SELECT FAKE_COL FROM FAKE_TABLE", "MYSQL-2", SCHEMAS)

    assert result["bad_tables"] == {"FAKE_TABLE"}
    assert result["bad_columns"] == {"FAKE_COL"}


def test_identifier_audit_accepts_cte_output_columns():
    sql = """
    WITH ranked AS (
      SELECT TCLOSE, ROW_NUMBER() OVER (ORDER BY TRADEDATE) AS rn
      FROM STK_MKT
    )
    SELECT r.TCLOSE FROM ranked r WHERE r.rn = 1
    """

    result = sql_identifier_audit(sql, "MYSQL-2", SCHEMAS)

    assert result["bad_tables"] == set()
    assert result["bad_columns"] == set()
