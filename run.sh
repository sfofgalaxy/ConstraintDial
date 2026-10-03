#!/usr/bin/env bash
# 题目在旁边的 huggingface 目录。本目录是 ConstraintDial 的运行代码。
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DATA="$(cd "$HERE/../huggingface" && pwd)"
NAME="${1:-}"
MODE="${2:-chain}"
if [ -z "$NAME" ]; then
  echo "用法: bash run.sh <题目名> [chain|judge]"
  echo "例如: bash run.sh 4000-0001-case"
  exit 2
fi
TASK="$DATA/tasks/$NAME"
if [ ! -d "$TASK" ]; then
  echo "没有这道题: $TASK" >&2
  exit 2
fi
case "$MODE" in
  chain) exec bash "$TASK/run.sh" ;;
  judge) exec bash "$TASK/judge.sh" ;;
  *)
    echo "第二个参数只能是 chain 或 judge" >&2
    exit 2
    ;;
esac
