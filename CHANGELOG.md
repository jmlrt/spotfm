# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### ⚠️ BREAKING CHANGES

- **Minimum Python version upgraded from 3.11 to 3.14**
  - Adopted PEP 758 bracketless exception syntax (`except A, B:` instead of `except (A, B):`)
  - CI/CD now tests only Python 3.14 (dropped 3.11, 3.12, 3.13 support)
  - Projects requiring older Python versions must pin to spotfm 0.0.4

- **Spotify API Migration (February 2026)**
  - Spotify removed batch endpoints (`GET /albums`, `GET /artists`, `GET /tracks`)
  - Upgraded spotipy from 2.25.2 to >=2.26.0 (released 2026-03-03)
  - spotfm now uses individual endpoints with proactive rate limiting
  - **User-visible API changes:**
    - `BATCH_SIZE` constant removed from `spotfm.spotify.constants`
    - `Track.get_tracks()` no longer accepts `batch_size` parameter
    - `Playlist.add_tracks()` no longer accepts `batch_size` parameter (always uses Spotify's limit of 50)
  - Improved error handling for deleted/unavailable tracks, albums, artists
  - Rate limiting: 0.1s between track calls, 0.05s between album/artist calls (on multi-fetch paths)

### Added

**Spotify Playlist Management**:
- `remove-tracks-from-playlist` command to remove tracks from a playlist
  - Syntax: `spfm spotify remove-tracks-from-playlist -p <playlist_id> -f <file>`
  - Supports track IDs and Spotify URLs (one per line)
  - Removes from Spotify playlist and local database
  - Preserves orphaned tracks table entries (negative cache for discover workflow)
- `update-playlists --log-counts` flag for tracking playlist statistics
  - Appends timestamped track counts to CSV log file (`~/.spotfm/track-counts.csv`)
  - Supports multiple runs per day with separate timestamps
  - Configurable log path via `track_counts_log` in `spotfm.toml`
  - Optional secondary pattern tracking via `new_tracks_pattern` (e.g., "IR%", "New%")
  - Unopinionated by default (no pattern tracking without config)
  - Stable 3-column CSV schema: `timestamp;total_tracks;pattern_tracks` (pattern_tracks is empty when no pattern configured)

**Last.FM Recent Scrobbles Enhancements**:
- **State tracking now default** for `recent-scrobbles` command
  - First run initializes state file with current playcount; fetches up to `--limit` scrobbles (default 50)
  - Subsequent runs automatically fetch ALL new scrobbles since last run (ignores `--limit`)
  - State file (`~/.spotfm/lastfm_state.json`) safely rolls back on fetch errors
- **Period filtering** via `--period-minimum` flag
  - Filter tracks by minimum scrobbles within period window (default: no filter)
  - Works with `--scrobbles-minimum` to apply both filters (AND logic)
  - Configurable via `period_minimum` in `spotfm.toml`
- **Interactive mode** via `--interactive`/`-i` flag
  - Open results in `$EDITOR` with automatic deduplication
  - Safe temp file handling with cleanup
  - Only opens editor if results exist
- **Config-based defaults**
  - `scrobbles_minimum` option in `spotfm.toml` (default: 4)
  - `period_minimum` option in `spotfm.toml` (default: unset = no filter)
  - Eliminates need to repeatedly type `-s` flag
- **Fixed CLI flag conflict**
  - Dropped `-i` short form from top-level `--info` flag (now exclusive to `--interactive`)

**Documentation** (new comprehensive guides):
- `SPEC.md` (8K) - Architecture, design decisions, features, data model
- `CONTRIBUTING.md` (5.5K) - Development workflow, testing, code style
- `CHANGELOG.md` - Version history and release notes (this file)
- `TODO.md` - Feature roadmap prioritized by effort (HIGH/MEDIUM/LOW)
- Module-level docstrings explaining architecture (track.py, sqlite.py, misc.py)
- Enhanced conftest.py with testing patterns documentation
- Tool priority strategy to CLAUDE.md (Read/Grep/Glob/Edit/Write before bash)
- Commit strategy guidance (only commit changed files, not all files)

**Configuration & Tooling**:
- Added deny list to .claude/settings.json for security
- Consolidated git/gh subcommands to reduce permissions

### Changed

**Documentation Refactoring**:
- CLAUDE.md: Refactored to lean 1-page quick reference with navigation
- README.md: Consolidated and user-focused (removed duplication)
- Makefile: Updated test-all-versions to only test Python 3.14

**Code Quality**:
- Updated all Python version references from 3.11+ to 3.14+
- PEP 758 syntax adoption in exception handlers (sqlite.py, playlist.py)
- CI workflow: Clarified test steps vs separate jobs
- Updated author email to GitHub noreply address

**Performance Improvements**:
- **ThreadPoolExecutor-based parallel track fetching** (Track.get_tracks)
  - Parallelizes individual track API calls (Phase 2) for 35-40% faster discovery
  - Maintains original API request rate (~10 req/s) via submission-based rate limiting
  - Reduces `discover-from-playlists` time from ~2.5 min to ~1.5 min for 500+ new tracks
  - Includes batch album/artist fetching post-parallel-phase for efficiency

## [Recent Releases]

### Version History
Releases are tagged with version numbers on GitHub. Release dates and changes are documented in git tags and GitHub releases.

For version-specific changes, see git history and GitHub releases: https://github.com/jmlrt/spotfm/releases

## Key Features by Version

### Core Features (All Versions)
- Spotify API integration (playlists, tracks, albums, artists)
- Last.FM API integration (scrobbles, listening history)
- SQLite database for offline querying
- Three-tier caching strategy (pickle, database, API)
- Duplicate track detection (by ID and fuzzy matching)
- Smart track discovery with orphaned track prevention
- Lifecycle tracking (created_at, last_seen_at)

### Commands
- `spfm spotify update-playlists` - Sync all playlists
- `spfm spotify discover-from-playlists` - Find new tracks in source playlists
- `spfm spotify find-duplicate-ids` - Find tracks in multiple playlists
- `spfm spotify find-duplicate-names` - Find similar tracks via fuzzy matching
- `spfm spotify find-relinked-tracks` - Find Spotify-replaced tracks
- `spfm lastfm recent-scrobbles` - Get recent listening history

## Planned Features

See [TODO.md](TODO.md) for detailed feature specifications:
- **Logging improvements**: Better progress and summary output
- **Random playlist generator**: Create randomized playlists from library
- **Duplicate detection enhancements**: Smarter suffix handling
- **CHANGELOG automation**: Automated release notes generation

## Development

### Tools & Dependencies
- **Python**: 3.14+
- **Package Manager**: uv
- **Testing**: pytest with coverage
- **Linting & Formatting**: ruff
- **Type Checking**: Built-in type hints (Python 3.14+)
- **CI/CD**: GitHub Actions
- **APIs**:
  - Spotify Web API via spotipy
  - Last.FM API via pylast

### Test Coverage
- 240+ tests covering unit, integration, and CLI scenarios
- Target: ≥90% coverage on modified code
- Continuous integration on Python 3.14
- Multi-platform testing (Ubuntu, macOS)

---

## Contributing

Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on how to contribute to spotfm.

## License

spotfm is released under the MIT License. See LICENSE file for details.
