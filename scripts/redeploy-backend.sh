#!/usr/bin/env bash
# =============================================================================
# === scripts/redeploy-backend.sh ===
# "Break glass" manual redeploy — for when GitHub Actions is genuinely
# unreachable, not a routine alternative to pushing and letting CI run.
#
# This is a DELIBERATE, close mirror of deploy.yml's "Deploy backend" +
# "Health check" steps — same COMPOSE definition (both -f flags, always),
# same force-recreate, same freshness/caddy-net/migration verification
# gates. The goal is that running this by hand carries the identical
# safety net as a real CI run, so there's no "manual path" that's
# secretly weaker than the automated one — which is exactly the gap that
# caused the 2026-07-22 caddy-net incident (a hand-run command silently
# omitted -f docker-compose.prod.yml, the ONLY file that declares
# caddy-net, with no error at any point).
#
# Run from anywhere; it cd's to the repo root itself.
# =============================================================================
set -e

cd "$(dirname "$0")/.."

# The single source of truth for which compose files apply — every
# invocation below uses this exact variable, never a bare `docker
# compose` call, so there is no path that can silently use a different,
# incomplete set of files.
COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"

echo "=== Pulling latest code ==="
git pull origin main

echo "=== Building backend image ==="
$COMPOSE build --no-cache --pull arthasee_backend

echo "=== Checking DB is already healthy ==="
# Deliberately NOT `docker compose up -d arthasee_db` + a 30-iteration
# wait loop here — that earns its keep in deploy.yml, which has to work
# from a cold/first-time state, but this script is specifically for
# redeploying the backend, and the DB is essentially always already
# running when that's needed. One fast check, fail loud and immediately
# if it's somehow not — better than silently proceeding into `migrate`
# and hitting a more confusing connection error two steps later.
DB_STATUS=$(docker inspect arthasee_db --format='{{.State.Health.Status}}' 2>/dev/null || echo "missing")
if [ "$DB_STATUS" != "healthy" ]; then
  echo "❌ arthasee_db is not healthy (status: $DB_STATUS)."
  echo "❌ This script assumes the DB is already running — if it's genuinely down, start it separately first:"
  echo "    $COMPOSE up -d arthasee_db"
  exit 1
fi
echo "✅ DB already healthy"

echo "=== Running migrations ==="
$COMPOSE run --rm arthasee_backend python manage.py migrate --noinput

echo "=== Collecting static files ==="
$COMPOSE run --rm arthasee_backend python manage.py collectstatic --noinput

echo "=== Force-recreating backend ==="
$COMPOSE up -d --no-deps --force-recreate arthasee_backend

echo "=== Verifying container actually persisted ==="
sleep 2
if ! docker ps -a --format '{{.Names}}' | grep -q '^arthasee_backend$'; then
  echo "❌ Container does not exist immediately after 'docker compose up -d'."
  exit 1
fi
echo "✅ Container exists: $(docker ps -a --filter name=arthasee_backend --format '{{.Status}}')"

echo "=== Verifying container is actually fresh ==="
CREATED=$(docker inspect arthasee_backend --format '{{.Created}}')
CREATED_EPOCH=$(date -u -d "$CREATED" +%s)
NOW_EPOCH=$(date -u +%s)
AGE=$((NOW_EPOCH - CREATED_EPOCH))
echo "Container created: $CREATED ($AGE seconds ago)"
if [ "$AGE" -gt 60 ]; then
  echo "❌ Container is ${AGE}s old — force-recreate silently failed to actually recreate it."
  exit 1
fi
echo "✅ Container genuinely recreated $AGE seconds ago"

echo "=== Verifying container joined caddy-net ==="
NETWORKS=$(docker inspect arthasee_backend --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}')
echo "Networks joined: $NETWORKS"
if ! echo "$NETWORKS" | grep -q "caddy-net"; then
  echo "❌ Container is NOT on caddy-net — Caddy cannot reach it. This is the exact 2026-07-22 bug — did you use this script, or a bare docker compose command?"
  exit 1
fi
echo "✅ caddy-net confirmed"

echo "=== Verifying migrations actually applied ==="
# Extended to inventory alongside service, matching deploy.yml's gate
# exactly — this script exists specifically as the break-glass
# fallback for when the pipeline can't be trusted, so it needs the
# SAME safety net, not a narrower one. This exact gap (checking only
# service, missing inventory) went unnoticed through several runs on
# 2026-07-23 before being caught here.
MIGRATION_STATUS=$($COMPOSE run --rm arthasee_backend python manage.py showmigrations service inventory)
echo "$MIGRATION_STATUS"
if echo "$MIGRATION_STATUS" | grep -q "\[ \]"; then
  echo "❌ Unapplied migration(s) detected in apps.service or apps.inventory."
  exit 1
fi
echo "✅ All service and inventory migrations applied"

echo "=== Reloading Caddy ==="
CADDY=$(docker ps -qf "name=caddy")
[ -n "$CADDY" ] && docker exec "$CADDY" caddy reload --config /etc/caddy/Caddyfile 2>/dev/null \
  && echo "✅ Caddy reloaded!" || echo "⚠️  Caddy reload skipped"

echo "=== Manual redeploy complete ==="
echo "$(date) | $(git rev-parse --short HEAD) | MANUAL | OK" >> deploy.log
