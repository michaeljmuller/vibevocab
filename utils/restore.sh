#!/usr/bin/env bash
set -euo pipefail

BACKUP="${1:?Usage: restore.sh <backup-file>}"
# Resolve to absolute path before changing context
BACKUP="$(cd "$(dirname "$BACKUP")" && pwd)/$(basename "$BACKUP")"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$ROOT/src/docker/.env" ] && set -a && . "$ROOT/src/docker/.env" && set +a

COMPOSE="docker compose -f $ROOT/src/docker/docker-compose.yml -p ${COMPOSE_PROJECT_NAME:-vibevocab}"
DB_USER="${POSTGRES_USER:-vibevocab}"
DB_NAME="${POSTGRES_DB:-vibevocab}"

$COMPOSE up -d db

echo "Waiting for database to be ready..."
until $COMPOSE exec db pg_isready -U "$DB_USER" -q; do sleep 1; done

# Back up existing data if the database exists and has tables
HAS_DATA=$($COMPOSE exec -T db psql -U "$DB_USER" -d "$DB_NAME" -tAc \
    "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';" 2>/dev/null || echo 0)

if [ "$HAS_DATA" -gt 0 ]; then
    SAFETY_BACKUP="$ROOT/backups/pre_restore_$(date +%Y%m%d_%H%M%S).sql"
    echo "Backing up existing data to $SAFETY_BACKUP..."
    $COMPOSE exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$SAFETY_BACKUP"
    echo "Safety backup complete."
fi

echo "Dropping and recreating database..."
$COMPOSE exec db bash -c "dropdb -U $DB_USER --if-exists $DB_NAME && createdb -U $DB_USER $DB_NAME"

echo "Restoring from $BACKUP..."
$COMPOSE exec -T db psql -U "$DB_USER" "$DB_NAME" < "$BACKUP"

echo "Restore complete."
