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
- Verify with `make test-unit` or targeted `uv run pytest -k ...`, not ad-hoc `uv run python -c` one-liners

## Critical Warnings

**Orphaned Tracks:**
- DO NOT delete orphaned tracks from the `tracks` table (tracks with no playlists)
- Orphaned tracks serve as a "negative cache" preventing re-adding intentionally removed tracks
- Deleting them will cause `discover_from_playlists` to re-add previously removed tracks

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
- `spotfm/spotify/misc.py` - High-level commands (discover, add, remove, count)
- `spotfm/sqlite.py` - SQLite singleton connection management
- `spotfm/utils.py` - Config, caching, string sanitization

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
   - See SPEC.md section 5 for the detailed strategy
2. **Spotify API Migration** (Feb 2026): Batch endpoints removed; all Track/Album/Artist fetching uses individual API calls
   - Playlist add_tracks uses batch_size=50 (Spotify API limit for add operations)
   - Playlist remove_tracks uses batch_size=100 (Spotify API limit for remove operations)
   - Exception handling distinguishes KeyError/ValueError (unavailable) from unexpected errors
3. **`sync_to_db` in discover context** — `Track.get_tracks()` and `Playlist.get_tracks()` default to `sync_to_db=True`. Any caller that needs to check "is this track new before writing it?" must pass `sync_to_db=False` (e.g. `discover_from_playlists`). Forgetting this causes discover to silently add nothing.
4. **SQL Injection Risk**: F-strings used in queries (TODO: migrate to parameterized)
5. **Global DB Connection**: `spotfm/sqlite.py` uses module-level singleton with atexit cleanup
6. **Duplicate Detection**: Operates on SQLite only, no API calls (optimization)
7. **String Safety**: `utils.sanitize_string()` removes single quotes (SQL safety)

## Testing

- `make test` - Full suite
- `make test-unit` - Unit tests only (fast)
- `make test-coverage` - Coverage report (HTML in htmlcov/)
- `make lint-fix` - Auto-fix style issues

Markers: `@pytest.mark.unit` (fast), `@pytest.mark.integration` (temp databases), `@pytest.mark.slow` (run with `pytest -m slow`).

Requirement: 90%+ coverage on modified code before committing.
