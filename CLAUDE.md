# CLAUDE.md - Quick Reference for Claude Code

This file provides essential guidance for Claude Code when working on spotfm.

## 📚 Documentation Navigation

**This is a 1-page quick reference.** For comprehensive documentation, see:

- **[SPEC.md](SPEC.md)** - Source of truth for architecture, design decisions, features, and data model
  - Read this for: understanding three-tier caching, entity lifecycle, critical design decisions, orphaned tracks handling
- **[CONTRIBUTING.md](CONTRIBUTING.md)** - Complete development guide for contributing code
  - Read this for: testing requirements, code style, commit messages, workflow, database isolation practices
- **[README.md](README.md)** - User-facing documentation with setup, configuration, and usage
  - Read this for: installation, CLI commands, configuration guide, project overview

## What is spotfm?

A Python library and CLI tool for Spotify and Last.FM API interaction. Focuses on playlist management, track discovery, and music library analytics. Data syncs to a local SQLite database for offline querying.

## Critical Warnings ⚠️

**Orphaned Tracks:**
- **DO NOT delete orphaned tracks** from the `tracks` table (tracks with no playlists)
- Orphaned tracks serve as a "negative cache" to prevent re-adding intentionally removed tracks
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
- `retrieve_object_from_cache()` → `update_from_db()` → `update_from_api(client)` → `sync_to_db()`

**Module Map:**
- `spotfm/cli.py` - CLI entry point, argument parsing
- `spotfm/lastfm.py` - Last.FM client and scrobble analysis
- `spotfm/spotify/client.py` - Spotify wrapper, playlist filtering
- `spotfm/spotify/track.py` - Track model with lifecycle tracking
- `spotfm/spotify/album.py`, `artist.py`, `playlist.py` - Entity models
- `spotfm/spotify/dupes.py` - Duplicate detection (ID and fuzzy match)
- `spotfm/spotify/misc.py` - High-level commands (discover, add, count)
- `spotfm/sqlite.py` - SQLite singleton connection management
- `spotfm/utils.py` - Config, caching, string sanitization

## Code Style & Requirements

- **Python**: 3.11+ (match/case statements)
- **Formatting**: ruff (120 char line length)
- **Testing**: ≥90% coverage on modified code before committing
- **String Safety**: `utils.sanitize_string()` removes single quotes (SQL safety)

## Key Implementation Notes

1. **Rate Limiting**: `sleep()` calls prevent Spotify 429 errors - do not remove without understanding impact
2. **SQL Injection Risk**: F-strings used in queries (TODO: migrate to parameterized)
3. **Batch Operations**: Default batch sizes: 50 for tracks (`BATCH_SIZE`), 20 for albums (`ALBUM_BATCH_SIZE`)
4. **Global DB Connection**: `spotfm/sqlite.py` uses module-level singleton with atexit cleanup
5. **Duplicate Detection**: Operates on SQLite only, no API calls (optimization)

## Development Practices

**Before committing:**
- Run `make test` (all tests pass)
- Run `make lint` (no ruff violations)
- When fixing a bug in one CLI command, proactively check ALL similar commands for the same issue

**Test execution:**
- `make test` - Full suite
- `make test-unit` - Unit tests only (fast)
- `make test-coverage` - With coverage report (HTML in htmlcov/)
- `make lint-fix` - Auto-fix style issues

**Test markers** (for selective test runs):
- `@pytest.mark.unit` - Fast unit tests
- `@pytest.mark.integration` - Integration tests (use temp databases)
- `@pytest.mark.slow` - Long-running tests (run with `pytest -m slow`)

## Tool Priority Strategy

**Always use dedicated tools before requesting new bash permissions:**

1. **File reading** → Use `Read` tool (not `cat`)
2. **File searching** → Use `Grep` tool (not `grep`)
3. **File patterns** → Use `Glob` tool (not `find`)
4. **File writing** → Use `Write` tool (not `echo`/`cat`)
5. **File editing** → Use `Edit` tool (not `sed`)
6. **Git commands** → Use `Bash(git:*)` (already allowed)
7. **Build/test** → Use `make` targets (already allowed)

**Benefit**: Dedicated tools provide better UX, proper permissions handling, and reduce bash permission bloat.

## 📖 For More Information

- **Architecture & Design**: See [SPEC.md](SPEC.md) for comprehensive specification
- **Contributing & Workflow**: See [CONTRIBUTING.md](CONTRIBUTING.md) for complete development guide
- **Usage & Configuration**: See [README.md](README.md) for user documentation
- **Build Commands**: Run `make help` or see [Makefile](Makefile)
- **Feature Roadmap**: See [TODO.md](TODO.md) for planned enhancements
