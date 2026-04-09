# emby-dedup

Backend + minimal Vue frontend for Emby duplicate cleanup MVP.

## MVP Scope
- Sync Emby media snapshot into SQLite (one row per Emby `MediaSource`)
- Preserve rich Emby metadata while keeping normalized comparison fields
- Analyze duplicates using ordered rules
- Manual keep override per group
- Delete preview grouped by media
- Delete execution for selected items (including manual keep selections) or current `delete_candidate` set

Not included yet: delete automation policies, advanced UI polish.

## Project Structure
- `backend/app/main.py`: FastAPI bootstrap
- `backend/app/api/`: API routes
- `backend/app/services/`: sync, analysis, rules, delete, clients
- `backend/app/db/`: SQLite engine + ORM models
- `backend/tests/`: minimal unit tests
- `frontend/`: Vue 3 app

## Quick Start
1. Build and run the integrated Docker app:
```bash
docker compose up --build
```
2. URLs:
- App UI (served by FastAPI): `http://localhost:5055/`
- API docs: `http://localhost:5055/docs`
- Emby webhook callback: `http://localhost:5055/api/webhook/emby?token=<your-webhook-token>`

## Port Convention
- Unified service port is `5055` (Docker image default and recommended runtime port).
- If you run via uvicorn manually, keep it consistent:
```bash
uvicorn backend.main:app --host 0.0.0.0 --port 5055
```

## Frontend Serving (Docker)
- Docker builds the Vue frontend (`frontend/dist`) during image build.
- FastAPI serves built frontend files from `/app/frontend_dist`.
- `/` returns the frontend app entry.
- API routes are namespaced under `/api` (for example: `/api/health`, `/api/settings`, `/api/analysis/*`).

## Environment Variables
- `APP_DB_PATH` default `/config/app.db`
- `APP_SQLITE_URL` optional full SQLite URL override
- `APP_CONFIG_PATH` default `/config/config.json`
- `APP_LOGS_DIR` default `/config/logs`

## End-to-End MVP Usage
1. Open `Settings/Sync` page.
2. Save settings (`PUT /api/settings`):
- Emby base URL + API key + user ID
- Selected libraries
- Excluded paths
- Sync concurrency
3. Load libraries from Emby (`GET /api/libraries`) and confirm selection.
4. Trigger sync (`POST /api/sync`) and wait for status (`GET /api/sync/status`) to return `idle`.
5. Analysis runs automatically after successful sync; manual rerun is available from `Analysis Groups` (`POST /api/analysis/run`).
6. Open `Analysis Groups` (`GET /api/analysis/groups`) and inspect group details (`GET /api/analysis/groups/{groupId}`).
7. Optional manual override (`PUT /api/analysis/groups/{groupId}/override`) to choose a different keep item.
- Selected keep item is stored as `keep_manual`.
- Protected items remain non-deletable.
8. Open `Delete Preview` (`POST /api/delete/preview`) to verify keep/delete/protected sets.
9. Execute deletion (`POST /api/delete/execute`).
- Uses current `analysis_results` only (`action=delete_candidate`), no recompute.
- Calls `POST /Items/{Id}/DeleteVersion` with `DeleteParent=false`.
- Uses per-row `delete_target_item_id` first (derived from `media_source_id=mediasource_<id>`), falls back to top-level Emby item id when parsing is unavailable.
- Treats HTTP 200 and 204 as success, ignores response body.

## Metadata Model Highlights
Each synced row represents one Emby media version (`MediaSource`) and stores:
- Source-level: container, size, runtime ticks, bitrate, path, source name
- Video-level: codec/display/range/bit depth/resolution/fps/profile/pixel/color/extended Dolby Vision fields
- Audio-level: codec/display/channel/channels/bitrate/sample rate/profile/default + streams JSON
- Subtitle-level: codec/language/title/display/default/forced/external/location + streams JSON
- Normalized compare fields: `effect_label`, `resolution_label`, `codec_label`, `bit_depth`, `bitrate`, `frame_rate`, `file_size`, `has_chinese_subtitle`, `chinese_subtitle_rank`

## API Summary
- Health: `GET /api/health`
- Settings: `GET /api/settings`, `PUT /api/settings`
- Libraries: `GET /api/libraries`
- Sync: `POST /api/sync`, `GET /api/sync/status`
- Rules: `GET /api/rules`, `PUT /api/rules`
- Analysis: `POST /api/analysis/run`, `GET /api/analysis/groups`, `GET /api/analysis/groups/{groupId}`, `PUT /api/analysis/groups/{groupId}/override`
- Metadata Issues: `GET /api/metadata/issues`
- Delete: `POST /api/delete/preview`, `POST /api/delete/execute`

## Safety Rules Enforced
- Analysis only uses `eligible_for_dedup=1` and valid TMDb IDs.
- Grouping:
- Movie: `tmdb_id`
- Episode: `tmdb_id + season_number + episode_number`
- Protected (`is_excluded_path=1`) items never become executable delete targets.
- Without explicit item selection, delete execute uses current `delete_candidate` rows.
- With explicit `item_ids`, user-selected keep rows can be executed too (protected/ignored safety still enforced).

## Operation Logs (Delete)
Delete execution persists minimal logs per item in `operation_logs`:
- `item_id`
- `status`
- `status_code`
- `message`
- `timestamp`

## Tests
Run backend tests (local Python env with dependencies installed):
```bash
cd backend
set PYTHONPATH=X:\codex\backend
python -m unittest discover -s tests -p "test_*.py"
```


## Frontend I18n
- Locale files live in `frontend/src/i18n/locales/` (active locale: `zh-CN.json`).
- I18n bootstrap is in `frontend/src/i18n/index.js`, wired in `frontend/src/main.js`.
- Add/update all new UI text via i18n keys instead of hardcoded component strings.
- Run localization checks:
```bash
cd frontend
npm run i18n:check
```
- `i18n:check` reports:
- missing i18n keys referenced by `t(...)`
- possible hardcoded CJK UI strings
- unused locale keys (warning)
