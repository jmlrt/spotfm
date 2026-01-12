#!/bin/bash
# Safe migration script with backup
set -e

DB_PATH="${HOME}/.spotfm/spotify.db"
BACKUP_PATH="${HOME}/.spotfm/spotify.db.backup-$(date +%Y%m%d-%H%M%S)"

echo "Spotify Database Migration: Add Lifecycle Tracking"
echo "===================================================="
echo ""
echo "Database: $DB_PATH"
echo "Backup:   $BACKUP_PATH"
echo ""

# Check if database exists
if [ ! -f "$DB_PATH" ]; then
    echo "Error: Database not found at $DB_PATH"
    exit 1
fi

# Create backup
echo "Creating backup..."
cp "$DB_PATH" "$BACKUP_PATH"
echo "✓ Backup created"
echo ""

# Run migration
echo "Running migration..."
sqlite3 "$DB_PATH" < hacks/migrate-add-lifecycle.sql
echo "✓ Migration completed"
echo ""

# Verify
echo "Verifying migration..."
RESULT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM tracks WHERE created_at IS NULL OR last_seen_at IS NULL")

if [ "$RESULT" -eq 0 ]; then
    echo "✓ Migration successful! All tracks have lifecycle data."
    echo ""
    echo "Backup saved at: $BACKUP_PATH"
    echo "You can delete it after verifying everything works."
else
    echo "⚠ Warning: $RESULT tracks still missing lifecycle data"
    echo "Check the migration logs for issues."
fi
