#!/bin/bash
# =============================================================================
# === scripts/backup.sh ===
# =============================================================================
# Daily Postgres backup for arthasee_db — real DR item #1, arrived at
# directly from tonight's own incident: a full local DB reset was the
# right call for dev data with zero real customers on it, but the
# exact same class of mistake against the droplet, with CV Arya
# Motor's real production data and no backup on hand, would be a
# genuinely unrecoverable loss.
#
# Adapted from /home/apps/randomdots/scripts/backup.sh — same real,
# already-proven-on-this-droplet shape (docker exec into the DB
# container, dump, gzip, timestamp the filename), swapped from
# mongodump to pg_dump since arthasee_db is Postgres, not Mongo. Real
# credentials/container name taken directly from docker-compose.yml,
# not guessed: container arthasee_db, user arthasee, db arthasee_db.
#
# One deliberate addition beyond what the randomdots script does —
# flagged explicitly, not silently: RETENTION_DAYS below prunes old
# backups automatically. randomdots' own script has no such rotation
# at all (every backup it's ever taken is presumably still sitting on
# disk) — fine for a low-volume Mongo dump, a real gap for a daily
# job meant to run indefinitely without manual disk-space babysitting.
#
# Still LOCAL-DISK ONLY, same as randomdots' own script — this is
# real, meaningful protection against "a bad migration/reset/bug
# corrupts the live data," but NOT protection against "the droplet's
# disk itself dies," which is a genuinely separate, larger decision
# (an off-box copy target — S3, rclone, another host) deliberately
# left open rather than guessed at here.
# =============================================================================
set -euo pipefail

BACKUP_DIR="/home/backups/arthasee"
RETENTION_DAYS=14
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")

mkdir -p "$BACKUP_DIR"

echo "=== Backing up arthasee_db ($TIMESTAMP) ==="
docker exec arthasee_db pg_dump \
  --username=arthasee \
  --dbname=arthasee_db \
  --format=plain \
  | gzip > "$BACKUP_DIR/arthasee_backup_$TIMESTAMP.sql.gz"

# Real, honest verification — not just "the command exited 0." A
# genuinely empty or truncated dump (e.g. the DB container was
# unhealthy but docker exec still returned success) must be caught
# here, loudly, not discovered the day someone actually needs to
# restore from it.
BACKUP_SIZE=$(stat -c%s "$BACKUP_DIR/arthasee_backup_$TIMESTAMP.sql.gz" 2>/dev/null || stat -f%z "$BACKUP_DIR/arthasee_backup_$TIMESTAMP.sql.gz")
if [ "$BACKUP_SIZE" -lt 1024 ]; then
  echo "❌ Backup file is suspiciously small (${BACKUP_SIZE} bytes) — likely a failed/empty dump."
  exit 1
fi
echo "✅ Backup written: arthasee_backup_$TIMESTAMP.sql.gz (${BACKUP_SIZE} bytes)"

echo "=== Pruning backups older than $RETENTION_DAYS days ==="
find "$BACKUP_DIR" -name "arthasee_backup_*.sql.gz" -mtime "+$RETENTION_DAYS" -print -delete

echo "=== Done. Current backups: ==="
ls -lah "$BACKUP_DIR"
