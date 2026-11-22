# Deployment

One entrypoint publishes both the website and the runtime assets that scheduled
jobs refresh:

```bash
bash deploy/publish.sh site     # built site (requires `npm --prefix site run build`)
bash deploy/publish.sh assets   # assets/* by default, or PUBLISH_FILES
```

The GitHub workflows use the same commands, so a local publish and a CI publish
cannot diverge.

## What a publish guarantees

- `deploy/assets.py` defines the required runtime files (four README cards plus
  `Profile.jpg`). `npm run build` bundles them into `dist/assets` and fails if
  any is missing, empty, or not valid SVG.
- Every full-site release and asset upload takes `/var/lock/wangjinghong-deploy.lock`.
  Staged files are normalized to directory `0755` / file `0644`, and
  `runuser -u www-data -- test -r` proves the web server can read them before
  anything live changes.
- A full-site release is staged at `/var/www/wangjinghong.new`, keeps existing
  `static/` chunks and `harness/`, swaps atomically, and probes the origin from
  `127.0.0.1` (homepage plus all required assets) while holding the lock. A
  failed probe restores the previous tree and the previous release stays as
  `/var/www/wangjinghong.old`.
- An asset upload replaces files atomically, validates the merged directory
  (required files must all be present and readable), keeps unrelated files, and
  restores replaced files if the probe fails. A missing `assets/` directory is
  created with mode `0755` instead of being left to `scp`.
- After release, `deploy/publish.sh` checks the public URL. A public/CDN failure
  is reported as a job failure; the origin is not rolled back because it is
  already verified healthy.

## Environment

| Variable | Default | Meaning |
| --- | --- | --- |
| `DEPLOY_KEY` | `~/.ssh/wangjinghong-mac-2026.pem` | SSH private key |
| `DEPLOY_HOST` | `47.103.28.157` | ECS address |
| `DEPLOY_USER` | `root` | SSH user |
| `SITE_ORIGIN` | `https://www.wangjinghong.com` | Public origin used for checks |
| `ORIGIN_RESOLVE` | `<origin host>:443:127.0.0.1` | On-server origin probe target |
| `READER_USER` | `www-data` | Nginx worker user |
| `PUBLISH_FILES` | `assets/*` | Repo-relative files for assets mode |
| `LIVE_DIR` | `/var/www/wangjinghong` | Published site root |
| `SITE_STAGING` | `/var/www/wangjinghong.new` | Full-site staging directory |

The contribution-graph workflow sets `PUBLISH_FILES` to its own two SVGs so it
cannot overwrite fresher cards produced by the stats workflow.

## Recovery

If a publish fails, the job output names the asset or permission that failed.
The origin keeps serving the previous release. Manual inspection:

```bash
ssh -i "$DEPLOY_KEY" root@47.103.28.157 \
  'stat -c "%a %U:%G %n" /var/www/wangjinghong/assets /var/www/wangjinghong/assets/*; \
   runuser -u www-data -- test -r /var/www/wangjinghong/assets/blog-card.svg && echo readable'
```

Run `python3 deploy/assets.py smoke --base https://www.wangjinghong.com` to check
the public path without touching the server.

## Tests

```bash
python3 -m unittest discover -s deploy/tests -t .   # CI: Verify workflow
bash -n deploy/publish.sh
```
