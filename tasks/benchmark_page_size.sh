#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-/mnt/cache/sync/codex}"
BASE_URL="${BASE_URL:-http://10.105.2.70:5055}"
PAGE_SIZE_LIST="${PAGE_SIZE_LIST:-500,1000,2000,4000}"
MOVIE_LIBS="${MOVIE_LIBS:-}"
TV_LIBS="${TV_LIBS:-}"
OUTPUT_DIR="${OUTPUT_DIR:-/mnt/cache/sync/codex/tasks/reports/page-size-benchmark}"
VALIDATE_SCRIPT="${VALIDATE_SCRIPT:-/mnt/cache/sync/codex/tasks/validate_sync_performance.sh}"
HEALTH_TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS:-180}"

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required" >&2
  exit 1
fi
if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required" >&2
  exit 1
fi

run_id="$(date +%Y%m%d-%H%M%S)"
run_dir="${OUTPUT_DIR}/${run_id}"
validation_base="${run_dir}/validation-runs"
mkdir -p "$run_dir" "$validation_base"

results_jsonl="${run_dir}/results.jsonl"
: > "$results_jsonl"

IFS=',' read -r -a page_sizes <<< "$PAGE_SIZE_LIST"

wait_health() {
  local deadline=$(( $(date +%s) + HEALTH_TIMEOUT_SECONDS ))
  while [[ $(date +%s) -lt "$deadline" ]]; do
    if curl -fsS "${BASE_URL}/api/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  echo "Health check timeout for ${BASE_URL}" >&2
  return 1
}

run_once() {
  local page_size="$1"
  local override_file="${run_dir}/override-${page_size}.yml"

  cat > "$override_file" <<EOF
services:
  emby-dedup:
    environment:
      - APP_SYNC_LIBRARY_PAGE_SIZE=${page_size}
EOF

  echo
  echo "=== Page Size ${page_size} ==="
  docker compose -f "${REPO_DIR}/docker-compose.yml" -f "$override_file" up -d --build
  wait_health

  BASE_URL="$BASE_URL" \
  MOVIE_LIBS="$MOVIE_LIBS" \
  TV_LIBS="$TV_LIBS" \
  CONCURRENCY_LIST="1" \
  OUTPUT_DIR="$validation_base" \
  bash "$VALIDATE_SCRIPT" >/dev/null

  local latest_validation
  latest_validation="$(ls -1dt "${validation_base}"/* | head -n 1)"
  if [[ -z "$latest_validation" ]]; then
    echo "No validation output found for page size ${page_size}" >&2
    exit 1
  fi

  local result_json
  result_json="$(jq -c '.[0]' "${latest_validation}/results.json")"
  if [[ -z "$result_json" || "$result_json" == "null" ]]; then
    echo "Invalid result json for page size ${page_size}" >&2
    exit 1
  fi

  jq -nc --argjson row "$result_json" --arg page_size "$page_size" --arg run_id "$run_id" '
    {
      run_id: $run_id,
      page_size: ($page_size | tonumber),
      scenario_name: ($row.scenario_name // ""),
      libraries: ($row.libraries // ""),
      duration_seconds: ($row.duration_seconds // 0),
      items_synced: ($row.items_synced // 0),
      detail_requests_total: ($row.detail_requests_total // 0),
      timing_list_library_items: ($row.timing_list_library_items // 0),
      timing_detail_requests: ($row.timing_detail_requests // 0),
      timing_db_insert: ($row.timing_db_insert // 0),
      timing_analysis: ($row.timing_analysis // 0),
      last_result: ($row.last_result // "")
    }' >> "$results_jsonl"
}

for p in "${page_sizes[@]}"; do
  p="$(echo "$p" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
  [[ -z "$p" ]] && continue
  run_once "$p"
done

jq -s '.' "$results_jsonl" > "${run_dir}/results.json"

jq -r '
  (["run_id","page_size","scenario_name","duration_seconds","items_synced","detail_requests_total","timing_list_library_items","timing_detail_requests","timing_db_insert","timing_analysis","last_result"] | @csv),
  (.[] | [.run_id,.page_size,.scenario_name,.duration_seconds,.items_synced,.detail_requests_total,.timing_list_library_items,.timing_detail_requests,.timing_db_insert,.timing_analysis,.last_result] | @csv)
' "${run_dir}/results.json" > "${run_dir}/results.csv"

{
  echo "# Page Size Benchmark Summary"
  echo
  echo "| Page Size | Scenario | Result | Duration(s) | list_library_items(s) | detail_requests(s) | detail_requests_total |"
  echo "| ---: | --- | --- | ---: | ---: | ---: | ---: |"
  jq -r '.[] | "| \(.page_size) | \(.scenario_name) | \(.last_result) | \(.duration_seconds) | \(.timing_list_library_items) | \(.timing_detail_requests) | \(.detail_requests_total) |"' "${run_dir}/results.json"
} > "${run_dir}/SUMMARY.md"

echo
echo "Done."
echo "Run Dir: ${run_dir}"
echo "Summary: ${run_dir}/SUMMARY.md"
echo "JSON   : ${run_dir}/results.json"
echo "CSV    : ${run_dir}/results.csv"




