# Emby Dedup V1 - Full Product Specification

## 1. Project Summary

Build a dedicated Emby duplicate-version cleanup tool for **Unraid + Docker**.

The tool must:
- Fully sync media metadata from Emby into a local SQLite database
- Detect duplicate versions of the same movie or episode
- Compare versions using user-configurable rule ordering
- Recommend one version to keep
- Allow manual override
- Delete unwanted versions through the external **emby 神医** API
- Provide a Web UI for sync, rules, results, manual override, and deletion
- Keep operation logs
- Reserve a webhook route for future incremental updates

This is a dedicated tool focused on **Emby duplicate cleanup only**.

---

## 2. Runtime / Tech Stack

### Deployment
- Unraid
- Docker

### Backend
- Python 3.11
- FastAPI

### Frontend
- Vue 3

### Database
- SQLite

### Persistent Storage
Use mounted `/config` directory for:
- SQLite database
- app configuration
- logs

Suggested paths inside container:
- `/config/app.db`
- `/config/config.json`
- `/config/logs/`

---

## 3. Core Business Goal

Given multiple versions of the same media item, the system should:
1. identify duplicate versions
2. compare them by enabled rules in user-defined order
3. recommend which one to keep
4. mark the others as delete candidates
5. allow manual override
6. delete confirmed items through emby 神医

Example:
- Movie A version 1: 4K HDR HEVC no Chinese subtitles
- Movie A version 2: 1080p SDR H264 with Chinese subtitles

If subtitle rule is ordered before resolution/effect, version 2 may win.

The rule order is fully user-controlled.

---

## 4. Sync Strategy

### Before every analysis
The system must perform a **full Emby sync** before running analysis.

Required behavior:
- fetch selected libraries from Emby
- fetch media item details concurrently
- normalize metadata
- clear and rebuild media snapshot table
- clear and rebuild analysis results

This ensures each analysis is based on the latest Emby data.

### After delete
After delete execution:
- prefer **local incremental DB update**
- do not force another full sync by default
- reserve a webhook route for future Emby notifications

---

## 5. Dedup Eligibility

### Important rule
Only media with **TMDb ID** participate in dedup analysis.

Behavior:
- items without `tmdbid` may still be synced into database
- but must be marked `eligible_for_dedup = false`
- they do not participate in duplicate grouping
- they do not become delete candidates

Future version may expose a UI page listing items without TMDb ID.

---

## 6. Duplicate Grouping Logic

### Movies
Group by:
- `tmdbid`

### Episodic media
Includes:
- TV
- Anime
- Variety
- Documentary episodes
- Any episode-based content

Group by:
- `tmdbid + season_number + episode_number`

### Not supported
- season-level dedup
- filename-based primary grouping
- grouping by title/year as fallback

If no TMDb ID exists, do not dedup.

---

## 7. User-Controlled Scope

### Library selection
User can choose which Emby libraries are included in sync / analysis.

Examples:
- Movies
- TV Shows
- Anime
- Documentary
- Variety

### Excluded paths
User can configure excluded paths.
Any item under an excluded path:
- may be synced into DB
- but must not be deleted
- should be marked protected / excluded in analysis results

---

## 8. Rule Engine

## 8.1 General Rule Model
Each rule supports:
- enable / disable
- overall order in comparison chain
- optional internal priority ordering

The user can:
- enable only selected rules
- drag rules into any order
- reorder internal priority for categorical rules

Example:
User enables only:
- subtitle
- runtime
- effect
- resolution
- codec

Then user orders them as:
1. subtitle
2. effect
3. resolution
4. codec
5. runtime

The comparator must follow exactly that sequence.

---

## 8.2 V1 Rules Included
- subtitle
- runtime
- effect
- resolution
- bit_depth
- bitrate
- codec
- filesize
- date_added
- frame_rate (present but default disabled)

### V1 Rule Removed
- quality

Do not implement filename/path based inference of:
- REMUX
- BluRay
- WEB-DL
- HDTV
- WEBRip

Ignore quality tags in V1.

---

## 8.3 Rule Semantics

### subtitle
Critical business rule.

Interpretation:
- only compare whether a version has **Chinese subtitles**
- do not compare subtitle count
- do not give extra advantage to multi-language subtitle sets if Chinese already exists

Examples:
- A: Chinese + English + multi-language
- B: Chinese only
- On subtitle rule, A == B
- C: English only, no Chinese
- C < A/B

For V1:
- any subtitle stream returned by Emby can be used
- do not distinguish internal/external/default/forced
- detect Chinese via language/title matching

Suggested Chinese detection:
Language codes:
- zh
- chi
- zho
- zh-cn
- zh-tw
- zh-hans
- zh-hant

Subtitle title keywords:
- 中文
- 简体
- 繁体
- CHS
- CHT

### runtime
Numeric comparison.
Default preference example:
- longer runtime wins (`desc`)
Used mainly to avoid broken/trimmed versions.

### effect
Categorical comparison.
Typical values:
- dovi_p8
- dovi_p7
- dovi_p5
- dovi_other
- hdr10+
- hdr10
- hdr
- sdr

Internal priority should be configurable.

### resolution
Categorical comparison.
Typical values:
- 4k
- 1080p
- 720p
- 480p

Internal priority should be configurable.

### bit_depth
Numeric comparison.
Default:
- higher wins (`desc`)

### bitrate
Numeric comparison.
Default:
- higher wins (`desc`)

### codec
Categorical comparison.
Typical values:
- av1
- hevc
- h264
- vp9

Internal priority should be configurable.

### filesize
Numeric comparison.
Default:
- larger wins (`desc`)

### date_added
Temporal comparison.
Default:
- earlier wins (`asc`)
Used only as a late tiebreaker.

### frame_rate
Numeric comparison.
Default disabled.
If enabled:
- higher wins (`desc`) unless user changes it

---

## 8.4 Comparator Behavior
When comparing two versions:
1. take enabled rules only
2. sort rules by user-defined order
3. compare one rule at a time
4. first rule that produces a winner decides the result
5. if all enabled rules tie, keep deterministic stable choice

Tie behavior:
- if all relevant fields are equal, keep one deterministically
- other items become delete candidates

---

## 9. Manual Override

The system should recommend:
- keep item
- delete candidates

But user must be able to override:
- choose a different item to keep
- update which items will be deleted

Manual choice always takes precedence over automatic recommendation.

---

## 10. Delete Flow

### V1 requirements
- no read-only mode
- deletion requires explicit user confirmation
- deletion must go through **emby 神医** API
- do not directly delete files in local filesystem

### Protected items
If an item is under excluded path:
- it must not be auto-deleted
- it should be shown as protected / not deletable

### After successful deletion
- update local DB incrementally
- remove / mark deleted items from analysis results
- keep operation log

---

## 11. Logging

The system must record logs for:
- sync start
- sync finish
- analysis start
- analysis finish
- delete request
- delete success
- delete failure
- mapping of keep item vs delete items

Keep both:
- structured DB logs
- plain text file logs under `/config/logs`

---

## 12. Web UI Scope (V1)

### Page 1: Dashboard
Show:
- Emby connection status
- last sync time
- duplicate group count
- delete candidate count
- quick actions

### Page 2: Library / Sync
Allow:
- configure Emby server info
- choose libraries
- configure concurrency
- trigger sync
- view sync status

### Page 3: Rule Configuration
Allow:
- enable / disable rules
- drag rule order
- reorder internal priorities for categorical rules
- save config

### Page 4: Duplicate Results
Show:
- duplicate groups
- keep recommendation
- delete candidates
- item metadata used for comparison
- protected / excluded items
- manual override controls

### Page 5: Delete Confirmation
Show:
- exact items to delete
- grouped by media
- confirmation action

---

## 13. Database Persistence Rules

### Rebuilt every full sync
- `media_items`
- `analysis_results`

### Persistent across syncs
- `rule_config`
- `operation_logs`
- `app_settings`

---

## 14. Webhook Scope

V1 only requires:
- reserve webhook route
- return valid stub response
- optional logging of received event payload

Full webhook-driven sync/update can be implemented later.

---

## 15. Non-Goals for V1
Do not implement:
- season-level dedup
- quality tag parsing
- automatic scheduled sync
- Sonarr/Radarr integration
- subtitle download
- multi-user permissions
- direct filesystem delete
- fallback dedup for items without TMDb ID

---

## 16. Delivery Strategy
Implement in phases:
- Phase 1: project skeleton, DB schema, Emby sync
- Phase 2: duplicate grouping + rule engine
- Phase 3: Web UI + manual override
- Phase 4: delete integration + logs + webhook stub