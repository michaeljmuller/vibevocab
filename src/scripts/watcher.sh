#!/bin/bash
PGHOST=db
DELAY=${BACKUP_INACTIVITY_MINUTES:-15}
POLL=${BACKUP_POLL_SECONDS:-60}

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
            BACKUP_FILE="/backups/backup_$(date +%Y%m%d_%H%M%S).sql"
            echo "Starting backup: $BACKUP_FILE"
            if pg_dump -h "$PGHOST" -f "$BACKUP_FILE"; then
                psql -h "$PGHOST" -c "UPDATE db_state SET last_backup_at = last_modified WHERE id = 1"
                echo "Backup complete: $BACKUP_FILE"
            else
                echo "Backup failed; will retry next poll" >&2
                rm -f "$BACKUP_FILE"
            fi
        fi
    fi
done
