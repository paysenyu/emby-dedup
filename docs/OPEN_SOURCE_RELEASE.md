# Open Source Release Guide

This folder contains sanitized files for publishing to GitHub and Docker Hub.

## 1. Privacy cleanup scope
- Remove private network addresses and host bind paths from `docker-compose.yml`.
- Replace real tokens/API keys with placeholders in sample config.
- Ignore runtime DB/log/report artifacts from source control.
- Use localhost defaults in validation scripts and docs.

## 2. GitHub publish process
1. Create a clean branch for open-source release.
2. Replace repository files with corresponding files from `release-package/`.
3. Remove tracked private/generated artifacts from git index (if tracked).
4. Confirm no secrets in history for this release branch.
5. Update project README with open-source run instructions.
6. Tag release (`vX.Y.Z`) and push to GitHub.

## 3. Docker Hub publish process
1. Build image locally (no extra sqlite3 apt package required):
   ```bash
   docker build -t <dockerhub-username>/emby-dedup:<tag> .
   ```
2. Smoke test image:
   ```bash
   docker run --rm -p 5055:5055 <dockerhub-username>/emby-dedup:<tag>
   ```
3. Login and push:
   ```bash
   docker login
   docker push <dockerhub-username>/emby-dedup:<tag>
   docker tag <dockerhub-username>/emby-dedup:<tag> <dockerhub-username>/emby-dedup:latest
   docker push <dockerhub-username>/emby-dedup:latest
   ```
4. Verify Docker Hub README/description and pull command.

## 4. Suggested release tags
- GitHub: `v0.0.1`, `v0.0.2`, ...
- Docker: same as GitHub tag plus `latest`.

## 5. How to release after future updates
1. Develop and verify new features in your working folder.
2. Bump `backend/app/core/version.py` (for example `0.0.1` -> `0.0.2`).
3. Sync open-source cleanup files if needed (from `release-package/`).
4. Commit to `main` (or merge from a feature branch).
5. Create and push git tag `v0.0.2`.
6. Build and push Docker image tags:
   - `<dockerhub-user>/emby-dedup:0.0.2`
   - `<dockerhub-user>/emby-dedup:latest`

