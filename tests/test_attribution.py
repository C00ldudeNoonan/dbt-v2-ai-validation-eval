import pyarrow as pa
import pytest

from harness.engines import DbtResult, NodeResult, Workspace
from harness.layers.recon_common import ReconQuery, Sandbox, run_queries
from harness.layers.reconcile_ai import parse_queries
from harness.layers.reconcile_manual import manual_queries
from harness.layers.structural import classify_build

REF = pa.table({"m": ["2025-01-01", "2025-02-01"], "loc": ["a", "b"], "rev": [100.0, 200.0]})
GOLDEN = REF
FAULTED = pa.table({"m": ["2025-01-01", "2025-02-01"], "loc": ["a", "b"], "rev": [100.0, 230.0]})
TOTAL = ReconQuery("total", "select 'total' slice, (select sum(rev) from model_output) model_value, "
                   "(select sum(rev) from reference_output) reference_value", "ai")
BY_LOC = ReconQuery("by_loc", "select coalesce(m.loc, r.loc) slice, m.rev model_value, r.rev reference_value "
                    "from model_output m full outer join reference_output r on m.loc = r.loc", "ai")
BROKEN = ReconQuery("broken", "select nope from model_output", "ai")


def test_flag_caused_by_fault_is_attributable():
    res = {r.query.query_id: r for r in run_queries([TOTAL, BY_LOC, BROKEN], FAULTED, REF, GOLDEN)}
    assert res["total"].flagged and res["total"].attributable
    assert res["by_loc"].flagged and res["by_loc"].n_flagged_rows == 1 and res["by_loc"].worst_slice == "b"
    assert not res["broken"].executed and not res["broken"].flagged


def test_flag_present_on_golden_too_is_not_attributable():
    # The reference disagrees with golden (e.g. a pre-existing discrepancy or a bad query):
    ref_off = pa.table({"m": ["2025-01-01", "2025-02-01"], "loc": ["a", "b"], "rev": [100.0, 300.0]})
    (r,) = run_queries([BY_LOC], FAULTED, ref_off, GOLDEN)
    assert r.flagged and r.counterfactual_flagged and r.attributable is False


def test_shared_definition_bug_is_not_flagged():
    # Reference shares the model's bug, so nothing flags even though golden differs.
    (r,) = run_queries([TOTAL], FAULTED, FAULTED, GOLDEN)
    assert not r.flagged


def test_total_vs_slice_tolerance():
    small = pa.table({"m": ["x", "y"], "loc": ["a", "b"], "rev": [100.4, 200.0]})  # +0.4% on a, +0.13% total
    res = {r.query.query_id: r for r in run_queries([TOTAL, BY_LOC], small, REF, GOLDEN)}
    assert not res["total"].flagged and not res["by_loc"].flagged
    small = pa.table({"m": ["x", "y"], "loc": ["a", "b"], "rev": [101.5, 200.0]})  # +1.5% on a, +0.5% total
    res = {r.query.query_id: r for r in run_queries([TOTAL, BY_LOC], small, REF, GOLDEN)}
    assert not res["total"].flagged and res["by_loc"].flagged


def test_missing_slice_flags():
    fewer = pa.table({"m": ["2025-01-01"], "loc": ["a"], "rev": [100.0]})
    (r,) = run_queries([BY_LOC], fewer, REF, GOLDEN)
    assert r.flagged and r.worst_slice == "b"


def test_sandbox_rejects_readers_and_hides_other_tables():
    with pytest.raises(TypeError):
        Sandbox(pa.RecordBatchReader.from_batches(REF.schema, REF.to_batches()), REF)
    sb = Sandbox(REF, REF)
    with pytest.raises(Exception):
        sb.run("select 1 as slice, 1 as model_value, 1 as reference_value from raw.raw_orders")
    sb.close()


def test_manual_queries_are_two_totals():
    qs = manual_queries("monthly_revenue_by_location")
    assert [q.query_id for q in qs] == ["manual_grand_total", "manual_latest_period_total"]
    assert all(q.kind == "total" for q in qs)


def test_parse_queries_handles_fences_and_caps():
    text = '```json\n{"queries": [' + ",".join(
        f'{{"id": "q", "sql": "select 1", "dimensions": ["d{i}"]}}' for i in range(50)) + "]}\n```"
    qs = parse_queries(text, 40)
    assert len(qs) == 40 and len({q.query_id for q in qs}) == 40


def _ws(tmp_path):
    ws = Workspace(tmp_path)
    (ws.project / "target").mkdir(parents=True)
    return ws


def test_classify_gate_failure_is_pre_execution(tmp_path):
    res = DbtResult("v2", ["compile"], 1, "[error] No column x\n  --> models/marts/metrics/t1.sql:3:4", 0.1,
                    [NodeResult("model.jaffle_shop.t1", "error", "No column x", "model", "")])
    o = classify_build(_ws(tmp_path), res, "t1", gate=True)
    assert o.caught and o.layer == "L1" and o.before_execution and o.attributable and o.queries_before_catch == 0


def test_classify_runtime_model_error_is_L1_and_test_fail_is_L2(tmp_path):
    ws = _ws(tmp_path)
    nodes = [NodeResult("model.jaffle_shop.stg", "success", "", "model", "1"),
             NodeResult("model.jaffle_shop.t1", "error", "Binder Error", "model", "2")]
    o = classify_build(ws, DbtResult("v1", ["build"], 1, "", 1, nodes), "t1", gate=False)
    assert o.layer == "L1" and not o.before_execution and o.queries_before_catch == 2 and o.attributable
    nodes = [NodeResult("model.jaffle_shop.t1", "success", "", "model", "1"),
             NodeResult("test.jaffle_shop.unique_t1_k.abc", "fail", "Got 3 results", "test", "2")]
    o = classify_build(ws, DbtResult("v1", ["build"], 1, "", 1, nodes), "t1", gate=False)
    assert o.layer == "L2" and o.attributable
    nodes = [NodeResult("unit_test.jaffle_shop.t1.ut", "error", "Binder Error", "unit_test", "1")]
    o = classify_build(ws, DbtResult("v1", ["build"], 1, "", 1, nodes), "t1", gate=False)
    assert o.layer == "L1"


def test_failure_in_other_model_is_not_attributable(tmp_path):
    nodes = [NodeResult("model.jaffle_shop.other", "error", "boom", "model", "1")]
    o = classify_build(_ws(tmp_path), DbtResult("v1", ["build"], 1, "", 1, nodes), "t1", gate=False)
    assert o.caught and not o.attributable


def test_non_numeric_values_are_a_query_error_not_a_crash():
    q = ReconQuery("dates", "select 'x' slice, '2024-09-01' model_value, '2024-09-01' reference_value", "ai")
    (r,) = run_queries([q], REF, REF, GOLDEN)
    assert not r.executed and not r.flagged and "ValueError" in r.error
