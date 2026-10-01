"""Run the full matrix end to end.

    python -m harness.run_all                 # all arms, all variants, then score + report
    python -m harness.run_all --arms A,B      # subset of arms
    python -m harness.run_all --fresh         # discard previous raw results first

Runs are resumable. A (variant, arm, repetition) whose results/raw/<key>.json already
exists with the current config_hash is skipped.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

from harness.common import GOLDEN_DIR, PROJECT_DIR, ROOT, config_hash, eval_config, tasks
from harness.mutate import all_variants
from harness.run_arm import RAW_DIR, run, run_key
from harness.warehouse import BASE_WAREHOUSE, build_base_warehouse


def preflight() -> None:
    if not (PROJECT_DIR / "dbt_packages" / "dbt_utils").exists():
        print("installing dbt packages ...")
        subprocess.run([str(ROOT / "venv-v1" / "bin" / "dbt"), "deps"], cwd=PROJECT_DIR, check=True,
                       env={**os.environ, "DBT_PROFILES_DIR": str(PROJECT_DIR),
                            "EVAL_DUCKDB_PATH": str(BASE_WAREHOUSE)})
    if not BASE_WAREHOUSE.exists():
        print("building base warehouse ...")
        build_base_warehouse()
    if not all((GOLDEN_DIR / f"{t}.parquet").exists() for t in tasks()):
        print("building golden snapshots + verifying reference ...")
        from harness import golden
        if golden.main() != 0:
            sys.exit("reference dashboard does not match golden; fix before running")


def _done(key: str, h: str) -> bool:
    p = RAW_DIR / f"{key}.json"
    if not p.exists():
        return False
    try:
        return json.loads(p.read_text())["row"]["config_hash"] == h
    except (json.JSONDecodeError, KeyError):
        return False


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--arms", default="A,B,C")
    p.add_argument("--variants", default="", help="substring filter on variant_id")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--fresh", action="store_true")
    p.add_argument("--no-report", action="store_true")
    a = p.parse_args()

    preflight()
    if a.fresh and RAW_DIR.exists():
        shutil.rmtree(RAW_DIR)
    cfg, h = eval_config(), config_hash()
    arms = [x.strip() for x in a.arms.split(",") if x.strip()]
    jobs = []
    for v in all_variants():
        if a.variants and a.variants not in v.variant_id:
            continue
        for arm in arms:
            for rep in range(1, cfg["arms"][arm]["repetitions"] + 1):
                if not _done(run_key(v.variant_id, arm, rep), h):
                    jobs.append((v.variant_id, arm, rep))
    print(f"config_hash={h}  {len(jobs)} runs to do (arms {','.join(arms)})")

    failures = []
    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        futs = {pool.submit(run, *job): job for job in jobs}
        for i, fut in enumerate(as_completed(futs), 1):
            job = futs[fut]
            try:
                row = fut.result()["row"]
                print(f"[{i}/{len(jobs)}] {run_key(*job):70} caught={row['caught']!s:5} "
                      f"layer={row['caught_by_layer']:4} pre_exec={row['caught_before_execution']!s:5} "
                      f"recon={row['recon_queries_executed']}/{row['recon_queries_generated']} {row['wall_clock_s']}s",
                      flush=True)
            except Exception as e:  # noqa: BLE001 - keep going; failed runs are retried next time
                failures.append((job, f"{type(e).__name__}: {e}"))
                print(f"[{i}/{len(jobs)}] {run_key(*job)} FAILED: {type(e).__name__}: {e}", flush=True)
                traceback.print_exc(limit=2)
    print(f"finished in {time.monotonic() - start:.0f}s; {len(failures)} failed runs")
    for job, err in failures:
        print("  FAILED", run_key(*job), err[:300])

    from harness import score
    score.main()
    if not a.no_report:
        from harness import report
        report.main()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
