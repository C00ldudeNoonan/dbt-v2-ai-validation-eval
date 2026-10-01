"""Milestones 1-2: build the clean project, snapshot golden outputs, verify the reference.

    python -m harness.golden

Builds the unmodified project on both engines, checks v1 and v2 outputs agree,
writes results/golden/<task>.parquet, and verifies every reference dashboard query
matches its golden model within floating-point tolerance. A mismatch is a harness
bug and exits non-zero.
"""
from __future__ import annotations

import sys

import duckdb

from harness.common import GOLDEN_DIR, WORK, eval_config, reference_sql, strip_sql, tasks
from harness.compare import diff_tables
from harness.engines import Workspace, run_dbt


def build_clean(engine: str) -> Workspace:
    ws = Workspace.create(WORK / "golden" / engine)
    for args in (["deps"], ["build"]):
        r = run_dbt(engine, ws, args)
        if not r.ok:
            sys.exit(f"clean project failed `dbt {' '.join(args)}` on {engine}:\n{r.output[-3000:]}")
    return ws


def main() -> int:
    tol = eval_config()["tolerances"]
    v1, v2 = build_clean("v1"), build_clean("v2")
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(v2.db))
    con.execute(f"attach '{v1.db}' as v1 (read_only)")
    failures = 0
    for task, spec in tasks().items():
        engines = diff_tables(con, f"main.{task}", f"v1.main.{task}", spec["grain"])
        con.execute(f"copy main.{task} to '{GOLDEN_DIR / (task + '.parquet')}' (format parquet)")
        con.execute(f"create or replace temp table ref_{task} as {strip_sql(reference_sql(task))}")
        ref = diff_tables(con, f"main.{task}", f"ref_{task}", spec["grain"],
                          rel_tolerance=tol["reference_match_rel"], abs_floor=tol["abs_floor"])
        n = con.execute(f"select count(*) from main.{task}").fetchone()[0]
        status = "OK" if engines.identical and ref.identical else "MISMATCH"
        failures += status != "OK"
        print(f"{status:9} {task:38} rows={n:<5} v1==v2={engines.identical}  golden==reference={ref.identical}")
        if not ref.identical:
            print("          reference diff:", ref.as_dict())
        if not engines.identical:
            print("          engine diff:", engines.as_dict())
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
