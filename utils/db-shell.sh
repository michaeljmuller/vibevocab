#!/usr/bin/env bash
set -euo pipefail
# Load .env if present so POSTGRES_* vars are available
[ -f src/docker/.env ] && set -a && . ./src/docker/.env && set +a
docker compose -f src/docker/docker-compose.yml -p vibevocab \
    exec db psql \
        -U "${POSTGRES_USER:-vibevocab}" \
        -d "${POSTGRES_DB:-vibevocab}"
