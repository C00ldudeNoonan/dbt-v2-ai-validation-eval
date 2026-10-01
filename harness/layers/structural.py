"""L1 structural layer and the shared classifier for dbt build results.

Arm A (v1) has no separate gate. Parse/compile errors and model build errors that
surface during `dbt build` are L1, and they count as runtime catches unless no node
executed. Arms B/C (v2) first run `dbt compile` with strict static analysis. That
gate issues no model SQL on the warehouse, so a failure there is caught before execution.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from harness.engines import DbtResult, NodeResult, Workspace, run_dbt

EXECUTED = {"success", "pass", "fail", "error", "warn"}
FAILED = {"fail", "error"}


@dataclass
class LayerOutcome:
    caught: bool                       # the workflow stopped / failed here
    layer: str                         # L1 / L2 / L3
    before_execution: bool = False
    attributable: bool = False         # failure references the target model
    queries_before_catch: int = 0      # warehouse node executions before + including the catch
    nodes_executed: int = 0
    failures: list[dict] = field(default_factory=list)
    wall_s: float = 0.0


def target_tokens(task: str) -> list[str]:
    return [f"model.jaffle_shop.{task}", f"models/marts/metrics/{task}.", f".{task}.", f"_{task}_", f" {task} "]


def _attached_model(ws: Workspace, unique_id: str) -> set[str]:
    manifest = ws.project / "target" / "manifest.json"
    if not manifest.exists():
        return set()
    try:
        node = json.loads(manifest.read_text()).get("nodes", {}).get(unique_id) or {}
    except json.JSONDecodeError:
        return set()
    attached = {node.get("attached_node")} if node.get("attached_node") else set()
    return attached | set((node.get("depends_on") or {}).get("nodes") or [])


def node_targets_task(ws: Workspace, node: NodeResult, task: str) -> bool:
    model_uid = f"model.jaffle_shop.{task}"
    if node.unique_id == model_uid:
        return True
    if node.resource_type == "unit_test":
        return node.unique_id.split(".")[2:3] == [task]
    if node.resource_type == "test":
        deps = _attached_model(ws, node.unique_id)
        if deps:
            return model_uid in deps
        return f"_{task}_" in node.unique_id
    return False


def output_errors(output: str) -> list[str]:
    """Error lines from either engine's console output."""
    errs = []
    lines = output.splitlines()
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("[error]"):
            ctx = " ".join(x.strip() for x in lines[i + 1:i + 3] if x.strip().startswith("-->"))
            errs.append((s + " " + ctx).strip())
        elif re.match(r"^\S*\s*(Compilation|Runtime|Parsing|Database|Binder|Catalog) Error", s):
            errs.append(" ".join(x.strip() for x in lines[i:i + 3]))
    return errs


def classify_build(ws: Workspace, result: DbtResult, task: str, gate: bool) -> LayerOutcome:
    """Classify a gate (`compile`) or `build` result into a LayerOutcome."""
    executed = [n for n in result.nodes if n.status in EXECUTED and n.resource_type in ("model", "test", "unit_test", "seed", "snapshot")]
    if result.ok:
        return LayerOutcome(False, "L1" if gate else "L2", nodes_executed=0 if gate else len(executed), wall_s=result.wall_s)

    failed = [n for n in result.nodes if n.status in FAILED]
    first = failed[0] if failed else None
    failures = [{"unique_id": n.unique_id, "status": n.status, "message": n.message[:500],
                 "targets_task": node_targets_task(ws, n, task)} for n in failed]
    errors = output_errors(result.output)
    if not failures:
        failures = [{"unique_id": "", "status": "error", "message": e[:500],
                     "targets_task": any(t in e for t in target_tokens(task))} for e in errors[:5]]
    attributable = any(f["targets_task"] for f in failures) and all(
        f["targets_task"] for f in failures if f["status"] == "error" and f["unique_id"].startswith("model."))

    if gate:
        return LayerOutcome(True, "L1", before_execution=True, attributable=attributable,
                            queries_before_catch=0, failures=failures, wall_s=result.wall_s)

    if first is None:
        # parse/compile failure during `dbt build` before any node ran
        return LayerOutcome(True, "L1", before_execution=not executed, attributable=attributable,
                            queries_before_catch=len(executed), nodes_executed=len(executed),
                            failures=failures, wall_s=result.wall_s)
    # A model error, or a test/unit test that *errors* (e.g. a binder error while running the
    # model SQL against fixtures), is structural (L1 at runtime). An assertion that runs and
    # *fails* is L2.
    layer = "L1" if (first.resource_type == "model" or first.status == "error") else "L2"
    before = [n for n in executed if n.started_at and first.started_at and n.started_at < first.started_at]
    return LayerOutcome(True, layer, before_execution=False, attributable=attributable,
                        queries_before_catch=len(before) + 1, nodes_executed=len(executed),
                        failures=failures, wall_s=result.wall_s)


def static_gate(ws: Workspace, task: str, engine: str) -> LayerOutcome:
    return classify_build(ws, run_dbt(engine, ws, ["compile"]), task, gate=True)
