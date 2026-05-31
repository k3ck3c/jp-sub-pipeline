#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

profile="${1:-local}"
shift || true

case "$profile" in
  local)
    exec docker compose --profile local run --rm jpsub-local "$@"
    ;;
  api)
    exec docker compose --profile api run --rm jpsub-api "$@"
    ;;
  *)
    echo "Usage: ./drun.sh [local|api] <args for main.py>"
    exit 1
    ;;
esac
