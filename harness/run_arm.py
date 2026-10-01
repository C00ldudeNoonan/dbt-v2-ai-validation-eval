"""Run one variant through one arm (one repetition).

    python -m harness.run_arm monthly_revenue_by_location__F-FILTER C --rep 1
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from dataclasses import asdict
from pathlib import Path

import duckdb

from harness.common import GOLDEN_DIR, METRICS_DIR, RESULTS, WORK, config_hash, eval_config, strip_sql
from harness.engines import Workspace, engine_version
from harness.layers import assertion, structural
from harness.layers.recon_common import QueryResult, ReconQuery, finite, run_queries
from harness.layers.reconcile_manual import manual_queries
from harness.mutate import Variant, apply_variant, get_variant

RAW_DIR = RESULTS / "raw"


def run_key(variant_id: str, arm: str, rep: int) -> str:
    return f"{variant_id}__{arm}__r{rep}"


def _schema(con: duckdb.DuckDBPyConnection, relation_sql: str) -> list[tuple[str, str]]:
    return [(r[0], r[1]) for r in con.execute(f"describe {relation_sql}").fetchall()]


def _l3(ws: Workspace, v: Variant, arm_cfg: dict, raw_extra: dict) -> tuple[list[QueryResult], dict]:
    con = duckdb.connect(str(ws.db), read_only=True)
    try:
        model_tbl = con.execute(f"select * from main.{v.task}").fetch_arrow_table()
        ref_sql = strip_sql(v.reference_query())
        ref_tbl = con.execute(ref_sql).fetch_arrow_table()
        model_schema = _schema(con, f"main.{v.task}")
        ref_schema = _schema(con, f"({ref_sql})")
    finally:
        con.close()
    golden_tbl = duckdb.connect().execute(f"select * from '{GOLDEN_DIR / (v.task + '.parquet')}'").fetch_arrow_table()

    llm = {"llm_calls": 0, "llm_input_tokens": 0, "llm_output_tokens": 0, "llm_cost_usd": None,
           "llm_model_reported": "", "llm_wall_s": 0.0, "recon_generation_error": ""}
    if arm_cfg["reconciliation"] == "manual":
        queries: list[ReconQuery] = manual_queries(v.task)
    else:
        from harness.layers.reconcile_ai import generate
        model_sql = (ws.project / v.target_file).read_text()
        model_yml = (ws.project / v.target_file).with_suffix(".yml").read_text()
        gen = generate(v.task, model_sql, model_yml, model_schema, ref_schema)
        queries = gen.queries
        llm.update(llm_calls=gen.llm_calls, llm_input_tokens=gen.input_tokens, llm_output_tokens=gen.output_tokens,
                   llm_cost_usd=gen.cost_usd, llm_model_reported=gen.model_reported, llm_wall_s=gen.llm_wall_s,
                   recon_generation_error=gen.error)
        raw_extra["ai"] = {"prompt": gen.prompt, "response": gen.raw_response}
    return run_queries(queries, model_tbl, ref_tbl, golden_tbl), llm


def run(variant_id: str, arm: str, rep: int = 1, keep_workspace: bool = False) -> dict:
    cfg = eval_config()
    arm_cfg = cfg["arms"][arm]
    engine = arm_cfg["engine"]
    v = get_variant(variant_id)
    key = run_key(variant_id, arm, rep)
    ws = Workspace.create(WORK / "runs" / key)
    apply_variant(v, ws.project)
    start = time.monotonic()

    row = {
        "variant_id": v.variant_id, "task": v.task, "fault_id": v.fault_id, "category": v.category,
        "arm": arm, "repetition": rep, "hypothesized_layer": v.hypothesized_layer,
        "engine": engine, "engine_version": engine_version(engine), "warehouse": cfg["warehouse"],
        "reconciliation": arm_cfg["reconciliation"], "static_analysis_gate": arm_cfg["static_analysis_gate"],
        "config_hash": config_hash(),
    }
    stages: list[dict] = []
    stop: structural.LayerOutcome | None = None
    build_nodes = 0

    if arm_cfg["static_analysis_gate"]:
        gate = structural.static_gate(ws, v.task, engine)
        stages.append({"stage": "static_analysis", **asdict(gate)})
        if gate.caught:
            stop = gate
    if stop is None:
        b = assertion.build(ws, v.task, engine)
        stages.append({"stage": "build", **asdict(b)})
        build_nodes = b.nodes_executed
        if b.caught:
            stop = b

    results: list[QueryResult] = []
    raw_extra: dict = {}
    llm = {"llm_calls": 0, "llm_input_tokens": 0, "llm_output_tokens": 0, "llm_cost_usd": None,
           "llm_model_reported": "", "llm_wall_s": 0.0, "recon_generation_error": ""}
    if stop is None:
        results, llm = _l3(ws, v, arm_cfg, raw_extra)
    row.update(llm)

    executed = [r for r in results if r.executed]
    flagged = [r for r in executed if r.flagged]
    if stop is not None:
        flagged_any = True
        stopped_at = stop.layer
        attributable = stop.attributable and not v.is_control
        caught_layer = stop.layer if (attributable or v.is_control) else "none"
        before_exec = stop.before_execution
        wq = stop.queries_before_catch
    else:
        flagged_any = bool(flagged)
        stopped_at = "L3" if flagged else "none"
        first_attr = next((i for i, r in enumerate(executed) if r.flagged and (r.attributable or v.is_control)), None)
        attributable = (not v.is_control) and first_attr is not None
        caught_layer = "L3" if (attributable or (v.is_control and flagged)) else "none"
        before_exec = False
        wq = build_nodes + (first_attr + 1 if first_attr is not None else len(executed))

    row.update({
        "caught": (flagged_any if v.is_control else attributable),
        "caught_by_layer": caught_layer,
        "caught_before_execution": bool(before_exec and caught_layer != "none"),
        "flagged_any": flagged_any,
        "stopped_at": stopped_at,
        "unattributed_flags": (0 if v.is_control else (len([r for r in flagged if not r.attributable])
                               + (1 if stop is not None and not stop.attributable else 0))),
        "warehouse_queries_before_catch": wq,
        "build_nodes_executed": build_nodes,
        "wall_clock_s": round(time.monotonic() - start, 2),
        "recon_queries_generated": len(results),
        "recon_queries_executed": len(executed),
        "recon_queries_failed": len(results) - len(executed),
        "recon_queries_flagged": len(flagged),
        "recon_exec_time_s": round(sum(r.exec_s for r in results), 3),
        "dims_covered": ";".join(sorted({d for r in executed for d in r.query.dimensions})),
        "grains_covered": ";".join(sorted({(r.query.time_grain or "none") for r in executed})),
        "failure_messages": " || ".join(f.get("message", "")[:200] for s in stages for f in s.get("failures", []))[:1000],
    })
    flags = [{
        "variant_id": v.variant_id, "fault_id": v.fault_id, "arm": arm, "repetition": rep,
        "query_id": r.query.query_id, "source": r.query.source, "kind": r.query.kind, "measure": r.query.measure,
        "dimensions": ";".join(r.query.dimensions), "time_grain": r.query.time_grain,
        "description": r.query.description, "executed": r.executed, "error": r.error, "n_rows": r.n_rows,
        "tolerance": r.tolerance, "n_flagged_rows": r.n_flagged_rows, "max_rel_diff": finite(r.max_rel_diff),
        "max_rel_diff_inf": r.max_rel_diff == float("inf"), "worst_slice": r.worst_slice, "flagged": r.flagged,
        "counterfactual_flagged": r.counterfactual_flagged, "attributable": r.attributable,
        "exec_s": round(r.exec_s, 4), "sql": r.query.sql, "config_hash": row["config_hash"],
    } for r in results]

    record = {"run_key": key, "row": row, "flags": flags, "stages": stages, **raw_extra}
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    (RAW_DIR / f"{key}.json").write_text(json.dumps(record, indent=1, default=str))
    if not keep_workspace:
        shutil.rmtree(ws.root, ignore_errors=True)
    return record


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("variant_id")
    p.add_argument("arm", choices=["A", "B", "C"])
    p.add_argument("--rep", type=int, default=1)
    p.add_argument("--keep", action="store_true")
    a = p.parse_args()
    rec = run(a.variant_id, a.arm, a.rep, a.keep)
    print(json.dumps(rec["row"], indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
