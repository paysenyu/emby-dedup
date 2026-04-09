# Acceptance Criteria

## Phase 1
- Backend and frontend directories exist with clean structure
- Docker assets exist and are documented
- FastAPI app starts successfully
- SQLite DB file is created under `/config`
- Settings can be persisted
- Emby base URL/API key can be configured
- Selected libraries can be read from Emby
- Full sync endpoint rebuilds `media_items`
- Sync concurrency is configurable
- README documents setup and usage

## Phase 2
- Only items with tmdbid are analyzed
- Movies are grouped by tmdbid
- Episodic items are grouped by tmdbid + season + episode
- Rule config can be saved and loaded
- User-defined rule ordering changes result
- Subtitle rule matches business logic:
  - Chinese subtitle > no Chinese subtitle
  - Chinese+multi == Chinese-only on subtitle comparison
- Protected/excluded paths do not become deletable
- Analysis output includes:
  - keep item
  - delete candidates
  - protected items if any

## Phase 3
- User can trigger sync from UI
- User can configure selected libraries from UI
- User can enable/disable rules
- User can drag and reorder rules
- User can review duplicate groups
- User can manually change the keep item
- UI clearly shows delete candidates and protected items

## Phase 4
- Delete requires explicit confirmation
- Delete requests go through emby 神医 API
- Successful delete updates local DB without forced full resync
- Operation logs are persisted
- Webhook route exists and returns a valid stub response