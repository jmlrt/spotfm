# AGENTS.md - spotfm

Guidance for coding agents working on spotfm.

## Documentation Navigation

This is a quick reference. For comprehensive documentation:

- [SPEC.md](SPEC.md) - Source of truth for architecture, design decisions, features, and data model (three-tier caching, entity lifecycle, orphaned tracks handling)
- [CONTRIBUTING.md](CONTRIBUTING.md) - Complete development guide (testing requirements, code style, commit messages, workflow, database isolation)
- [README.md](README.md) - Setup, configuration, and usage

## What is spotfm?

A Python library and CLI tool for Spotify and Last.FM API interaction. Focuses on playlist management, track discovery, and music library analytics. Data syncs to a local SQLite database for offline querying.

## Tooling

- Run all Python commands through `uv` in this repo, e.g. `uv run pytest`
- Formatting: ruff (120 char line length), Python 3.14+ (PEP 758 bracketless exception syntax)
- Shell commands already run in the repo root: use plain `git log`, `git status`, `git ls-files`, ... — not `git -C <path>` — so Vibe's bash allowlist (whole-word prefix match) auto-approves them instead of prompting
- Mutating commands — `git commit`/`git push`, `make publish`/`build`/`clean`, dependency changes, library-mutating `spfm` ops, `uv run python` — prompt by design: never re-invoke the same operation in a different form to get around a prompt
- For searching and filtering, use the allowlisted tools (`grep`, `find`, `head`, `tail`, `sort`, `wc`), not `rg`, `fd`, `awk`, or `sed`
- Prefer builtin file tools over shell commands: `read_file` (offset/limit) for reading files and regions, not `sed -n`, `cat`, or `head`
- Verify with `make test-unit` or targeted `uv run pytest -k ...`, not ad-hoc `uv run python -c` one-liners

## Critical Warnings

**Orphaned Tracks:**
- DO NOT delete orphaned tracks from the `tracks` table (tracks with no playlists)
- Orphaned tracks serve as a "negative cache" preventing re-adding intentionally removed tracks
- Deleting them will cause `discover_from_playlists` to re-add previously removed tracks
- Same for liked tracks: unliking only flips the `liked` flag; the row (and `liked_at`, for history) is kept

**Database Testing:**
- All tests MUST use temp databases via `monkeypatch.setattr(utils, "DATABASE", temp_database)`
- Never access the real database at `~/.spotfm/spotify.db` during testing
- Fixtures: `temp_database`, `temp_cache_dir` available in conftest.py

## Architecture Quick Reference

**Three-Tier Caching Strategy:**
1. Pickle cache: `~/.cache/spotfm/{kind}/{id}.pickle`
2. SQLite database: `~/.spotfm/spotify.db`
3. Spotify API: Fallback for uncached or `refresh=True`

**Entity Lifecycle Pattern** (Track, Album, Artist, Playlist):
- `get_{entity}(id, client, refresh=False, sync_to_db=True)` - Entry point
- `retrieve_object_from_cache()` -> `update_from_db()` -> `update_from_api(client)` -> `sync_to_db()`

**Module Map:**
- `spotfm/cli.py` - CLI entry point, argument parsing
- `spotfm/lastfm.py` - Last.FM client and scrobble analysis
- `spotfm/spotify/client.py` - Spotify wrapper, playlist filtering
- `spotfm/spotify/track.py` - Track model with lifecycle tracking
- `spotfm/spotify/album.py`, `artist.py`, `playlist.py` - Entity models
- `spotfm/spotify/dupes.py` - Duplicate detection (ID and fuzzy match)
- `spotfm/spotify/misc.py` - High-level commands (discover, add, remove, count, liked-songs sync, track queries)
- `spotfm/sqlite.py` - SQLite singleton connection management, schema migration, parameterized write helpers
- `spotfm/utils.py` - Config, caching, string sanitization
- `spotfm/web/` - FastAPI web UI (routes/, jobs/, templates/); jobs run in-process, single worker

**Layered Separation Rule (core vs. presentation):**
- Core modules (`spotfm/spotify/`, `spotfm/lastfm.py`): return structured data (dicts/lists), use `logging` for observability, never call `print()`
- Presentation layer (`spotfm/cli.py`, `spotfm/web/`): format and display data; never own business logic
- Shared orchestration logic used by both CLI and web belongs in the core module, not duplicated in each caller

## Key Implementation Notes

1. **Rate Limiting & Parallel Execution**: `sleep()` calls prevent Spotify 429 errors (~10 req/s target)
   - 0.1s between track API calls in `Track.get_tracks()` parallel submission phase
   - 0.05s between album/artist API calls in post-fetch hydration (Album/Artist multi-fetch helpers with rate_limit=True)
   - Single-entity fetches via `Album.get_album()` / `Artist.get_artist()` are not rate-limited
   - ThreadPoolExecutor (5 workers) parallelizes track API calls with submission-based rate limiting
   - Client configured with `retries=0` (no auto-retry); sleep is the primary rate limiting strategy
   - Liked Songs sync (`misc.update_liked_tracks`): 0.1s between `/me/tracks` pages, between 40-URI contains chunks, and between relinked hydrations
   - See SPEC.md "Critical Design Decisions" → "Rate Limiting" (subsection 5) for the detailed strategy
2. **Spotify API Migration** (Feb 2026): Batch endpoints removed; all Track/Album/Artist fetching uses individual API calls
   - Playlist add_tracks uses batch_size=50 (Spotify API limit for add operations)
   - Playlist remove_tracks uses batch_size=100 (Spotify API limit for remove operations)
   - Exception handling distinguishes KeyError/ValueError (unavailable) from unexpected errors
3. **Saved-tracks endpoint limits** (verified against Spotify's official OpenAPI schema): spotipy's `current_user_saved_tracks_contains` routes to `GET /me/library/contains` — **max 40 URIs** (the deprecated `/me/tracks/contains` allowed 50; 50-URI chunks fail with 400 "Too many uris requested"). `current_user_saved_tracks` uses `GET /me/tracks` — **not deprecated**, no `GET /me/library` paging replacement exists (the `/me/library` family covers save/remove/contains only), and its shared `QueryLimit` is default 20 / max 50 (matches `LIKED_PAGE_SIZE`). For endpoint limits and deprecation status, prefer the machine-readable schema (`https://developer.spotify.com/reference/web-api/open-api-schema.yaml`) over the reference pages (cookie walls/404s have already misled this project once); before trusting a limit, also check which URL the installed spotipy version actually requests.
4. **`sync_to_db` in discover context** — `Track.get_tracks()` and `Playlist.get_tracks()` default to `sync_to_db=True`. Any caller that needs to check "is this track new before writing it?" must pass `sync_to_db=False` (e.g. `discover_from_playlists`). Forgetting this causes discover to silently add nothing.
5. **`Track.get_tracks()` quirks** (both bite silently):
   - Pickle-cache hits return the Track without writing it to SQLite, even when `sync_to_db=True`. Callers that need a `tracks` row must re-check the DB and persist (see `_apply_liked_additions`).
   - Relinked (market-replaced) tracks fetched under their original ID come back in the response under the replacement ID: `get_tracks` persists the row under the replacement ID and drops the track from the returned list. Resolve `linked_from` before hydration instead (see `playlist.py` track extraction and `_apply_liked_additions`).
6. **Liked Songs**: a separate library, synced ONLY by `update-liked` (CLI command / web job); `update-playlists` is playlists-only. `tracks.liked`/`liked_at` are owned by the liked sync via explicit parameterized UPDATEs; `Track.sync_to_db()` COALESCE-preserves them, so playlist re-syncs must never reset liked state. Fast-path state (last observed total + top `added_at`) lives in `liked_sync_state`. Both the CLI command and the web job log track counts after a successful sync.
7. **SQL Injection Risk**: F-strings used in queries (TODO: migrate to parameterized). New code must use parameterized statements — `sqlite.select_db()` with params, or `sqlite.execute_many()` for batched writes (added with the Liked Songs PR).
8. **Global DB Connection**: `spotfm/sqlite.py` uses module-level singleton with atexit cleanup
9. **Duplicate Detection**: Operates on SQLite only, no API calls (optimization)
10. **String Safety**: `utils.sanitize_string()` removes single quotes (SQL safety)
11. **Schema migrations**: new columns/tables go in `sqlite.migrate_database_schema()` (idempotent, guarded by the up-to-date check) AND `hacks/create-tables.sql`; conftest's temp schema intentionally predates migrations so tests exercise them.
12. **No query helpers inside comprehension conditions**: `[x for x in xs if x not in query(xs)]` re-runs the query once per element (a real 11,000x blow-up shipped and was only caught by review — tests with small fixtures do not expose it). Hoist the query result to a variable first.
13. **Track-counts CSV writes** (`log_track_counts`): serialized in-process via `_track_counts_lock` (the update-playlists and update-liked web jobs run on parallel executor threads); the one-time schema migration rewrites atomically (temp file + replace) so readers never see a truncated file. Cross-process concurrency (CLI while the web app runs) is NOT covered — do not assume it is. Any new append-style log file should follow the same pattern.

## Testing

- `make test` - Full suite
- `make test-unit` - Unit tests only (fast)
- `make test-coverage` - Coverage report (HTML in htmlcov/)
- `make lint-fix` - Auto-fix style issues

Markers: `@pytest.mark.unit` (fast), `@pytest.mark.integration` (temp databases), `@pytest.mark.slow` (run with `pytest -m slow`).

Requirement: 90%+ coverage on modified code before committing.
