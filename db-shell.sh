#!/usr/bin/env bash
set -euo pipefail
# Load .env if present so POSTGRES_* vars are available
[ -f .env ] && set -a && . ./.env && set +a
docker compose -f src/docker/docker-compose.yml --project-directory . -p vibevocab \
    exec db psql \
        -U "${POSTGRES_USER:-vibevocab}" \
        -d "${POSTGRES_DB:-vibevocab}"
