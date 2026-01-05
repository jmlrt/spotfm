# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

spotfm is a Python library and CLI tool for interacting with Spotify and Last.FM APIs. It focuses on playlist management, track discovery, and music library analytics. The tool syncs data to a local SQLite database for offline querying and analysis.

## Development Commands

### Setup
```bash
make install          # Create venv, install package in editable mode with dev dependencies
```

### Code Quality
```bash
make pre-commit      # Run all pre-commit hooks (isort, black, flake8, pyupgrade, etc.)
pre-commit run --all-files
```

### Build and Publish
```bash
make build           # Build distribution packages
make clean           # Remove build artifacts, venv, and cache files
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

## Code Style

- **Python**: 3.11+ (uses match/case statements)
- **Formatting**: black (120 char line length), isort (black profile)
- **Linting**: flake8, pyupgrade (--py311-plus)
- Pre-commit hooks enforce all style rules automatically

## Testing

The `tests/` directory exists but is currently empty. When adding tests, use pytest (not currently in dev dependencies).
