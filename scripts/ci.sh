#!/usr/bin/env bash
# The quality gate, run against bind-mounted source at /work. Fail fast.
set -euo pipefail

export PYTHONPATH="/work/packages/contracts/src:/work/packages/server/src:/work/packages/cli/src"

echo "== ruff (lint) =="
ruff check packages tests scripts

echo "== ruff (format check) =="
ruff format --check packages tests scripts

echo "== ty (type check) =="
ty check packages tests scripts --python /opt/venv

echo "== pytest =="
pytest

echo "== ci: all green =="
