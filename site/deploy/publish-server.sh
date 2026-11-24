#!/usr/bin/env bash
# Standalone atomic publisher & rollback entrypoint for wangjinghong.com site/server.
# Never touches /var/www/wangjinghong (static frontend).
#
# Usage:
#   DEPLOY_HOST=<ECS_HOST> bash site/deploy/publish-server.sh deploy
#   DEPLOY_HOST=<ECS_HOST> bash site/deploy/publish-server.sh rollback [--to <release_id>] [--restore-db <backup_file>]
#
# Environment:
#   DEPLOY_HOST              Required target server host/address (e.g. <ECS_HOST>)
#   DEPLOY_USER              SSH user (default: root)
#   DEPLOY_KEY               SSH private key path (default: ~/.ssh/wangjinghong-mac-2026.pem)
#   RELEASE_ID               Release identifier (default: <UTC timestamp>-<git short sha>)
#   REMOTE_APP_ROOT          Remote app root (default: /opt/wangjinghong)
#   REMOTE_ETC_ENV           Remote env file (default: /etc/wangjinghong/server.env)
#   REMOTE_VAR_DIR           Remote persistent data dir (default: /var/lib/wangjinghong)
#   REMOTE_LOCK_FILE         Remote flock path (default: /var/lock/wangjinghong-server-deploy.lock)
#   SERVICE_NAME             systemd unit name (default: wangjinghong-api)
#   SERVICE_USER             service account user (default: www-data)
#   HEALTH_URL               loopback health probe URL (default: http://127.0.0.1:8000/api/health/)
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
usage:
  DEPLOY_HOST=<ECS_HOST> bash site/deploy/publish-server.sh deploy
  DEPLOY_HOST=<ECS_HOST> bash site/deploy/publish-server.sh rollback [--to <release_id>] [--restore-db <backup_file>]
EOF
  exit 2
}

MODE=${1:-}
case "$MODE" in
  deploy|rollback) shift ;;
  *) usage ;;
esac

ROLLBACK_TO=""
RESTORE_DB=""
if [ "$MODE" = "deploy" ]; then
  [ "$#" -eq 0 ] || usage
else
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --to)
        [ "$#" -ge 2 ] && [ -n "${2:-}" ] || usage
        ROLLBACK_TO=$2
        shift 2
        ;;
      --restore-db)
        [ "$#" -ge 2 ] && [ -n "${2:-}" ] || usage
        RESTORE_DB=$2
        shift 2
        ;;
      *)
        usage
        ;;
    esac
  done
fi

DEPLOY_HOST=${DEPLOY_HOST:-}
if [ -z "$DEPLOY_HOST" ]; then
  echo "error: DEPLOY_HOST must be set via environment (e.g. DEPLOY_HOST=<ECS_HOST>)" >&2
  exit 2
fi
if { ! [[ "$DEPLOY_HOST" =~ ^[A-Za-z0-9._:-]+$ ]] && ! [[ "$DEPLOY_HOST" =~ ^\[[A-Fa-f0-9:]+\]$ ]]; } || [[ "$DEPLOY_HOST" == -* ]]; then
  echo "error: invalid DEPLOY_HOST value" >&2
  exit 2
fi

DEPLOY_USER=${DEPLOY_USER:-root}
if ! [[ "$DEPLOY_USER" =~ ^[A-Za-z_][A-Za-z0-9._-]*$ ]]; then
  echo "error: invalid DEPLOY_USER '$DEPLOY_USER'" >&2
  exit 2
fi

DEPLOY_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SITE_DIR=$(cd "$DEPLOY_DIR/.." && pwd)
SERVER_DIR="$SITE_DIR/server"

DEPLOY_KEY=${DEPLOY_KEY:-$HOME/.ssh/wangjinghong-mac-2026.pem}
REMOTE_APP_ROOT=${REMOTE_APP_ROOT:-/opt/wangjinghong}
REMOTE_ETC_ENV=${REMOTE_ETC_ENV:-/etc/wangjinghong/server.env}
REMOTE_VAR_DIR=${REMOTE_VAR_DIR:-/var/lib/wangjinghong}
REMOTE_LOCK_FILE=${REMOTE_LOCK_FILE:-/var/lock/wangjinghong-server-deploy.lock}
SERVICE_NAME=${SERVICE_NAME:-wangjinghong-api}
SERVICE_USER=${SERVICE_USER:-www-data}
HEALTH_URL=${HEALTH_URL:-http://127.0.0.1:8000/api/health/}
SSH_BIN=${SSH_BIN:-ssh}
SCP_BIN=${SCP_BIN:-scp}
DEPLOY_STRICT_HOST_KEY=${DEPLOY_STRICT_HOST_KEY:-accept-new}

DEFAULT_SHA=$(git -C "$SITE_DIR" rev-parse --short=8 HEAD 2>/dev/null || printf 'manual')
RELEASE_ID=${RELEASE_ID:-"$(date -u +%Y%m%dT%H%M%SZ)-${DEFAULT_SHA}"}

validate_safe_id() {
  local label=$1 val=$2
  if [ -z "$val" ] || [ "$val" = "." ] || [ "$val" = ".." ] || ! [[ "$val" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "error: invalid $label '$val' (must match ^[A-Za-z0-9._-]+$)" >&2
    exit 2
  fi
}

if [ "$MODE" = "deploy" ]; then
  validate_safe_id "RELEASE_ID" "$RELEASE_ID"
else
  if [ -n "$ROLLBACK_TO" ]; then
    validate_safe_id "--to" "$ROLLBACK_TO"
  fi
  if [ -n "$RESTORE_DB" ]; then
    validate_safe_id "--restore-db" "$RESTORE_DB"
  fi
fi

if [ ! -f "$DEPLOY_KEY" ]; then
  echo "error: SSH private key not found at DEPLOY_KEY=$DEPLOY_KEY" >&2
  exit 1
fi

if [ "$MODE" = "deploy" ]; then
  node "$SITE_DIR/scripts/update-note-slugs.mjs" --check
fi

WORK=$(mktemp -d "${TMPDIR:-/tmp}/wangjinghong-server-publish.XXXXXX")
REMOTE_WORK=""

SSH_OPTIONS=(
  -i "$DEPLOY_KEY"
  -o BatchMode=yes
  -o StrictHostKeyChecking="$DEPLOY_STRICT_HOST_KEY"
  -o ConnectTimeout=15
)
if [ -n "${DEPLOY_KNOWN_HOSTS:-}" ]; then
  SSH_OPTIONS+=(-o UserKnownHostsFile="$DEPLOY_KNOWN_HOSTS")
fi

remote() { "$SSH_BIN" "${SSH_OPTIONS[@]}" "$DEPLOY_USER@$DEPLOY_HOST" "$@"; }
copy() { "$SCP_BIN" "${SSH_OPTIONS[@]}" "$@"; }

remote_bash() {
  local quoted_args=()
  local arg
  for arg in "$@"; do
    quoted_args+=("$(printf '%q' "$arg")")
  done
  remote "bash -s -- ${quoted_args[*]+"${quoted_args[*]}"}"
}

cleanup() {
  local status=$?
  if [ -n "$REMOTE_WORK" ]; then
    local quoted_work
    quoted_work=$(printf '%q' "$REMOTE_WORK")
    remote "rm -rf -- $quoted_work" >/dev/null 2>&1 || true
  fi
  rm -rf "$WORK"
  exit "$status"
}
trap cleanup EXIT

raw_remote_work=$(remote "umask 077 && mktemp -d /var/tmp/wangjinghong-server-publish.XXXXXX")
if [[ "$raw_remote_work" =~ ^/var/tmp/wangjinghong-server-publish\.[A-Za-z0-9_-]+$ ]]; then
  REMOTE_WORK=$raw_remote_work
else
  echo "error: unexpected remote staging directory: $raw_remote_work" >&2
  exit 1
fi

DEPLOY_TOOLS=(
  "$DEPLOY_DIR/remote_server.py"
  "$DEPLOY_DIR/runtime.py"
  "$DEPLOY_DIR/fs_safe.py"
  "$DEPLOY_DIR/history.py"
  "$DEPLOY_DIR/sqlite_ops.py"
)

if [ "$MODE" = "deploy" ]; then
  COPYFILE_DISABLE=1 tar -czf "$WORK/server.tar.gz" \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='*.pyo' \
    --exclude='var' \
    --exclude='./var' \
    --exclude='staticfiles' \
    --exclude='./staticfiles' \
    --exclude='.env' \
    --exclude='./.env' \
    --exclude='.venv' \
    --exclude='./.venv' \
    --exclude='*.sqlite3' \
    --exclude='*.sqlite3-*' \
    --exclude='*.db' \
    -C "$SERVER_DIR" .
  copy "$WORK/server.tar.gz" "${DEPLOY_TOOLS[@]}" "$DEPLOY_USER@$DEPLOY_HOST:$REMOTE_WORK/"
  remote_bash \
    "$REMOTE_WORK" "$RELEASE_ID" "$REMOTE_APP_ROOT" "$REMOTE_ETC_ENV" \
    "$REMOTE_VAR_DIR" "$REMOTE_LOCK_FILE" "$SERVICE_NAME" "$SERVICE_USER" "$HEALTH_URL" <<'REMOTE'
set -euo pipefail
work=$1 release_id=$2 app_root=$3 etc_env=$4 var_dir=$5 lock_file=$6 svc=$7 svc_user=$8 health=$9
trap 'rc=$?; rm -rf -- "$work"; exit "$rc"' EXIT
mkdir -p "$work/staged-server"
tar -xzf "$work/server.tar.gz" -C "$work/staged-server"
python3 "$work/remote_server.py" deploy \
  --staged-server "$work/staged-server" \
  --release-id "$release_id" \
  --app-root "$app_root" \
  --etc-env "$etc_env" \
  --var-dir "$var_dir" \
  --lock-file "$lock_file" \
  --service-name "$svc" \
  --service-user "$svc_user" \
  --health-url "$health"
REMOTE
  REMOTE_WORK=""
else
  copy "${DEPLOY_TOOLS[@]}" "$DEPLOY_USER@$DEPLOY_HOST:$REMOTE_WORK/"
  remote_bash \
    "$REMOTE_WORK" "$ROLLBACK_TO" "$RESTORE_DB" "$REMOTE_APP_ROOT" "$REMOTE_ETC_ENV" \
    "$REMOTE_VAR_DIR" "$REMOTE_LOCK_FILE" "$SERVICE_NAME" "$SERVICE_USER" "$HEALTH_URL" <<'REMOTE'
set -euo pipefail
work=$1 rb_to=$2 restore_db=$3 app_root=$4 etc_env=$5 var_dir=$6 lock_file=$7 svc=$8 svc_user=$9 health=${10}
trap 'rc=$?; rm -rf -- "$work"; exit "$rc"' EXIT
cmd_args=(
  rollback
  --app-root "$app_root"
  --etc-env "$etc_env"
  --var-dir "$var_dir"
  --lock-file "$lock_file"
  --service-name "$svc"
  --service-user "$svc_user"
  --health-url "$health"
)
if [ -n "$rb_to" ]; then
  cmd_args+=(--to "$rb_to")
fi
if [ -n "$restore_db" ]; then
  cmd_args+=(--restore-db "$restore_db")
fi
python3 "$work/remote_server.py" "${cmd_args[@]}"
REMOTE
  REMOTE_WORK=""
fi
