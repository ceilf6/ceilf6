#!/usr/bin/env bash
# Publish the built website or refreshed runtime assets to the ECS host.
#
#   bash deploy/publish.sh site     # requires site/dist, built with `npm run build`
#   bash deploy/publish.sh assets   # uploads PUBLISH_FILES (default: assets/*)
#
# Environment:
#   DEPLOY_KEY      private key path (default: ~/.ssh/wangjinghong-mac-2026.pem)
#   DEPLOY_HOST     server address (default: 47.103.28.157)
#   DEPLOY_USER     SSH user (default: root)
#   SITE_ORIGIN     public origin (default: https://www.wangjinghong.com)
#   ORIGIN_RESOLVE  host:port:address for the on-server origin check
#                   (default: <origin host>:443:127.0.0.1)
#   READER_USER     web-server user that must read published files (default: www-data)
#   PUBLISH_FILES   repo-relative asset paths for assets mode (default: assets/*)
set -euo pipefail

MODE=${1:-}
case "$MODE" in
  site|assets) ;;
  *) echo "usage: bash deploy/publish.sh site|assets" >&2; exit 2 ;;
esac

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
DEPLOY_KEY=${DEPLOY_KEY:-$HOME/.ssh/wangjinghong-mac-2026.pem}
DEPLOY_HOST=${DEPLOY_HOST:-47.103.28.157}
DEPLOY_USER=${DEPLOY_USER:-root}
SITE_ORIGIN=${SITE_ORIGIN:-https://www.wangjinghong.com}
READER_USER=${READER_USER:-www-data}
ORIGIN_HOST=$(printf '%s\n' "$SITE_ORIGIN" | sed -E 's#^https?://##; s#/.*$##')
ORIGIN_RESOLVE=${ORIGIN_RESOLVE:-"$ORIGIN_HOST:443:127.0.0.1"}
SITE_STAGING=${SITE_STAGING:-/var/www/wangjinghong.new}
LIVE_DIR=${LIVE_DIR:-/var/www/wangjinghong}

WORK=$(mktemp -d "${TMPDIR:-/tmp}/wangjinghong-publish.XXXXXX")
REMOTE_WORK=""

SSH_OPTIONS=(
  -i "$DEPLOY_KEY"
  -o BatchMode=yes
  -o StrictHostKeyChecking=yes
  -o UserKnownHostsFile="$WORK/known_hosts"
  -o ConnectTimeout=15
)
ssh-keyscan -H "$DEPLOY_HOST" >"$WORK/known_hosts" 2>/dev/null
remote() { ssh "${SSH_OPTIONS[@]}" "$DEPLOY_USER@$DEPLOY_HOST" "$@"; }
copy() { scp "${SSH_OPTIONS[@]}" "$@"; }

cleanup() {
  status=$?
  if [ -n "$REMOTE_WORK" ]; then
    remote "rm -rf '$REMOTE_WORK'" >/dev/null 2>&1 || true
  fi
  rm -rf "$WORK"
  exit "$status"
}
trap cleanup EXIT

python3 "$ROOT/deploy/assets.py" validate "$ROOT/assets"
tar -czf "$WORK/tools.tar.gz" -C "$ROOT" \
  deploy/__init__.py deploy/assets.py deploy/remote.py
REMOTE_WORK=$(remote "mktemp -d /var/tmp/wangjinghong-publish.XXXXXX")
case "$REMOTE_WORK" in
  /var/tmp/wangjinghong-publish.*) ;;
  *) echo "unexpected remote staging path: $REMOTE_WORK" >&2; exit 1 ;;
esac

if [ "$MODE" = site ]; then
  test -f "$ROOT/site/dist/index.html" ||
    { echo "site/dist/index.html missing; run npm run build first" >&2; exit 1; }
  python3 "$ROOT/deploy/assets.py" validate "$ROOT/site/dist/assets"
  tar -czf "$WORK/site.tar.gz" -C "$ROOT/site/dist" .
  copy "$WORK/site.tar.gz" "$WORK/tools.tar.gz" "$DEPLOY_USER@$DEPLOY_HOST:$REMOTE_WORK/"
  remote bash -s -- "$REMOTE_WORK" "$SITE_STAGING" "$LIVE_DIR" "$ORIGIN_RESOLVE" "$SITE_ORIGIN" "$READER_USER" <<'REMOTE'
set -euo pipefail
work=$1 staging=$2 live=$3 resolve=$4 origin=$5 reader=$6
trap 'rm -rf "$work"' EXIT
tar -xzf "$work/tools.tar.gz" -C "$work"
rm -rf "$staging"
mkdir -p "$staging"
chmod 755 "$staging"
tar -xzf "$work/site.tar.gz" -C "$staging"
cd "$work"
python3 -m deploy.remote site \
  --staging "$staging" --live "$live" \
  --reader "$reader" --origin "$origin" --resolve "$resolve"
REMOTE
else
  if [ -n "${PUBLISH_FILES:-}" ]; then
    read -r -a files <<<"$PUBLISH_FILES"
  else
    files=("$ROOT"/assets/*)
  fi
  tar_files=()
  for file in "${files[@]}"; do
    relative=${file#"$ROOT"/}
    test -f "$ROOT/$relative" || { echo "missing publish file: $relative" >&2; exit 1; }
    tar_files+=("$relative")
  done
  tar -czf "$WORK/assets.tar.gz" -C "$ROOT" "${tar_files[@]}"
  copy "$WORK/assets.tar.gz" "$WORK/tools.tar.gz" "$DEPLOY_USER@$DEPLOY_HOST:$REMOTE_WORK/"
  remote bash -s -- "$REMOTE_WORK" "$LIVE_DIR" "$ORIGIN_RESOLVE" "$SITE_ORIGIN" "$READER_USER" <<'REMOTE'
set -euo pipefail
work=$1 live=$2 resolve=$3 origin=$4 reader=$5
trap 'rm -rf "$work"' EXIT
tar -xzf "$work/tools.tar.gz" -C "$work"
mkdir -p "$work/staged"
tar -xzf "$work/assets.tar.gz" -C "$work/staged"
chmod 755 "$work" "$work/staged" "$work/staged/assets"
cd "$work"
python3 -m deploy.remote assets \
  --staging "$work/staged/assets" --live "$live" \
  --reader "$reader" --origin "$origin" --resolve "$resolve"
REMOTE
fi

# Public checks run after release. Failure means the origin is healthy but the
# public path is not; report it loudly instead of rolling back a good release.
if ! python3 "$ROOT/deploy/assets.py" smoke --base "$SITE_ORIGIN"; then
  echo "$MODE published to origin, but public asset checks failed" >&2
  exit 1
fi
if [ "$MODE" = site ]; then
  code=$(curl --noproxy '*' -sS -L --max-time 20 -o /dev/null -w '%{http_code}' "$SITE_ORIGIN/")
  if [ "$code" != 200 ]; then
    echo "site published to origin, but public homepage returned HTTP $code" >&2
    exit 1
  fi
fi
echo "$MODE publish verified at $SITE_ORIGIN"
