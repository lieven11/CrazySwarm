#!/bin/zsh

set -euo pipefail

PROJECT_ROOT="${0:A:h:h}"
LOCAL_ROOT="$(git -C "$PROJECT_ROOT" worktree list --porcelain | sed -n '1s/^worktree //p')"

if [[ -z "$LOCAL_ROOT" || "$LOCAL_ROOT" == "$PROJECT_ROOT" ]]; then
  exit 0
fi

if [[ ! -e "$PROJECT_ROOT/.venv" && -d "$LOCAL_ROOT/.venv" ]]; then
  ln -s "$LOCAL_ROOT/.venv" "$PROJECT_ROOT/.venv"
fi

if [[ ! -e "$PROJECT_ROOT/ui/node_modules" && -d "$LOCAL_ROOT/ui/node_modules" ]]; then
  ln -s "$LOCAL_ROOT/ui/node_modules" "$PROJECT_ROOT/ui/node_modules"
fi

print "Worktree ready: simulation-only runtime with isolated default ports."
