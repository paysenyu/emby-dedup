# emby-dedup

Open-source duplicate cleanup toolkit for Emby.

## Features
- Sync media snapshots from Emby into SQLite.
- Analyze duplicate media versions with rule-based ranking.
- Manual keep override per duplicate group.
- Delete preview and execution with webhook-based status updates.
- Minimal web UI (FastAPI + Vue).

## Quick Start (Docker Compose)
1. Prepare local config folder:
   - Create `./config`
   - Copy `examples/config.example.json` to `./config/config.json`
   - Fill in your own Emby values
2. Start service:
   ```bash
   docker compose up --build -d
   ```
3. Open:
   - UI: `http://localhost:5055/`
   - API docs: `http://localhost:5055/docs`

## Required Config Keys
- `emby.base_url`
- `emby.api_key`
- `emby.user_id`
- `libraries`
- `webhook_token`

## Environment Variables
- `APP_DB_PATH` default `/config/app.db`
- `APP_CONFIG_PATH` default `/config/config.json`
- `APP_LOGS_DIR` default `/config/logs`

## Publish Notes
This repository includes `release-package/` for open-source release cleanup.
Use files in that folder to replace private/local values before publishing.

## Security Notes
- Never commit real API keys/tokens.
- Never commit runtime DB/log/report artifacts.
- Review compose/scripts/docs for private IP/path leakage before release.

## License
Add your license file (for example MIT) before public release.
