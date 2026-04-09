# Sync Performance Validation Template (Open Source)

## 1. Goal
Validate sync performance improvements using neutral defaults and reproducible commands.

## 2. Preconditions
- Service is reachable: `http://localhost:5055/health`
- Emby settings are configured in `/settings`
- Test library names are confirmed

## 3. Run command (PowerShell)
```powershell
powershell -ExecutionPolicy Bypass -File X:\codex\tasks\validate_sync_performance.ps1 `
  -BaseUrl "http://localhost:5055" `
  -MovieLibraries @("Movies") `
  -TvLibraries @("TV Shows") `
  -ConcurrencyList @(1,4,8)
```

## 4. Run command (Bash)
```bash
cd /path/to/codex
BASE_URL="http://localhost:5055" \
MOVIE_LIBS="Movies" \
TV_LIBS="TV Shows" \
CONCURRENCY_LIST="1,4,8" \
OUTPUT_DIR="./tasks/reports/sync-performance" \
bash ./tasks/validate_sync_performance.sh
```

## 5. Outputs
- `results.json`
- `results.csv`
- `SUMMARY.md`

## 6. Review points
- Total duration trend by concurrency.
- `detail_requests_completed / total` fallback ratio.
- Any sync/analysis failures.
