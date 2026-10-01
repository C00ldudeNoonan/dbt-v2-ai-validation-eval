"""Shared L3 machinery: sandboxed execution, tolerance flagging, counterfactual attribution.

Every reconciliation query (manual or AI) runs in an in-memory DuckDB containing
exactly two tables, `model_output` and `reference_output`, and must return the
columns (slice, model_value, reference_value). A query with one result row is held
to the total tolerance; a query with several rows is held to the slice tolerance.

Attribution: a flag on a fault variant counts only if the same query, re-run with
`model_output` swapped for the golden output (same reference), does NOT flag. So the
flag is caused by the seeded fault and not by a query bug or pre-existing discrepancy.
"""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field

import duckdb
import pyarrow as pa

from harness.common import eval_config
from harness.compare import rel_diff

QUERY_TIMEOUT_S = 60
MAX_RESULT_ROWS = 5000


@dataclass
class ReconQuery:
    query_id: str
    sql: str
    source: str                  # manual | ai
    kind: str = ""               # total | dimension | time_grain | edge | other
    measure: str = ""
    dimensions: list[str] = field(default_factory=list)
    time_grain: str = ""
    description: str = ""


@dataclass
class QueryResult:
    query: ReconQuery
    executed: bool = False
    error: str = ""
    n_rows: int = 0
    n_flagged_rows: int = 0
    max_rel_diff: float = 0.0
    worst_slice: str = ""
    tolerance: float = 0.0
    exec_s: float = 0.0
    counterfactual_flagged: bool | None = None
    attributable: bool | None = None

    @property
    def flagged(self) -> bool:
        return self.n_flagged_rows > 0


class Sandbox:
    """In-memory DuckDB with only model_output and reference_output."""

    def __init__(self, model: pa.Table, reference: pa.Table):
        if not isinstance(model, pa.Table) or not isinstance(reference, pa.Table):
            raise TypeError("Sandbox needs materialized pyarrow Tables (a RecordBatchReader is single-use)")
        if reference.num_rows == 0:
            raise ValueError("reference_output is empty; refusing to reconcile against nothing")
        self.con = duckdb.connect(":memory:")
        self.con.register("_m", model)
        self.con.register("_r", reference)
        self.con.execute("create table model_output as select * from _m")
        self.con.execute("create table reference_output as select * from _r")
        self.con.unregister("_m")
        self.con.unregister("_r")
        self.con.execute("set enable_external_access = false")
        self.con.execute("set lock_configuration = true")

    def run(self, sql: str) -> list[tuple]:
        timer = threading.Timer(QUERY_TIMEOUT_S, self.con.interrupt)
        timer.start()
        try:
            cur = self.con.execute(sql)
            names = [d[0].lower() for d in cur.description or []]
            rows = cur.fetchmany(MAX_RESULT_ROWS + 1)
        finally:
            timer.cancel()
        if len(rows) > MAX_RESULT_ROWS:
            raise ValueError(f"query returned more than {MAX_RESULT_ROWS} rows")
        try:
            i_s, i_m, i_r = names.index("slice"), names.index("model_value"), names.index("reference_value")
        except ValueError:
            raise ValueError(f"query must return columns slice, model_value, reference_value; got {names}")
        return [(r[i_s], r[i_m], r[i_r]) for r in rows]

    def close(self) -> None:
        self.con.close()


def evaluate(sandbox: Sandbox, q: ReconQuery) -> QueryResult:
    tol = eval_config()["tolerances"]
    res = QueryResult(q)
    start = time.monotonic()
    try:
        rows = sandbox.run(q.sql)
        res.executed = True
        diffs = [rel_diff(m, r, tol["abs_floor"]) for _, m, r in rows]
    except Exception as e:  # noqa: BLE001 - SQL failures / non-numeric values are logged, never a flag
        res.executed = False
        res.error = f"{type(e).__name__}: {e}"[:500]
        res.exec_s = time.monotonic() - start
        return res
    res.exec_s = time.monotonic() - start
    res.n_rows = len(rows)
    res.tolerance = tol["total_rel"] if len(rows) <= 1 else tol["slice_rel"]
    for (slice_, m, r), d in zip(rows, diffs):
        if d > res.tolerance:
            res.n_flagged_rows += 1
        if d > res.max_rel_diff or (res.worst_slice == "" and d > 0):
            res.max_rel_diff = d
            res.worst_slice = str(slice_)[:200]
    return res


def flags_on(sandbox: Sandbox, sql: str) -> bool:
    tol = eval_config()["tolerances"]
    rows = sandbox.run(sql)
    t = tol["total_rel"] if len(rows) <= 1 else tol["slice_rel"]
    return any(rel_diff(m, r, tol["abs_floor"]) > t for _, m, r in rows)


def run_queries(
    queries: list[ReconQuery],
    model: pa.Table,
    reference: pa.Table,
    golden: pa.Table | None,
) -> list[QueryResult]:
    """Run all queries; for flagged ones, run the golden counterfactual."""
    sb = Sandbox(model, reference)
    cf = Sandbox(golden, reference) if golden is not None else None
    results = []
    try:
        for q in queries:
            r = evaluate(sb, q)
            if r.flagged and cf is not None:
                try:
                    r.counterfactual_flagged = flags_on(cf, q.sql)
                except Exception:  # noqa: BLE001
                    r.counterfactual_flagged = None
                r.attributable = r.counterfactual_flagged is False
            results.append(r)
    finally:
        sb.close()
        if cf is not None:
            cf.close()
    return results


def finite(x: float) -> float | None:
    return None if x is None or math.isinf(x) or math.isnan(x) else x
