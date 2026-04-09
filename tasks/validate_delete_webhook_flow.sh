#!/usr/bin/env bash
set -euo pipefail

# Real delete-flow validator for emby-dedup.
# WARNING: execute mode triggers real DeleteVersion requests.
#
# Defaults are prefilled for current environment:
#   BASE_URL=http://10.105.2.70:5055
#   TOKEN=paysen
#
# Examples:
#   ./tasks/validate_delete_webhook_flow.sh --mode preview
#   ./tasks/validate_delete_webhook_flow.sh --mode execute --item-ids 101,102
#   ./tasks/validate_delete_webhook_flow.sh --mode execute --group-ids movie:12345 --poll-seconds 180

BASE_URL="${BASE_URL:-http://10.105.2.70:5055}"
TOKEN="${TOKEN:-paysen}"
MODE="preview"
ITEM_IDS=""
GROUP_IDS=""
POLL_SECONDS=120
POLL_INTERVAL=3
LATEST_ONLY=true
LIMIT=20

require_bin() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

usage() {
  cat <<'EOF'
Usage:
  validate_delete_webhook_flow.sh [options]

Options:
  --mode preview|execute|queue   Default: preview
  --item-ids 1,2,3              Explicit item IDs for /delete/execute
  --group-ids g1,g2             Group IDs for /delete/execute
  --poll-seconds N              Poll timeout seconds. Default: 120
  --poll-interval N             Poll interval seconds. Default: 3
  --latest-only true|false      For /delete/queue/status. Default: true
  --limit N                     Queue status limit. Default: 20
  --base-url URL                Default: env BASE_URL or http://10.105.2.70:5055
  --token TOKEN                 Default: env TOKEN or paysen
  -h, --help

Environment:
  BASE_URL, TOKEN

Notes:
  - execute mode performs real deletion requests.
  - script does not trigger webhook manually; it waits for queue status transitions.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) MODE="$2"; shift 2 ;;
    --item-ids) ITEM_IDS="$2"; shift 2 ;;
    --group-ids) GROUP_IDS="$2"; shift 2 ;;
    --poll-seconds) POLL_SECONDS="$2"; shift 2 ;;
    --poll-interval) POLL_INTERVAL="$2"; shift 2 ;;
    --latest-only) LATEST_ONLY="$2"; shift 2 ;;
    --limit) LIMIT="$2"; shift 2 ;;
    --base-url) BASE_URL="$2"; shift 2 ;;
    --token) TOKEN="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage; exit 1 ;;
  esac
done

require_bin curl
require_bin jq

api_get() {
  local path="$1"
  curl -sS --fail "${BASE_URL}/api${path}"
}

api_post_json() {
  local path="$1"
  local body="$2"
  curl -sS --fail \
    -H 'Content-Type: application/json' \
    -X POST \
    -d "$body" \
    "${BASE_URL}/api${path}"
}

echo "[1/5] Health check: ${BASE_URL}/api/health"
HEALTH="$(api_get "/health")"
echo "$HEALTH" | jq .

echo "[2/5] Delete preview"
PREVIEW="$(api_post_json "/delete/preview" '{"group_ids":[]}')"
echo "$PREVIEW" | jq '{groups: (.groups | length), delete_count, protected_count}'

if [[ "$MODE" == "preview" ]]; then
  echo "Preview mode done."
  exit 0
fi

QUEUE_IDS_JSON='[]'
if [[ "$MODE" == "execute" ]]; then
  ITEM_IDS_JSON='[]'
  GROUP_IDS_JSON='[]'

  if [[ -n "$ITEM_IDS" ]]; then
    ITEM_IDS_JSON="$(echo "$ITEM_IDS" | tr ',' '\n' | sed '/^\s*$/d' | jq -R . | jq -s 'map(tonumber)')"
  fi
  if [[ -n "$GROUP_IDS" ]]; then
    GROUP_IDS_JSON="$(echo "$GROUP_IDS" | tr ',' '\n' | sed '/^\s*$/d' | jq -R . | jq -s '.')"
  fi

  if [[ "$ITEM_IDS_JSON" == "[]" && "$GROUP_IDS_JSON" == "[]" ]]; then
    echo "execute mode requires --item-ids or --group-ids" >&2
    exit 1
  fi

  PAYLOAD="$(jq -n --argjson item_ids "$ITEM_IDS_JSON" --argjson group_ids "$GROUP_IDS_JSON" '{item_ids:$item_ids, group_ids:$group_ids}')"
  echo "[3/5] Execute delete (REAL): $PAYLOAD"
  EXECUTE_RESP="$(api_post_json "/delete/execute" "$PAYLOAD")"
  echo "$EXECUTE_RESP" | jq '{success_count, failed_count, result_count: (.results|length)}'
  RESULT_COUNT="$(echo "$EXECUTE_RESP" | jq '.results | length')"
  QUEUE_IDS_JSON="$(echo "$EXECUTE_RESP" | jq '[.results[] | select(.id != null) | .id] | unique')"
  echo "Queue IDs from execute: $QUEUE_IDS_JSON"
  if [[ "$RESULT_COUNT" == "0" ]]; then
    echo "No delete candidates matched your --item-ids/--group-ids in current analysis_results." >&2
    echo "Tip: run with --mode preview first and choose real item_ids from delete_candidates." >&2
    exit 3
  fi
elif [[ "$MODE" == "queue" ]]; then
  echo "[3/5] Queue-only mode (no execute)"
else
  echo "Unsupported mode: $MODE" >&2
  exit 1
fi

echo "[4/5] Poll queue status"
START_TS="$(date +%s)"
END_TS=$((START_TS + POLL_SECONDS))

while true; do
  NOW_TS="$(date +%s)"
  if (( NOW_TS > END_TS )); then
    echo "Polling timeout after ${POLL_SECONDS}s."
    exit 2
  fi

  QUERY="latest_only=${LATEST_ONLY}&limit=${LIMIT}"
  if [[ "$QUEUE_IDS_JSON" != "[]" ]]; then
    while IFS= read -r qid; do
      QUERY="${QUERY}&ids=${qid}"
    done < <(echo "$QUEUE_IDS_JSON" | jq -r '.[]')
  fi

  STATUS_RESP="$(api_get "/delete/queue/status?${QUERY}")"
  echo "$STATUS_RESP" | jq '{items: (.items|length), by_status: (.items | group_by(.delete_status) | map({(.[0].delete_status): length}) | add // {}), by_reason: (.items | group_by(.status_reason) | map({(.[0].status_reason): length}) | add // {})}'

  TOTAL_ITEMS="$(echo "$STATUS_RESP" | jq '.items | length')"
  TERMINAL_ITEMS="$(echo "$STATUS_RESP" | jq '[.items[] | select(.delete_status == "done" or .delete_status == "failed")] | length')"

  if (( TOTAL_ITEMS > 0 && TERMINAL_ITEMS == TOTAL_ITEMS )); then
    echo "[5/5] All queue items reached terminal status."
    echo "$STATUS_RESP" | jq '.items[] | {id, item_id, delete_target_item_id, delete_status, status_reason, status_code, message}'
    exit 0
  fi

  sleep "$POLL_INTERVAL"
done




