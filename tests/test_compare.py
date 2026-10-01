import math

import duckdb

from harness.compare import diff_tables, exceeds, rel_diff


def test_rel_diff_basics():
    assert rel_diff(100, 100) == 0
    assert math.isclose(rel_diff(101, 100), 0.01)
    assert rel_diff(None, None) == 0
    assert math.isinf(rel_diff(None, 5))
    assert math.isinf(rel_diff(5, None))
    assert math.isinf(rel_diff(1, 0))
    assert rel_diff(1e-9, 0) == 0  # below abs floor


def test_tolerance_boundaries():
    assert not exceeds(100.5, 100, 0.005)      # exactly at +0.5% is within
    assert exceeds(100.51, 100, 0.005)
    assert not exceeds(99.0, 100, 0.01)
    assert exceeds(98.9, 100, 0.01)


def test_rel_diff_handles_decimals():
    from decimal import Decimal
    assert math.isclose(rel_diff(Decimal("10.10"), 10.0), 0.01)


def test_diff_tables_detects_value_row_and_key_differences():
    c = duckdb.connect()
    c.execute("create table a as select * from (values (1,'x',10.0),(2,'y',20.0)) t(k,s,v)")
    c.execute("create table same as select * from a")
    c.execute("create table val as select * from (values (1,'x',10.0),(2,'y',20.5)) t(k,s,v)")
    c.execute("create table extra as select * from (values (1,'x',10.0),(2,'y',20.0),(3,'z',1.0)) t(k,s,v)")
    c.execute("create table dup as select * from (values (1,'x',10.0),(2,'y',10.0),(2,'y',10.0)) t(k,s,v)")
    assert diff_tables(c, "a", "same", ["k"]).identical
    d = diff_tables(c, "val", "a", ["k"])
    assert d.columns_differing == {"v": 1} and math.isclose(d.max_rel_diff["v"], 0.025)
    assert diff_tables(c, "extra", "a", ["k"]).rows_only_left == 1
    d = diff_tables(c, "dup", "a", ["k"])
    assert d.duplicate_keys_left == 1 and d.columns_differing == {}  # collapsed dupes sum to the same total
