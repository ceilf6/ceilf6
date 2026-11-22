# Asset Deployment Hardening Implementation Plan

> **For agentic workers:** Use executing-plans to implement this plan inline. The user approved execution in this session; no commit or push is authorized.

**Goal:** Restore the four live cards and prevent missing assets, unreadable directories, partial uploads, and false-success releases from recurring.

**Architecture:** Keep the existing `/assets/` URLs and ECS/Nginx layout. A shared Python asset validator is used by builds, preflight, and HTTP smoke checks; one SSH publisher and one server-side release helper handle full-site and asset-only publication under the same filesystem lock. Site publication retains the previous release and rolls back on origin failure; asset publication restores prior files on failure.

**Tech Stack:** Python 3 standard library, Bash/OpenSSH, curl, existing npm/Vite and GitHub Actions. No new package dependencies.

## Approved design and evidence

- Live SVGs returned 404 because the root-owned assets directory was 0744; `www-data` got EACCES. The previous release had 0755.
- Local `scp -D /usr/libexec/sftp-server` reproduced 0755 preservation for an existing directory and creation of 0744 for a missing destination containing 0644 sources.
- The current assets directory was created by the November 21 sync after the November 20 site replacement. The exact historical manual deployment command is unavailable; missing bundling is a strong inference, not a proven recorded command.
- Restore only permissions and the missing Profile.jpg first; do not overwrite current live statistics with a stale checkout.
- Required assets: github-stats-card.svg, blog-card.svg, vlog-card.svg, huggingface-card.svg, Profile.jpg. Also copy other repository assets unchanged.
- Both deployment modes stage uploads before modification, normalize public assets to directory 0755/file 0644, check readability as www-data, and take `/var/lock/wangjinghong-deploy.lock`.
- Validate origin status, MIME, and SVG XML. Public/CDN failure is reported without blindly rolling back a healthy origin.

## Files and responsibilities

- `deploy/assets.py`: required-asset contract; local validation and bundling; HTTP smoke checks using curl.
- `deploy/remote.py`: locked site/asset publication, reader preflight, rollback, preservation of static chunks and harness.
- `deploy/publish.sh`: identical local/CI entrypoint, unique same-filesystem staging, transport cleanup and public smoke check.
- `deploy/tests/test_assets.py`: build and HTTP behavior using temporary directories and a real local HTTP server.
- `deploy/tests/test_remote.py`: publication and rollback using temporary site trees; Linux/root tests exercise a real unprivileged reader.
- `deploy/tests/test_integration.py`: build/workflow wiring contract.
- `deploy/README.md`: prerequisites, supported commands, invariants and recovery.
- `site/package.json`: make standard build include the asset bundling command.
- `.github/workflows/deploy-ecs.yml`: use shared publisher; trigger on deploy tooling changes.
- `.github/workflows/update-stats-schedule.yml` and `update-github-contribution-graph.yml`: use shared asset publisher.
- `.github/workflows/verify.yml`: run deployment regression tests, including real Linux permissions.

## Execution checklist

### 1. Restore service
- [x] Reproduce 404 and www-data EACCES before changing production.
- [x] Under the shared lock, set assets directory to 0755 and atomically restore Profile.jpg at 0644.
- [x] Check all four SVGs plus Profile.jpg against the origin and public URL, including body/MIME (all 200, correct MIME).

### 2. Asset contract and build
- [x] Write failing tests for complete bundle, missing/empty/malformed SVG, wrong MIME, HTTP 404 and HTML fallback.
- [x] Run `python3 -m unittest discover -s deploy/tests -p test_assets.py -v` and observe the missing implementation failures.
- [x] Implement `assets.py` with `validate`, `bundle`, and `smoke` commands; bundle validates the source before modifying output.
- [x] Add `python3 ../deploy/assets.py bundle ../assets dist/assets` after `vite build` in the existing build command.
- [x] Re-run tests and `npm --prefix site run build`; the build copied 10 assets, including all five required files, at 0755/0644.

### 3. Locked server-side publication
- [x] Write failing tests for missing-directory publication, unreadable staging, invalid staging preserving the old site, failed probes rolling back site/assets, and preservation of static/harness.
- [x] Run `python3 -m unittest discover -s deploy/tests -p test_remote.py -v` before implementation.
- [x] Implement locked, staged server publication. Preflight precedes live changes; origin checks run while holding the lock. A failed site switch restores the old root; failed asset publication restores changed files.
- [x] Rehearsed both modes against `/var/tmp/wangjinghong-rehearsal-*` on the ECS host with a real www-data reader; production root stayed untouched.

### 4. One entrypoint and CI
- [x] Write failing workflow-wiring tests: standard build bundles assets, all three publishers use the same entrypoint, and CI runs deployment tests.
- [x] Implement `bash deploy/publish.sh site` and `bash deploy/publish.sh assets` with SSH key from DEPLOY_KEY, staged archives, strict host checking, and public smoke checks.
- [x] Replace workflow copies of deployment logic with that entrypoint; preserve fetching, commits, failure reporting and existing site content.
- [x] Document requirements and both commands in deploy/README.md.

### 5. Verify and hand off
- [x] Run all Python deployment tests (28), existing Node tooling (29) and stats (15) tests, Vitest (91), type-check, lint, build, Bash syntax, Python compile, YAML parse and `git diff --check`.
- [x] Repeat origin/public probes for the repaired live service (all five assets 200, correct MIME).
- [x] Resolve the reader-preflight path bug found by the site rehearsal (it checked assets at the site root instead of `assets/`) with a regression test.
- [ ] Report exactly which live operations completed and that workflow/code changes remain local until the user authorizes commit/push. Do not trigger an unapproved repository publish.
