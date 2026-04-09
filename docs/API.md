# API Design (V1)

## Health
### GET /health
Returns service health.

Response:
```json
{
  "status": "ok"
}
```

---

## Settings
### GET /settings
Returns persisted application settings.

### PUT /settings
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
### GET /libraries
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
### POST /sync
Trigger full sync.

Possible behavior:
- async background task with status tracking
- returns task id / current status

### GET /sync/status
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
### GET /rules
Return current rule configuration.

### PUT /rules
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
### POST /analysis/run
Rebuild analysis results using latest synced media snapshot.

### GET /analysis/groups
List duplicate groups.

Suggested query params:
- page
- page_size
- library
- protected_only
- has_manual_override

### GET /analysis/groups/{group_id}
Return group detail:
- media identity
- keep recommendation
- delete candidates
- protected items
- item metadata

### PUT /analysis/groups/{group_id}/override
Manually choose keep item and update delete candidates.

Payload example:
```json
{
  "keep_item_id": 123
}
```

---

## Delete
### POST /delete/preview
Return what would be deleted for current confirmed selection.

### POST /delete/execute
Execute delete via emby 神医 API for selected delete candidates.

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
### GET /logs
List operation logs.

---

## Webhook
### POST /webhook/emby
Emby/StrmAssistant webhook endpoint.

Port convention:
- Use unified service port `5055`.
- Example callback URL:
  - `http://<dup-host>:5055/webhook/emby?token=<webhook-token>`

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
