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

### Added

**Documentation** (new comprehensive guides):
- `SPEC.md` (8K) - Architecture, design decisions, features, data model
- `CONTRIBUTING.md` (5.5K) - Development workflow, testing, code style
- `CHANGELOG.md` - Version history and release notes (this file)
- Module-level docstrings explaining architecture (track.py, sqlite.py, misc.py)
- Enhanced conftest.py with testing patterns documentation
- Tool priority strategy to CLAUDE.md (Read/Grep/Glob/Edit/Write before bash)
- Commit strategy guidance (only commit changed files, not all files)

**Configuration & Tooling**:
- Deny list in .claude/settings.json to prevent dangerous operations
- Consolidated git/gh subcommands into Bash(git:*) and Bash(gh:*)
- Reorganized TODO.md by priority (HIGH/MEDIUM/LOW) with effort estimates

### Changed

**Documentation Refactoring**:
- CLAUDE.md: 430 → 71 lines (lean 1-page quick reference with navigation)
- README.md: 242 → 171 lines (eliminated duplication, user-focused)
- .claude/settings.json: 45 → 20 permissions (57% reduction)
- Makefile: Updated test-all-versions to only test Python 3.14

**Code Quality**:
- Updated all Python version references from 3.11+ to 3.14+
- PEP 758 syntax adoption in exception handlers (sqlite.py, playlist.py)
- CI workflow: Clarified test steps vs separate jobs
- Updated author email to GitHub noreply address

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
