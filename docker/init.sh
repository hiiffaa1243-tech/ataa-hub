#!/usr/bin/env bash
# Builds an ERPNext v16 bench on first start, links this app into it, creates the
# site, finishes the setup wizard headless (fake association), then runs the dev
# server. Safe to re-run: every step is skipped when it is already done.
set -euo pipefail

HOME_DIR=/home/frappe
BENCH=$HOME_DIR/frappe-bench
APP_SRC=/workspace/ataa_hub
SITE="${SITE_NAME:-ataa.localhost}"
BRANCH="${FRAPPE_BRANCH:-version-16}"

git config --global --add safe.directory '*'
export PATH="$HOME_DIR/.local/bin:$PATH"

# 0) Toolchain required by v16: Python 3.14 (uv) and Node 24 (nvm ships with the image)
command -v uv >/dev/null || python3 -m pip install --user --quiet uv
uv python install "${PYTHON_VERSION:-3.14}"
# shellcheck disable=SC1091
source "$HOME_DIR/.nvm/nvm.sh"
nvm install "${NODE_VERSION:-24}" >/dev/null && nvm alias default "${NODE_VERSION:-24}" >/dev/null
command -v yarn >/dev/null || npm install -g yarn

# 1) Bench + ERPNext
if [ ! -d "$BENCH/apps/frappe" ]; then
  echo ">>> bench init (first run only, this is the slow part)"
  rm -rf "$BENCH"
  cd "$HOME_DIR"
  bench init --skip-redis-config-generation --frappe-branch "$BRANCH" \
    --python "$(uv python find "${PYTHON_VERSION:-3.14}")" frappe-bench
fi
cd "$BENCH"
bench set-config -g db_host mariadb
bench set-config -g redis_cache redis://redis-cache:6379
bench set-config -g redis_queue redis://redis-queue:6379
bench set-config -g redis_socketio redis://redis-queue:6379
bench set-config -g developer_mode 1
sed -i '/redis/d' ./Procfile
[ -d apps/erpnext ] || bench get-app --branch "$BRANCH" erpnext

# 2) Link this app (live edits from the host) and install it into the bench env
[ -e apps/ataa_hub ] || ln -s "$APP_SRC" apps/ataa_hub
grep -qx "ataa_hub" sites/apps.txt || echo "ataa_hub" >> sites/apps.txt
uv pip install --quiet --python env/bin/python -e apps/ataa_hub

# 3) Site: ERPNext + Ataa Hub, setup wizard done headless with a fake association
if [ ! -d "sites/$SITE" ]; then
  echo ">>> creating site $SITE"
  bench new-site "$SITE" \
    --mariadb-root-password "$DB_ROOT_PASSWORD" \
    --admin-password "${ADMIN_PASSWORD:-admin}" \
    --mariadb-user-host-login-scope='%'
  bench --site "$SITE" install-app erpnext
  bench --site "$SITE" install-app ataa_hub
  bench --site "$SITE" set-config developer_mode 1
  bench --site "$SITE" set-config allow_tests true
  bench --site "$SITE" execute ataa_hub.setup.wizard.complete_setup_wizard
fi
bench --site "$SITE" migrate
bench use "$SITE"
bench build --app ataa_hub

echo ">>> Ataa Hub is starting on http://localhost:8000"
exec bench start
