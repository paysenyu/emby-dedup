# SQLite Schema Design (V1)

## 1. app_settings
Stores persistent application settings.

Suggested columns:
- id INTEGER PRIMARY KEY
- emby_base_url TEXT NOT NULL
- emby_api_key TEXT NOT NULL
- selected_libraries_json TEXT NOT NULL
- excluded_paths_json TEXT NOT NULL
- sync_concurrency INTEGER NOT NULL DEFAULT 6
- shenyi_base_url TEXT
- shenyi_api_key TEXT
- created_at TEXT NOT NULL
- updated_at TEXT NOT NULL

---

## 2. media_items
Full synced media snapshot.
Rebuilt on each full sync.

Suggested columns:
- id INTEGER PRIMARY KEY
- emby_item_id TEXT NOT NULL
- library_name TEXT
- item_type TEXT NOT NULL
- parent_type TEXT
- title TEXT NOT NULL
- series_title TEXT
- production_year INTEGER
- tmdb_id TEXT
- imdb_id TEXT
- tvdb_id TEXT
- season_number INTEGER
- episode_number INTEGER
- runtime_ticks INTEGER
- runtime_seconds REAL
- video_codec TEXT
- video_width INTEGER
- video_height INTEGER
- resolution_label TEXT
- bitrate INTEGER
- bit_depth INTEGER
- effect_label TEXT
- frame_rate REAL
- file_size INTEGER
- path TEXT
- container TEXT
- subtitle_streams_json TEXT NOT NULL
- has_chinese_subtitle INTEGER NOT NULL DEFAULT 0
- eligible_for_dedup INTEGER NOT NULL DEFAULT 0
- is_excluded_path INTEGER NOT NULL DEFAULT 0
- date_created TEXT
- date_added TEXT
- raw_json TEXT NOT NULL
- created_at TEXT NOT NULL
- updated_at TEXT NOT NULL

Recommended indexes:
- idx_media_tmdb_id
- idx_media_group_movie (tmdb_id)
- idx_media_group_episode (tmdb_id, season_number, episode_number)
- idx_media_eligible
- idx_media_emby_item_id

---

## 3. rule_config
Stores persistent rule configuration.

Suggested columns:
- id INTEGER PRIMARY KEY
- rules_json TEXT NOT NULL
- created_at TEXT NOT NULL
- updated_at TEXT NOT NULL

Only one active row is also acceptable.

---

## 4. analysis_results
Rebuilt on each analysis run.

Suggested columns:
- id INTEGER PRIMARY KEY
- group_key TEXT NOT NULL
- media_kind TEXT NOT NULL
- tmdb_id TEXT NOT NULL
- title TEXT NOT NULL
- season_number INTEGER
- episode_number INTEGER
- item_id INTEGER NOT NULL
- emby_item_id TEXT NOT NULL
- action TEXT NOT NULL
  - keep_recommended
  - delete_candidate
  - protected
  - keep_manual
- reason_json TEXT
- is_manual_override INTEGER NOT NULL DEFAULT 0
- created_at TEXT NOT NULL
- updated_at TEXT NOT NULL

Recommended indexes:
- idx_analysis_group_key
- idx_analysis_action

---

## 5. operation_logs
Persistent operational logs.

Suggested columns:
- id INTEGER PRIMARY KEY
- log_type TEXT NOT NULL
  - sync
  - analysis
  - delete
  - webhook
- level TEXT NOT NULL
  - info
  - warning
  - error
- message TEXT NOT NULL
- detail_json TEXT
- created_at TEXT NOT NULL

---

## Optional future table
### unidentified_media
Not needed in V1 because items without tmdbid are already stored in media_items.
Can be added later as a convenience view/table if needed.