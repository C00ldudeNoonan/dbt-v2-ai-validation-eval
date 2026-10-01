"""Timeboxed manual spot check (Arms A and B).

Simulates what a person typically does under time pressure. The same two
total-level comparisons run for every task:
  1. grand_total: the grand total of the primary measure
  2. latest_period_total: the total of the primary measure in the most recent period
"""
from __future__ import annotations

from harness.common import eval_config
from harness.layers.recon_common import ReconQuery


def manual_queries(task: str) -> list[ReconQuery]:
    spec = eval_config()["tasks"][task]
    m, col, grain = spec["primary_measure"], spec["period_column"], spec["period_grain"]
    builders = {
        "grand_total": lambda: ReconQuery(
            "manual_grand_total",
            f"select 'grand_total' as slice,\n"
            f"  (select sum({m}) from model_output) as model_value,\n"
            f"  (select sum({m}) from reference_output) as reference_value",
            "manual", "total", m, [], "total", f"Grand total of {m}",
        ),
        "latest_period_total": lambda: ReconQuery(
            "manual_latest_period_total",
            f"with latest as (select max(date_trunc('{grain}', {col})) as p from reference_output)\n"
            f"select 'latest {grain}' as slice,\n"
            f"  (select sum({m}) from model_output where date_trunc('{grain}', {col}) = (select p from latest)) as model_value,\n"
            f"  (select sum({m}) from reference_output where date_trunc('{grain}', {col}) = (select p from latest)) as reference_value",
            "manual", "total", m, [], grain, f"Total of {m} in the most recent {grain}",
        ),
    }
    return [builders[c]() for c in eval_config()["manual_reconciliation"]["checks"]]
