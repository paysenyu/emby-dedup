#!/usr/bin/env bash
set -euo pipefail

# Backfill legacy empty status_reason values for delete_queue / operation_logs.
# Safe defaults for Docker runtime:
#   DB_PATH=/config/app.db
#
# Usage:
#   bash ./tasks/backfill_status_reason.sh
#   DB_PATH=/config/app.db bash ./tasks/backfill_status_reason.sh

DB_PATH="${DB_PATH:-/config/app.db}"

require_bin() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

require_bin sqlite3

if [[ ! -f "$DB_PATH" ]]; then
  echo "DB not found: $DB_PATH" >&2
  exit 1
fi

TS="$(date +%Y%m%d_%H%M%S)"
BACKUP_PATH="${DB_PATH}.bak_${TS}"
cp -f "$DB_PATH" "$BACKUP_PATH"
echo "Backup created: $BACKUP_PATH"

SQL="
BEGIN TRANSACTION;

UPDATE delete_queue
SET status_reason = 'webhook_confirmed'
WHERE (status_reason IS NULL OR TRIM(status_reason) = '')
  AND delete_status = 'done'
  AND message LIKE 'Webhook confirmed delete%';

UPDATE delete_queue
SET status_reason = 'probe_confirmed'
WHERE (status_reason IS NULL OR TRIM(status_reason) = '')
  AND delete_status = 'done'
  AND message LIKE 'Confirmed by Emby probe%';

UPDATE delete_queue
SET status_reason = 'accepted'
WHERE (status_reason IS NULL OR TRIM(status_reason) = '')
  AND delete_status = 'in_progress';

UPDATE delete_queue
SET status_reason = 'timeout_exists'
WHERE (status_reason IS NULL OR TRIM(status_reason) = '')
  AND delete_status = 'failed'
  AND (
    message LIKE 'Webhook timeout and Emby item still exists%'
    OR message LIKE 'Webhook timeout and Emby probe failed%'
    OR message LIKE 'Webhook not received before retry limit.%'
  );

UPDATE delete_queue
SET status_reason = 'invalid_payload'
WHERE (status_reason IS NULL OR TRIM(status_reason) = '')
  AND delete_status = 'failed'
  AND message LIKE 'Invalid webhook payload:%';

UPDATE operation_logs
SET status_reason = 'webhook_confirmed'
WHERE (status_reason IS NULL OR TRIM(status_reason) = '')
  AND status = 'done'
  AND message LIKE 'Webhook confirmed delete%';

UPDATE operation_logs
SET status_reason = 'probe_confirmed'
WHERE (status_reason IS NULL OR TRIM(status_reason) = '')
  AND status = 'done'
  AND message LIKE 'Confirmed by Emby probe%';

UPDATE operation_logs
SET status_reason = 'accepted'
WHERE (status_reason IS NULL OR TRIM(status_reason) = '')
  AND status = 'in_progress';

UPDATE operation_logs
SET status_reason = 'timeout_exists'
WHERE (status_reason IS NULL OR TRIM(status_reason) = '')
  AND status = 'failed'
  AND (
    message LIKE 'Webhook timeout and Emby item still exists%'
    OR message LIKE 'Webhook timeout and Emby probe failed%'
    OR message LIKE 'Webhook not received before retry limit.%'
  );

UPDATE operation_logs
SET status_reason = 'invalid_payload'
WHERE (status_reason IS NULL OR TRIM(status_reason) = '')
  AND status = 'failed'
  AND message LIKE 'Invalid webhook payload:%';

COMMIT;
"

sqlite3 "$DB_PATH" "$SQL"

echo "Backfill completed."
echo "Current delete_queue status_reason distribution:"
sqlite3 "$DB_PATH" "
SELECT
  COALESCE(NULLIF(TRIM(status_reason), ''), '(empty)') AS reason,
  COUNT(1) AS cnt
FROM delete_queue
GROUP BY reason
ORDER BY cnt DESC, reason ASC;
"

echo "Current operation_logs status_reason distribution:"
sqlite3 "$DB_PATH" "
SELECT
  COALESCE(NULLIF(TRIM(status_reason), ''), '(empty)') AS reason,
  COUNT(1) AS cnt
FROM operation_logs
GROUP BY reason
ORDER BY cnt DESC, reason ASC;
"
