# TODO

## Enhancements (Ordered by Priority)

### 🔴 HIGH PRIORITY

#### Audit Log for Playlist Mutations
- Write a persistent audit log file for all mutating spotify commands (tracks/playlists added, removed, moved)
  - **Motivation**: When a bug like the `discover_from_playlists` pre-sync bug causes silent data issues, there is currently no way to reconstruct what happened after the fact to assess impact and fix it manually
  - **Log location**: `~/.spotfm/audit.log` (append-only, one JSON-line per event)
  - **Events to capture** (with timestamp, command name, playlist id/name, track ids):
    - `track_added` — track added to a playlist (`discover_from_playlists`, `add` commands)
    - `track_removed` — track removed from a playlist
    - `playlist_synced` — playlist synced to DB (record snapshot_id, track count delta)
    - `playlist_removed` — playlist removed/unmanaged
  - **Format** (JSON-lines for easy `grep` / `jq` post-processing):
    ```json
    {"ts": "2026-03-09T12:00:00Z", "cmd": "discover_from_playlists", "event": "track_added", "playlist_id": "3iu...", "track_ids": ["4ab...", "7cd..."]}
    ```
  - **Implementation**: thin `audit.log(event, **kwargs)` helper in `spotfm/audit.py`; called from `misc.py` after successful mutations; no external dependencies
  - **Files**: `spotfm/audit.py` (new), `spotfm/spotify/misc.py`, `spotfm/cli.py` (log path config)
  - **Effort**: Small (~2-3 hours)

#### Logging Improvements
- Add progress & summary logging to spotify commands by default
  - Desired output examples:
    - `fetching playlist <name> 12/122` (progress during fetch)
    - `discovered 12 new tracks from playlist <name>` (per-playlist summary)
    - `total discovered from all playlists: 122 new tracks` (final summary)
  - Currently: too minimal in standard mode, excess noise in --info mode
  - Goal: High-level progress & results without debug details
  - Files: `spotfm/cli.py`, `spotfm/spotify/client.py`, `spotfm/spotify/misc.py`
  - Note: Some logging already exists but buried in debug/verbose output
  - **Effort**: Medium (~4-6 hours)

### 🟡 MEDIUM PRIORITY

#### Migrate SQL Queries to Parameterized Statements
- Replace f-string SQL queries with parameterized queries
  - Current: `SELECT * FROM tracks WHERE id = '{track_id}'` (SQL injection risk)
  - Target: `SELECT * FROM tracks WHERE id = ?` with parameters
  - Impact: Improves security, prevents injection via user input
  - Files: `spotfm/sqlite.py`, `spotfm/spotify/*.py`, tests
  - **Effort**: Medium (~3-5 hours)

#### Improve Duplicate Detection
- Enhance `dupes-names` to ignore suffix-only matches
  - Current: matches tracks where only part after "-" is similar
  - Example issue: Groups "- Nouvelle Ecole" or "- 2011 remastered" as duplicates
  - Target: Smart parsing to compare only title core, ignore common suffixes
  - Files: `spotfm/spotify/dupes.py`, `tests/test_dupes.py`
  - **Effort**: Medium (~3-4 hours)

### 🟢 LOW PRIORITY

#### Random Playlist Generator
- Generate randomized playlist with N tracks from user's library
- Reference implementation: `toolbox/python/spotify_random_playlist.py`
- **Effort**: LOW (~1-2 hours)

**Expected behavior:**
```bash
spfm spotify random-playlist <size> [--target-playlist <id>] [--exclude <id1,id2,...>]
```

**Implementation details:**

1. **Seed data collection:**
   - Fetch all user playlists (excluding specified list)
   - Aggregate all tracks from seed playlists using Track.get_tracks()
   - De-duplicate by track ID
   - Store track ID pool in SQLite (new table: `random_pool`)

2. **Selection logic:**
   - Use `random.sample()` for without-replacement sampling
   - Track previously selected tracks in `random_history` table (track_id, selected_at)
   - Skip tracks selected in last N runs (configurable, default 10 runs)
   - Select N random tracks meeting criteria

3. **Playlist update:**
   - Clear target playlist or create new one if not specified
   - Add selected tracks to target playlist via Playlist.add_tracks()
   - Log selection summary: "Selected 50 tracks, skipped X from recent history"

4. **Database schema additions:**
   ```sql
   CREATE TABLE random_pool (
     track_id TEXT PRIMARY KEY,
     added_at TIMESTAMP
   );
   CREATE TABLE random_history (
     id INTEGER PRIMARY KEY,
     track_id TEXT,
     run_at TIMESTAMP,
     FOREIGN KEY (track_id) REFERENCES tracks(id)
   );
   ```

5. **CLI integration:**
   - Add `random-playlist` command to `spotfm/cli.py` spotify_cli()
   - Add function to `spotfm/spotify/misc.py`
   - Config options: `random_exclude_playlists`, `random_history_runs` in spotfm.toml

6. **Testing:**
   - Add `test_random_playlist.py` with fixtures for seed playlists
   - Test selection without replacement
   - Test history filtering
   - All tests should use `temp_database` fixture
