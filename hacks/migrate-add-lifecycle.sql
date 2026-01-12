-- Migration script: Add lifecycle tracking to tracks table
-- Run this manually if automatic migration fails
-- Usage: sqlite3 ~/.spotfm/spotify.db < hacks/migrate-add-lifecycle.sql

BEGIN TRANSACTION;

-- Add columns (will fail silently if they already exist)
ALTER TABLE tracks ADD COLUMN created_at TEXT;
ALTER TABLE tracks ADD COLUMN last_seen_at TEXT;

-- Backfill last_seen_at
-- Strategy:
--   - Tracks currently in playlists: set to current date (they are "seen" now)
--   - Orphaned tracks: use their MAX(added_at) as proxy (when last in a playlist)
UPDATE tracks
SET last_seen_at = (
    CASE
        WHEN EXISTS (SELECT 1 FROM playlists_tracks WHERE track_id = tracks.id)
            THEN date('now')  -- Track is currently in a playlist
        ELSE (
            SELECT MAX(added_at) FROM playlists_tracks WHERE track_id = tracks.id
        )  -- Orphaned: use last known playlist date
    END
)
WHERE last_seen_at IS NULL;

-- Backfill created_at
-- Strategy:
--   - Use MIN(added_at) from playlists_tracks as best guess for first discovery
--   - Fallback to last_seen_at, then current date
UPDATE tracks
SET created_at = COALESCE(
    (SELECT MIN(added_at) FROM playlists_tracks WHERE track_id = tracks.id),
    last_seen_at,
    date('now')
)
WHERE created_at IS NULL;

-- Verify migration
SELECT
    COUNT(*) as total_tracks,
    COUNT(created_at) as tracks_with_created,
    COUNT(last_seen_at) as tracks_with_last_seen,
    COUNT(CASE WHEN created_at IS NULL OR last_seen_at IS NULL THEN 1 END) as incomplete
FROM tracks;

-- Expected output: incomplete should be 0

COMMIT;
