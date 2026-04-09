# Phase 2 Task Brief for Codex

Read:
- SPEC.md
- PLAN.md
- ACCEPTANCE.md
- docs/API.md
- docs/DB_SCHEMA.md

Implement **Phase 2 only** on top of existing Phase 1 code.

## Scope
- duplicate grouping
- ordered rule engine
- analysis results generation
- rule persistence APIs

### Must include
- POST /analysis/run
- GET /analysis/groups
- GET /analysis/groups/{group_id}
- GET /rules
- PUT /rules

### Required behavior
- analyze only items with eligible_for_dedup = true
- movies grouped by tmdb_id
- episodic grouped by tmdb_id + season_number + episode_number
- excluded-path items must not be deletable
- subtitle comparison must match spec exactly

### Output
Rebuild `analysis_results` each analysis run.