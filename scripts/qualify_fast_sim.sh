#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON:-$ROOT/.venv/bin/python}"
NPM_BIN="${NPM:-$(command -v npm || true)}"
NODE_BIN="${NODE:-$(command -v node || true)}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python runtime not found: $PYTHON_BIN" >&2
  echo "Create .venv or set PYTHON=/absolute/path/to/python." >&2
  exit 2
fi
if [[ -z "$NPM_BIN" || ! -x "$NPM_BIN" ]]; then
  echo "npm was not found; install Node.js 22.13+ or set NPM=/absolute/path/to/npm." >&2
  exit 2
fi
if [[ -z "$NODE_BIN" || ! -x "$NODE_BIN" ]]; then
  echo "node was not found; install Node.js 22.13+ or set NODE=/absolute/path/to/node." >&2
  exit 2
fi

export PATH="$(dirname "$NPM_BIN"):$PATH"
cd "$ROOT"

if [[ "${1:-}" == "--install" ]]; then
  "$PYTHON_BIN" -m pip install -r requirements.txt
  "$NPM_BIN" --prefix ui ci
elif [[ $# -ne 0 ]]; then
  echo "Usage: scripts/qualify_fast_sim.sh [--install]" >&2
  exit 2
fi

echo "[1/9] Health and configuration"
"$PYTHON_BIN" -m crazyswarm_app health --config config/app.yaml

echo "[2/9] Canonical clean-process reproducibility"
"$PYTHON_BIN" scripts/verify_canonical_scenarios.py

echo "[3/9] Backend tests"
"$PYTHON_BIN" -m pytest -q

echo "[4/9] Python lint"
"$PYTHON_BIN" -m ruff check .

echo "[5/9] Strict Python typing"
"$PYTHON_BIN" -m mypy src tests

echo "[6/9] OpenAPI export"
"$PYTHON_BIN" scripts/export_openapi.py --output ui/openapi.json
ui/node_modules/.bin/openapi-typescript ui/openapi.json -o ui/app/lib/api.generated.ts

echo "[7/9] UI lint, typing, tests, and production build"
"$NPM_BIN" --prefix ui run lint
"$NPM_BIN" --prefix ui run typecheck
"$NPM_BIN" --prefix ui run test:unit
"$NPM_BIN" --prefix ui run build
"$NODE_BIN" --test ui/tests/rendered-html.test.mjs

echo "[8/9] Complete UI dependency audit"
"$NPM_BIN" --prefix ui audit --json

echo "[9/9] Release artifact validation"
"$PYTHON_BIN" -m pytest -q tests/test_release_artifacts.py

echo "FAST-SIM QUALIFICATION: PASS"
