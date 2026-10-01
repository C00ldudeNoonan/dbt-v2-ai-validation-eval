"""Run dbt commands in venv-v1 or venv-v2 against an isolated workspace."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from harness.common import PROJECT_DIR, ROOT, eval_config
from harness.warehouse import clone_warehouse

ANSI = re.compile(r"\x1b\[[0-9;]*m")
COPY_IGNORE = shutil.ignore_patterns("target", "logs", "*.duckdb", "*.duckdb.wal", ".user.yml")


@dataclass
class NodeResult:
    unique_id: str
    status: str
    message: str = ""
    resource_type: str = ""
    started_at: str = ""


@dataclass
class DbtResult:
    engine: str
    args: list[str]
    returncode: int
    output: str
    wall_s: float
    nodes: list[NodeResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.returncode == 0


@dataclass
class Workspace:
    """An isolated copy of the dbt project plus its own DuckDB warehouse file."""

    root: Path

    def __post_init__(self) -> None:
        self.root = Path(self.root).resolve()

    @property
    def project(self) -> Path:
        return self.root / "project"

    @property
    def db(self) -> Path:
        return self.root / "warehouse.duckdb"

    @classmethod
    def create(cls, root: Path) -> "Workspace":
        root = Path(root).resolve()
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True)
        ws = cls(root)
        shutil.copytree(PROJECT_DIR, ws.project, ignore=COPY_IGNORE)
        clone_warehouse(ws.db)
        return ws


def dbt_executable(engine: str) -> Path:
    return ROOT / eval_config()["engines"][engine]["venv"] / "bin" / "dbt"


@lru_cache
def engine_version(engine: str) -> str:
    out = subprocess.run([str(dbt_executable(engine)), "--version"], capture_output=True, text=True).stdout
    out = ANSI.sub("", out)
    m = re.search(r"installed:\s*([\w.\-]+)", out) or re.search(r"dbt[^\d]*(\d+\.\d+\.\d+)", out)
    return m.group(1) if m else out.strip().splitlines()[0]


def run_dbt(engine: str, ws: Workspace, args: list[str], timeout_s: int = 900) -> DbtResult:
    env = {
        **os.environ,
        "DBT_PROFILES_DIR": str(ws.project),
        "EVAL_DUCKDB_PATH": str(ws.db),
        "DBT_ENGINE_NO_WARN_SEMANTIC_MANIFEST_VALIDATION": "1",
        "DBT_SEND_ANONYMOUS_USAGE_STATS": "false",
        "DBT_DO_NOT_TRACK": "1",
        "NO_COLOR": "1",
    }
    threads = str(eval_config()["dbt"]["threads"])
    run_results = ws.project / "target" / "run_results.json"
    run_results.unlink(missing_ok=True)
    cmd = [str(dbt_executable(engine)), *args]
    if args and args[0] in ("build", "run", "test", "compile", "seed"):
        cmd += ["--threads", threads]
    start = time.monotonic()
    proc = subprocess.run(cmd, cwd=ws.project, env=env, capture_output=True, text=True, timeout=timeout_s)
    wall = time.monotonic() - start
    output = ANSI.sub("", proc.stdout + proc.stderr)
    return DbtResult(engine, args, proc.returncode, output, wall, _parse_run_results(run_results))


def _parse_run_results(path: Path) -> list[NodeResult]:
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    nodes = []
    for r in data.get("results", []):
        uid = r.get("unique_id", "")
        starts = [t.get("started_at") or "" for t in r.get("timing") or []]
        nodes.append(NodeResult(
            uid, str(r.get("status", "")).lower(), r.get("message") or "", uid.split(".")[0], min(starts, default=""),
        ))
    # threads=1, but v2 still reports results out of order; sort by start time.
    return sorted(nodes, key=lambda n: n.started_at)
