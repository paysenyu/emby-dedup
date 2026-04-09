# Emby Dedup Development Plan

## Development Principles
- Do not try to build everything at once
- Deliver runnable increments
- Keep code structure clean and production-friendly
- Update README after each phase
- Keep configuration externalized

---

## Phase 1 - Foundation and Full Sync

### Goal
Create a runnable project skeleton and implement full Emby sync into SQLite.

### Tasks
1. Create backend project structure
2. Create frontend placeholder structure
3. Add Dockerfile and docker-compose
4. Add FastAPI app bootstrap
5. Add settings/config persistence
6. Add SQLite schema / ORM models
7. Add Emby client
8. Add library discovery API
9. Add full sync service:
   - load selected libraries
   - fetch items
   - fetch item details concurrently
   - normalize metadata
   - clear/rebuild `media_items`
10. Add sync status tracking
11. Add health endpoint
12. Add README and example config

### Deliverable
- App runs in Docker
- Can connect to Emby
- Can fetch selected libraries
- Can write media snapshot into DB

---

## Phase 2 - Analysis Engine

### Goal
Generate duplicate groups and recommendations.

### Tasks
1. Build duplicate grouping logic
2. Include only `eligible_for_dedup = true`
3. Add rule config storage
4. Add ordered comparator engine
5. Implement categorical/numeric comparator helpers
6. Implement subtitle comparator per spec
7. Generate `analysis_results`
8. Exclude protected path items from deletion
9. Add analysis APIs
10. Add unit tests for comparator logic

### Deliverable
- Analysis produces keep/delete recommendations
- Duplicate groups retrievable through API
- Rules configurable through API

---

## Phase 3 - Web UI

### Goal
Provide full browser workflow.

### Tasks
1. Add dashboard page
2. Add settings page
3. Add library selection and sync page
4. Add rules page
5. Add drag-and-drop order controls
6. Add duplicate list page
7. Add detail panel
8. Add manual override interactions
9. Add delete preview page

### Deliverable
- End-to-end review workflow available in UI

---

## Phase 4 - Delete Integration and Operations

### Goal
Execute deletion and keep system state consistent.

### Tasks
1. Add emby 神医 API client
2. Add delete confirmation endpoint
3. Execute delete for selected candidates
4. Update DB incrementally after success
5. Add operation logs to DB and file
6. Add webhook route stub
7. Add production notes to README

### Deliverable
- End-to-end delete flow works
- Logs persist
- Webhook route exists