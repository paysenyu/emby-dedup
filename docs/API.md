# API Design (V1)

## Health
### GET /api/health
Returns service health.

Response:
```json
{
  "status": "ok"
}
```

---

## Settings
### GET /api/settings
Returns persisted application settings.

### PUT /api/settings
Updates application settings.

Suggested payload:
```json
{
  "emby": {
    "base_url": "http://emby:8096",
    "api_key": "xxx"
  },
  "libraries": ["Movies", "TV Shows"],
  "excluded_paths": ["/mnt/media/protected"],
  "sync": {
    "concurrency": 6
  },
  "shenyi": {
    "base_url": "http://emby-shenyi:8080",
    "api_key": ""
  }
}
```

---

## Libraries
### GET /api/libraries
Fetch available libraries from Emby.

Response example:
```json
{
  "items": [
    {"id": "1", "name": "Movies", "collection_type": "movies"},
    {"id": "2", "name": "TV Shows", "collection_type": "tvshows"}
  ]
}
```

---

## Sync
### POST /api/sync
Trigger full sync.

Possible behavior:
- async background task with status tracking
- returns task id / current status

### GET /api/sync/status
Return current or last sync status.

Response example:
```json
{
  "state": "idle",
  "last_started_at": null,
  "last_finished_at": null,
  "items_synced": 0,
  "error": null
}
```

---

## Rules
### GET /api/rules
Return current rule configuration.

### PUT /api/rules
Persist new rule configuration.

Payload example:
```json
{
  "rules": [
    {
      "id": "subtitle",
      "enabled": true,
      "order": 1,
      "priority": ["zh", "other", "none"]
    },
    {
      "id": "resolution",
      "enabled": true,
      "order": 2,
      "priority": ["4k", "1080p", "720p", "480p"]
    }
  ]
}
```

---

## Analysis
### POST /api/analysis/run
Rebuild analysis results using latest synced media snapshot.

### GET /api/analysis/groups
List duplicate groups.

Suggested query params:
- page
- page_size
- library
- protected_only
- has_manual_override

### GET /api/analysis/groups/{group_id}
Return group detail:
- media identity
- keep recommendation
- delete candidates
- protected items
- item metadata

### PUT /api/analysis/groups/{group_id}/override
Manually choose keep item and update delete candidates.

Payload example:
```json
{
  "keep_item_id": 123
}
```

---

## Delete
### POST /api/delete/preview
Return what would be deleted for current confirmed selection.

### POST /api/delete/execute
Execute delete via emby 绁炲尰 API for selected delete candidates.

Payload example:
```json
{
  "group_ids": [1, 2, 3]
}
```

Response example:
```json
{
  "success_count": 5,
  "failed_count": 1,
  "results": [
    {"item_id": 11, "status": "success"},
    {"item_id": 12, "status": "failed", "message": "API error"}
  ]
}
```

---

## Logs
### GET /api/logs
List operation logs.

---

## Webhook
### POST /api/webhook/emby
Emby/StrmAssistant webhook endpoint.

Port convention:
- Use unified service port `5055`.
- Example callback URL:
  - `http://<dup-host>:5055/api/webhook/emby?token=<webhook-token>`

Supported content types:
- `application/json`
- `multipart/form-data`

Notes:
- Query token `?token=...` has higher priority than body `Token`.
- Token mismatch returns `401`.
- Malformed/unknown payload shape returns safe response:
```json
{
  "status": "ok",
  "matched": 0,
  "updated": 0
}
```

