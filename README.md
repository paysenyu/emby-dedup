功能
同步emby媒体数据
采用SQLite数据库
根据媒体信息洗板去重
缺失元数据列表

去重说明：
按规则进行emby存量去重，如库内存在4k HDR ，4k SDR ， 1080p

根据自定义规则， 即删除4k sdr 和1080p  仅保留4k HDR版本

适合人群 ：仅限已安装神医pro用户，cd2方式挂载 ，可联动删除115网盘资源

 
 
 # emby-dedup

Open-source duplicate cleanup toolkit for Emby.

Current version: `0.0.1`

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

## Versioning
- Current version source of truth: `backend/app/core/version.py`
- Release tag format: `vX.Y.Z` (for example `v0.0.1`)
- For each feature release:
  1. Update `APP_VERSION`
  2. Commit and push
  3. Create Git tag
  4. Publish GitHub Release and Docker image with the same tag

## Security Notes
- Never commit real API keys/tokens.
- Never commit runtime DB/log/report artifacts.
- Review compose/scripts/docs for private IP/path leakage before release.

## License
Add your license file (for example MIT) before public release.
