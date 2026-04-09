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
- GitHub: `v0.1.0`, `v0.1.1`, ...
- Docker: same as GitHub tag plus `latest`.

