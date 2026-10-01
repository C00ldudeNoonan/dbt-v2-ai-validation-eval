"""Apply one seeded fault to an isolated copy of the project.

    python -m harness.mutate --list
    python -m harness.mutate --verify        # M3: every fault changes output or breaks the build
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from harness.common import RESULTS, WORK, fault_catalog, reference_sql, tasks

CONTROL = "CONTROL"


class MutationError(Exception):
    pass


@dataclass
class Edit:
    find: str
    replace: str
    file: str | None = None     # project-relative; None = the target model's SQL


@dataclass
class Variant:
    variant_id: str
    task: str
    fault_id: str                       # fault id or CONTROL
    category: str = "Clean control"
    description: str = "Unmodified golden model."
    hypothesized_layer: str = "none"
    hypothesized_v1_vs_v2: str = ""
    edits: list[Edit] = field(default_factory=list)
    reference_edits: list[Edit] = field(default_factory=list)

    @property
    def is_control(self) -> bool:
        return self.fault_id == CONTROL

    @property
    def target_file(self) -> str:
        return f"{fault_catalog()['defaults']['target_dir']}/{self.task}.sql"

    def reference_query(self) -> str:
        return apply_edits(reference_sql(self.task), self.reference_edits, f"reference/{self.task}.sql")


def _edits(raw: list[dict] | None) -> list[Edit]:
    return [Edit(e["find"], e["replace"], e.get("file")) for e in raw or []]


def all_variants() -> list[Variant]:
    catalog = fault_catalog()
    variants = []
    for task in tasks():
        variants.append(Variant(f"{task}__{CONTROL}", task, CONTROL))
    for fault in catalog["faults"]:
        for app in fault["applications"]:
            task = app["task"]
            if task not in tasks():
                raise MutationError(f"{fault['id']}: unknown task {task}")
            variants.append(Variant(
                variant_id=f"{task}__{fault['id']}",
                task=task,
                fault_id=fault["id"],
                category=fault["category"],
                description=app.get("description", fault["description"]),
                hypothesized_layer=app.get("hypothesized_layer", fault["hypothesized_layer"]),
                hypothesized_v1_vs_v2=app.get("hypothesized_v1_vs_v2", fault["hypothesized_v1_vs_v2"]),
                edits=_edits(app["mutation"]),
                reference_edits=_edits(app.get("reference_override")),
            ))
    ids = [v.variant_id for v in variants]
    if len(ids) != len(set(ids)):
        raise MutationError("duplicate variant ids")
    return variants


def get_variant(variant_id: str) -> Variant:
    for v in all_variants():
        if v.variant_id == variant_id:
            return v
    raise KeyError(variant_id)


def apply_edits(text: str, edits: list[Edit], label: str) -> str:
    for e in edits:
        n = text.count(e.find)
        if n != 1:
            raise MutationError(f"{label}: find string must occur exactly once, found {n}: {e.find!r}")
        text = text.replace(e.find, e.replace)
    return text


def apply_variant(variant: Variant, project_dir: Path) -> None:
    """Apply the variant's mutation in place to an (already isolated) project copy."""
    by_file: dict[str, list[Edit]] = {}
    for e in variant.edits:
        by_file.setdefault(e.file or variant.target_file, []).append(e)
    for rel, edits in by_file.items():
        if not rel.startswith(fault_catalog()["defaults"]["target_dir"] + f"/{variant.task}."):
            raise MutationError(f"{variant.variant_id}: edits must stay within the target model, got {rel}")
        path = project_dir / rel
        path.write_text(apply_edits(path.read_text(), edits, rel))


def verify(engine: str = "v2") -> int:
    """M3 check: each fault breaks the build or changes the target's output vs golden."""
    import duckdb

    from harness.compare import diff_tables
    from harness.engines import Workspace, run_dbt
    from harness.golden_io import load_golden

    out = []
    broken = 0
    for v in all_variants():
        ws = Workspace.create(WORK / "verify" / v.variant_id)
        apply_variant(v, ws.project)
        v.reference_query()  # reference override must apply cleanly
        build = run_dbt(engine, ws, ["build"])
        row = {"variant_id": v.variant_id, "fault_id": v.fault_id, "hypothesized_layer": v.hypothesized_layer}
        con = duckdb.connect(str(ws.db))
        exists = con.execute(
            "select count(*) from information_schema.tables where table_schema='main' and table_name=?", [v.task]
        ).fetchone()[0]
        if not exists:
            row.update(effect="build_broken", detail=_first_error(build.output))
        else:
            load_golden(con, v.task)
            d = diff_tables(con, f"main.{v.task}", f"golden.{v.task}", tasks()[v.task]["grain"])
            row.update(effect="unchanged" if d.identical else "output_changed", build_ok=build.ok, diff=d.as_dict())
            if not build.ok:
                row["build_failures"] = [n.unique_id for n in build.nodes if n.status in ("error", "fail")]
        con.close()
        ok = (row["effect"] == "unchanged") if v.is_control else (row["effect"] != "unchanged")
        broken += not ok
        row["verified"] = ok
        out.append(row)
        print(f"{'OK ' if ok else 'BAD'} {v.variant_id:58} {row['effect']:15} "
              f"{_summary(row)}")
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "fault_verification.json").write_text(json.dumps(out, indent=2, default=str))
    print(f"\n{len(out) - broken}/{len(out)} variants verified; details in results/fault_verification.json")
    return 1 if broken else 0


def _first_error(output: str) -> str:
    for line in output.splitlines():
        s = line.strip()
        if s.startswith("[error]") or "Error" in s.split(" ")[0:3] or s.startswith(("Runtime Error", "Compilation Error", "Binder Error", "Catalog Error")):
            return s[:200]
    for line in output.splitlines():
        if "error" in line.lower() and "Errors and Warnings" not in line:
            return line.strip()[:200]
    return output.strip().splitlines()[-1][:200] if output.strip() else ""


def _summary(row: dict) -> str:
    if row["effect"] == "build_broken":
        return row["detail"][:110]
    d = row.get("diff", {})
    parts = []
    if not row.get("build_ok", True):
        parts.append("tests_failed=" + ",".join(f.split(".")[-1][:40] for f in row.get("build_failures", [])[:2]))
    if d.get("duplicate_keys_left"):
        parts.append(f"dup_keys={d['duplicate_keys_left']}")
    if d.get("rows_only_left") or d.get("rows_only_right"):
        parts.append(f"rows +{d['rows_only_left']}/-{d['rows_only_right']}")
    for c, n in d.get("columns_differing", {}).items():
        mx = d["max_rel_diff"].get(c)
        parts.append(f"{c}:{n}rows(max {mx:.2%})" if isinstance(mx, float) else f"{c}:{n}rows")
    if d.get("schema_mismatch"):
        parts.append(f"schema:{d['schema_mismatch']}")
    return " ".join(parts)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--list", action="store_true")
    p.add_argument("--verify", action="store_true")
    p.add_argument("--review", action="store_true", help="write results/fault_catalog_review.md")
    p.add_argument("--engine", default="v2")
    a = p.parse_args()
    if a.list:
        for v in all_variants():
            print(f"{v.variant_id:58} {v.hypothesized_layer:6} {v.description}")
        return 0
    if a.verify:
        rc = verify(a.engine)
        print(write_review())
        return rc
    if a.review:
        print(write_review())
        return 0
    p.print_help()
    return 0



def write_review(path: Path = RESULTS / "fault_catalog_review.md") -> Path:
    """Render the adapted catalog + M3 verification evidence for the human review pause."""
    verification = {}
    vf = RESULTS / "fault_verification.json"
    if vf.exists():
        verification = {r["variant_id"]: r for r in json.loads(vf.read_text())}
    lines = [
        "# Adapted fault catalog: for review before freezing",
        "",
        "Source: `config/faults.yaml`. Verified effect is from `python -m harness.mutate --verify` "
        "(full `dbt build` on v2, target output diffed against golden). It shows whether the fault "
        "*does anything*. It is not an arm result.",
        "",
        "| Variant | Category | Hypothesized layer | Mutation | Verified effect |",
        "|---|---|---|---|---|",
    ]
    for v in all_variants():
        r = verification.get(v.variant_id, {})
        effect = r.get("effect", "not verified")
        if r:
            effect += f": {_summary(r)}".replace("|", "/") if _summary(r) else ""
        lines.append(f"| `{v.variant_id}` | {v.category} | {v.hypothesized_layer} | "
                     f"{' '.join(v.description.split())} | {effect[:160]} |")
    path.write_text("\n".join(lines) + "\n")
    return path


if __name__ == "__main__":
    sys.exit(main())
