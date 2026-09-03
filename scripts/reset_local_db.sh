#!/bin/bash
# =============================================================================
# === scripts/reset_local_db.sh ===
# =============================================================================
# Real DR item #3 — wraps the exact manual sequence that worked
# tonight (terminate connections -> drop -> recreate -> grant schema
# -> migrate) into one repeatable command, instead of hand-typing
# psql across several messages the next time local dev data needs a
# clean reset.
#
# Deliberately a shell script wrapping raw psql, NOT a Django
# management command. A Django command can't drop the database it's
# currently connected to, and — the real reason a per-model deletion
# command was rejected instead — this whole codebase's own
# architecture leans on on_delete=PROTECT specifically to make
# surgical deletion hard, by design (Vehicle->Customer, Invoice->
# ServiceRecord, and dozens more, per the "never delete, always
# audit" principle this project states repeatedly). Fighting that
# architecture with a partial, best-guess deletion order across every
# app risks a half-deleted, WORSE state than doing nothing — a full
# DB-level wipe sidesteps the problem entirely rather than solving it
# incorrectly.
#
# LOCAL DEV DATABASE ONLY. Targets the native local Postgres install
# used tonight (confirmed via the real \l output showing arthasee_db
# alongside unrelated local databases — developindo_db, cortex_llm,
# etc. — all on one native Postgres instance, NOT the Dockerized
# arthasee_db from docker-compose.yml, which is a separate, port-5433
# instance entirely and untouched by this script).
#
# Two real, hard safety gates before anything destructive runs:
#   1. Refuses to run at all if /home/apps/arthasee exists — that
#      path is the droplet's own real, confirmed layout; this script
#      has no business ever running there.
#   2. Requires the exact typed confirmation phrase, no flag to skip
#      it — a single wrong keystroke on a destructive command like
#      this should never be all it takes.
# =============================================================================
set -euo pipefail

DB_NAME="arthasee_db"
DB_OWNER="postgres"
APP_ROLE="arthasee"
# Same real path tonight's manual session used — override via
# PSQL_BIN if your local install lives somewhere else
# (e.g. `PSQL_BIN=/usr/local/bin/psql ./reset_local_db.sh`).
PSQL_BIN="${PSQL_BIN:-/Library/PostgreSQL/15/bin/psql}"
BACKEND_DIR="$(cd "$(dirname "$0")/../backend" && pwd)"

# ── Gate 1: refuse outright if this looks like the real droplet ────
if [ -d "/home/apps/arthasee" ]; then
  echo "❌ /home/apps/arthasee exists — this looks like the production droplet."
  echo "❌ This script is for local dev only. Refusing to run."
  exit 1
fi

# ── Gate 2: explicit typed confirmation, no bypass flag ────────────
echo "⚠️  This will PERMANENTLY WIPE the local '$DB_NAME' database and"
echo "⚠️  everything in it — every organization, every test fixture,"
echo "⚠️  everything. This cannot be undone."
echo ""
read -rp "Type 'reset arthasee_db' to continue: " CONFIRM
if [ "$CONFIRM" != "reset arthasee_db" ]; then
  echo "Aborted — confirmation did not match."
  exit 1
fi

echo "=== Terminating active connections to $DB_NAME ==="
"$PSQL_BIN" -U "$DB_OWNER" -c "
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = '$DB_NAME' AND pid <> pg_backend_pid();
"

echo "=== Dropping $DB_NAME ==="
"$PSQL_BIN" -U "$DB_OWNER" -c "DROP DATABASE IF EXISTS $DB_NAME;"

echo "=== Recreating $DB_NAME (UTF8 / C / C, template0) ==="
"$PSQL_BIN" -U "$DB_OWNER" -c "
CREATE DATABASE $DB_NAME
    WITH OWNER = $DB_OWNER
    ENCODING = 'UTF8'
    LC_COLLATE = 'C'
    LC_CTYPE = 'C'
    TEMPLATE = template0;
"

echo "=== Granting privileges to $APP_ROLE ==="
"$PSQL_BIN" -U "$DB_OWNER" -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $APP_ROLE;"
# The real Postgres 15 gap found live tonight — database-level GRANT
# alone does NOT include CREATE on the public schema inside it
# (Postgres 15 stopped granting that to PUBLIC by default). Without
# this, the app role can connect but the very first migration fails
# with "permission denied for schema public."
"$PSQL_BIN" -U "$DB_OWNER" -d "$DB_NAME" -c "GRANT ALL ON SCHEMA public TO $APP_ROLE;"

echo "=== Running migrations ==="
if [ -x "$BACKEND_DIR/.venv/bin/python" ]; then
  PYTHON_BIN="$BACKEND_DIR/.venv/bin/python"
else
  echo "❌ No venv found at $BACKEND_DIR/.venv — refusing to fall back to a bare 'python'"
  echo "❌ (a fresh script subshell has no activated venv, even if your interactive shell does)."
  exit 1
fi
(cd "$BACKEND_DIR" && "$PYTHON_BIN" manage.py migrate)

echo "=== Verifying the database is genuinely empty ==="
ORG_COUNT=$(cd "$BACKEND_DIR" && "$PYTHON_BIN" manage.py shell -c "
from apps.organizations.models import Organization
print(Organization.objects.count())
" | tail -n 1)

if [ "$ORG_COUNT" != "0" ]; then
  echo "❌ Expected 0 organizations after reset, found $ORG_COUNT — something didn't wipe cleanly."
  exit 1
fi

echo "✅ Reset complete — $DB_NAME is genuinely empty, migrations applied clean."
echo "✅ Next step: go through the real signup flow to create a fresh org (this is what runs seed_coa)."
