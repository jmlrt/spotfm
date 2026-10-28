# TODO

## Enhancements (Ordered by Priority)

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
  - **Note**: `sqlite.execute_many()` (parameterized executemany) landed with the
    Liked Songs PR (#57) and the liked-sync queries are parameterized; remaining
    work is migrating the f-string queries across the rest of the codebase

#### Track Selection with Batch Actions (Web /tracks Page)
- Add checkboxes to select tracks on the /tracks page, then run actions on the selection:
  - **Like / unlike**: save/unsave on Spotify (spotipy `current_user_saved_tracks_add` /
    `current_user_saved_tracks_delete`), then update the local `liked` state
  - **Batch playlist edit**:
    - Add selected tracks to an existing playlist or a new one
    - Remove selected tracks from a playlist
    - Move selected tracks from one playlist to another
    - UI: tick the playlists the selected tracks are part of (or should be part of),
      then apply the change to the whole selection
- Core logic in `spotfm/spotify/misc.py` (structured data, logging only, no printing);
  routes/actions in `spotfm/web/routes/spotify.py`; UI in `spotfm/web/templates/tracks.html`
- Respect the entity rules from SPEC: `liked` state is only mutated by explicit
  parameterized UPDATEs; never delete orphaned track rows
- **Effort**: High (~1-2 days)
- **Scope**: standalone PR

#### Job Cancellation in Web UI
- Add a Cancel button and endpoint (`POST /jobs/{id}/cancel`) so a stuck or
  unwanted job can be cleared from the UI without restarting the container
  (currently requires `docker compose restart spotfm-web`, see FAQ)
- Mark the job as cancelled and stop rendering it as running; cooperative
  cancellation where feasible — a per-job `cancel_requested` flag checked
  between API pages/batches in long-running syncs; the underlying thread may
  still finish in the background
- Out of scope here: persisting jobs across restarts (they live in an in-memory
  dict in `spotfm/web/jobs.py` and are lost on restart)
- Files: `spotfm/web/jobs.py`, `spotfm/web/routes/` (new route), job templates
- **Effort**: Medium (~2-4 hours)
- **Scope**: standalone PR

#### First-Time Spotify Auth in Web UI (No input() Hang)
- First-time auth blocks on an `input()` paste prompt inside the server process,
  so a webapp job with no cached token hangs forever when the server runs in a
  container or detached (workaround in FAQ: authenticate once on the host to
  populate the shared `~/.spotfm/spotify-token-cache` mount)
- Add an in-webapp flow: when no cached token exists, surface the authorize URL
  on a dedicated page, accept the pasted redirect URL there, and complete the
  token exchange inside the web process, writing the same token cache the CLI
  uses — no `input()` calls anywhere reachable by a job
- Files: `spotfm/web/routes/`, `spotfm/spotify/client.py`, templates
- **Effort**: Medium (~3-5 hours)
- **Scope**: standalone PR

### 🟢 LOW PRIORITY

#### Job Page Log Follows the Last Line
- The job status page renders the log in a scrollable `<pre>` pinned to the top
  (first job line); it should auto-scroll to the latest line on load and on each
  refresh while the job is running, so the tail is always visible
- Files: `spotfm/web/templates/job_status.html`
- **Effort**: Low (~30 minutes)
- **Scope**: standalone PR

#### Resizable Columns on Tracks Page
- Make the table columns of the web /tracks page resizable (drag column edges);
  consider sharing the mechanism via `base.html` for reuse on other tables
  (playlists, duplicates)
- Files: `spotfm/web/templates/tracks.html` (small JS/CSS addition)
- **Effort**: Low (~1-2 hours)
- **Scope**: standalone PR

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
