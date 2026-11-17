#!/usr/bin/env bash
set -euo pipefail

cd /app

mkdir -p /app/output /app/input /app/data

# `serve` lance l'appli web ; sans sous-commande, `--input URL` traite en CLI comme avant.
exec python -m jpsub "$@"
