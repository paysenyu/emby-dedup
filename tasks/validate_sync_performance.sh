#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:5055}"
MOVIE_LIBS="${MOVIE_LIBS:-}"
TV_LIBS="${TV_LIBS:-}"
CONCURRENCY_LIST="${CONCURRENCY_LIST:-1,4,8}"
POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-2}"
TIMEOUT_MINUTES="${TIMEOUT_MINUTES:-180}"
OUTPUT_DIR="${OUTPUT_DIR:-./tasks/reports/sync-performance}"
KEEP_TEST_SETTINGS="${KEEP_TEST_SETTINGS:-0}"

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required" >&2
  exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required" >&2
  exit 1
fi

trim_csv() {
  local input="$1"
  local out=""
  IFS=',' read -r -a arr <<< "$input"
  for raw in "${arr[@]}"; do
    local s
    s="$(echo "$raw" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    [[ -z "$s" ]] && continue
    if [[ -z "$out" ]]; then
      out="$s"
    else
      out="$out,$s"
    fi
  done
  echo "$out"
}

csv_to_json_array() {
  local csv
  csv="$(trim_csv "$1")"
  if [[ -z "$csv" ]]; then
    echo "[]"
    return
  fi
  jq -nc --arg csv "$csv" '$csv | split(",")'
}

api_get() {
  local path="$1"
  curl -fsS "${BASE_URL}${path}"
}

api_post_empty() {
  local path="$1"
  curl -fsS -X POST "${BASE_URL}${path}" -H "Content-Type: application/json"
}

api_put_json_file() {
  local path="$1"
  local file="$2"
  curl -fsS -X PUT "${BASE_URL}${path}" -H "Content-Type: application/json" --data @"$file"
}

wait_sync_idle() {
  local end_ts
  end_ts=$(( $(date +%s) + 120 ))
  while [[ $(date +%s) -lt "$end_ts" ]]; do
    local st
    st="$(api_get "/sync/status" | jq -r '.state // "idle"')"
    if [[ "$st" != "running" ]]; then
      return 0
    fi
    sleep 1
  done
  echo "sync/status still running after 120s wait" >&2
  return 1
}

get_available_libraries_csv() {
  api_get "/libraries" | jq -r '.items // [] | map(.name // "") | map(select(length>0)) | unique | join(",")'
}

validate_scenario_libraries() {
  local scenario_name="$1"
  local wanted_csv="$2"
  local available_csv="$3"

  local missing=()
  IFS=',' read -r -a wanted_arr <<< "$wanted_csv"
  for w in "${wanted_arr[@]}"; do
    [[ -z "$w" ]] && continue
    local found=0
    IFS=',' read -r -a avail_arr <<< "$available_csv"
    for a in "${avail_arr[@]}"; do
      if [[ "$w" == "$a" ]]; then
        found=1
        break
      fi
    done
    if [[ "$found" -eq 0 ]]; then
      missing+=("$w")
    fi
  done

  if [[ ${#missing[@]} -gt 0 ]]; then
    echo "Invalid libraries in scenario '${scenario_name}': ${missing[*]}" >&2
    echo "Available libraries: ${available_csv}" >&2
    return 1
  fi
}

timestamp_compact() {
  date +"%Y%m%d-%H%M%S"
}

RUN_ID="$(timestamp_compact)"
RUN_DIR="${OUTPUT_DIR}/${RUN_ID}"
mkdir -p "$RUN_DIR"

echo "Run ID: $RUN_ID"
echo "Output: $RUN_DIR"
echo "API Base: $BASE_URL"

api_get "/health" >/dev/null
api_get "/settings" > "${RUN_DIR}/settings.before.json"

restore_settings() {
  if [[ "$KEEP_TEST_SETTINGS" == "1" ]]; then
    return 0
  fi
  if api_put_json_file "/settings" "${RUN_DIR}/settings.before.json" >/dev/null 2>&1; then
    echo "Settings restored."
  else
    echo "WARN: failed to restore settings." >&2
  fi
}
trap restore_settings EXIT

movie_csv="$(trim_csv "$MOVIE_LIBS")"
tv_csv="$(trim_csv "$TV_LIBS")"

SCENARIOS=()
if [[ -n "$movie_csv" ]]; then
  SCENARIOS+=("movies-only|$movie_csv")
fi
if [[ -n "$movie_csv" && -n "$tv_csv" ]]; then
  combo="$(trim_csv "${movie_csv},${tv_csv}")"
  # dedupe in order
  combo="$(echo "$combo" | awk -F',' '{
    out=""; n=split($0,a,",");
    for(i=1;i<=n;i++){ if(!seen[a[i]]++){ out=(out==""?a[i]:out","a[i]) } }
    print out
  }')"
  SCENARIOS+=("movies-plus-tv|$combo")
fi
if [[ ${#SCENARIOS[@]} -eq 0 ]]; then
  current="$(jq -r '.libraries // [] | join(",")' "${RUN_DIR}/settings.before.json")"
  current="$(trim_csv "$current")"
  SCENARIOS+=("current-libraries|$current")
fi

available_csv="$(get_available_libraries_csv)"
if [[ -z "$available_csv" ]]; then
  echo "No libraries returned by /libraries. Check Emby settings first." >&2
  exit 1
fi
echo "Available libraries: ${available_csv}"
for sc in "${SCENARIOS[@]}"; do
  scenario_name="${sc%%|*}"
  scenario_libs_csv="${sc#*|}"
  validate_scenario_libraries "$scenario_name" "$scenario_libs_csv" "$available_csv"
done

IFS=',' read -r -a CONCURRENCIES <<< "$CONCURRENCY_LIST"
for i in "${!CONCURRENCIES[@]}"; do
  CONCURRENCIES[$i]="$(echo "${CONCURRENCIES[$i]}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
done

RESULTS_JSONL="${RUN_DIR}/results.jsonl"
: > "$RESULTS_JSONL"

wait_sync_idle

for sc in "${SCENARIOS[@]}"; do
  scenario_name="${sc%%|*}"
  scenario_libs_csv="${sc#*|}"
  scenario_libs_json="$(csv_to_json_array "$scenario_libs_csv")"

  for c in "${CONCURRENCIES[@]}"; do
    [[ -z "$c" ]] && continue
    run_label="${scenario_name}-c${c}"
    echo
    echo "=== Running ${run_label} ==="
    echo "Libraries: ${scenario_libs_csv}"

    jq -n \
      --slurpfile s "${RUN_DIR}/settings.before.json" \
      --argjson libs "$scenario_libs_json" \
      --argjson c "$c" \
      '{
        emby: {
          base_url: ($s[0].emby.base_url // ""),
          api_key: ($s[0].emby.api_key // ""),
          user_id: ($s[0].emby.user_id // "")
        },
        libraries: $libs,
        excluded_paths: ($s[0].excluded_paths // []),
        sync: { concurrency: $c },
        shenyi: {
          base_url: ($s[0].shenyi.base_url // ""),
          api_key: ($s[0].shenyi.api_key // "")
        },
        webhook_token: ($s[0].webhook_token // "")
      }' > "${RUN_DIR}/payload.${run_label}.json"

    api_put_json_file "/settings" "${RUN_DIR}/payload.${run_label}.json" >/dev/null
    api_post_empty "/sync" >/dev/null

    snap_file="${RUN_DIR}/${run_label}.snapshots.jsonl"
    : > "$snap_file"
    deadline=$(( $(date +%s) + TIMEOUT_MINUTES * 60 ))

    while true; do
      status_json="$(api_get "/sync/status")"
      now_iso="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
      jq -nc --arg now "$now_iso" --argjson s "$status_json" \
        '{polled_at:$now, state:($s.state//""), current_step:($s.current_step//""), current_library:($s.current_library//""), items_synced:($s.items_synced//0), items_discovered:($s.items_discovered//0), libraries_total:($s.libraries_total//0), libraries_completed:($s.libraries_completed//0), detail_requests_total:($s.detail_requests_total//0), detail_requests_completed:($s.detail_requests_completed//0), current_page:($s.current_page//0), current_page_size:($s.current_page_size//0), current_library_total_items:($s.current_library_total_items//0), failed_items:($s.failed_items//0)}' >> "$snap_file"

      state="$(echo "$status_json" | jq -r '.state // "idle"')"
      finished="$(echo "$status_json" | jq -r '.last_finished_at // ""')"
      if [[ "$state" != "running" && -n "$finished" ]]; then
        break
      fi
      if [[ $(date +%s) -gt "$deadline" ]]; then
        echo "Timeout waiting sync completion for ${run_label}" >&2
        exit 1
      fi
      sleep "$POLL_INTERVAL_SECONDS"
    done

    row="$(jq -nc \
      --arg run_id "$RUN_ID" \
      --arg scenario_name "$scenario_name" \
      --arg concurrency "$c" \
      --arg libraries "$scenario_libs_csv" \
      --argjson s "$status_json" \
      '{
        run_id:$run_id,
        scenario_name:$scenario_name,
        concurrency:($concurrency|tonumber),
        libraries:$libraries,
        state:($s.state//""),
        last_result:($s.last_result//""),
        error:($s.error//""),
        analysis_error:($s.analysis_error//""),
        last_started_at:($s.last_started_at//""),
        last_finished_at:($s.last_finished_at//""),
        duration_seconds:($s.duration_seconds//0),
        items_synced:($s.items_synced//0),
        items_discovered:($s.items_discovered//0),
        detail_requests_total:($s.detail_requests_total//0),
        detail_requests_completed:($s.detail_requests_completed//0),
        failed_items:($s.failed_items//0),
        analysis_groups:($s.analysis_groups//0),
        timing_list_user_views:($s.timings.list_user_views//0),
        timing_list_library_items:($s.timings.list_library_items//0),
        timing_detail_requests:($s.timings.detail_requests//0),
        timing_normalize_items:($s.timings.normalize_items//0),
        timing_db_delete:($s.timings.db_delete//0),
        timing_db_insert:($s.timings.db_insert//0),
        timing_analysis:($s.timings.analysis//0)
      }')"
    echo "$row" >> "$RESULTS_JSONL"
    echo "Completed ${run_label}"
  done
done

jq -s '.' "$RESULTS_JSONL" > "${RUN_DIR}/results.json"

jq -r '
  ([
    "run_id","scenario_name","concurrency","libraries","state","last_result","error","analysis_error",
    "last_started_at","last_finished_at","duration_seconds","items_synced","items_discovered",
    "detail_requests_total","detail_requests_completed","failed_items","analysis_groups",
    "timing_list_user_views","timing_list_library_items","timing_detail_requests","timing_normalize_items",
    "timing_db_delete","timing_db_insert","timing_analysis"
  ] | @csv),
  (.[] | [
    .run_id,.scenario_name,.concurrency,.libraries,.state,.last_result,.error,.analysis_error,
    .last_started_at,.last_finished_at,.duration_seconds,.items_synced,.items_discovered,
    .detail_requests_total,.detail_requests_completed,.failed_items,.analysis_groups,
    .timing_list_user_views,.timing_list_library_items,.timing_detail_requests,.timing_normalize_items,
    .timing_db_delete,.timing_db_insert,.timing_analysis
  ] | @csv)
' "${RUN_DIR}/results.json" > "${RUN_DIR}/results.csv"

{
  echo "# Sync Performance Validation Summary"
  echo
  echo "| Scenario | Concurrency | Result | Duration(s) | Items Synced | Discovered | Fallback (done/total) | Failed Items | list_library_items(s) | detail_requests(s) | db_insert(s) | analysis(s) |"
  echo "| --- | ---: | --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |"
  jq -r '.[] | "| \(.scenario_name) | \(.concurrency) | \(.last_result) | \(.duration_seconds) | \(.items_synced) | \(.items_discovered) | \(.detail_requests_completed)/\(.detail_requests_total) | \(.failed_items) | \(.timing_list_library_items) | \(.timing_detail_requests) | \(.timing_db_insert) | \(.timing_analysis) |"' "${RUN_DIR}/results.json"
} > "${RUN_DIR}/SUMMARY.md"

echo
echo "Done."
echo "JSON: ${RUN_DIR}/results.json"
echo "CSV : ${RUN_DIR}/results.csv"
echo "MD  : ${RUN_DIR}/SUMMARY.md"



