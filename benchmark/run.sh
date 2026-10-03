#!/usr/bin/env bash
# Run one task from a local checkout of the Hugging Face dataset.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
ENV_FILE="$ROOT/.env"
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

DATA="${HF_DATASET_DIR:-}"
NAME="${1:-}"
MODE="${2:-chain}"
if [ -z "$DATA" ]; then
  echo "Set HF_DATASET_DIR in .env to the local dataset directory." >&2
  exit 2
fi
if [ -z "$NAME" ]; then
  echo "usage: bash benchmark/run.sh <task> [chain|judge]" >&2
  echo "example: bash benchmark/run.sh 4000-0001-case" >&2
  exit 2
fi
TASK="$DATA/tasks/$NAME"
if [ ! -d "$TASK" ]; then
  echo "task not found: $TASK" >&2
  exit 2
fi
case "$MODE" in
  chain) exec bash "$TASK/run.sh" ;;
  judge) exec bash "$TASK/judge.sh" ;;
  *)
    echo "mode must be chain or judge" >&2
    exit 2
    ;;
esac
