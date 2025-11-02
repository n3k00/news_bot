#!/usr/bin/env bash
set -euo pipefail

# cd into repo root
cd "$(dirname "$0")"

LOG_DIR="logs"
DELAY_SECONDS="5"
PYTHON_BIN="python3"
SCRIPT="news_push_bot.py"

mkdir -p "$LOG_DIR"

echo "Supervisor starting. Will restart '$SCRIPT' on exit/crash."

while true; do
  ts=$(date +"%Y-%m-%d_%H-%M-%S")
  log="$LOG_DIR/run_${ts}.log"
  echo "[$ts] Starting $SCRIPT ... logging to $log"
  set +e
  "$PYTHON_BIN" "$SCRIPT" >>"$log" 2>&1
  code=$?
  set -e
  if [ "$code" -eq 0 ]; then
    echo "[$ts] Process exited normally (0). Restarting in ${DELAY_SECONDS}s..."
  else
    echo "[$ts] Process crashed with code $code. See log: $log" >&2
  fi
  sleep "$DELAY_SECONDS"
done