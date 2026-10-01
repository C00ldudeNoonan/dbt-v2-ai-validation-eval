"""Collect raw run records into runs.csv / flags.csv / adjudication.csv and compute scores.

    python -m harness.score
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

from harness.common import RESULTS, config_hash

RAW_DIR = RESULTS / "raw"
RUNS_CSV = RESULTS / "runs.csv"
FLAGS_CSV = RESULTS / "flags.csv"
ADJ_CSV = RESULTS / "adjudication.csv"
LABELS = ("true_issue", "acceptable_difference", "noise")

RUN_FIELDS = [
    "variant_id", "task", "fault_id", "category", "arm", "repetition", "hypothesized_layer",
    "caught", "caught_by_layer", "caught_before_execution", "warehouse_queries_before_catch",
    "flagged_any", "stopped_at", "unattributed_flags", "build_nodes_executed", "wall_clock_s",
    "llm_calls", "llm_input_tokens", "llm_output_tokens", "llm_cost_usd", "llm_model_reported", "llm_wall_s",
    "recon_generation_error", "recon_queries_generated", "recon_queries_executed", "recon_queries_failed",
    "recon_queries_flagged", "recon_exec_time_s", "dims_covered", "grains_covered",
    "engine", "engine_version", "warehouse", "reconciliation", "static_analysis_gate", "config_hash",
    "failure_messages",
]
FLAG_FIELDS = [
    "variant_id", "fault_id", "arm", "repetition", "query_id", "source", "kind", "measure", "dimensions",
    "time_grain", "description", "executed", "error", "n_rows", "tolerance", "n_flagged_rows", "max_rel_diff",
    "max_rel_diff_inf", "worst_slice", "flagged", "counterfactual_flagged", "attributable", "exec_s", "sql",
    "config_hash",
]
ADJ_FIELDS = [
    "adjudication_id", "variant_id", "fault_id", "arm", "repetition", "layer", "query_id", "kind", "measure",
    "worst_slice", "max_rel_diff", "detail", "sql", "label", "notes",
]


def load_records(raw_dir: Path = RAW_DIR) -> list[dict]:
    recs = []
    for p in sorted(raw_dir.glob("*.json")):
        recs.append(json.loads(p.read_text()))
    return recs


def _write(path: Path, fields: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _adj_id(*parts) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:10]


def adjudication_rows(records: list[dict]) -> list[dict]:
    """Every flag/failure on a clean control, plus every unattributable flag on a fault variant."""
    rows = []
    for rec in records:
        r = rec["row"]
        control = r["fault_id"] == "CONTROL"
        base = {k: r[k] for k in ("variant_id", "fault_id", "arm", "repetition")}
        # L1/L2 stop
        for s in rec["stages"]:
            if not s["caught"]:
                continue
            if control or not s["attributable"]:
                detail = " || ".join(f"{f['unique_id']}: {f['message'][:300]}" for f in s["failures"])[:1500]
                rows.append({**base, "adjudication_id": _adj_id(rec["run_key"], s["stage"]), "layer": s["layer"],
                             "query_id": "", "kind": s["stage"], "measure": "", "worst_slice": "",
                             "max_rel_diff": "", "detail": detail, "sql": "", "label": "", "notes": ""})
        for f in rec["flags"]:
            if f["flagged"] and (control or not f["attributable"]):
                cf = f["counterfactual_flagged"]
                detail = (f"{f['n_flagged_rows']}/{f['n_rows']} rows beyond ±{f['tolerance']:.1%}; "
                          f"golden counterfactual flagged={cf}; {f['description']}")
                rows.append({**base, "adjudication_id": _adj_id(rec["run_key"], f["query_id"]), "layer": "L3",
                             "query_id": f["query_id"], "kind": f["kind"], "measure": f["measure"],
                             "worst_slice": f["worst_slice"],
                             "max_rel_diff": "inf" if f["max_rel_diff_inf"] else f["max_rel_diff"],
                             "detail": detail, "sql": f["sql"], "label": "", "notes": ""})
    return rows


def write_outputs(records: list[dict]) -> dict:
    runs = sorted((rec["row"] for rec in records), key=lambda r: (r["variant_id"], r["arm"], r["repetition"]))
    flags = [f for rec in records for f in rec["flags"]]
    _write(RUNS_CSV, RUN_FIELDS, runs)
    _write(FLAGS_CSV, FLAG_FIELDS, flags)
    existing = {r["adjudication_id"]: r for r in read_csv(ADJ_CSV)}
    adj = adjudication_rows(records)
    for row in adj:
        prev = existing.get(row["adjudication_id"])
        if prev:
            row["label"], row["notes"] = prev.get("label", ""), prev.get("notes", "")
    _write(ADJ_CSV, ADJ_FIELDS, adj)
    return {"runs": len(runs), "flags": len(flags), "adjudication": len(adj),
            "unlabeled": sum(1 for r in adj if r["label"] not in LABELS)}


# ---------------------------------------------------------------- aggregates


def _b(x) -> bool:
    return x is True or str(x).lower() == "true"


def _f(x, default=0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def detection_matrix(runs: list[dict]) -> dict:
    """{(variant_id, arm): {caught, reps, layers, pre_exec, ...}} for fault variants."""
    out: dict = {}
    for r in runs:
        if r["fault_id"] == "CONTROL":
            continue
        k = (r["variant_id"], r["arm"])
        d = out.setdefault(k, {"variant_id": r["variant_id"], "task": r["task"], "fault_id": r["fault_id"],
                               "category": r["category"], "arm": r["arm"], "hypothesized_layer": r["hypothesized_layer"],
                               "reps": 0, "caught": 0, "pre_exec": 0, "layers": defaultdict(int), "wq": [],
                               "dims": set(), "grains": set()})
        d["reps"] += 1
        d["caught"] += _b(r["caught"])
        d["pre_exec"] += _b(r["caught_before_execution"])
        d["layers"][r["caught_by_layer"]] += 1
        d["wq"].append(int(_f(r["warehouse_queries_before_catch"])))
        d["dims"] |= {x for x in str(r["dims_covered"]).split(";") if x}
        d["grains"] |= {x for x in str(r["grains_covered"]).split(";") if x}
    return out


def false_positive_summary(runs: list[dict], adj: list[dict]) -> dict:
    """Per arm: control runs, runs with any flag, and, if fully labeled, the FP rate."""
    labels = {(a["variant_id"], a["arm"], str(a["repetition"])): [] for a in adj}
    for a in adj:
        labels[(a["variant_id"], a["arm"], str(a["repetition"]))].append(a)
    control_adj = [a for a in adj if a["fault_id"] == "CONTROL"]
    unlabeled = sum(1 for a in adj if a["label"] not in LABELS)
    out = {"unlabeled": unlabeled, "per_arm": {}}
    for arm in sorted({r["arm"] for r in runs}):
        ctrl = [r for r in runs if r["arm"] == arm and r["fault_id"] == "CONTROL"]
        flagged = [r for r in ctrl if _b(r["flagged_any"])]
        q_exec = sum(int(_f(r["recon_queries_executed"])) for r in ctrl)
        q_flag = sum(int(_f(r["recon_queries_flagged"])) for r in ctrl)
        d = {"control_runs": len(ctrl), "flagged_runs": len(flagged), "queries_executed": q_exec,
             "queries_flagged": q_flag, "fp_runs": None, "fp_rate": None, "fp_queries": None,
             "true_issue_runs": None}
        if unlabeled == 0:
            fp_runs = 0
            ti_runs = 0
            fp_q = 0
            for r in flagged:
                items = labels.get((r["variant_id"], arm, str(r["repetition"])), [])
                if any(a["label"] != "true_issue" for a in items):
                    fp_runs += 1
                if items and all(a["label"] == "true_issue" for a in items):
                    ti_runs += 1
                fp_q += sum(1 for a in items if a["label"] != "true_issue" and a["layer"] == "L3")
            d.update(fp_runs=fp_runs, true_issue_runs=ti_runs,
                     fp_rate=(fp_runs / len(ctrl)) if ctrl else None, fp_queries=fp_q)
        out["per_arm"][arm] = d
    out["control_items"] = len(control_adj)
    return out


def cost_summary(runs: list[dict]) -> dict:
    out = {}
    for arm in sorted({r["arm"] for r in runs}):
        rr = [r for r in runs if r["arm"] == arm]
        recon = [r for r in rr if int(_f(r["recon_queries_generated"])) > 0 or int(_f(r["llm_calls"])) > 0]
        n = len(recon) or 1
        costs = [_f(r["llm_cost_usd"], None) for r in recon if r["llm_cost_usd"] not in ("", None, "None")]
        out[arm] = {
            "runs": len(rr),
            "validations_reaching_l3": len(recon),
            "mean_recon_queries": sum(int(_f(r["recon_queries_executed"])) for r in recon) / n,
            "mean_recon_generated": sum(int(_f(r["recon_queries_generated"])) for r in recon) / n,
            "mean_recon_exec_s": sum(_f(r["recon_exec_time_s"]) for r in recon) / n,
            "mean_llm_calls": sum(_f(r["llm_calls"]) for r in recon) / n,
            "mean_input_tokens": sum(_f(r["llm_input_tokens"]) for r in recon) / n,
            "mean_output_tokens": sum(_f(r["llm_output_tokens"]) for r in recon) / n,
            "mean_llm_cost_usd": (sum(costs) / len(costs)) if costs else None,
            "total_llm_cost_usd": sum(costs) if costs else None,
            "mean_llm_wall_s": sum(_f(r["llm_wall_s"]) for r in recon) / n,
            "mean_wall_clock_s": sum(_f(r["wall_clock_s"]) for r in rr) / (len(rr) or 1),
        }
    return out


def config_hashes(runs: list[dict]) -> list[str]:
    return sorted({r["config_hash"] for r in runs})


def main() -> int:
    records = load_records()
    if not records:
        print("no raw results yet")
        return 0
    stats = write_outputs(records)
    hashes = config_hashes([r["row"] for r in records])
    print(f"runs={stats['runs']} flags={stats['flags']} adjudication rows={stats['adjudication']} "
          f"(unlabeled {stats['unlabeled']}); config hashes in results: {hashes} (current {config_hash()})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
