#!/usr/bin/env bash
set -euo pipefail

# Inspect Emby entity consistency for split-series diagnosis.
#
# Purpose:
# - Verify whether target item IDs still exist in Emby.
# - Show multiple Series entities for same title (if any).
# - Show episode IDs under each series for season/episode mapping checks.
#
# Defaults:
#   DEDUP_BASE_URL=http://10.105.2.70:5055
#
# Example:
#   bash ./tasks/inspect_emby_entities.sh --name "閽㈤搧妫灄" --targets 1104830,1104831,1104832

DEDUP_BASE_URL="${DEDUP_BASE_URL:-http://10.105.2.70:5055}"
NAME=""
TARGETS=""
EP_LIMIT=2000

require_bin() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

usage() {
  cat <<'EOF'
Usage:
  inspect_emby_entities.sh [options]

Options:
  --name "鍓у悕"                 Required for series/entity scan
  --targets 1101,1102          Optional target IDs for /Items/{id} existence checks
  --dedup-base-url URL         Default: env DEDUP_BASE_URL or http://10.105.2.70:5055
  --episode-limit N            Default: 2000
  -h, --help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --name) NAME="$2"; shift 2 ;;
    --targets) TARGETS="$2"; shift 2 ;;
    --dedup-base-url) DEDUP_BASE_URL="$2"; shift 2 ;;
    --episode-limit) EP_LIMIT="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage; exit 1 ;;
  esac
done

require_bin curl
require_bin jq

if [[ -z "$NAME" ]]; then
  echo "--name is required." >&2
  exit 1
fi

SETTINGS_JSON="$(curl -sS --fail "${DEDUP_BASE_URL}/api/settings")"
EMBY_BASE_URL="$(echo "$SETTINGS_JSON" | jq -r '.emby.base_url // empty')"
EMBY_API_KEY="$(echo "$SETTINGS_JSON" | jq -r '.emby.api_key // empty')"
EMBY_USER_ID="$(echo "$SETTINGS_JSON" | jq -r '.emby.user_id // empty')"

if [[ -z "$EMBY_BASE_URL" || -z "$EMBY_API_KEY" || -z "$EMBY_USER_ID" ]]; then
  echo "Failed to load Emby settings from ${DEDUP_BASE_URL}/api/settings" >&2
  exit 1
fi

EMBY_BASE_URL="${EMBY_BASE_URL%/}"
echo "Dedup URL: $DEDUP_BASE_URL"
echo "Emby URL:  $EMBY_BASE_URL"
echo "User ID:   $EMBY_USER_ID"
echo

urlencode() {
  jq -nr --arg v "$1" '$v|@uri'
}

NAME_Q="$(urlencode "$NAME")"

echo "[1] Series entities by name: $NAME"
SERIES_JSON="$(curl -sS --fail "${EMBY_BASE_URL}/Users/${EMBY_USER_ID}/Items?Recursive=true&IncludeItemTypes=Series&SearchTerm=${NAME_Q}&Fields=ProviderIds,Path,ProductionYear,PremiereDate,DateCreated,RecursiveItemCount&Limit=200&api_key=${EMBY_API_KEY}")"
echo "$SERIES_JSON" | jq -r '
  (.Items // []) as $items
  | "series_count=\($items|length)",
    ($items[]? | [
      "series_id=\(.Id // "")",
      "name=\(.Name // "")",
      "year=\(.ProductionYear // "")",
      "tmdb=\(.ProviderIds.Tmdb // "")",
      "recursive_count=\(.RecursiveItemCount // "")",
      "path=\(.Path // "")"
    ] | join(" | "))
'
echo

echo "[2] Episodes matched by name (for id/瀛ｉ泦鏄犲皠)"
EP_JSON="$(curl -sS --fail "${EMBY_BASE_URL}/Users/${EMBY_USER_ID}/Items?Recursive=true&IncludeItemTypes=Episode&SearchTerm=${NAME_Q}&Fields=ProviderIds,Path,ParentId,SeriesName,ParentIndexNumber,IndexNumber,RunTimeTicks&Limit=${EP_LIMIT}&api_key=${EMBY_API_KEY}")"
echo "$EP_JSON" | jq -r '
  (.Items // []) as $items
  | "episode_count=\($items|length)",
    ($items[]? | [
      "ep_id=\(.Id // "")",
      "series=\(.SeriesName // "")",
      "series_parent_id=\(.SeriesId // .ParentId // "")",
      "S=\(.ParentIndexNumber // "")",
      "E=\(.IndexNumber // "")",
      "tmdb=\(.ProviderIds.Tmdb // "")",
      "path=\(.Path // "")"
    ] | join(" | "))
'
echo

if [[ -n "$TARGETS" ]]; then
  echo "[3] Target item existence checks"
  while IFS= read -r tid; do
    [[ -z "$tid" ]] && continue
    CODE="$(curl -sS -o /tmp/emby_target_${tid}.json -w '%{http_code}' "${EMBY_BASE_URL}/Items/${tid}?api_key=${EMBY_API_KEY}")"
    if [[ "$CODE" == "200" ]]; then
      echo "target=${tid} | exists=yes"
      jq -r '[ "name=\(.Name // "")", "type=\(.Type // "")", "series=\(.SeriesName // "")", "S=\(.ParentIndexNumber // "")", "E=\(.IndexNumber // "")", "tmdb=\(.ProviderIds.Tmdb // "")", "path=\(.Path // "")" ] | join(" | ")' "/tmp/emby_target_${tid}.json"
    else
      echo "target=${tid} | exists=no | http=${CODE}"
    fi
  done < <(echo "$TARGETS" | tr ',' '\n' | sed '/^\s*$/d')
fi




