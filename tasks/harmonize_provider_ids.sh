#!/usr/bin/env bash
set -euo pipefail

# Harmonize Emby ProviderIds within same TMDb groups.
#
# Safety defaults:
# - dry-run by default (no writes)
# - only fills missing provider ids (tvdb/imdb/douban)
# - never overrides non-empty provider ids
# - skips groups with tmdb empty or tmdb==0
#
# Example:
#   bash ./tasks/harmonize_provider_ids.sh --name "????"
#   bash ./tasks/harmonize_provider_ids.sh --name "????" --apply

DEDUP_BASE_URL="${DEDUP_BASE_URL:-http://localhost:5055}"
NAME_FILTER=""
INCLUDE_ITEM_TYPES="Episode,Movie,Series"
LIMIT=20000
APPLY=0

require_bin() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

usage() {
  cat <<'EOF'
Usage:
  harmonize_provider_ids.sh [options]

Options:
  --name "keyword"            Optional search term (recommended for first run)
  --item-types "Episode,Movie,Series"  Default: Episode,Movie,Series
  --limit N                    Default: 20000
  --dedup-base-url URL         Default: env DEDUP_BASE_URL or http://localhost:5055
  --apply                      Apply updates to Emby (default is dry-run)
  -h, --help

Notes:
  - Only fills missing Tvdb/Imdb/Douban from peers in same TMDb group.
  - Existing non-empty provider ids are never overridden.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --name) NAME_FILTER="$2"; shift 2 ;;
    --item-types) INCLUDE_ITEM_TYPES="$2"; shift 2 ;;
    --limit) LIMIT="$2"; shift 2 ;;
    --dedup-base-url) DEDUP_BASE_URL="$2"; shift 2 ;;
    --apply) APPLY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage; exit 1 ;;
  esac
done

require_bin curl
require_bin jq

SETTINGS_JSON="$(curl -sS --fail "${DEDUP_BASE_URL}/settings")"
EMBY_BASE_URL="$(echo "$SETTINGS_JSON" | jq -r '.emby.base_url // empty')"
EMBY_API_KEY="$(echo "$SETTINGS_JSON" | jq -r '.emby.api_key // empty')"
EMBY_USER_ID="$(echo "$SETTINGS_JSON" | jq -r '.emby.user_id // empty')"

if [[ -z "$EMBY_BASE_URL" || -z "$EMBY_API_KEY" || -z "$EMBY_USER_ID" ]]; then
  echo "Failed to load Emby settings from ${DEDUP_BASE_URL}/settings" >&2
  exit 1
fi

EMBY_BASE_URL="${EMBY_BASE_URL%/}"

urlencode() {
  jq -nr --arg v "$1" '$v|@uri'
}

Q_NAME=""
if [[ -n "$NAME_FILTER" ]]; then
  Q_NAME="&SearchTerm=$(urlencode "$NAME_FILTER")"
fi

echo "Dedup URL: ${DEDUP_BASE_URL}"
echo "Emby URL:  ${EMBY_BASE_URL}"
echo "User ID:   ${EMBY_USER_ID}"
echo "Mode:      $([[ "$APPLY" == "1" ]] && echo APPLY || echo DRY-RUN)"
echo

echo "[1/3] Fetching items from Emby ..."
ITEMS_JSON="$(curl -sS --fail "${EMBY_BASE_URL}/Users/${EMBY_USER_ID}/Items?Recursive=true&IncludeItemTypes=${INCLUDE_ITEM_TYPES}&Fields=ProviderIds,Path,SeriesName,ParentIndexNumber,IndexNumber,ProductionYear&Limit=${LIMIT}${Q_NAME}&api_key=${EMBY_API_KEY}")"

echo "[2/3] Building harmonization plan ..."
PLAN_JSON="$(echo "$ITEMS_JSON" | jq -c '
  def norm(x): ((x // "")|tostring|gsub("^\\s+|\\s+$";""));
  def nonempty(x): (norm(x) != "");
  def safe_tmdb(x): (norm(x) != "" and norm(x) != "0");

  [(.Items // [])[]
   | {
       id: (.Id|tostring),
       name: (.Name // ""),
       type: (.Type // ""),
       series_name: (.SeriesName // ""),
       s: (.ParentIndexNumber // null),
       e: (.IndexNumber // null),
       path: (.Path // ""),
       tmdb: (.ProviderIds.Tmdb // "" | tostring),
       tvdb: (.ProviderIds.Tvdb // "" | tostring),
       imdb: (.ProviderIds.Imdb // "" | tostring),
       douban: (.ProviderIds.Douban // "" | tostring)
     }
  ] as $rows
  | ($rows | group_by(.tmdb) | map(select(safe_tmdb(.[0].tmdb) and (length > 1)))) as $groups
  | $groups
  | map(
      . as $g
      | {
          tmdb: $g[0].tmdb,
          size: ($g|length),
          canonical: {
            tvdb: (($g | map(select(nonempty(.tvdb)) | .tvdb) | group_by(.) | map({v: .[0], c: length}) | sort_by(-.c, .v) | .[0].v) // ""),
            imdb: (($g | map(select(nonempty(.imdb)) | .imdb) | group_by(.) | map({v: .[0], c: length}) | sort_by(-.c, .v) | .[0].v) // ""),
            douban: (($g | map(select(nonempty(.douban)) | .douban) | group_by(.) | map({v: .[0], c: length}) | sort_by(-.c, .v) | .[0].v) // "")
          },
          items: $g
        }
      | .updates = (
          .canonical as $canon
          | .items
          | map(
              . as $i
              | {
                  id: $i.id,
                  name: $i.name,
                  type: $i.type,
                  series_name: $i.series_name,
                  s: $i.s,
                  e: $i.e,
                  path: $i.path,
                  tmdb: $i.tmdb,
                  old: {tvdb: $i.tvdb, imdb: $i.imdb, douban: $i.douban},
                  new: {
                    tvdb: (if nonempty($i.tvdb) then $i.tvdb elif nonempty($canon.tvdb) then $canon.tvdb else "" end),
                    imdb: (if nonempty($i.imdb) then $i.imdb elif nonempty($canon.imdb) then $canon.imdb else "" end),
                    douban: (if nonempty($i.douban) then $i.douban elif nonempty($canon.douban) then $canon.douban else "" end)
                  }
                }
            )
          | map(select((.old.tvdb != .new.tvdb) or (.old.imdb != .new.imdb) or (.old.douban != .new.douban)))
        )
      | select((.updates|length) > 0)
    )
  | {
      group_count: length,
      update_count: (map(.updates|length)|add // 0),
      groups: .
    }
')"

echo "$PLAN_JSON" | jq '{group_count, update_count}'

echo "[Preview]"
echo "$PLAN_JSON" | jq -r '
  .groups[]? as $g
  | "tmdb=\($g.tmdb) group_size=\($g.size) updates=\($g.updates|length) canonical(tvdb=\($g.canonical.tvdb), imdb=\($g.canonical.imdb), douban=\($g.canonical.douban))",
    ($g.updates[] | "  id=\(.id) type=\(.type) name=\(.name) S=\(.s // "") E=\(.e // "") old(tvdb=\(.old.tvdb),imdb=\(.old.imdb),douban=\(.old.douban)) => new(tvdb=\(.new.tvdb),imdb=\(.new.imdb),douban=\(.new.douban))")
'

if [[ "$APPLY" != "1" ]]; then
  echo
  echo "Dry-run complete. Re-run with --apply to write changes to Emby."
  exit 0
fi

echo
echo "[3/3] Applying updates to Emby ..."
OK=0
FAIL=0

while IFS= read -r u; do
  [[ -z "$u" ]] && continue
  item_id="$(echo "$u" | jq -r '.id')"

  # Pull full item payload, then patch ProviderIds in-memory.
  DETAIL="$(curl -sS --fail "${EMBY_BASE_URL}/Users/${EMBY_USER_ID}/Items/${item_id}?Fields=ProviderIds&api_key=${EMBY_API_KEY}")"
  PATCHED="$(jq -c --arg tvdb "$(echo "$u" | jq -r '.new.tvdb')" --arg imdb "$(echo "$u" | jq -r '.new.imdb')" --arg douban "$(echo "$u" | jq -r '.new.douban')" '
    .ProviderIds = (.ProviderIds // {})
    | .ProviderIds.Tvdb = $tvdb
    | .ProviderIds.Imdb = $imdb
    | .ProviderIds.Douban = $douban
  ' <<< "$DETAIL")"

  code="$(curl -sS -o /tmp/emby_update_${item_id}.json -w '%{http_code}' -X POST -H 'Content-Type: application/json' --data "$PATCHED" "${EMBY_BASE_URL}/Items/${item_id}?api_key=${EMBY_API_KEY}")"
  if [[ "$code" == "200" || "$code" == "204" ]]; then
    echo "apply_ok item_id=${item_id} http=${code}"
    OK=$((OK+1))
  else
    echo "apply_fail item_id=${item_id} http=${code} body=$(cat /tmp/emby_update_${item_id}.json 2>/dev/null || true)" >&2
    FAIL=$((FAIL+1))
  fi
done < <(echo "$PLAN_JSON" | jq -c '.groups[]?.updates[]?')

echo "Apply finished: ok=${OK} fail=${FAIL}"
if [[ "$FAIL" -gt 0 ]]; then
  exit 2
fi



