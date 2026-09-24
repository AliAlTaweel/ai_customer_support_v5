#!/usr/bin/env bash
# Starts the API and the Gmail poller together for local dev.
#
# They stay separate OS processes on purpose (see docs/superpowers/specs/
# 2026-09-24-email-channel-gmail-design.md) -- a crash in the poll loop must
# not take the API down. This script is only a convenience so you don't have
# to remember to start both by hand; it does not change that isolation.
#
# Usage: ./scripts/run_dev.sh   (run from backend/)
set -euo pipefail
cd "$(dirname "$0")/.."

pids=()
cleanup() {
    trap - INT TERM EXIT
    for pid in "${pids[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

python main.py &
pids+=($!)

python -m scripts.poll_gmail &
pids+=($!)

# wait -n isn't available in bash 3.2 (macOS default), so poll instead.
while true; do
    for pid in "${pids[@]}"; do
        if ! kill -0 "$pid" 2>/dev/null; then
            exit 0
        fi
    done
    sleep 1
done
