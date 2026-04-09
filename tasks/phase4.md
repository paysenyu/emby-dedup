# Phase 4 Task Brief for Codex

Implement **Phase 4 only**.

## Scope
- emby 神医 delete integration
- delete preview / execute APIs
- incremental local DB update after successful delete
- operation logging
- webhook stub route

Required endpoints:
- POST /delete/preview
- POST /delete/execute
- GET /logs
- POST /webhook/emby