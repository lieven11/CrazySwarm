#!/bin/zsh

set -u

PROJECT_ROOT="${0:A:h}"
CONTROL="$PROJECT_ROOT/.venv/bin/crazyswarm-control"
SERVICE_TARGET="gui/$(id -u)/com.crazyswarm.control-center"
UI_URL="http://localhost:3001"

cd "$PROJECT_ROOT" || exit 1

print "Restarting CrazySwarm…"

if [[ ! -x "$CONTROL" ]]; then
  print -u2 "CrazySwarm is not set up yet: $CONTROL was not found."
  print -u2 "Follow the Local setup steps in docs/project/README.md, then try again."
  print
  read -k 1 "?Press any key to close."
  print
  exit 1
fi

if /bin/launchctl print "$SERVICE_TARGET" >/dev/null 2>&1; then
  if ! "$CONTROL" dashboard-service restart; then
    print -u2 "CrazySwarm could not be restarted."
    print
    read -k 1 "?Press any key to close."
    print
    exit 1
  fi
else
  print -u2 "The background service is not installed."
  print -u2 "Run scripts/deploy_hardware_dashboard.sh from Terminal to install it safely."
  print
  read -k 1 "?Press any key to close."
  print
  exit 1
fi

print "Waiting for the app to become ready…"
for attempt in {1..120}; do
  if "$CONTROL" dashboard-service status --allow-stale-source >/dev/null 2>&1; then
    print "CrazySwarm is running at $UI_URL"
    if ! "$CONTROL" dashboard-service status >/dev/null 2>&1; then
      print "Local source changes are not deployed; the installed release is running."
    fi
    open "$UI_URL"
    exit 0
  fi
  if (( attempt % 15 == 0 )); then
    print "Still starting (${attempt}s elapsed)…"
  fi
  sleep 1
done

print -u2 "CrazySwarm restarted, but it did not become ready."
"$CONTROL" dashboard-service status --allow-stale-source || true
print -u2 "Check .cache/crazyswarm/dashboard.stderr.log for details."
print
read -k 1 "?Press any key to close."
print
exit 1
