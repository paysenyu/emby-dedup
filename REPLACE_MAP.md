# Release Package Mapping

Copy the following files from this folder to repository root before open-source release:

- `release-package/.gitignore` -> `.gitignore`
- `release-package/.dockerignore` -> `.dockerignore`
- `release-package/Dockerfile` -> `Dockerfile`
- `release-package/docker-compose.yml` -> `docker-compose.yml`
- `release-package/examples/config.example.json` -> `examples/config.example.json`
- `release-package/docs/SYNC_PERF_VALIDATION_TEMPLATE.md` -> `docs/SYNC_PERF_VALIDATION_TEMPLATE.md`

Optional script replacements for open-source defaults:
- `release-package/tasks/*.sh|ps1` -> `tasks/`

New docs to add:
- `release-package/docs/OPEN_SOURCE_RELEASE.md`
- `release-package/docs/RELEASE_CHECKLIST.md`

Key change notes:
- Docker runtime image removes `sqlite3` package install.
- Defaults changed from private network values to localhost/relative paths.
- Sample config includes `user_id` and `webhook_token` placeholders.
