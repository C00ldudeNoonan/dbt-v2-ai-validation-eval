"""AI-generated reconciliation (Arm C).

The LLM gets the model SQL, the YAML business definition, and the output schemas
of the model and the reference. It never sees the fault id, the catalog or any hint.
The prompt template is identical for every variant, including clean controls.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
import urllib.request
from dataclasses import dataclass

import yaml

from harness.common import eval_config
from harness.layers.recon_common import ReconQuery

SYSTEM_PROMPT = """You are a meticulous analytics engineer validating a dbt metric model against a trusted reference dashboard before merge.
You write DuckDB SQL reconciliation queries. You respond with a single JSON object and nothing else."""

PROMPT_TEMPLATE = """A dbt model has been changed and must be reconciled against an independent reference dashboard before it ships.

## Model: {model_name}

### Business definition (from the model's YAML)
{definition}

### Model SQL (dbt/Jinja, DuckDB dialect)
```sql
{model_sql}
```

## Tables available to your queries
Your queries run in a sandbox that contains exactly two tables and nothing else:

`model_output`: the model's output.
{model_schema}

`reference_output`: the trusted reference dashboard, computed independently from raw data at the same grain.
{reference_schema}

Grain (one row per): {grain}

## Task
Write up to {max_queries} reconciliation queries comparing `model_output` to `reference_output`. Choose slices that would expose wrong numbers that still pass schema checks and data tests, for example: grand totals of each measure; totals by each dimension and dimension member; each available time grain (day, week, month, as applicable); edge periods (first/last periods, period boundaries); row counts and key coverage (keys present in one table but not the other); and averages/ratios where nulls or join fan-out could distort them.

Each query MUST return exactly these columns:
- `slice` (varchar): a human-readable label for the row, e.g. 'total', '2025-03 | Brooklyn'
- `model_value` (numeric): the value computed from model_output
- `reference_value` (numeric): the same value computed from reference_output

A query may return one row (a total) or many rows (one per slice). Use a full outer join on the slice keys so that slices missing on either side appear, with NULL on the missing side. Do not compute differences yourself; the harness compares model_value to reference_value. Return at most 5000 rows per query.

Respond with only this JSON object:
{{"queries": [{{"id": "short_snake_case_id", "kind": "total|dimension|time_grain|edge|coverage|ratio", "measure": "<column compared, or row_count>", "dimensions": ["<columns sliced by>"], "time_grain": "none|day|week|month|quarter|year", "description": "<one sentence>", "sql": "<DuckDB SQL>"}}]}}"""


@dataclass
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    model_reported: str
    wall_s: float


class ModelMismatch(RuntimeError):
    pass


def _schema_text(schema: list[tuple[str, str]]) -> str:
    return "\n".join(f"  - {name}: {dtype}" for name, dtype in schema)


def build_prompt(task: str, model_sql: str, model_yml: str,
                 model_schema: list[tuple[str, str]], reference_schema: list[tuple[str, str]]) -> str:
    doc = yaml.safe_load(model_yml)
    model_doc = next(m for m in doc["models"] if m["name"] == task)
    definition = " ".join(str(model_doc.get("description", "")).split())
    return PROMPT_TEMPLATE.format(
        model_name=task,
        definition=definition,
        model_sql=model_sql.strip(),
        model_schema=_schema_text(model_schema),
        reference_schema=_schema_text(reference_schema),
        grain=", ".join(eval_config()["tasks"][task]["grain"]),
        max_queries=eval_config()["llm"]["max_queries"],
    )


def _call_claude_cli(prompt: str, model: str, timeout_s: int) -> LLMResponse:
    cmd = [
        "claude", "-p", "--model", model, "--system-prompt", SYSTEM_PROMPT,
        "--tools", "", "--setting-sources", "", "--strict-mcp-config", "--disable-slash-commands",
        "--output-format", "json", "--no-session-persistence",
    ]
    start = time.monotonic()
    with tempfile.TemporaryDirectory() as empty:  # no CLAUDE.md / project context
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=empty, timeout=timeout_s)
    wall = time.monotonic() - start
    out = proc.stdout
    i = out.find('{"')
    if i < 0:
        raise RuntimeError(f"claude CLI returned no JSON (rc={proc.returncode}): {(out + proc.stderr)[-500:]}")
    data = json.loads(out[i:])
    if data.get("is_error"):
        raise RuntimeError(f"claude CLI error: {data.get('result')}")
    reported = list((data.get("modelUsage") or {}).keys())
    if not any(r.startswith(model) for r in reported):
        raise ModelMismatch(f"requested {model} but CLI reports {reported}")
    u = data.get("usage") or {}
    in_tok = int(u.get("input_tokens", 0)) + int(u.get("cache_creation_input_tokens", 0)) + int(u.get("cache_read_input_tokens", 0))
    return LLMResponse(data.get("result", ""), in_tok, int(u.get("output_tokens", 0)),
                       data.get("total_cost_usd"), ",".join(reported), wall)


def _call_anthropic_api(prompt: str, model: str, timeout_s: int) -> LLMResponse:
    key = os.environ["ANTHROPIC_API_KEY"]
    body = json.dumps({
        "model": model, "max_tokens": 32000, "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    start = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        data = json.loads(resp.read())
    wall = time.monotonic() - start
    if not data.get("model", "").startswith(model):
        raise ModelMismatch(f"requested {model} but API reports {data.get('model')}")
    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    u = data.get("usage", {})
    return LLMResponse(text, int(u.get("input_tokens", 0)), int(u.get("output_tokens", 0)), None, data["model"], wall)


def call_llm(prompt: str) -> LLMResponse:
    cfg = eval_config()["llm"]
    fn = {"claude_cli": _call_claude_cli, "anthropic_api": _call_anthropic_api}[cfg["backend"]]
    return fn(prompt, cfg["model"], cfg["timeout_s"])


def parse_queries(text: str, max_queries: int) -> list[ReconQuery]:
    t = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", t, re.S)
    if fence:
        t = fence.group(1)
    else:
        t = t[t.find("{"): t.rfind("}") + 1]
    data = json.loads(t)
    out = []
    seen = set()
    for i, q in enumerate(data.get("queries", [])[:max_queries]):
        qid = re.sub(r"\W+", "_", str(q.get("id") or f"q{i + 1}"))[:60]
        while qid in seen:
            qid += "_"
        seen.add(qid)
        out.append(ReconQuery(
            query_id=qid, sql=str(q.get("sql", "")), source="ai", kind=str(q.get("kind", "")),
            measure=str(q.get("measure", "")), dimensions=[str(d) for d in q.get("dimensions") or []],
            time_grain=str(q.get("time_grain", "none")), description=str(q.get("description", "")),
        ))
    return out


@dataclass
class AIGeneration:
    queries: list[ReconQuery]
    llm_calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    model_reported: str
    llm_wall_s: float
    prompt: str
    raw_response: str
    error: str = ""


def generate(task: str, model_sql: str, model_yml: str,
             model_schema: list[tuple[str, str]], reference_schema: list[tuple[str, str]]) -> AIGeneration:
    cfg = eval_config()["llm"]
    prompt = build_prompt(task, model_sql, model_yml, model_schema, reference_schema)
    gen = AIGeneration([], 0, 0, 0, 0.0, "", 0.0, prompt, "")
    for _ in range(cfg["max_attempts"]):
        resp = call_llm(prompt)  # ModelMismatch propagates: never silently use another model
        gen.llm_calls += 1
        gen.input_tokens += resp.input_tokens
        gen.output_tokens += resp.output_tokens
        gen.cost_usd = (gen.cost_usd or 0.0) + resp.cost_usd if resp.cost_usd is not None else None
        gen.model_reported = resp.model_reported
        gen.llm_wall_s += resp.wall_s
        gen.raw_response = resp.text
        try:
            gen.queries = parse_queries(resp.text, cfg["max_queries"])
            gen.error = ""
            break
        except (json.JSONDecodeError, ValueError, AttributeError) as e:
            gen.error = f"unparseable response: {e}"
    return gen
