"""Paths, config loading and the config hash shared by every harness module."""
from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
PROJECT_DIR = ROOT / "reference_project"
REFERENCE_QUERIES = ROOT / "reference_dashboard" / "queries"
RESULTS = ROOT / "results"
GOLDEN_DIR = RESULTS / "golden"
WORK = ROOT / "work"
METRICS_DIR = PROJECT_DIR / "models" / "marts" / "metrics"


@lru_cache
def eval_config() -> dict:
    return yaml.safe_load((CONFIG_DIR / "eval.yaml").read_text())


@lru_cache
def fault_catalog() -> dict:
    return yaml.safe_load((CONFIG_DIR / "faults.yaml").read_text())


def config_hash() -> str:
    h = hashlib.sha256()
    for name in ("eval.yaml", "faults.yaml"):
        h.update((CONFIG_DIR / name).read_bytes())
    return h.hexdigest()[:12]


def tasks() -> dict[str, dict]:
    return eval_config()["tasks"]


def reference_sql(task: str) -> str:
    return (REFERENCE_QUERIES / f"{task}.sql").read_text()


def strip_sql(sql: str) -> str:
    """Drop comment-only lines and a trailing semicolon so SQL can be embedded."""
    lines = [ln for ln in sql.splitlines() if not ln.strip().startswith("--")]
    return "\n".join(lines).strip().rstrip(";")
