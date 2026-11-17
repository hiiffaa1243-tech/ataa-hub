#!/usr/bin/env bash
# M0 spike runner. Answers, on a clean ERPNext bench:
#   1. Does ERPNext ${FRAPPE_BRANCH} install cleanly?               (D6)
#   2. Does ksa_compliance install on it?                           (D5)
#   3. Does zatca_erpgulf install on it?                            (D5, fallback)
#   4. When does a monthly Subscription create its first invoice?   (R3)
#   5. Can a guest browser socket receive publish_realtime events?  (R2)
#   6. Optional: Moyasar test token charge with 3ds:false           (Q5)
# Every check is recorded in /home/frappe/spike-report.md, pass or fail, and the
# script keeps going after a failure. Re-running skips finished steps.
set -uo pipefail

HOME_DIR=/home/frappe
BENCH=$HOME_DIR/frappe-bench
REPORT=$HOME_DIR/spike-report.md
SPIKE_SRC=/workspace/docker/spike
LOG_DIR=$HOME_DIR/spike-logs
mkdir -p "$LOG_DIR"
git config --global --add safe.directory '*'

report() { echo "$1" | tee -a "$REPORT"; }
check() {  # check <id> <title> <command...>
  local id=$1 title=$2; shift 2
  echo ">>> [$id] $title"
  if "$@" >"$LOG_DIR/$id.log" 2>&1; then
    report "| $id | $title | PASS | spike-logs/$id.log |"
  else
    report "| $id | $title | **FAIL** | spike-logs/$id.log (last lines below) |"
    tail -n 15 "$LOG_DIR/$id.log" | sed 's/^/    /' >>"$REPORT.tail"
  fi
}

: >"$REPORT"; : >"$REPORT.tail"
report "# M0 spike report — $(date -Iseconds)"
report ""
report "Branch: ${FRAPPE_BRANCH} · Python ${PYTHON_VERSION} · Node ${NODE_VERSION}"
report ""
report "| # | Check | Result | Log |"
report "|---|---|---|---|"

# ---- 0. Toolchain: Python and Node versions required by v16 ----------------
toolchain() {
  python3 -m pip install --user --quiet --upgrade uv
  export PATH="$HOME_DIR/.local/bin:$PATH"
  uv python install "$PYTHON_VERSION"
  # nvm ships with the frappe/bench image
  # shellcheck disable=SC1091
  source "$HOME_DIR/.nvm/nvm.sh"
  nvm install "$NODE_VERSION" && nvm alias default "$NODE_VERSION"
  npm install -g yarn
}
check 0 "Toolchain (Python ${PYTHON_VERSION}, Node ${NODE_VERSION})" toolchain
export PATH="$HOME_DIR/.local/bin:$PATH"
# shellcheck disable=SC1091
source "$HOME_DIR/.nvm/nvm.sh" && nvm use default >/dev/null 2>&1 || true

# ---- 1. Bench + ERPNext ----------------------------------------------------
init_bench() {
  if [ ! -d "$BENCH/apps/frappe" ]; then
    rm -rf "$BENCH"
    cd "$HOME_DIR"
    bench init --skip-redis-config-generation \
      --frappe-branch "$FRAPPE_BRANCH" \
      --python "$(uv python find "$PYTHON_VERSION")" frappe-bench
  fi
  cd "$BENCH"
  bench set-config -g db_host mariadb
  bench set-config -g redis_cache redis://redis-cache:6379
  bench set-config -g redis_queue redis://redis-queue:6379
  bench set-config -g redis_socketio redis://redis-queue:6379
  sed -i '/redis/d' ./Procfile
  [ -d apps/erpnext ] || bench get-app --branch "$FRAPPE_BRANCH" erpnext
}
check 1a "bench init + get erpnext" init_bench
cd "$BENCH" || exit 1

new_site() {  # new_site <site> <apps...>
  local site=$1; shift
  [ -d "sites/$site" ] && return 0
  bench new-site "$site" --mariadb-root-password "$DB_ROOT_PASSWORD" \
    --admin-password admin --mariadb-user-host-login-scope='%' || return 1
  for app in "$@"; do bench --site "$site" install-app "$app" || return 1; done
  bench --site "$site" set-config allow_tests true
}
check 1b "Site erp.localhost with erpnext" new_site erp.localhost erpnext

# ---- 2/3. ZATCA apps, each on its own site so one can't break the other ------
zatca_app() {  # zatca_app <app> <repo> <branch> <site>
  [ -d "apps/$1" ] || bench get-app --branch "$3" "$2" || return 1
  new_site "$4" erpnext "$1" || return 1
  bench --site "$4" migrate
}
check 2 "ksa_compliance (master) on ${FRAPPE_BRANCH}" \
  zatca_app ksa_compliance https://github.com/lavaloon-eg/ksa_compliance.git master ksa.localhost
check 3 "zatca_erpgulf (main) on ${FRAPPE_BRANCH}" \
  zatca_app zatca_erpgulf https://github.com/ERPGulf/zatca_erpgulf.git main zatca.localhost

# ---- 4/5/6. Behaviour checks (Python executed inside the site) ---------------
# Put the checks inside an installed package so `bench execute` can import them
cp "$SPIKE_SRC/spike_checks.py" apps/frappe/frappe/spike_checks.py
check 4 "Subscription first-invoice timing" \
  bench --site erp.localhost execute frappe.spike_checks.subscription_timing

realtime() {
  bench use erp.localhost
  (bench start >"$LOG_DIR/bench-start.log" 2>&1 &)
  for _ in $(seq 1 60); do curl -sf http://localhost:8000/api/method/ping >/dev/null && break; sleep 2; done
  cp "$SPIKE_SRC/guest_socket.js" apps/frappe/guest_socket.js
  (cd apps/frappe && timeout 60 node guest_socket.js erp.localhost) &
  local listener=$!
  sleep 8
  bench --site erp.localhost execute frappe.spike_checks.publish_test_event
  wait $listener
}
check 5 "Guest socket receives publish_realtime (room 'website')" realtime

if [ -n "${MOYASAR_SECRET_KEY:-}" ]; then
  check 6 "Moyasar test token charge (3ds:false)" \
    bench --site erp.localhost execute frappe.spike_checks.moyasar_token_charge
else
  report "| 6 | Moyasar test token charge | SKIPPED (no MOYASAR_SECRET_KEY) | — |"
fi

report ""
report "## Failure details"
cat "$REPORT.tail" >>"$REPORT"
report ""
report "## Findings printed by the checks"
grep -h '^SPIKE:' "$LOG_DIR"/*.log | sed 's/^SPIKE: /- /' >>"$REPORT" || true

echo ">>> Spike finished. Report: $REPORT"
cat "$REPORT"
# Keep the container alive so the sites can be opened on http://localhost:8001
exec sleep infinity
