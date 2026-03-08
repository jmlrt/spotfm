# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Test markers for selective test runs (@pytest.mark.unit, @pytest.mark.integration, @pytest.mark.slow)
- Comprehensive TODO.md with feature roadmap and implementation specs
- Enhanced CLAUDE.md with test markers documentation
- Contributing guidelines (CONTRIBUTING.md)
- Improved .claude/settings.json with deny list for safety

### Changed
- CLAUDE.md refactored from 430 → 71 lines (focused 1-page reference)
- README.md expanded with comprehensive usage, setup, and database documentation
- Makefile enhanced with help target and organized command groups
- Architecture documentation moved to code docstrings (track.py, sqlite.py, misc.py)
- Testing patterns documented in conftest.py docstrings
- SQL injection risk documentation (TODO: migrate to parameterized queries)
- Rate limiting documentation clarified with actual sleep pattern locations

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
