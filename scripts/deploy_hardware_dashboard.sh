#!/bin/zsh

set -euo pipefail

SCRIPT_DIRECTORY="${0:A:h}"
PROJECT_ROOT="${SCRIPT_DIRECTORY:h}"
CONTROL="$PROJECT_ROOT/.venv/bin/crazyswarm-control"
ACTUATION_URL="http://127.0.0.1:3001/control-api/api/v1/physical-twin/lab/motor-actuation"
PHYSICAL_FLIGHT_URL="http://127.0.0.1:3001/control-api/api/v1/physical-twin/lab/physical-flight"
PHYSICAL_FLIGHT_MARKER="$PROJECT_ROOT/.cache/crazyswarm/physical-flight-operation.json"
POWER_REMOVAL_CONFIRMED=0

cd "$PROJECT_ROOT"

if [[ -f .git ]]; then
  print -u2 "Hardware deployment is allowed only from the Local checkout, not a worktree."
  exit 2
fi

if [[ ! -x "$CONTROL" ]]; then
  print -u2 "CrazySwarm is not set up: $CONTROL was not found."
  exit 2
fi

if ! actuation_json="$(curl -fsS --max-time 3 "$ACTUATION_URL")"; then
  print -u2 "Deployment refused: the current motor-actuation state could not be confirmed."
  print -u2 "Start the operator service and confirm Motor output is IDLE first."
  exit 3
fi
if ! print -r -- "$actuation_json" | "$PROJECT_ROOT/.venv/bin/python" -c \
  'import json,sys; value=json.load(sys.stdin); raise SystemExit(0 if value.get("state") == "IDLE" and value.get("stop_required") is False else 1)'
then
  print -u2 "Deployment refused: physical motor output is active or unconfirmed."
  print -u2 "Use the global Stop motors action and confirm IDLE first."
  exit 3
fi

if ! physical_flight_json="$(curl -fsS --max-time 3 "$PHYSICAL_FLIGHT_URL")"; then
  print -u2 "Deployment refused: the current physical-flight state could not be confirmed."
  exit 3
fi
if ! print -r -- "$physical_flight_json" | "$PROJECT_ROOT/.venv/bin/python" -c \
  'import json,sys; value=json.load(sys.stdin); raise SystemExit(0 if value.get("stop_required") is False else 1)'
then
  if [[ "${CRAZYSWARM_PHYSICAL_POWER_REMOVED:-0}" != "1" ]]; then
    print -u2 "Deployment refused: a physical flight stop is active or unconfirmed."
    print -u2 "Disconnect the Crazyflie battery, then explicitly confirm physical power removal."
    exit 3
  fi
  print "Physical power removal explicitly confirmed; replacing unconfirmed flight state."
  POWER_REMOVAL_CONFIRMED=1
fi

if (( POWER_REMOVAL_CONFIRMED == 1 )) && [[ -f "$PHYSICAL_FLIGHT_MARKER" ]]; then
  marker_archive="${PHYSICAL_FLIGHT_MARKER}.power-removed-$(date -u +%Y%m%dT%H%M%SZ)"
  mv -- "$PHYSICAL_FLIGHT_MARKER" "$marker_archive"
  print "Archived the stale physical-flight marker at $marker_archive"
fi

print "Building and replacing the operator hardware service once…"
"$CONTROL" dashboard-service install
"$CONTROL" dashboard-service status
owner_json="$("$CONTROL" hardware-owner status)"
print -r -- "$owner_json"
if ! print -r -- "$owner_json" | "$PROJECT_ROOT/.venv/bin/python" -c \
  'import json,sys; value=json.load(sys.stdin); owner=value.get("owner") or {}; raise SystemExit(0 if value.get("owned") is True and owner.get("name") == "operator-dashboard-service" else 1)'
then
  print -u2 "Deployment failed validation: operator service does not own the hardware lane."
  exit 4
fi
