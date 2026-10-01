#!/usr/bin/env bash
# Milestone 0: two isolated environments. venv-v1 also runs the harness itself.
set -euo pipefail
cd "$(dirname "$0")"
uv venv -q --python 3.12 venv-v1
uv pip install -q --python venv-v1/bin/python -r requirements-v1.txt
uv venv -q --python 3.12 venv-v2
uv pip install -q --python venv-v2/bin/python -r requirements-v2.txt
venv-v1/bin/dbt --version
venv-v2/bin/dbt --version
