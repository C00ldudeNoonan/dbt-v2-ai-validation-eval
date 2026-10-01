"""Raw-data warehouse setup.

Both engines read the same raw tables. We load them once with explicit types
(rather than through `dbt seed`), so v1 and v2 see byte-identical raw data and
seed type inference can't differ between engines.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
SEED_DIR = ROOT / "reference_project" / "seeds" / "jaffle-data"
BASE_WAREHOUSE = ROOT / "work" / "base" / "warehouse.duckdb"

RAW_TABLES: dict[str, dict[str, str]] = {
    "raw_customers": {"id": "varchar", "name": "varchar"},
    "raw_items": {"id": "varchar", "order_id": "varchar", "sku": "varchar"},
    "raw_orders": {
        "id": "varchar",
        "customer": "varchar",
        "ordered_at": "timestamp",
        "store_id": "varchar",
        "subtotal": "bigint",
        "tax_paid": "bigint",
        "order_total": "bigint",
    },
    "raw_products": {
        "sku": "varchar",
        "name": "varchar",
        "type": "varchar",
        "price": "bigint",
        "description": "varchar",
    },
    "raw_stores": {"id": "varchar", "name": "varchar", "opened_at": "timestamp", "tax_rate": "double"},
    "raw_supplies": {
        "id": "varchar",
        "name": "varchar",
        "cost": "bigint",
        "perishable": "boolean",
        "sku": "varchar",
    },
    "raw_refunds": {"order_id": "varchar", "refunded_at": "timestamp", "reason": "varchar"},
}


def load_raw(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("create schema if not exists raw")
    for table, cols in RAW_TABLES.items():
        csv = SEED_DIR / f"{table}.csv"
        col_spec = "{" + ", ".join(f"'{c}': '{t}'" for c, t in cols.items()) + "}"
        con.execute(
            f"create or replace table raw.{table} as "
            f"select * from read_csv('{csv}', header=true, delim=',', quote='\"', escape='\"', columns={col_spec})"
        )


def build_base_warehouse(path: Path = BASE_WAREHOUSE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    con = duckdb.connect(str(path))
    try:
        load_raw(con)
    finally:
        con.close()
    return path


def clone_warehouse(dest: Path, base: Path = BASE_WAREHOUSE) -> Path:
    if not base.exists():
        build_base_warehouse(base)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(base, dest)
    return dest


if __name__ == "__main__":
    print(build_base_warehouse())
