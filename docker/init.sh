#!/usr/bin/env bash
# Builds a Frappe bench on first start, links this app into it, creates the site
# with demo data, then runs the dev server. Safe to re-run: every step is skipped
# when it is already done.
set -euo pipefail

BENCH=/home/frappe/frappe-bench
APP_SRC=/workspace/ataa_hub
SITE="${SITE_NAME:-ataa.localhost}"

git config --global --add safe.directory '*'

# 1) Bench (Frappe framework + Python env + node modules)
if [ ! -d "$BENCH/apps/frappe" ]; then
  echo ">>> bench init (first run only, this is the slow part)"
  rm -rf "$BENCH"
  cd /home/frappe
  bench init --skip-redis-config-generation --frappe-branch "${FRAPPE_BRANCH:-version-15}" frappe-bench
fi

cd "$BENCH"
bench set-config -g db_host mariadb
bench set-config -g redis_cache redis://redis-cache:6379
bench set-config -g redis_queue redis://redis-queue:6379
bench set-config -g redis_socketio redis://redis-queue:6379
bench set-config -g developer_mode 1

# Redis runs in its own containers
sed -i '/redis/d' ./Procfile

# 2) Link the app (live edits from the host) and install it into the Python env
if [ ! -e "apps/ataa_hub" ]; then
  ln -s "$APP_SRC" apps/ataa_hub
fi
grep -qx "ataa_hub" sites/apps.txt || echo "ataa_hub" >> sites/apps.txt
./env/bin/pip install --quiet -e apps/ataa_hub

# 3) Site + app + demo data
if [ ! -d "sites/$SITE" ]; then
  echo ">>> creating site $SITE"
  bench new-site "$SITE" \
    --mariadb-root-password "$DB_ROOT_PASSWORD" \
    --admin-password "${ADMIN_PASSWORD:-admin}" \
    --mariadb-user-host-login-scope='%'
  bench --site "$SITE" install-app ataa_hub
  bench --site "$SITE" set-config developer_mode 1
  bench --site "$SITE" set-config allow_tests true
  bench --site "$SITE" execute ataa_hub.setup.demo.seed
else
  bench --site "$SITE" migrate
fi
bench use "$SITE"
bench build --app ataa_hub

echo ">>> Ataa Hub is starting on http://localhost:8000"
exec bench start
