"""L2 assertion layer: `dbt build` (models + data tests + unit tests).

Model build errors during `dbt build` (binder errors, contract preflight) are
classified L1 at runtime; test and unit-test failures are L2.
"""
from __future__ import annotations

from harness.engines import Workspace, run_dbt
from harness.layers.structural import LayerOutcome, classify_build


def build(ws: Workspace, task: str, engine: str) -> LayerOutcome:
    return classify_build(ws, run_dbt(engine, ws, ["build"]), task, gate=False)
