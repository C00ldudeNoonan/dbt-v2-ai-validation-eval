"""Load golden snapshots into a DuckDB connection (schema `golden`)."""
from __future__ import annotations

import duckdb

from harness.common import GOLDEN_DIR


def load_golden(con: duckdb.DuckDBPyConnection, task: str) -> str:
    path = GOLDEN_DIR / f"{task}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"{path} missing; run `python -m harness.golden` first")
    con.execute("create schema if not exists golden")
    con.execute(f"create or replace table golden.{task} as select * from '{path}'")
    return f"golden.{task}"
