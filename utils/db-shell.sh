#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$ROOT/src/docker/.env" ] && set -a && . "$ROOT/src/docker/.env" && set +a
${DOCKER:-docker} compose -f "$ROOT/src/docker/docker-compose.yml" \
    exec db psql \
        -U "${POSTGRES_USER:-vibevocab}" \
        -d "${POSTGRES_DB:-vibevocab}"
