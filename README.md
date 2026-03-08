# spotfm

A Python library and CLI tool for interacting with Spotify and Last.FM APIs. Focuses on playlist management, track discovery, and music library analytics. Data syncs to a local SQLite database for offline querying and analysis.

## Features

- **Spotify Integration**: Manage playlists, discover tracks, analyze library
- **Last.FM Integration**: Fetch scrobbling history and analyze listening patterns
- **Local Database**: SQLite backend for offline querying and analytics
- **Duplicate Detection**: Find duplicate tracks by ID and fuzzy-match similar tracks
- **Smart Caching**: Three-tier caching (pickle → SQLite → API) for performance

## Installation

### Prerequisites
- Python 3.11 or higher
- [uv](https://docs.astral.sh/uv/) (fast Python package manager)

### Setup

```bash
# Clone the repository
git clone https://github.com/jmlrt/spotfm.git
cd spotfm

# Install dependencies (creates .venv)
make install
# or directly:
uv sync --all-extras
```

## Configuration

Configuration is stored in `~/.spotfm/spotfm.toml`. Start by copying the example:

```bash
cp spotfm.example.toml ~/.spotfm/spotfm.toml
```

**Required settings:**

```toml
[spotify]
client_id = "your_spotify_client_id"
client_secret = "your_spotify_client_secret"
excluded_playlists = ["Playlist Name 1", "Playlist Name 2"]
sources_playlists = ["Source Playlist 1", "Source Playlist 2"]
discover_playlist = "Discover Weekly"

[lastfm]
api_key = "your_lastfm_api_key"
api_secret = "your_lastfm_api_secret"
username = "your_username"
password_hash = "your_password_hash"
```

**OAuth tokens** are automatically cached in `~/.spotfm/spotify-token-cache`.

## Quick Start

### Spotify Commands

```bash
# Update all playlists with latest tracks
spfm spotify update-playlists

# Discover new tracks from source playlists (adds to discover_playlist)
spfm spotify discover-from-playlists

# Add tracks from a file (one per line, format: "artist - track")
spfm spotify add-tracks-from-file tracks.txt

# Count total tracks across playlists
spfm spotify count-tracks

# Find duplicate track IDs (same track in multiple playlists)
spfm spotify find-duplicate-ids
spfm spotify find-duplicate-ids -o output.csv  # Save to CSV

# Find similar track names (fuzzy matching)
spfm spotify find-duplicate-names
spfm spotify find-duplicate-names -t 90          # Adjust similarity threshold (0-100)
spfm spotify find-duplicate-names -o output.csv  # Save to CSV

# Find relinked tracks (Spotify replaces deleted tracks)
spfm spotify find-relinked-tracks
spfm spotify find-relinked-tracks -o output.csv  # Save to CSV
```

### Last.FM Commands

```bash
# Fetch recent scrobbles
spfm lastfm recent-scrobbles

# Get top tracks by period
spfm lastfm top-tracks --period month
spfm lastfm top-tracks --period year
```

## Development

### Running Tests

```bash
# Run all tests
make test

# Run specific test types
make test-unit          # Unit tests only (fast)
make test-integration   # Integration tests only

# Run with coverage report
make test-coverage      # Generates HTML report in htmlcov/

# Run in parallel (faster)
make test-parallel

# Run only failed tests
make test-failed

# Test across Python versions (3.11, 3.12, 3.13, 3.14)
make test-all-versions
```

### Code Quality

```bash
# Format code with ruff
make format

# Check for linting issues
make lint

# Auto-fix linting issues
make lint-fix
make lint-fix-unsafe    # Includes unsafe fixes

# Run all pre-commit hooks
make pre-commit
```

### Adding Dependencies

```bash
make add PACKAGE=package-name
make remove PACKAGE=package-name
```

### Build & Publish

```bash
make build              # Build distribution packages
make clean              # Remove build artifacts and .venv
make publish            # Tag release, push, and upload to PyPI
```

## Database Schema

Data is stored in SQLite at `~/.spotfm/spotify.db`. Key tables:

- `playlists` - Playlist metadata
- `tracks` - Track information with lifecycle timestamps (`created_at`, `last_seen_at`)
- `albums` - Album metadata
- `artists` - Artist metadata
- `playlists_tracks` - Many-to-many with `added_at` timestamp
- `tracks_artists`, `albums_tracks`, `albums_artists` - Relationship tables
- `artists_genres` - Genre associations

See `hacks/create-tables.sql` for full schema.

## Architecture

### Three-Tier Caching

Entities (Track, Album, Artist, Playlist) use a three-tier caching strategy:

1. **Pickle Cache** (`~/.cache/spotfm/{kind}/{id}.pickle`) - Fastest
2. **SQLite Database** (`~/.spotfm/spotify.db`) - Persistent
3. **Spotify API** - Source of truth, used as fallback

### Workflow

All entity classes follow this pattern:

```
get_entity(id, client)
  → check pickle cache
  → check SQLite database
  → fetch from Spotify API
  → update cache & database
```

### Track Lifecycle Tracking

Tracks have timestamps to prevent re-adding intentionally removed tracks:

- `created_at`: When track was first discovered (set once, immutable)
- `last_seen_at`: Last time track appeared in any playlist (updated on sync)

**Orphaned tracks** (in database but not in any playlist) accumulate and prevent re-discovery. This is intentional - they serve as a "negative cache".

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines on:
- Development workflow and branch naming
- Code style and testing requirements
- Writing commit messages
- Running quality checks
- Common tasks (adding commands, fixing bugs, etc.)

Quick start:
```bash
make install           # Setup development environment
make test              # Run tests
make check             # Full quality check (lint + tests)
git checkout -b feature/your-feature  # Create feature branch
```

## License

MIT

## Support

For issues, feature requests, or questions, please open an issue on [GitHub](https://github.com/jmlrt/spotfm/issues).
