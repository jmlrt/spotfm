# TODO

## Enhancements (Ordered by Priority)

### 🔴 HIGH PRIORITY

#### Fix `find-duplicate-names` to Filter Same-ID Dupes
- Remove false positives where both tracks have the same Spotify ID
  - Current: Outputs dupes even when `playlists1` and `playlists2` are identical or track IDs match
  - Root cause: `get_fuzzy_match_candidates()` doesn't pre-filter by playlist/ID before fuzzy matching
  - Impact: Reduces noise, makes output actionable (every dupe is a real version difference)
  - Target: Only output dupes where track IDs differ (true versions/remixes)
  - Files: `spotfm/spotify/dupes.py` (get_fuzzy_match_candidates, find_duplicate_names)
  - **Effort**: Low (~30 minutes)

### 🟡 MEDIUM PRIORITY

#### Improve Duplicate Detection with Duration & Version Categorization
- **Part 1: Add duration_ms to track storage**
  - Store Spotify's `duration_ms` field when syncing tracks (currently fetched but discarded)
  - Add `duration_ms INTEGER` column to tracks table via migration
  - Files: `spotfm/sqlite.py` (add migration), `spotfm/spotify/track.py` (store in sync_to_db)
  - **Effort**: Low (~30 minutes)

- **Part 2: Enhance `find-duplicate-names` output with categorization**
  - Current: Outputs all fuzzy matches equally, requiring manual review
  - Target: Flag each dupe as SAFE, QUESTIONABLE, or NOT_A_DUPE based on:
    - **SAFE**: A COLORS SHOW versions, duration match within 90% (same track, different encoding)
    - **QUESTIONABLE**: Original vs Remix, Studio vs Live, different named versions (Angela vs Angela - Version 2)
    - **NOT_A_DUPE**: Sequels (Pt. 2, II, 2.0), medleys, collaborations that aren't the same track
  - Add `--include-duration` flag to `find-duplicate-names` to output duration & duration_diff in CSV
  - Add categorization logic to classify each dupe pair
  - Files: `spotfm/spotify/dupes.py` (add duration column to output, add dupe_category logic), `spotfm/cli.py` (add --include-duration flag)
  - **Effort**: Medium (~2-3 hours)

#### Migrate SQL Queries to Parameterized Statements
- Replace f-string SQL queries with parameterized queries
  - Current: `SELECT * FROM tracks WHERE id = '{track_id}'` (SQL injection risk)
  - Target: `SELECT * FROM tracks WHERE id = ?` with parameters
  - Impact: Improves security, prevents injection via user input
  - Files: `spotfm/sqlite.py`, `spotfm/spotify/*.py`, tests
  - **Effort**: Medium (~3-5 hours)

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
