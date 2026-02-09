# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

spotfm is a Python library and CLI tool for interacting with Spotify and Last.FM APIs. It focuses on playlist management, track discovery, and music library analytics. The tool syncs data to a local SQLite database for offline querying and analysis.

## Development Commands

### Setup
```bash
make install          # Sync dependencies using uv (creates .venv)
# or directly:
uv sync --all-extras  # Install package with all optional dependencies
```

### Code Quality
```bash
make format          # Format code with ruff
make lint            # Check code with ruff
make lint-fix        # Auto-fix linting issues with ruff
make lint-fix-unsafe # Auto-fix linting issues including unsafe fixes
make pre-commit      # Run all pre-commit hooks (includes ruff)
# or directly:
uv run ruff format .
uv run ruff check .
uv run ruff check --fix .
uv run ruff check --fix --unsafe-fixes .
```

### Testing
```bash
make test              # Run all tests
make test-unit         # Run only unit tests (fast)
make test-integration  # Run only integration tests
make test-coverage     # Run tests with HTML coverage report
make test-verbose      # Run tests with verbose output
make test-parallel     # Run tests in parallel (faster)
make test-failed       # Re-run only failed tests
make test-all-versions # Run tests across Python 3.11, 3.12, 3.13, 3.14
# or directly:
uv run pytest                    # Run all tests
uv run pytest -m unit            # Run unit tests only
uv run pytest -m integration     # Run integration tests only
uv run pytest --cov=spotfm       # Run with coverage
uv run pytest -n auto            # Run in parallel
uv run --python=3.13 pytest      # Run with specific Python version
```

### Duplicate Detection
```bash
make dupes-ids           # Find tracks with same ID in multiple playlists (console output)
make dupes-names         # Find similar tracks using fuzzy matching (console output)
make dupes-ids-csv       # Export duplicate IDs to data/dupes_ids.csv
make dupes-names-csv     # Export similar tracks to data/dupes_names.csv
# or directly:
spfm spotify find-duplicate-ids                  # Find duplicate track IDs
spfm spotify find-duplicate-ids -o output.csv    # Save to CSV
spfm spotify find-duplicate-names                # Find similar track names (fuzzy)
spfm spotify find-duplicate-names -t 90          # Adjust similarity threshold (0-100)
spfm spotify find-duplicate-names -o output.csv  # Save to CSV
```

### Build and Publish
```bash
make build           # Build distribution packages with uv
make clean           # Remove build artifacts, .venv, and cache files
make publish         # Tag release, push to git, upload to PyPI
```

### CLI Usage
```bash
spfm spotify <command> [options]
spfm lastfm <command> [options]
```

## Configuration

Configuration is stored in `~/.spotfm/spotfm.toml`. See [spotfm.example.toml](spotfm.example.toml) for the template.

Required settings:
- **Spotify**: `client_id`, `client_secret`, `excluded_playlists`, `sources_playlists`, `discover_playlist`
- **Last.FM**: `api_key`, `api_secret`, `username`, `password_hash`

OAuth tokens are cached in `~/.spotfm/spotify-token-cache`.

## Architecture

### Core Design Pattern

The codebase uses a **three-tier caching strategy** for Spotify entities (Track, Album, Artist, Playlist):

1. **In-memory cache**: Pickle files in `~/.cache/spotfm/{kind}/{id}.pickle`
2. **SQLite database**: Persistent storage in `~/.spotfm/spotify.db`
3. **Spotify API**: Fallback when data is not cached or `refresh=True`

All entity classes (Track, Album, Artist, Playlist) follow this pattern:
- `get_{entity}(id, client, refresh=False, sync_to_db=True)` - Main entry point
- `update_from_cache()` - Check pickle cache first
- `update_from_db()` - Try SQLite database
- `update_from_api(client)` - Fetch from Spotify API as last resort
- `sync_to_db()` - Persist to SQLite

### Module Structure

- **[spotfm/cli.py](spotfm/cli.py)** - CLI entry point with argument parsing, dispatches to lastfm_cli() or spotify_cli()
- **[spotfm/lastfm.py](spotfm/lastfm.py)** - Last.FM client, Track, and User classes for scrobble analysis
- **[spotfm/spotify/client.py](spotfm/spotify/client.py)** - Spotify client wrapper, handles playlist filtering and bulk updates
- **[spotfm/spotify/dupes.py](spotfm/spotify/dupes.py)** - Duplicate detection using exact ID matching and fuzzy name matching (rapidfuzz)
- **[spotfm/spotify/misc.py](spotfm/spotify/misc.py)** - High-level commands: discover-from-playlists, add-tracks-from-file, count-tracks
- **[spotfm/spotify/track.py](spotfm/spotify/track.py)** - Track model with genre aggregation from artists
- **[spotfm/spotify/playlist.py](spotfm/spotify/playlist.py)** - Playlist model with track batch operations
- **[spotfm/spotify/album.py](spotfm/spotify/album.py)** - Album model with artist relationships
- **[spotfm/spotify/artist.py](spotfm/spotify/artist.py)** - Artist model with genre metadata
- **[spotfm/sqlite.py](spotfm/sqlite.py)** - SQLite connection management with global singleton pattern
- **[spotfm/utils.py](spotfm/utils.py)** - Config parsing, URL parsing, caching utilities, string sanitization

### Database Schema

See [hacks/create-tables.sql](hacks/create-tables.sql) for the full schema. Key tables:

- `playlists`, `tracks`, `albums`, `artists` - Core entities
- `playlists_tracks` - Many-to-many with added_at timestamp
- `tracks_artists`, `albums_tracks`, `albums_artists` - Relationship tables
- `artists_genres` - Genre associations (artists can have multiple genres)

### Key Behavioral Notes

1. **SQL Injection Risk**: The codebase currently uses f-string interpolation for SQL queries. There's a TODO in [spotfm/spotify/client.py:11-12](spotfm/spotify/client.py#L11-L12) to migrate to parameterized queries.

2. **Rate Limiting**: `sleep()` calls are scattered throughout to prevent Spotify 429 errors:
   - 0.1s between tracks in [spotfm/spotify/misc.py:26](spotfm/spotify/misc.py#L26)
   - 1s between batches in [spotfm/spotify/misc.py:50](spotfm/spotify/misc.py#L50)
   - 0.05s-0.1s in Track.get_tracks()

3. **String Sanitization**: All user-facing strings go through `utils.sanitize_string()` which removes single quotes (for SQL safety).

4. **Batch Operations**: Default batch size is 90 (BATCH_SIZE constant), used for Spotify API bulk operations to stay under rate limits.

5. **Global DB Connection**: [spotfm/sqlite.py](spotfm/sqlite.py) uses a module-level singleton connection with atexit cleanup.

6. **Discover Workflow**: The discover-from-playlists command finds tracks in source playlists that don't exist in the DB, adds them to a destination playlist, then syncs to DB (see [spotfm/spotify/misc.py:53-82](spotfm/spotify/misc.py#L53-L82)).

7. **Duplicate Detection**: The dupes module operates entirely on SQLite database data (no API calls):
   - `find_duplicate_ids()` finds tracks appearing in multiple playlists (exact ID match)
   - `find_duplicate_names()` uses rapidfuzz for fuzzy string matching to find similar tracks
   - Both functions support excluding playlists via config and exporting results to CSV
   - Fuzzy matching uses 4 algorithms: ratio, partial_ratio, token_sort_ratio, token_set_ratio

8. **Track Lifecycle Tracking & Orphaned Tracks** (CRITICAL):
   - **Purpose**: Tracks have lifecycle timestamps to prevent re-discovering intentionally removed tracks
   - **Schema**:
     - `created_at`: When track was first discovered (set once, never changes)
     - `last_seen_at`: Last time track appeared in any playlist (updated on every sync)
   - **Orphaned tracks**: Tracks that exist in `tracks` table but not in `playlists_tracks`
     - These are tracks that were removed from ALL playlists
     - They accumulate in the database over time (this is intentional)
   - **Discovery behavior**: `discover_from_playlists` skips orphaned tracks to prevent re-adding removed tracks

   **⚠️ CRITICAL WARNING**:
   - **DO NOT delete orphaned tracks from the `tracks` table**
   - Orphaned tracks serve as a "negative cache" for the discovery feature
   - Deleting them will cause `discover_from_playlists` to re-add previously removed tracks
   - If cleanup is needed, it should only be done for tracks not seen in 90+ days AND with explicit user opt-in

   **Implementation notes**:
   - `track.is_orphaned()` checks if track is in zero playlists
   - See [spotfm/spotify/misc.py:45-106](spotfm/spotify/misc.py#L45-L106) for discovery logic
   - See [spotfm/spotify/track.py](spotfm/spotify/track.py) for lifecycle timestamp handling
   - See [spotfm/spotify/track.py:285-301](spotfm/spotify/track.py#L285-L301) for `is_orphaned()` implementation

## Code Style

- **Python**: 3.11+ (uses match/case statements)
- **Package Manager**: uv (fast Python package installer and resolver)
- **Build System**: hatchling (modern Python build backend)
- **Formatting & Linting**: ruff (all-in-one tool replacing black, isort, flake8, pyupgrade)
  - 120 character line length
  - Targets Python 3.11+
  - Auto-fixes import sorting, syntax upgrades, and common issues
- Pre-commit hooks enforce all style rules automatically

## Development Practices

When fixing a bug or inconsistency in one CLI command, proactively check ALL similar commands for the same issue before considering the task done. Do not wait for the user to ask twice.

## Commit Messages

Write **concise, focused commit messages** that clearly describe what changed and why:

### Structure
```
Brief summary (50 chars or less)

- Key change 1
- Key change 2
- Key change 3

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
```

### Guidelines
1. **Be concise**: Focus on the most important changes, not exhaustive details
2. **Use bullet points**: Group related changes under clear categories
3. **Highlight impact**: Mention test coverage, performance improvements, or breaking changes
4. **Skip implementation details**: Don't describe every file changed or every function modified
5. **Include metrics**: Add coverage percentages, test counts only if significant
6. **Keep it scannable**: Use short sentences and clear formatting

### Examples

**Good** (concise):
```
Migrate database operations to sqlite module

- Create singleton connection pattern for better performance
- Remove duplicate query functions from utils.py
- Add comprehensive test suite (87% coverage)
- Use parameterized queries to prevent SQL injection

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
```

**Bad** (too verbose):
```
Migrate database operations to sqlite module and add comprehensive test coverage

This commit consolidates database operations and adds extensive test coverage
for the duplicate detection functionality.

Database Migration:
- Create new spotfm/sqlite.py module with singleton connection pattern
- Migrate all database operations from utils.py to sqlite.py
- Add connection pooling to avoid creating new connections for each query
- Implement dynamic attribute resolution (__getattr__) for test monkeypatching
- Add database path tracking to handle multiple databases in tests
- Update all 9 production files to use sqlite module instead of utils
[...15 more bullet points...]
```

## Git Workflow

When staging and committing changes, ensure ONLY changes from the current task are included. Review staged files against the current session scope before committing.

## Testing

The project has a comprehensive test suite with **243 tests** achieving **76% overall coverage** (100% on core modules).

### Test Structure

- **[tests/conftest.py](tests/conftest.py)** - Shared fixtures (temp database, cache, mock Spotify client)
- **[tests/test_utils.py](tests/test_utils.py)** - Unit tests for utility and database functions (100% coverage)
- **[tests/test_artist.py](tests/test_artist.py)** - Unit tests for Artist class (100% coverage)
- **[tests/test_track.py](tests/test_track.py)** - Unit tests for Track class (97% coverage)
- **[tests/test_album.py](tests/test_album.py)** - Unit tests for Album class (100% coverage)
- **[tests/test_playlist.py](tests/test_playlist.py)** - Unit tests for Playlist class (97% coverage)
- **[tests/test_dupes.py](tests/test_dupes.py)** - Unit tests for duplicate detection (87% coverage)
- **[tests/test_integration.py](tests/test_integration.py)** - Integration and regression tests for workflows

### Testing Best Practices

1. **Isolation**: Each test uses temporary databases and cache directories
2. **Fixtures**: Reusable test data via pytest fixtures in conftest.py
3. **Markers**: Tests are marked as `@pytest.mark.unit` or `@pytest.mark.integration`
4. **Mocking**: Extensive use of mocks to avoid real API calls
5. **Time Freezing**: Uses `freezegun` for deterministic date testing
6. **Coverage**: Branch coverage enabled with HTML reports in `htmlcov/`
7. **Fast Execution**: Full suite runs in ~4 seconds
8. **Coverage Target**: **All modified or new code must have ≥90% test coverage** before committing

### CRITICAL: Database Isolation in Tests

**All tests MUST use mock databases and NEVER access the real database at `~/.spotfm/spotify.db`.**

#### When to Add Database Fixtures

A test needs the `temp_database` fixture and `monkeypatch` if it:
- Calls `get_artist()`, `get_album()`, `get_track()`, or `get_playlist()` with a client parameter
- Calls `update_from_db()` or `sync_to_db()` methods
- Calls `update_from_api()` which internally calls other `get_*()` methods

#### How to Add Database Fixtures

For any test that interacts with the database, add these parameters and setup:

```python
def test_example(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
    """Test that interacts with database."""
    # CRITICAL: Monkeypatch DATABASE to use temp database
    monkeypatch.setattr(utils, "DATABASE", temp_database)
    monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

    # ... test code
```

#### Tests That Don't Need Database Fixtures

Tests that only test representations, initializations, or direct API calls (without database persistence) don't need database fixtures:
- `__repr__()`, `__str__()`, or `__init__()` methods
- Direct calls to `update_from_api()` without `get_*()` methods
- Tests that only mock responses without database interaction

#### Current State

- **Total tests**: 129
- **Tests with DATABASE monkeypatch**: 49 (only those that need it)
- **Tests accessing real database**: 0 ✅

#### Verification

To verify no tests access the real database, check that:
1. All tests calling `get_*()` methods have `temp_database` fixture
2. All tests calling `update_from_db()` have `temp_database` fixture
3. `~/.spotfm/spotify.db` is never created or accessed during test runs
4. All GitHub Actions tests pass on all platforms (Ubuntu, macOS, Windows)

### Running Tests

```bash
# Run all tests
make test

# Run specific test types
make test-unit         # Only unit tests (fast)
make test-integration  # Only integration tests

# Run with coverage report
make test-coverage     # Generates HTML report in htmlcov/

# Run in parallel (faster)
make test-parallel

# Run only failed tests (useful during debugging)
make test-failed

# Run specific test file
uv run pytest tests/test_utils.py

# Run specific test
uv run pytest tests/test_utils.py::TestSanitizeString::test_sanitize_removes_single_quotes

# Check coverage for specific module
uv run pytest tests/test_dupes.py --cov=spotfm.spotify.dupes --cov-report=term-missing
```

### Coverage Verification Workflow

**IMPORTANT**: Before committing any changes, verify test coverage meets the ≥90% requirement:

1. **After writing/modifying code**:
   ```bash
   # Run tests for the modified module with coverage
   uv run pytest tests/test_<module>.py --cov=spotfm.<module> --cov-report=term-missing
   ```

2. **Check the coverage output**:
   - Look for the coverage percentage in the report
   - Review "Missing" column to see uncovered lines
   - If coverage < 90%, add more tests to cover edge cases

3. **Add tests until ≥90% coverage**:
   - Focus on branches, edge cases, and error conditions
   - Use fixtures for test data isolation
   - Test both success and failure paths

4. **Run full test suite** before committing:
   ```bash
   make test
   ```

5. **Only commit when**:
   - All tests pass (179/179 or more)
   - Modified modules have ≥90% coverage
   - No linting errors (pre-commit hooks pass)

### CI/CD

Tests run automatically via GitHub Actions on:
- Every push to `main`
- Every pull request
- Multiple Python versions (3.11, 3.12)
- Multiple platforms (Ubuntu, macOS, Windows)

See [.github/workflows/tests.yml](.github/workflows/tests.yml) for the full workflow configuration.

## Claude Code Settings

### Permissions Management

The project uses `.claude/settings.local.json` to manage Claude Code permissions for bash commands and skills.

**IMPORTANT: Permissions MUST be kept in alphabetical order.**

When adding new permissions:
1. Insert the permission in alphabetical order
2. Sort order rules:
   - `Bash()` permissions come before `Skill()` permissions
   - Within `Bash()`, sort by command name (e.g., `cat` before `git`)
   - Within same command, sort by subcommand (e.g., `git add` before `git commit`)
   - Wildcard permissions (`*`) come after the base permission

Example structure:
```json
{
  "permissions": {
    "allow": [
      "Bash(cat:*)",
      "Bash(gh pr create:*)",
      "Bash(gh pr view:*)",
      "Bash(git add:*)",
      "Bash(git commit:*)",
      "Bash(make test:*)",
      "Skill(create-pr)",
      "Skill(create-pr:*)"
    ]
  }
}
```

**Why alphabetical order?**
- Easier to find existing permissions
- Prevents duplicate permissions
- Cleaner git diffs when adding/removing permissions
- Consistent with project organization standards
