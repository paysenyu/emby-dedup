# Release Checklist (GitHub + Docker Hub)

## A. Secret and privacy check
- [ ] No private IP/domain in compose/docs/scripts.
- [ ] No real API key/token/user ID in configs/docs/tests.
- [ ] No runtime DB/log/report artifacts tracked.
- [ ] `.gitignore` and `.dockerignore` block local sensitive files.

## B. Functional baseline check
- [ ] `docker compose up --build` works on clean machine.
- [ ] `/health` endpoint returns OK.
- [ ] Frontend homepage loads from port 5055.
- [ ] Settings can be saved with example config shape.

## C. Documentation check
- [ ] README has open-source quick start.
- [ ] Sample config includes required keys (`user_id`, `webhook_token`).
- [ ] Release instructions for GitHub and Docker Hub are present.
- [ ] Versioning/tagging policy is clear.

## D. GitHub release check
- [ ] Release branch created from latest baseline.
- [ ] Commit message references open-source cleanup.
- [ ] Tag `vX.Y.Z` created.
- [ ] Release notes include known limitations.

## E. Docker Hub release check
- [ ] Image builds with no local-only dependencies.
- [ ] Image starts with default env settings.
- [ ] Version tag pushed.
- [ ] `latest` tag pushed.
- [ ] Pull + run validated from fresh environment.
