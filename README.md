# dbt-v2-ai-validation-eval

A seeded-fault evaluation of dbt v2 validation and AI-assisted reconciliation. It
implements `SPEC-validation-eval.md`. Known faults are planted in dbt metric models, each
faulted model runs through three validation workflows (arms), and the harness records what
each one catches, at which layer, how early, at what cost, and with what false-positive rate.

| Arm | Engine | L1 | L2 | L3 |
|---|---|---|---|---|
| A | dbt v1 (dbt-core 1.12.5) | parse/compile/runtime | `dbt build` tests | timeboxed manual spot check (2 totals) |
| B | dbt v2 (2.0.6), `+static_analysis: strict` | strict static-analysis gate (`dbt compile`), then runtime | `dbt build` tests | same manual spot check |
| C | same as B | same as B | same as B | AI-generated reconciliation (up to 40 queries, 3 repetitions) |

## Quick start

```bash
./setup_env.sh                       # venv-v1 and venv-v2 (separate on purpose)
claude auth login                    # Arm C calls `claude -p`
venv-v1/bin/python -m harness.run_all          # full matrix -> results/
venv-v1/bin/python -m pytest -q tests          # harness self-tests
```

`run_all` is resumable: results are cached per (variant, arm, repetition) in `results/raw/`,
keyed by `config_hash`. Other entry points:

| Command | What it does |
|---|---|
| `python -m harness.golden` | Builds the clean project on both engines, snapshots `results/golden/`, verifies the reference dashboard |
| `python -m harness.mutate --list` / `--verify` | Lists variants / checks every fault changes output or breaks the build |
| `python -m harness.run_arm <variant> <A/B/C> --rep N --keep` | Runs a single run, keeping the workspace for debugging |
| `python -m harness.score` | Rebuilds `runs.csv`, `flags.csv` and `adjudication.csv` (keeps existing labels) |
| `python -m harness.report` | Renders `results/report.md` |
| `python -m harness.report_html` | Renders the shareable `results/report.html` (with a hand-written executive summary) |

The only manual inputs are the `claude` login, the fault-catalog review (done; the catalog is frozen) and the
adjudication labels.

## Adjudication

`results/adjudication.csv` lists every flag or failure on a clean control, and every flag on a
fault variant that could not be attributed to the seeded fault (its golden counterfactual also
flagged). Fill the `label` column with `true_issue`, `acceptable_difference` or `noise` (and
optionally `notes`), then re-run `python -m harness.score && python -m harness.report`. The report
withholds false-positive rates until every row is labeled.

## How it works

- **Warehouse**: local DuckDB. Raw tables are loaded once with explicit types (`harness/warehouse.py`) and
  copied into every isolated workspace, so both engines read identical data.
- **Workspaces**: each run gets `work/runs/<variant>__<arm>__r<rep>/` with its own project copy and DuckDB file.
- **Mutations** (`config/faults.yaml`) are exact find/replace edits that must match exactly once, and they
  may only touch the target model's own `.sql`/`.yml` files.
- **Reconciliation** queries run in an in-memory DuckDB sandbox that contains only `model_output` and
  `reference_output`, and must return `(slice, model_value, reference_value)`. A one-row result is held
  to ±0.5%, a multi-row result to ±1%.
- **Attribution**: an L3 flag counts only if the same query against the *golden* output (same reference)
  does not flag. An L1/L2 failure counts only if it is the target model or a test or unit test attached to it.

## Adaptations to the vendored jaffle-shop (dbt-labs/jaffle-shop@5beb145)

Migration findings (needed to make the **clean** project pass, not faults):
- `require-dbt-version` relaxed from `>=2.0.0` to `>=1.10.0` so v1 can run it; the `dbt-cloud` block and
  the unused `audit_helper` package were removed.
- **v2 strict**: `metricflow_time_spine.sql` passed date bounds to `dbt.date_spine`, which compares a
  timestamp with a date. DuckDB allows that implicitly; v2 strict rejects it (`dbt0407 InvalidComparison`).
  The bounds are now cast to timestamp.

Evaluation additions:
- `harness/augment_seeds.py` (deterministic) appends 8 "QA Test Account" customers with 120 orders at Brooklyn
  (2025-03-10..16) and writes `raw_refunds.csv` (~1.5% of orders). jaffle-shop has no status, refund or test
  data, so F-FILTER and F-SHARED-DEF need these.
- `stg_customers.is_test_account`, `stg_orders.ordered_at_ts` (untruncated timestamp, needed by F-TZ),
  and a new `stg_refunds` model.
- Six metric models in `models/marts/metrics/`, each with an enforced contract, data tests and a business
  definition. Three have happy-path unit tests.
- The reference dashboard (`reference_dashboard/queries/`) reads only `raw.*` tables, with a deliberately
  different code path (cents arithmetic, `not exists` for refunds, no dbt macros).

## Deviations from the spec

- **Arm C model**: `claude-sonnet-5` through `claude -p`, not `claude-sonnet-5-5`. The installed CLI
  (2.1.259) does not recognize `claude-sonnet-5-5` and silently falls back to a different model. The
  harness checks the model the CLI reports on every call and fails the run if it doesn't match.
- **Catalog adaptations** (decided during fault verification, before any arm ran) are documented at the top
  of `config/faults.yaml`: new_vs_returning × F-OFFSET was dropped (it changed nothing), so there are
  45 variants (39 faults + 6 controls).
