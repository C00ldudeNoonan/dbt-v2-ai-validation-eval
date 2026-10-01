# Seeded-fault evaluation: dbt v2 validation and AI-assisted reconciliation

> **DRAFT: adjudication pending.** 8 row(s) in `results/adjudication.csv` are unlabeled. False-positive rates are withheld until every row has a label (true_issue, acceptable_difference, noise). Re-run `python -m harness.report` after labeling.

Generated from `results/runs.csv` (225 runs). Config hash(es) in results: `e6ec2ffdc948`; current config: `e6ec2ffdc948`. Config did not change between runs.
Engines: dbt v1 `1.12.5`, dbt v2 `2.0.6`. Warehouse: duckdb. Arm C model: `claude-sonnet-5` via `claude_cli`.

## 1. Summary

Across 18 structural fault variants (F-REF, F-TYPE, F-CONTRACT), dbt v2 strict (Arm B) caught 11 before any model SQL executed on the warehouse, versus 0 for dbt v1 (Arm A). Both arms eventually caught all 18 (the rest at runtime). On the 13 semantic fault variants that the reference can detect (F-SHARED-DEF excluded), the timeboxed manual spot check caught 3 on v2 (Arm B) and 3 on v1 (Arm A), while AI-generated reconciliation (Arm C) caught 39 of 39 runs (13 variants in all 3 repetitions, 13 in at least one). F-SHARED-DEF, where the reference dashboard shares the model's bug, was caught in 0 of 10 runs across all arms, as hypothesized. On clean controls, Arm C raised at least one flag in 0 of 18 runs; its false-positive rate awaits adjudication of 8 item(s). Arm C cost a mean of 36.4 executed reconciliation queries and $0.155 of LLM usage per validation that reached reconciliation (vs 2 queries and $0 for the manual check).

## 2. Tasks tested

| Metric model | Grain | Primary measure (manual check) | Business definition |
|---|---|---|---|
| `monthly_revenue_by_location` | order_month, location_id | revenue_gross | Monthly revenue per store location. Revenue counts only qualifying orders: orders placed by real customers (internal "QA Test Account" customers are excluded) that have not been refunded. Months are calendar months of the store-local order timestamp. revenue_gross includes tax; revenue_pretax is the order subtotal. |
| `daily_order_counts` | order_date | order_count | Daily order activity. One row per calendar day (store-local order timestamp) with at least one qualifying order. Qualifying orders exclude internal "QA Test Account" customers and refunded orders. avg_items_per_order is the mean item count over orders that have item records; orders with no item records are excluded from the average rather than counted as zero. |
| `monthly_active_customers` | activity_month | active_customers | Monthly active customers. A customer is active in a calendar month if they placed at least one qualifying order that month (store-local time). Qualifying orders exclude internal "QA Test Account" customers and refunded orders. order_count is the number of qualifying orders in the month, and orders_per_active_customer is order_count divided by active_customers. |
| `customer_lifetime_value` | customer_id | lifetime_revenue | Lifetime value per customer. One row per real customer with at least one qualifying order (internal "QA Test Account" customers and refunded orders are excluded). lifetime_revenue is the sum of qualifying order totals including tax. avg_order_value is lifetime_revenue / lifetime_orders. avg_order_supply_cost is the mean supply cost over qualifying orders that have item records; orders with no item records are excluded from the average rather than counted as zero. |
| `product_margin_monthly` | order_month, product_id | revenue | Monthly units, revenue, supply cost and gross margin per product (SKU), from items on qualifying orders (internal "QA Test Account" customers and refunded orders are excluded). revenue is the sum of item list prices; supply_cost is the sum of each item's per-unit supply cost; gross_margin = revenue - supply_cost. |
| `new_vs_returning_customers_monthly` | order_month, customer_type | customers | Monthly customers, orders and revenue split by new vs returning. A customer is "new" in the calendar month of their first qualifying order and "returning" in every later month. Qualifying orders exclude internal "QA Test Account" customers and refunded orders, both when finding a customer's first order and when counting activity. |

## 3. Baseline (Arm A)

Arm A is **dbt v1** `dbt build` (parse + compile + models + data tests + unit tests), followed by a **timeboxed manual spot check**: the grand total of the model's primary measure, and the total for the most recent period, each compared with the reference dashboard at ±0.5%. These are the same two total-level queries for every task. **This simulates current practice under time pressure. It is an assumption, not a measurement of how any team actually validates.** Arm B is identical except for the engine (dbt v2 with mandatory strict static analysis run first as a gate). Arm C is Arm B with the spot check replaced by AI-generated reconciliation.

## 4. How correctness was judged

- **Detection** is scored against seeded ground truth: every variant carries exactly one known fault (or none, for clean controls). Each fault was verified before any arm ran to break the build or change the target model's output relative to golden (`results/fault_verification.json`).
- **Attribution.** An L1/L2 failure counts only if the failing node is the target model, or a test/unit test attached to it. An L3 flag counts only if the same query, re-run with the model output replaced by the golden output (same reference), does *not* flag. That proves the flag is caused by the seeded fault and not by a query bug or a pre-existing discrepancy.
- **False positives**: any failure or flag on a clean control, plus any unattributable flag on a fault variant, goes to `results/adjudication.csv` for a human label (true_issue / acceptable_difference / noise).
- **Frozen tolerances**: totals (single-row results) ±0.5%; slices (multi-row results) ±1.0%; absolute floor 1e-06 (differences below it always match); a slice missing on one side always flags. Golden-vs-reference verification used a relative tolerance of 1e-09.

## 5. Engine comparison (H1: Arm A vs Arm B)

| Variant | Fault | Arm A (v1) | Arm B (v2 strict) |
|---|---|---|---|
| `customer_lifetime_value__F-REF` | F-REF | L1, at runtime, 43 queries | L1, before execution, 0 queries |
| `daily_order_counts__F-REF` | F-REF | L1, at runtime, 46 queries | L1, before execution, 0 queries |
| `monthly_active_customers__F-REF` | F-REF | L1, at runtime, 48 queries | L1, before execution, 0 queries |
| `monthly_revenue_by_location__F-REF` | F-REF | L1, at runtime, 49 queries | L1, before execution, 0 queries |
| `new_vs_returning_customers_monthly__F-REF` | F-REF | L1, at runtime, 51 queries | L1, before execution, 0 queries |
| `product_margin_monthly__F-REF` | F-REF | L1, at runtime, 52 queries | L1, before execution, 0 queries |
| `customer_lifetime_value__F-TYPE` | F-TYPE | L1, at runtime, 43 queries | L1, before execution, 0 queries |
| `daily_order_counts__F-TYPE` | F-TYPE | L1, at runtime, 46 queries | L1, before execution, 0 queries |
| `monthly_active_customers__F-TYPE` | F-TYPE | L1, at runtime, 48 queries | L1, before execution, 0 queries |
| `monthly_revenue_by_location__F-TYPE` | F-TYPE | L1, at runtime, 49 queries | L1, before execution, 0 queries |
| `new_vs_returning_customers_monthly__F-TYPE` | F-TYPE | L1, at runtime, 51 queries | L1, at runtime, 47 queries |
| `product_margin_monthly__F-TYPE` | F-TYPE | L1, at runtime, 52 queries | L1, before execution, 0 queries |
| `customer_lifetime_value__F-CONTRACT` | F-CONTRACT | L2, at runtime, 43 queries | L1, at runtime, 52 queries |
| `daily_order_counts__F-CONTRACT` | F-CONTRACT | L1, at runtime, 47 queries | L1, at runtime, 47 queries |
| `monthly_active_customers__F-CONTRACT` | F-CONTRACT | L1, at runtime, 48 queries | L1, at runtime, 51 queries |
| `monthly_revenue_by_location__F-CONTRACT` | F-CONTRACT | L1, at runtime, 50 queries | L1, at runtime, 48 queries |
| `new_vs_returning_customers_monthly__F-CONTRACT` | F-CONTRACT | L1, at runtime, 51 queries | L1, at runtime, 46 queries |
| `product_margin_monthly__F-CONTRACT` | F-CONTRACT | L1, at runtime, 52 queries | L1, at runtime, 49 queries |
| `customer_lifetime_value__F-DUPKEY` | F-DUPKEY | L2, at runtime, 56 queries | L2, at runtime, 70 queries |
| `daily_order_counts__F-DUPKEY` | F-DUPKEY | L2, at runtime, 63 queries | L2, at runtime, 72 queries |
| `monthly_active_customers__F-DUPKEY` | F-DUPKEY | L2, at runtime, 67 queries | L2, at runtime, 74 queries |
| `monthly_revenue_by_location__F-DUPKEY` | F-DUPKEY | L2, at runtime, 69 queries | L2, at runtime, 72 queries |
| `new_vs_returning_customers_monthly__F-DUPKEY` | F-DUPKEY | L2, at runtime, 74 queries | L2, at runtime, 78 queries |
| `product_margin_monthly__F-DUPKEY` | F-DUPKEY | L2, at runtime, 78 queries | L2, at runtime, 57 queries |

"queries" = `warehouse_queries_before_catch`: dbt nodes (models, tests, unit tests) that executed SQL on the warehouse up to and including the failing one. This is the earliness proxy for rework.

| Fault | Variants | v1 caught / before exec | v2 caught / before exec | Mean queries before catch (v1 → v2) | Hypothesis (recorded before running) |
|---|---|---|---|---|---|
| F-REF | 6 | 6 / 0 | 6 / 6 | 48 → 0 | v2: L1 before execution (static analysis). v1: L1 at runtime (binder error when the model builds). |
| F-TYPE | 6 | 6 / 0 | 6 / 5 | 48 → 8 | v2 strict: L1 before execution (type inference). v1: L1 at runtime (DuckDB binder error) at best. |
| F-CONTRACT | 6 | 6 / 0 | 6 / 0 | 48 → 49 | v2: L1 before execution (inferred output schema vs contract). v1: L1 at runtime (contract preflight) for base-type drift. |
| F-DUPKEY | 6 | 6 / 0 | 6 / 0 | 68 → 70 | Same on both: L2 (unique / unique_combination_of_columns test) after the model builds. |

## 6. Reconciliation comparison (H2: Arm B vs Arm C)

Cells show runs caught / runs, with the catching layer(s). Arm C ran 3 repetitions per variant.

**By fault category**

| Fault | Category | Arm A | Arm B | Arm C |
|---|---|---|---|---|
| F-REF | Broken reference | 6/6 (100%) | 6/6 (100%) | 18/18 (100%) |
| F-TYPE | Type / signature error | 6/6 (100%) | 6/6 (100%) | 18/18 (100%) |
| F-CONTRACT | Contract violation | 6/6 (100%) | 6/6 (100%) | 18/18 (100%) |
| F-DUPKEY | Duplicate keys | 6/6 (100%) | 6/6 (100%) | 18/18 (100%) |
| F-FANOUT | Join fan-out | 2/3 (67%) | 2/3 (67%) | 9/9 (100%) |
| F-FILTER | Missing business filter | 0/4 (0%) | 0/4 (0%) | 12/12 (100%) |
| F-TZ | Time boundary | 1/2 (50%) | 1/2 (50%) | 6/6 (100%) |
| F-NULL | Null handling | 0/2 (0%) | 0/2 (0%) | 6/6 (100%) |
| F-SHARED-DEF | Definition drift shared with reference | 0/2 (0%) | 0/2 (0%) | 0/6 (0%) |
| F-OFFSET | Offsetting errors | 0/2 (0%) | 0/2 (0%) | 6/6 (100%) |

**By variant (hypothesized vs observed layer)**

| Variant | Hypothesized | Arm A | Arm B | Arm C | Observed layers (any arm) |
|---|---|---|---|---|---|
| `customer_lifetime_value__F-REF` | L1 | 1/1 (L1) | 1/1 (L1) | 3/3 (L1) | L1 |
| `daily_order_counts__F-REF` | L1 | 1/1 (L1) | 1/1 (L1) | 3/3 (L1) | L1 |
| `monthly_active_customers__F-REF` | L1 | 1/1 (L1) | 1/1 (L1) | 3/3 (L1) | L1 |
| `monthly_revenue_by_location__F-REF` | L1 | 1/1 (L1) | 1/1 (L1) | 3/3 (L1) | L1 |
| `new_vs_returning_customers_monthly__F-REF` | L1 | 1/1 (L1) | 1/1 (L1) | 3/3 (L1) | L1 |
| `product_margin_monthly__F-REF` | L1 | 1/1 (L1) | 1/1 (L1) | 3/3 (L1) | L1 |
| `customer_lifetime_value__F-TYPE` | L1 | 1/1 (L1) | 1/1 (L1) | 3/3 (L1) | L1 |
| `daily_order_counts__F-TYPE` | L1 | 1/1 (L1) | 1/1 (L1) | 3/3 (L1) | L1 |
| `monthly_active_customers__F-TYPE` | L1 | 1/1 (L1) | 1/1 (L1) | 3/3 (L1) | L1 |
| `monthly_revenue_by_location__F-TYPE` | L1 | 1/1 (L1) | 1/1 (L1) | 3/3 (L1) | L1 |
| `new_vs_returning_customers_monthly__F-TYPE` | L1 | 1/1 (L1) | 1/1 (L1) | 3/3 (L1) | L1 |
| `product_margin_monthly__F-TYPE` | L1 | 1/1 (L1) | 1/1 (L1) | 3/3 (L1) | L1 |
| `customer_lifetime_value__F-CONTRACT` | L1 | 1/1 (L2) | 1/1 (L1) | 3/3 (L1) | L1, L2 |
| `daily_order_counts__F-CONTRACT` | L1 | 1/1 (L1) | 1/1 (L1) | 3/3 (L1) | L1 |
| `monthly_active_customers__F-CONTRACT` | L1 | 1/1 (L1) | 1/1 (L1) | 3/3 (L1) | L1 |
| `monthly_revenue_by_location__F-CONTRACT` | L1 | 1/1 (L1) | 1/1 (L1) | 3/3 (L1) | L1 |
| `new_vs_returning_customers_monthly__F-CONTRACT` | L1 | 1/1 (L1) | 1/1 (L1) | 3/3 (L1) | L1 |
| `product_margin_monthly__F-CONTRACT` | L1 | 1/1 (L1) | 1/1 (L1) | 3/3 (L1) | L1 |
| `customer_lifetime_value__F-DUPKEY` | L2 | 1/1 (L2) | 1/1 (L2) | 3/3 (L2) | L2 |
| `daily_order_counts__F-DUPKEY` | L2 | 1/1 (L2) | 1/1 (L2) | 3/3 (L2) | L2 |
| `monthly_active_customers__F-DUPKEY` | L2 | 1/1 (L2) | 1/1 (L2) | 3/3 (L2) | L2 |
| `monthly_revenue_by_location__F-DUPKEY` | L2 | 1/1 (L2) | 1/1 (L2) | 3/3 (L2) | L2 |
| `new_vs_returning_customers_monthly__F-DUPKEY` | L2 | 1/1 (L2) | 1/1 (L2) | 3/3 (L2) | L2 |
| `product_margin_monthly__F-DUPKEY` | L2 | 1/1 (L2) | 1/1 (L2) | 3/3 (L2) | L2 |
| `customer_lifetime_value__F-FANOUT` | L3 | 1/1 (L3) | 1/1 (L3) | 3/3 (L3) | L3 |
| `monthly_active_customers__F-FANOUT` | L3-ai | 0/1 | 0/1 | 3/3 (L3) | L3, none |
| `product_margin_monthly__F-FANOUT` | L3 | 1/1 (L3) | 1/1 (L3) | 3/3 (L3) | L3 |
| `customer_lifetime_value__F-FILTER` | L3-ai | 0/1 | 0/1 | 3/3 (L3) | L3, none |
| `monthly_active_customers__F-FILTER` | L3-ai | 0/1 | 0/1 | 3/3 (L3) | L3, none |
| `monthly_revenue_by_location__F-FILTER` | L3-ai | 0/1 | 0/1 | 3/3 (L3) | L3, none |
| `new_vs_returning_customers_monthly__F-FILTER` | L3-ai | 0/1 | 0/1 | 3/3 (L3) | L3, none |
| `daily_order_counts__F-TZ` | L3-ai | 1/1 (L3) | 1/1 (L3) | 3/3 (L3) | L3 |
| `monthly_revenue_by_location__F-TZ` | none | 0/1 | 0/1 | 3/3 (L3) | L3, none |
| `customer_lifetime_value__F-NULL` | L3-ai | 0/1 | 0/1 | 3/3 (L3) | L3, none |
| `daily_order_counts__F-NULL` | L3-ai | 0/1 | 0/1 | 3/3 (L3) | L3, none |
| `customer_lifetime_value__F-SHARED-DEF` | none | 0/1 | 0/1 | 0/3 | none |
| `monthly_revenue_by_location__F-SHARED-DEF` | none | 0/1 | 0/1 | 0/3 | none |
| `monthly_revenue_by_location__F-OFFSET` | L3-ai | 0/1 | 0/1 | 3/3 (L3) | L3, none |
| `product_margin_monthly__F-OFFSET` | L3-ai | 0/1 | 0/1 | 3/3 (L3) | L3, none |

**Arm C catch margin**: attributable flagged queries per repetition. A margin of 1 means a single generated query was the difference between a catch and a miss.

| Variant | Attributable flags per rep | Min |
|---|---|---|
| `customer_lifetime_value__F-FANOUT` | 22, 21, 15 | 15 |
| `monthly_active_customers__F-FANOUT` | 14, 19, 12 | 12 |
| `product_margin_monthly__F-FANOUT` | 19, 24, 24 | 19 |
| `customer_lifetime_value__F-FILTER` | 14, 14, 16 | 14 |
| `monthly_active_customers__F-FILTER` | 2, 2, 4 | 2 |
| `monthly_revenue_by_location__F-FILTER` | 7, 7, 8 | 7 |
| `new_vs_returning_customers_monthly__F-FILTER` | 15, 13, 14 | 13 |
| `daily_order_counts__F-TZ` | 21, 17, 25 | 17 |
| `monthly_revenue_by_location__F-TZ` | 12, 14, 15 | 12 |
| `customer_lifetime_value__F-NULL` | 3, 2, 4 | 2 |
| `daily_order_counts__F-NULL` | 1, 2, 4 | 1 |
| `customer_lifetime_value__F-SHARED-DEF` | 0, 0, 0 | 0 |
| `monthly_revenue_by_location__F-SHARED-DEF` | 0, 0, 0 | 0 |
| `monthly_revenue_by_location__F-OFFSET` | 8, 9, 9 | 8 |
| `product_margin_monthly__F-OFFSET` | 13, 15, 15 | 13 |

Layer key: L1 structural, L2 assertion, L3 reconciliation; `L3-ai` = hypothesized to be caught only by broad AI reconciliation; `none` = hypothesized miss.

## 7. False positives (clean controls)

**Withheld: 8 adjudication row(s) unlabeled.** Raw counts, *not* false-positive rates:

| Arm | Control runs | Runs with any flag/failure | Recon queries executed | Recon queries flagged | FP rate (runs) | Runs flagged only for true issues |
|---|---|---|---|---|---|---|
| Arm A | 6 | 0 | 12 | 0 | pending | pending |
| Arm B | 6 | 0 | 12 | 0 | pending | pending |
| Arm C | 18 | 0 | 662 | 0 | pending | pending |

Fault-variant runs that also raised unattributable flags: 4 (listed in `adjudication.csv`).

## 8. Cost

| Arm | Runs | Runs reaching L3 | Mean recon queries executed | Mean recon exec time (s) | Mean LLM calls | Mean tokens in/out | Mean LLM cost / validation | Total LLM cost | Mean LLM wall time (s) | Mean run wall clock (s) |
|---|---|---|---|---|---|---|---|---|---|---|
| Arm A | 45 | 21 | 2.0 | 0.002 | 0.00 | 0 / 0 | n/a | n/a | 0 | 7.1 |
| Arm B | 45 | 21 | 2.0 | 0.002 | 0.00 | 0 / 0 | n/a | n/a | 0 | 1.8 |
| Arm C | 135 | 63 | 36.4 | 0.025 | 1.02 | 3072 / 14246 | $0.155 | $9.75 | 103 | 49.7 |

LLM cost is the `total_cost_usd` reported by the claude CLI for `claude-sonnet-5`. Means are over runs that reached reconciliation (L1/L2-caught runs never call the LLM). The warehouse is local DuckDB, so there is no warehouse cost; execution times do not transfer to cloud warehouses.

## 9. Missed cases

**`monthly_active_customers__F-FANOUT`** (Join fan-out; hypothesized L3-ai). Missed in: Arm A 1/1, Arm B 1/1.

- Fault effect vs golden: `order_count` differs in 12 rows (max 58.84%); `orders_per_active_customer` differs in 12 rows (max 58.84%).
- Arm A rep 1: dims_covered=[-], grains_covered=[month;total].
- Arm B rep 1: dims_covered=[-], grains_covered=[month;total].

**`customer_lifetime_value__F-FILTER`** (Missing business filter; hypothesized L3-ai). Missed in: Arm A 1/1, Arm B 1/1.

- Fault effect vs golden: rows only in model 8, only in golden 0.
- Arm A rep 1: dims_covered=[-], grains_covered=[month;total].
- Arm B rep 1: dims_covered=[-], grains_covered=[month;total].

**`monthly_active_customers__F-FILTER`** (Missing business filter; hypothesized L3-ai). Missed in: Arm A 1/1, Arm B 1/1.

- Fault effect vs golden: `active_customers` differs in 1 rows (max 1.29%); `order_count` differs in 1 rows (max 1.97%); `orders_per_active_customer` differs in 1 rows (max 0.67%).
- Arm A rep 1: dims_covered=[-], grains_covered=[month;total].
- Arm B rep 1: dims_covered=[-], grains_covered=[month;total].

**`monthly_revenue_by_location__F-FILTER`** (Missing business filter; hypothesized L3-ai). Missed in: Arm A 1/1, Arm B 1/1.

- Fault effect vs golden: `order_count` differs in 1 rows (max 6.02%); `revenue_pretax` differs in 1 rows (max 10.36%); `revenue_gross` differs in 1 rows (max 10.36%).
- Arm A rep 1: dims_covered=[-], grains_covered=[month;total].
- Arm B rep 1: dims_covered=[-], grains_covered=[month;total].

**`new_vs_returning_customers_monthly__F-FILTER`** (Missing business filter; hypothesized L3-ai). Missed in: Arm A 1/1, Arm B 1/1.

- Fault effect vs golden: `customers` differs in 1 rows (max 2.83%); `order_count` differs in 1 rows (max 5.43%); `revenue_gross` differs in 1 rows (max 9.23%).
- Arm A rep 1: dims_covered=[-], grains_covered=[month;total].
- Arm B rep 1: dims_covered=[-], grains_covered=[month;total].

**`monthly_revenue_by_location__F-TZ`** (Time boundary; hypothesized none). Missed in: Arm A 1/1, Arm B 1/1.

- Fault effect vs golden: rows only in model 1, only in golden 0; `order_count` differs in 17 rows (max 1.02%); `revenue_pretax` differs in 17 rows (max 0.63%); `revenue_gross` differs in 17 rows (max 0.63%).
- Arm A rep 1: dims_covered=[-], grains_covered=[month;total]; a daily slice was NOT generated.
- Arm B rep 1: dims_covered=[-], grains_covered=[month;total]; a daily slice was NOT generated.

**`customer_lifetime_value__F-NULL`** (Null handling; hypothesized L3-ai). Missed in: Arm A 1/1, Arm B 1/1.

- Fault effect vs golden: `avg_order_supply_cost` differs in 85 rows (max 40.00%).
- Arm A rep 1: dims_covered=[-], grains_covered=[month;total].
- Arm B rep 1: dims_covered=[-], grains_covered=[month;total].

**`daily_order_counts__F-NULL`** (Null handling; hypothesized L3-ai). Missed in: Arm A 1/1, Arm B 1/1.

- Fault effect vs golden: `avg_items_per_order` differs in 246 rows (max 14.29%).
- Arm A rep 1: dims_covered=[-], grains_covered=[day;total].
- Arm B rep 1: dims_covered=[-], grains_covered=[day;total].

**`customer_lifetime_value__F-SHARED-DEF`** (Definition drift shared with reference; hypothesized none). Missed in: Arm A 1/1, Arm B 1/1, Arm C 3/3.

- Fault effect vs golden: `first_order_date` differs in 12 rows; `last_order_date` differs in 13 rows; `lifetime_orders` differs in 502 rows (max 25.00%); `lifetime_revenue` differs in 500 rows (max 36.18%); `avg_order_value` differs in 501 rows (max 8.94%); `avg_order_supply_cost` differs in 500 rows (max 29.18%).
- Why: the reference dashboard was given the same definitional error (refunds included) through a per-fault override, so the model and the reference agree. No reconciliation against this reference can catch it. This is the designed blind spot of reconciliation.
- Arm A rep 1: dims_covered=[-], grains_covered=[month;total].
- Arm B rep 1: dims_covered=[-], grains_covered=[month;total].
- Arm C rep 1: dims_covered=[customer_id;customer_name;first_order_date;last_order_date;lifetime_orders], grains_covered=[day;month;none;quarter;week;year].
- Arm C rep 2: dims_covered=[customer_id;first_order_date;last_order_date;lifetime_orders_bucket], grains_covered=[month;none;quarter;year].
- Arm C rep 3: dims_covered=[customer_id;customer_name;first_order_date;last_order_date;lifetime_orders], grains_covered=[day;month;none;quarter;week;year].

**`monthly_revenue_by_location__F-SHARED-DEF`** (Definition drift shared with reference; hypothesized none). Missed in: Arm A 1/1, Arm B 1/1, Arm C 3/3.

- Fault effect vs golden: `order_count` differs in 18 rows (max 1.83%); `revenue_pretax` differs in 18 rows (max 1.99%); `revenue_gross` differs in 18 rows (max 1.99%).
- Why: the reference dashboard was given the same definitional error (refunds included) through a per-fault override, so the model and the reference agree. No reconciliation against this reference can catch it. This is the designed blind spot of reconciliation.
- Arm A rep 1: dims_covered=[-], grains_covered=[month;total].
- Arm B rep 1: dims_covered=[-], grains_covered=[month;total].
- Arm C rep 1: dims_covered=[location_id;location_name;order_month], grains_covered=[month;none;quarter;year].
- Arm C rep 2: dims_covered=[location_id;order_month], grains_covered=[month;none;quarter;year].
- Arm C rep 3: dims_covered=[location_id;location_name;order_month], grains_covered=[month;none;quarter;year].

**`monthly_revenue_by_location__F-OFFSET`** (Offsetting errors; hypothesized L3-ai). Missed in: Arm A 1/1, Arm B 1/1.

- Fault effect vs golden: `order_count` differs in 2 rows (max 15.01%); `revenue_pretax` differs in 2 rows (max 15.75%); `revenue_gross` differs in 2 rows (max 15.75%).
- Arm A rep 1: dims_covered=[-], grains_covered=[month;total].
- Arm B rep 1: dims_covered=[-], grains_covered=[month;total].

**`product_margin_monthly__F-OFFSET`** (Offsetting errors; hypothesized L3-ai). Missed in: Arm A 1/1, Arm B 1/1.

- Fault effect vs golden: rows only in model 0, only in golden 12; `units_sold` differs in 12 rows (max 122.62%); `revenue` differs in 12 rows (max 122.62%); `supply_cost` differs in 12 rows (max 80.07%); `gross_margin` differs in 12 rows (max 141.29%).
- Arm A rep 1: dims_covered=[-], grains_covered=[month;total].
- Arm B rep 1: dims_covered=[-], grains_covered=[month;total].

## 10. Measured vs expected

**Measured (this harness, seeded faults, local DuckDB):**

- Structural faults caught before warehouse execution: v1 0/18, v2 strict 11/18.
- Semantic faults (excluding F-SHARED-DEF) caught by the manual spot check: Arm A 3/13, Arm B 3/13 variants.
- Same faults caught by AI reconciliation: 39/39 runs; 13/13 variants in every repetition.
- Arm C mean cost per validation reaching L3: 36.4 queries, 3072/14246 tokens, $0.155, 103s LLM latency.
- Shared-definition faults caught: 0 (expected 0).

**Expected, not demonstrated here:**

- *Reduced production rework.* Earlier detection (fewer warehouse queries before a catch, pre-execution catches) is only a proxy. Field study: compare time-to-fix and re-run counts on real PRs before and after adopting v2 strict plus AI reconciliation, over matched periods.
- *Fewer post-merge metric fixes.* Field study: count commits touching metric models within N days after merge that change output values, for teams with vs without the workflow (or before/after).
- *Fewer dashboard-mismatch tickets.* Field study: tag and count data-quality tickets that report a dashboard/model mismatch per quarter, before and after rollout, normalized by model count.
- *Generalization to real faults and real dashboards.* Field study: replay historical incident PRs (real bugs with known fixes) through the arms, using a production dashboard as the reference.

## 11. Limitations

- Seeded faults are cleaner and more isolated than real ones: one fault per variant, each in a single model.
- The sample is small: 6 metric models, 39 fault variants, 6 clean controls, 3 repetitions for Arm C.
- The faults, the tests, the reference dashboard and the checks were all designed by the same team (here, the same agent). Unit tests were deliberately written as happy-path tests.
- The manual baseline is simulated (two fixed total-level queries). Real reviewers vary.
- DuckDB was used: there is no warehouse cost, and execution times and cost numbers do not transfer to cloud warehouses.
- Evaluation-only data was seeded into jaffle-shop (QA test accounts, refunds) to give business filters something to act on; fault magnitudes depend on those seeds.
- The spec's default model `claude-sonnet-5-5` is not recognized by the installed claude CLI, which silently falls back to another model. Arm C used `claude-sonnet-5`, and every call is checked against the model the CLI reports.
- The reference dashboard has the same grain and column names as each model, which makes reconciliation queries easier to write than against a real dashboard with different naming and grain.
- Several mutations are conspicuous in the SQL the AI reads (a hard-coded remap, a `- interval 8 hour`, a `coalesce(x, 0)`, a dropped filter). That may steer query generation more than subtler real bugs would.
- The AI saw the (faulted) model SQL, as it would in a real review. Detection is credited only for flagged reconciliation queries, not for anything the model might have noticed by reading the code.

## Appendix: arm isolation check

- Arm A: engine=v1 (1.12.5), static-analysis gate=False, reconciliation=manual. Matches config, single-valued across all runs.
- Arm B: engine=v2 (2.0.6), static-analysis gate=True, reconciliation=manual. Matches config, single-valued across all runs.
- Arm C: engine=v2 (2.0.6), static-analysis gate=True, reconciliation=ai. Matches config, single-valued across all runs.
- Config keys that differ A vs B: ['engine', 'static_analysis_gate']. B vs C: ['reconciliation']. (A vs B: engine; v2's mandatory strict gate comes with the engine. B vs C: reconciliation only.)

