#!/usr/bin/env bash
# Root-cause patch gates: parent A0 fails, honest flow succeeds, J stays fail.
# Usage: run_patch_gates.sh TASK_DIR [PORT]
set -euo pipefail
TASK="$(cd "$1" && pwd)"
PORT="${2:-18547}"
ROOT="$TASK"
while [ "$ROOT" != "/" ]; do
  if [ -f "$ROOT/infra/revm_node.py" ]; then
    break
  fi
  ROOT="$(dirname "$ROOT")"
done
if [ -d "$ROOT/vendor" ] && PYTHONPATH="$ROOT/vendor" /usr/bin/python3.10 -c 'import pyrevm' >/dev/null 2>&1; then
  PYTHON=/usr/bin/python3.10
else
  PYTHON=python3
fi
export PYTHONPATH="$ROOT:$ROOT/vendor${PYTHONPATH:+:$PYTHONPATH}"

start_node() {
  "$PYTHON" "$ROOT/infra/revm_node.py" --task-dir "$TASK" --port "$PORT" "$@" \
    >>"$TASK/revm-gate.log" 2>&1 &
  NODE_PID=$!
  for i in $(seq 1 80); do
    if curl -s -X POST -H 'Content-Type: application/json' \
         --data '{"jsonrpc":"2.0","id":1,"method":"eth_blockNumber","params":[]}' \
         "http://127.0.0.1:$PORT" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.2
  done
  return 1
}

stop_node() {
  kill "$NODE_PID" 2>/dev/null || true
  wait "$NODE_PID" 2>/dev/null || true
}

echo "== patch kill: parent solve must fail =="
start_node
set +e
RPC_URL="http://127.0.0.1:$PORT" "$PYTHON" "$TASK/held/parent_solve.py"
KILL_RC=$?
set -e
stop_node
if [ "$KILL_RC" -eq 0 ]; then
  echo "FAIL: parent solve still passes; not a root-cause patch"
  exit 2
fi
echo "parent solve failed as required (rc=$KILL_RC)"

echo "== patch honest =="
exec "$(dirname "$0")/../../../run_honest_gates.sh" "$TASK" "$((PORT + 1))"
