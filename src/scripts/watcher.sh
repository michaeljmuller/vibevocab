#!/bin/bash
PGHOST=db
DELAY=${BACKUP_INACTIVITY_MINUTES:-15}
POLL=${BACKUP_POLL_SECONDS:-60}
S3_BUCKET=${S3_BUCKET:?S3_BUCKET is required}
ENV_NAME=${ENVIRONMENT:?ENVIRONMENT is required}

export AWS_ACCESS_KEY_ID="${S3_ACCESS_KEY:?S3_ACCESS_KEY is required}"
export AWS_SECRET_ACCESS_KEY="${S3_SECRET_KEY:?S3_SECRET_KEY is required}"
[ -n "${S3_REGION:-}" ] && export AWS_DEFAULT_REGION="$S3_REGION"
if [ -n "${S3_ENDPOINT:-}" ]; then
    case "$S3_ENDPOINT" in
        http://*|https://*) export AWS_ENDPOINT_URL="$S3_ENDPOINT" ;;
        *) export AWS_ENDPOINT_URL="https://$S3_ENDPOINT" ;;
    esac
fi

echo "Backup watcher started (inactivity threshold=${DELAY}m, poll=${POLL}s)"

while true; do
    sleep "$POLL"

    NEEDS_BACKUP=$(psql -h "$PGHOST" -t -A -c "
        SELECT 1 FROM db_state
        WHERE last_modified > COALESCE(last_backup_at, '-infinity'::timestamptz)
    " 2>/dev/null)

    if [ "$NEEDS_BACKUP" = "1" ]; then
        IDLE_SECONDS=$(curl -sf "http://web:5000/internal/last-interaction" 2>/dev/null || echo 0)
        if [ "$IDLE_SECONDS" -ge "$((DELAY * 60))" ]; then
            BACKUP_KEY="${ENV_NAME}/backup_$(date +%Y%m%d_%H%M%S).sql"
            BACKUP_TMP=$(mktemp)
            echo "Starting backup: s3://${S3_BUCKET}/${BACKUP_KEY}"
            if pg_dump -h "$PGHOST" -f "$BACKUP_TMP" && aws s3 cp "$BACKUP_TMP" "s3://${S3_BUCKET}/${BACKUP_KEY}"; then
                psql -h "$PGHOST" -c "UPDATE db_state SET last_backup_at = last_modified WHERE id = 1"
                echo "Backup complete: s3://${S3_BUCKET}/${BACKUP_KEY}"
            else
                echo "Backup failed; will retry next poll" >&2
            fi
            rm -f "$BACKUP_TMP"
        fi
    fi
done
