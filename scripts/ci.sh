#!/usr/bin/env bash
# The quality gate, run against bind-mounted source at /work. Fail fast.
set -euo pipefail

export PYTHONPATH="/work/packages/contracts/src:/work/packages/server/src:/work/packages/cli/src"

echo "== ruff (lint) =="
ruff check packages tests

echo "== ruff (format check) =="
ruff format --check packages tests

echo "== ty (type check) =="
ty check packages tests --python /opt/venv

echo "== pytest =="
pytest

echo "== ci: all green =="
