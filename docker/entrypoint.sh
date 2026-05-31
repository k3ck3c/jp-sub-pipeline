#!/usr/bin/env bash
set -euo pipefail

cd /app

mkdir -p /app/output /app/input

exec python main.py "$@"
