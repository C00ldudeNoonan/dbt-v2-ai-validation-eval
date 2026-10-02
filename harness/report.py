"""Render results/report.md from runs.csv, flags.csv, adjudication.csv and the catalog.

    python -m harness.report

Tone rule: every claim in the summary is computed from the tables below and is
never stronger than the data. False-positive rates are withheld until every
adjudication row has a label.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict

import yaml

from harness.common import METRICS_DIR, RESULTS, config_hash, eval_config, fault_catalog, tasks
from harness.score import (ADJ_CSV, FLAGS_CSV, LABELS, RUNS_CSV, _b, _f, config_hashes, cost_summary, detection_matrix,
                           false_positive_summary, read_csv)

STRUCTURAL = ["F-REF", "F-TYPE", "F-CONTRACT"]
ASSERTION = ["F-DUPKEY"]
SEMANTIC = ["F-FANOUT", "F-FILTER", "F-TZ", "F-NULL", "F-OFFSET", "F-SHARED-DEF"]
ARMS = ["A", "B", "C"]


def pct(a: float, b: float) -> str:
    return f"{a}/{b}" + (f" ({a / b:.0%})" if b else "")


def md_table(headers: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(str(c).replace("|", "/").replace("\n", " ") for c in r) + " |" for r in rows]
    return "\n".join(out)


def fault_order() -> list[str]:
    return [f["id"] for f in fault_catalog()["faults"]]


def cell(d: dict | None) -> str:
    if not d:
        return "n/a"
    layers = ", ".join(f"{k}" for k, v in sorted(d["layers"].items()) if k != "none" and v)
    s = f"{d['caught']}/{d['reps']}"
    if layers:
        s += f" ({layers})"
    return s


def definitions() -> dict[str, str]:
    out = {}
    for t in tasks():
        doc = yaml.safe_load((METRICS_DIR / f"{t}.yml").read_text())
        m = next(x for x in doc["models"] if x["name"] == t)
        out[t] = " ".join(str(m.get("description", "")).split())
    return out


def verification() -> dict:
    p = RESULTS / "fault_verification.json"
    return {r["variant_id"]: r for r in json.loads(p.read_text())} if p.exists() else {}


def arm_isolation_check(runs: list[dict]) -> list[str]:
    cfg = eval_config()["arms"]
    lines = []
    seen = defaultdict(set)
    for r in runs:
        seen[r["arm"]].add((r["engine"], r["engine_version"], r["reconciliation"], str(r["static_analysis_gate"])))
    for arm in ARMS:
        if arm not in seen:
            continue
        vals = seen[arm]
        ok = len(vals) == 1
        e, v, rec, gate = next(iter(vals))
        expected = (cfg[arm]["engine"], cfg[arm]["reconciliation"], str(cfg[arm]["static_analysis_gate"]))
        ok = ok and (e, rec, gate) == expected
        lines.append(f"- Arm {arm}: engine={e} ({v}), static-analysis gate={gate}, reconciliation={rec}. "
                     f"{'Matches config, single-valued across all runs.' if ok else 'MISMATCH with config or not single-valued!'}")
    a, b, c = (cfg[x] for x in ARMS)
    ab = {k for k in a if a[k] != b[k] and k != "repetitions"}
    bc = {k for k in b if b[k] != c[k] and k != "repetitions"}
    lines.append(f"- Config keys that differ A vs B: {sorted(ab)}. B vs C: {sorted(bc)}. "
                 "(A vs B: engine; v2's mandatory strict gate comes with the engine. B vs C: reconciliation only.)")
    return lines


def main() -> int:
    runs = read_csv(RUNS_CSV)
    if not runs:
        print("no runs.csv; run `python -m harness.score` first")
        return 1
    adj = read_csv(ADJ_CSV)
    cfg = eval_config()
    tol = cfg["tolerances"]
    matrix = detection_matrix(runs)
    fp = false_positive_summary(runs, adj)
    costs = cost_summary(runs)
    ver = verification()
    hashes = config_hashes(runs)
    variants = sorted({(r["variant_id"], r["task"], r["fault_id"], r["hypothesized_layer"], r["category"]) for r in runs},
                      key=lambda x: (fault_order().index(x[2]) if x[2] in fault_order() else -1, x[1]))
    fault_variants = [v for v in variants if v[2] != "CONTROL"]
    arms_present = [a for a in ARMS if any(r["arm"] == a for r in runs)]
    versions = {r["engine"]: r["engine_version"] for r in runs}
    reps_c = cfg["arms"]["C"]["repetitions"]

    def m(vid, arm):
        return matrix.get((vid, arm))

    def by_fault(ids):
        return [v for v in fault_variants if v[2] in ids]

    L = []
    pending = fp["unlabeled"] > 0
    L.append("# Seeded-fault evaluation: dbt v2 validation and AI-assisted reconciliation")
    L.append("")
    if pending:
        L.append(f"> **DRAFT: adjudication pending.** {fp['unlabeled']} row(s) in `results/adjudication.csv` "
                 "are unlabeled. False-positive rates are withheld until every row has a label "
                 f"({', '.join(LABELS)}). Re-run `python -m harness.report` after labeling.")
        L.append("")
    L.append(f"Generated from `results/runs.csv` ({len(runs)} runs). Config hash(es) in results: "
             f"{', '.join(f'`{h}`' for h in hashes)}; current config: `{config_hash()}`. "
             + ("Config did not change between runs." if len(hashes) == 1 and hashes[0] == config_hash()
                else "**Config changed between runs; results mix configurations.**"))
    L.append(f"Engines: dbt v1 `{versions.get('v1', '?')}`, dbt v2 `{versions.get('v2', '?')}`. "
             f"Warehouse: {cfg['warehouse']}. Arm C model: `{cfg['llm']['model']}` via `{cfg['llm']['backend']}`.")
    L.append("")

    # ------------------------------------------------------------- 1. Summary
    struct = by_fault(STRUCTURAL)
    pre_b = sum(1 for v in struct if m(v[0], "B") and m(v[0], "B")["pre_exec"])
    pre_a = sum(1 for v in struct if m(v[0], "A") and m(v[0], "A")["pre_exec"])
    caught_a = sum(1 for v in struct if m(v[0], "A") and m(v[0], "A")["caught"])
    caught_b = sum(1 for v in struct if m(v[0], "B") and m(v[0], "B")["caught"])
    sem = [v for v in by_fault(SEMANTIC) if v[2] != "F-SHARED-DEF"]
    sem_b = sum(1 for v in sem if m(v[0], "B") and m(v[0], "B")["caught"])
    sem_a = sum(1 for v in sem if m(v[0], "A") and m(v[0], "A")["caught"])
    c_runs = sum(m(v[0], "C")["reps"] for v in sem if m(v[0], "C"))
    c_caught_runs = sum(m(v[0], "C")["caught"] for v in sem if m(v[0], "C"))
    c_all = sum(1 for v in sem if m(v[0], "C") and m(v[0], "C")["caught"] == m(v[0], "C")["reps"])
    c_any = sum(1 for v in sem if m(v[0], "C") and m(v[0], "C")["caught"] > 0)
    shared = by_fault(["F-SHARED-DEF"])
    shared_caught = sum(m(v[0], a)["caught"] for v in shared for a in arms_present if m(v[0], a))
    L.append("## 1. Summary")
    L.append("")
    s = []
    s.append(f"Across {len(struct)} structural fault variants (F-REF, F-TYPE, F-CONTRACT), dbt v2 strict (Arm B) caught "
             f"{pre_b} before any model SQL executed on the warehouse, versus {pre_a} for dbt v1 (Arm A). "
             + (f"Both arms eventually caught all {caught_a} (the rest at runtime)."
                if caught_a == caught_b == len(struct) else
                f"In total, Arm B caught {caught_b} and Arm A caught {caught_a}."))
    if "C" in arms_present:
        s.append(f"On the {len(sem)} semantic fault variants that the reference can detect (F-SHARED-DEF excluded), "
                 f"the timeboxed manual spot check caught {sem_b} on v2 (Arm B) and {sem_a} on v1 (Arm A), while "
                 f"AI-generated reconciliation (Arm C) caught {c_caught_runs} of {c_runs} runs "
                 f"({c_all} variants in all {reps_c} repetitions, {c_any} in at least one).")
    else:
        s.append(f"On the {len(sem)} semantic fault variants that the reference can detect (F-SHARED-DEF excluded), "
                 f"the timeboxed manual spot check caught {sem_b} on v2 (Arm B) and {sem_a} on v1 (Arm A); Arm C has not run yet.")
    s.append(f"F-SHARED-DEF, where the reference dashboard shares the model's bug, was caught in {shared_caught} of "
             f"{sum(m(v[0], a)['reps'] for v in shared for a in arms_present if m(v[0], a))} runs across all arms, as hypothesized.")
    if "C" in arms_present:
        fpc = fp["per_arm"].get("C", {})
        if pending:
            s.append(f"On clean controls, Arm C raised at least one flag in {fpc.get('flagged_runs')} of "
                     f"{fpc.get('control_runs')} runs; its false-positive rate awaits adjudication of "
                     f"{fp['unlabeled']} item(s).")
        else:
            s.append(f"After adjudication, Arm C's false-positive rate on clean controls was "
                     f"{fpc['fp_runs']}/{fpc['control_runs']} runs.")
        cc = costs.get("C", {})
        if cc.get("mean_llm_cost_usd") is not None:
            s.append(f"Arm C cost a mean of {cc['mean_recon_queries']:.1f} executed reconciliation queries and "
                     f"${cc['mean_llm_cost_usd']:.3f} of LLM usage per validation that reached reconciliation "
                     f"(vs {costs.get('B', {}).get('mean_recon_queries', 0):.0f} queries and $0 for the manual check).")
    L.append(" ".join(s))
    L.append("")

    # ------------------------------------------------------------- 2. Tasks
    L.append("## 2. Tasks tested")
    L.append("")
    defs = definitions()
    L.append(md_table(["Metric model", "Grain", "Primary measure (manual check)", "Business definition"],
                      [[f"`{t}`", ", ".join(sp["grain"]), sp["primary_measure"], defs[t]] for t, sp in tasks().items()]))
    L.append("")

    # ------------------------------------------------------------- 3. Baseline
    L.append("## 3. Baseline (Arm A)")
    L.append("")
    L.append("Arm A is **dbt v1** `dbt build` (parse + compile + models + data tests + unit tests), followed by a "
             "**timeboxed manual spot check**: the grand total of the model's primary measure, and the total for "
             "the most recent period, each compared with the reference dashboard at ±"
             f"{tol['total_rel']:.1%}. These are the same two total-level queries for every task. **This simulates "
             "current practice under time pressure. It is an assumption, not a measurement of how any team actually "
             "validates.** Arm B is identical except for the engine (dbt v2 with mandatory strict static "
             "analysis run first as a gate). Arm C is Arm B with the spot check replaced by AI-generated reconciliation.")
    L.append("")

    # ------------------------------------------------------------- 4. Correctness
    L.append("## 4. How correctness was judged")
    L.append("")
    L.append("- **Detection** is scored against seeded ground truth: every variant carries exactly one known fault "
             "(or none, for clean controls). Each fault was verified before any arm ran to break the build or change "
             "the target model's output relative to golden (`results/fault_verification.json`).")
    L.append("- **Attribution.** An L1/L2 failure counts only if the failing node is the target model, or a test/unit "
             "test attached to it. An L3 flag counts only if the same query, re-run with the model output replaced "
             "by the golden output (same reference), does *not* flag. That proves the flag is caused by the seeded "
             "fault and not by a query bug or a pre-existing discrepancy.")
    L.append("- **False positives**: any failure or flag on a clean control, plus any unattributable flag on a fault "
             "variant, goes to `results/adjudication.csv` for a human label (true_issue / acceptable_difference / noise).")
    L.append(f"- **Frozen tolerances**: totals (single-row results) ±{tol['total_rel']:.1%}; slices (multi-row results) "
             f"±{tol['slice_rel']:.1%}; absolute floor {tol['abs_floor']} (differences below it always match); a slice "
             "missing on one side always flags. Golden-vs-reference verification used a relative tolerance of "
             f"{tol['reference_match_rel']}.")
    L.append("")

    # ------------------------------------------------------------- 5. Engine comparison
    L.append("## 5. Engine comparison (H1: Arm A vs Arm B)")
    L.append("")
    rows = []
    for vid, task, fid, hyp, cat in by_fault(STRUCTURAL + ASSERTION):
        a, b = m(vid, "A"), m(vid, "B")

        def desc(d):
            if not d:
                return "n/a"
            if not d["caught"]:
                return "missed"
            layer = next(k for k, v in d["layers"].items() if v and k != "none")
            return f"{layer}, {'before execution' if d['pre_exec'] else 'at runtime'}, {d['wq'][0]} queries"
        rows.append([f"`{vid}`", fid, desc(a), desc(b)])
    L.append(md_table(["Variant", "Fault", "Arm A (v1)", "Arm B (v2 strict)"], rows))
    L.append("")
    L.append("\"queries\" = `warehouse_queries_before_catch`: dbt nodes (models, tests, unit tests) that executed SQL on "
             "the warehouse up to and including the failing one. This is the earliness proxy for rework.")
    L.append("")
    by_f = defaultdict(lambda: {"n": 0, "a_pre": 0, "b_pre": 0, "a_c": 0, "b_c": 0, "a_wq": 0, "b_wq": 0})
    for vid, task, fid, hyp, cat in by_fault(STRUCTURAL + ASSERTION):
        a, b = m(vid, "A"), m(vid, "B")
        d = by_f[fid]
        d["n"] += 1
        d["a_pre"] += a["pre_exec"] if a else 0
        d["b_pre"] += b["pre_exec"] if b else 0
        d["a_c"] += a["caught"] if a else 0
        d["b_c"] += b["caught"] if b else 0
        d["a_wq"] += a["wq"][0] if a else 0
        d["b_wq"] += b["wq"][0] if b else 0
    cat_hyp = {f["id"]: f["hypothesized_v1_vs_v2"] for f in fault_catalog()["faults"]}
    L.append(md_table(
        ["Fault", "Variants", "v1 caught / before exec", "v2 caught / before exec", "Mean queries before catch (v1 → v2)", "Hypothesis (recorded before running)"],
        [[f, d["n"], f"{d['a_c']} / {d['a_pre']}", f"{d['b_c']} / {d['b_pre']}",
          f"{d['a_wq'] / d['n']:.0f} → {d['b_wq'] / d['n']:.0f}", cat_hyp.get(f, "")] for f, d in by_f.items()]))
    L.append("")

    # ------------------------------------------------------------- 6. Reconciliation comparison
    L.append("## 6. Reconciliation comparison (H2: Arm B vs Arm C)")
    L.append("")
    L.append(f"Cells show runs caught / runs, with the catching layer(s). Arm C ran {reps_c} repetitions per variant.")
    L.append("")
    cats = defaultdict(lambda: {a: [0, 0] for a in ARMS})
    for vid, task, fid, hyp, cat in fault_variants:
        for a in ARMS:
            d = m(vid, a)
            if d:
                cats[fid][a][0] += d["caught"]
                cats[fid][a][1] += d["reps"]
    L.append("**By fault category**")
    L.append("")
    L.append(md_table(["Fault", "Category", *[f"Arm {a}" for a in ARMS]],
                      [[fid, next(v[4] for v in fault_variants if v[2] == fid),
                        *[pct(*cats[fid][a]) if cats[fid][a][1] else "n/a" for a in ARMS]]
                       for fid in fault_order() if fid in cats]))
    L.append("")
    L.append("**By variant (hypothesized vs observed layer)**")
    L.append("")
    rows = []
    for vid, task, fid, hyp, cat in fault_variants:
        obs = sorted({k for a in ARMS if m(vid, a) for k, v in m(vid, a)["layers"].items() if v})
        rows.append([f"`{vid}`", hyp, cell(m(vid, "A")), cell(m(vid, "B")), cell(m(vid, "C")), ", ".join(obs)])
    L.append(md_table(["Variant", "Hypothesized", "Arm A", "Arm B", "Arm C", "Observed layers (any arm)"], rows))
    L.append("")
    margin = defaultdict(lambda: defaultdict(int))
    for f in read_csv(FLAGS_CSV):
        if f["arm"] == "C" and f["fault_id"] != "CONTROL" and _b(f["flagged"]) and _b(f["attributable"]):
            margin[f["variant_id"]][f["repetition"]] += 1
    mrows = []
    for vid, task, fid, hyp, cat in by_fault(SEMANTIC):
        d = m(vid, "C")
        if not d:
            continue
        counts = [margin[vid].get(str(rep), 0) for rep in range(1, d["reps"] + 1)]
        mrows.append([f"`{vid}`", ", ".join(map(str, counts)), min(counts)])
    if mrows:
        L.append("**Arm C catch margin**: attributable flagged queries per repetition. A margin of 1 means a "
                 "single generated query was the difference between a catch and a miss.")
        L.append("")
        L.append(md_table(["Variant", "Attributable flags per rep", "Min"], mrows))
        L.append("")
    L.append("Layer key: L1 structural, L2 assertion, L3 reconciliation; `L3-ai` = hypothesized to be caught only "
             "by broad AI reconciliation; `none` = hypothesized miss.")
    L.append("")

    # ------------------------------------------------------------- 7. False positives
    L.append("## 7. False positives (clean controls)")
    L.append("")
    if pending:
        L.append(f"**Withheld: {fp['unlabeled']} adjudication row(s) unlabeled.** Raw counts, *not* false-positive rates:")
        L.append("")
    rows = []
    for a in arms_present:
        d = fp["per_arm"].get(a, {})
        rows.append([f"Arm {a}", d.get("control_runs"), d.get("flagged_runs"), d.get("queries_executed"),
                     d.get("queries_flagged"),
                     "pending" if pending else f"{d['fp_runs']}/{d['control_runs']} ({(d['fp_rate'] or 0):.0%})",
                     "pending" if pending else d.get("true_issue_runs")])
    L.append(md_table(["Arm", "Control runs", "Runs with any flag/failure", "Recon queries executed",
                       "Recon queries flagged", "FP rate (runs)", "Runs flagged only for true issues"], rows))
    L.append("")
    unattr = [r for r in runs if r["fault_id"] != "CONTROL" and int(_f(r["unattributed_flags"])) > 0]
    L.append(f"Fault-variant runs that also raised unattributable flags: {len(unattr)} (listed in `adjudication.csv`).")
    L.append("")

    # ------------------------------------------------------------- 8. Cost
    L.append("## 8. Cost")
    L.append("")
    rows = []
    for a in arms_present:
        c = costs[a]
        rows.append([f"Arm {a}", c["runs"], c["validations_reaching_l3"], f"{c['mean_recon_queries']:.1f}",
                     f"{c['mean_recon_exec_s']:.3f}", f"{c['mean_llm_calls']:.2f}",
                     f"{c['mean_input_tokens']:.0f} / {c['mean_output_tokens']:.0f}",
                     "n/a" if c["mean_llm_cost_usd"] is None else f"${c['mean_llm_cost_usd']:.3f}",
                     "n/a" if c["total_llm_cost_usd"] is None else f"${c['total_llm_cost_usd']:.2f}",
                     f"{c['mean_llm_wall_s']:.0f}", f"{c['mean_wall_clock_s']:.1f}"])
    L.append(md_table(["Arm", "Runs", "Runs reaching L3", "Mean recon queries executed", "Mean recon exec time (s)",
                       "Mean LLM calls", "Mean tokens in/out", "Mean LLM cost / validation", "Total LLM cost",
                       "Mean LLM wall time (s)", "Mean run wall clock (s)"], rows))
    L.append("")
    L.append(f"LLM cost is the `total_cost_usd` reported by the claude CLI for `{cfg['llm']['model']}`. Means are over "
             "runs that reached reconciliation (L1/L2-caught runs never call the LLM). The warehouse is local DuckDB, "
             "so there is no warehouse cost; execution times do not transfer to cloud warehouses.")
    L.append("")

    # ------------------------------------------------------------- 9. Missed cases
    L.append("## 9. Missed cases")
    L.append("")
    for vid, task, fid, hyp, cat in fault_variants:
        misses = {a: m(vid, a) for a in arms_present if m(vid, a) and m(vid, a)["caught"] < m(vid, a)["reps"]}
        if not misses:
            continue
        v = ver.get(vid, {})
        d = v.get("diff", {})
        effect = []
        if d.get("rows_only_left") or d.get("rows_only_right"):
            effect.append(f"rows only in model {d['rows_only_left']}, only in golden {d['rows_only_right']}")
        for col, n in (d.get("columns_differing") or {}).items():
            mx = (d.get("max_rel_diff") or {}).get(col)
            effect.append(f"`{col}` differs in {n} rows" + (f" (max {mx:.2%})" if isinstance(mx, (int, float)) else ""))
        L.append(f"**`{vid}`** ({cat}; hypothesized {hyp}). Missed in: "
                 + ", ".join(f"Arm {a} {d_['reps'] - d_['caught']}/{d_['reps']}" for a, d_ in misses.items()) + ".")
        L.append("")
        L.append(f"- Fault effect vs golden: {'; '.join(effect) if effect else v.get('effect', 'n/a')}.")
        if fid == "F-SHARED-DEF":
            L.append("- Why: the reference dashboard was given the same definitional error (refunds included) through a "
                     "per-fault override, so the model and the reference agree. No reconciliation against this "
                     "reference can catch it. This is the designed blind spot of reconciliation.")
        for a, d_ in misses.items():
            arm_runs = [r for r in runs if r["variant_id"] == vid and r["arm"] == a and not _b(r["caught"])]
            for r in arm_runs:
                why = []
                if r["stopped_at"] not in ("none", "L3"):
                    why.append(f"workflow stopped at {r['stopped_at']} for an unattributable reason")
                if r["recon_queries_generated"] in ("0", 0) and r["stopped_at"] == "none":
                    why.append("no reconciliation queries were generated" + (f" ({r['recon_generation_error']})" if r["recon_generation_error"] else ""))
                why.append(f"dims_covered=[{r['dims_covered'] or '-'}], grains_covered=[{r['grains_covered'] or '-'}]")
                if fid == "F-TZ":
                    why.append("a daily slice was " + ("generated" if "day" in str(r["grains_covered"]).split(";") else "NOT generated"))
                if r["recon_queries_flagged"] not in ("0", 0):
                    why.append(f"{r['recon_queries_flagged']} queries flagged, none attributable to the fault")
                L.append(f"- Arm {a} rep {r['repetition']}: " + "; ".join(why) + ".")
        L.append("")

    # ------------------------------------------------------------- 10. Measured vs expected
    L.append("## 10. Measured vs expected")
    L.append("")
    L.append("**Measured (this harness, seeded faults, local DuckDB):**")
    L.append("")
    L.append(f"- Structural faults caught before warehouse execution: v1 {pre_a}/{len(struct)}, v2 strict {pre_b}/{len(struct)}.")
    L.append(f"- Semantic faults (excluding F-SHARED-DEF) caught by the manual spot check: Arm A {sem_a}/{len(sem)}, Arm B {sem_b}/{len(sem)} variants.")
    if "C" in arms_present:
        L.append(f"- Same faults caught by AI reconciliation: {c_caught_runs}/{c_runs} runs; {c_all}/{len(sem)} variants in every repetition.")
        if not pending:
            L.append(f"- Arm C false-positive rate on clean controls: {fp['per_arm']['C']['fp_runs']}/{fp['per_arm']['C']['control_runs']} runs.")
        cc = costs["C"]
        if cc.get("mean_llm_cost_usd") is not None:
            L.append(f"- Arm C mean cost per validation reaching L3: {cc['mean_recon_queries']:.1f} queries, "
                     f"{cc['mean_input_tokens']:.0f}/{cc['mean_output_tokens']:.0f} tokens, ${cc['mean_llm_cost_usd']:.3f}, "
                     f"{cc['mean_llm_wall_s']:.0f}s LLM latency.")
    L.append(f"- Shared-definition faults caught: {shared_caught} (expected 0).")
    L.append("")
    L.append("**Expected, not demonstrated here:**")
    L.append("")
    L.append("- *Reduced production rework.* Earlier detection (fewer warehouse queries before a catch, pre-execution "
             "catches) is only a proxy. Field study: compare time-to-fix and re-run counts on real PRs before and "
             "after adopting v2 strict plus AI reconciliation, over matched periods.")
    L.append("- *Fewer post-merge metric fixes.* Field study: count commits touching metric models within N days "
             "after merge that change output values, for teams with vs without the workflow (or before/after).")
    L.append("- *Fewer dashboard-mismatch tickets.* Field study: tag and count data-quality tickets that report a "
             "dashboard/model mismatch per quarter, before and after rollout, normalized by model count.")
    L.append("- *Generalization to real faults and real dashboards.* Field study: replay historical incident PRs "
             "(real bugs with known fixes) through the arms, using a production dashboard as the reference.")
    L.append("")

    # ------------------------------------------------------------- 11. Limitations
    L.append("## 11. Limitations")
    L.append("")
    L.append("- Seeded faults are cleaner and more isolated than real ones: one fault per variant, each in a single model.")
    L.append(f"- The sample is small: {len(tasks())} metric models, {len(fault_variants)} fault variants, "
             f"{len([v for v in variants if v[2] == 'CONTROL'])} clean controls, {reps_c} repetitions for Arm C.")
    L.append("- The faults, the tests, the reference dashboard and the checks were all designed by the same team "
             "(here, the same agent). Unit tests were deliberately written as happy-path tests.")
    agent_labeled = sum(1 for a in adj if "agent-labeled" in a.get("notes", ""))
    if agent_labeled:
        L.append(f"- Adjudication was not independent: {agent_labeled} of {len(adj)} adjudication labels were applied by "
                 "the AI agent that built the harness, at the user's direction (see `notes` in `adjudication.csv`). "
                 "A human should review them before the false-positive numbers are relied on.")
    L.append("- The manual baseline is simulated (two fixed total-level queries). Real reviewers vary.")
    L.append("- DuckDB was used: there is no warehouse cost, and execution times and cost numbers do not transfer to cloud warehouses.")
    L.append("- Evaluation-only data was seeded into jaffle-shop (QA test accounts, refunds) to give business filters "
             "something to act on; fault magnitudes depend on those seeds.")
    L.append(f"- The spec's default model `claude-sonnet-5-5` is not recognized by the installed claude CLI, which "
             f"silently falls back to another model. Arm C used `{cfg['llm']['model']}`, and every call is checked "
             "against the model the CLI reports.")
    L.append("- The reference dashboard has the same grain and column names as each model, which makes "
             "reconciliation queries easier to write than against a real dashboard with different naming and grain.")
    L.append("- Several mutations are conspicuous in the SQL the AI reads (a hard-coded remap, a `- interval 8 hour`, "
             "a `coalesce(x, 0)`, a dropped filter). That may steer query generation more than subtler real bugs would.")
    L.append("- The AI saw the (faulted) model SQL, as it would in a real review. Detection is credited only for "
             "flagged reconciliation queries, not for anything the model might have noticed by reading the code.")
    L.append("")
    L.append("## Appendix: arm isolation check")
    L.append("")
    L.extend(arm_isolation_check(runs))
    L.append("")
    (RESULTS / "report.md").write_text("\n".join(L) + "\n")
    print(f"wrote results/report.md ({'DRAFT, adjudication pending: ' + str(fp['unlabeled']) + ' unlabeled' if pending else 'final'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
