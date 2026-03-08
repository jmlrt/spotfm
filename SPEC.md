# spotfm Specification

**This document is the source of truth for spotfm's architecture, design decisions, and features.**

Last updated: 2026-03-08

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Core Architecture](#core-architecture)
3. [Data Model](#data-model)
4. [Caching Strategy](#caching-strategy)
5. [Entity Lifecycle](#entity-lifecycle)
6. [Features & Commands](#features--commands)
7. [Critical Design Decisions](#critical-design-decisions)
8. [Testing Strategy](#testing-strategy)
9. [Future Enhancements](#future-enhancements)

---

## Project Overview

**spotfm** is a Python library and CLI tool for interacting with Spotify and Last.FM APIs. It enables users to:

- Manage Spotify playlists
- Discover new tracks from existing playlists
- Find duplicate tracks (by ID or similarity)
- Analyze music library with offline database queries
- Track listening history from Last.FM

### Philosophy

- **Offline-first**: Data syncs to local SQLite for querying without API calls
- **Smart caching**: Three-tier caching reduces API usage and improves performance
- **Lifecycle tracking**: Tracks maintain timestamps to enable intelligent discovery
- **Intentional deletion**: Tracks intentionally removed are never re-discovered

### Technologies

- **Language**: Python 3.14+ (PEP 758 bracketless exception syntax)
- **APIs**: Spotify Web API (spotipy), Last.FM API (pylast)
- **Database**: SQLite with lifecycle tracking
- **Caching**: Pickle files for individual entities
- **Testing**: pytest with 240+ tests, ≥90% coverage target
- **Build**: uv (fast Python package manager), hatchling (build backend)

---

## Core Architecture

### Module Organization

```
spotfm/
├── cli.py              # CLI entry point, argument parsing
├── lastfm.py           # Last.FM client, Track, User classes
├── spotify/
│   ├── client.py       # Spotify API wrapper, playlist filtering
│   ├── track.py        # Track entity with lifecycle tracking
│   ├── album.py        # Album entity with relationships
│   ├── artist.py       # Artist entity with genres
│   ├── playlist.py     # Playlist entity with batch operations
│   ├── dupes.py        # Duplicate detection (ID, fuzzy match)
│   ├── misc.py         # High-level commands (discover, add, count)
│   └── constants.py    # BATCH_SIZE, MARKET, etc.
├── sqlite.py           # SQLite singleton connection, schema migrations
└── utils.py            # Config parsing, caching, string sanitization
```

### Key Design Principles

1. **Separation of Concerns**: CLI logic separate from business logic
2. **Entity Pattern**: All Spotify entities follow identical lifecycle pattern
3. **Caching Hierarchy**: Multiple cache levels reduce API calls
4. **Singleton Connection**: Single persistent SQLite connection for performance
5. **Idempotent Operations**: Safe to run commands multiple times
6. **Rate Limiting**: Sleep calls protect against Spotify 429 errors

---

## Data Model

### Core Entities

#### Track
- `id`: Spotify track ID (primary key)
- `name`: Track title
- `album_id`: Reference to Album
- `artists_id`: List of Artist IDs (many-to-many)
- `release_date`: Album release date
- `updated_at`: Last API update timestamp
- `created_at`: First discovery timestamp (immutable)
- `last_seen_at`: Last appearance in any playlist (updated on sync)
- `genres`: Aggregated from artists (not stored, computed)

#### Album
- `id`: Spotify album ID (primary key)
- `name`: Album title
- `release_date`: Release date
- `artists_id`: List of Artist IDs
- `updated_at`: Last API update timestamp

#### Artist
- `id`: Spotify artist ID (primary key)
- `name`: Artist name
- `genres`: List of genres
- `updated_at`: Last API update timestamp

#### Playlist
- `id`: Spotify playlist ID (primary key)
- `name`: Playlist name
- `owner`: Playlist owner ID
- `snapshot_id`: Spotify snapshot ID for change detection
- `updated_at`: Last API update timestamp

### Relationship Tables

- `playlists_tracks`: Many-to-many with `added_at` timestamp
- `tracks_artists`: Links tracks to artists
- `albums_tracks`: Links albums to tracks
- `albums_artists`: Links albums to artists
- `artists_genres`: Links artists to genres (many genres per artist)

---

## Caching Strategy

spotfm implements **three-tier caching** to minimize API calls:

### Tier 1: Pickle Cache
- **Location**: `~/.cache/spotfm/{kind}/{id}.pickle`
- **Speed**: Fastest (file I/O only)
- **Scope**: Individual entities only
- **Lifetime**: Persistent across sessions

### Tier 2: SQLite Database
- **Location**: `~/.spotfm/spotify.db`
- **Speed**: Fast (local queries)
- **Scope**: All entities and relationships
- **Lifetime**: Persistent across sessions
- **Benefit**: Offline querying, relationship navigation

### Tier 3: Spotify API
- **Speed**: Slow (network latency + rate limiting)
- **Rate limit**: ~10 requests/second
- **Sleep pattern**:
  - Track fetches via `Track.get_tracks()`: 0.1s between individual track API calls
  - Album fetches via `Album.get_albums()`: 0.05s between album API calls
  - Artist fetches via `Artist.get_artists()`: 0.05s between artist API calls
  - Note: Spotify removed batch endpoints (Feb 2026); all fetches now use individual endpoints
  - Proactive rate limiting prevents 429 Too Many Requests errors
- **Fallback**: Used when data not in Tier 1 or 2, or `refresh=True`

### Cache Hit Order

```
get_track(id, client)
  ↓ (1) Check pickle cache
  ├─ Hit: return cached track
  ├─ Miss: (2) Check SQLite database
  │    ├─ Hit: load from DB, write to pickle, return
  │    └─ Miss: (3) Fetch from Spotify API
  │         ├─ Update cache and DB
  │         └─ Return fresh track
```

---

## Entity Lifecycle

All entities (Track, Album, Artist, Playlist) follow this lifecycle:

### 1. Entry Point: `get_{entity}(id, client, refresh=False, sync_to_db=True)`

```python
from spotfm.spotify.track import Track

track = Track.get_track("spotify:track:123", client)
```

**Parameters:**
- `id`: Spotify ID or full URI
- `client`: Spotipy client instance
- `refresh`: Force fetch from API (skip cache)
- `sync_to_db`: Save to database after loading

### 2. Loading Phase

a. **Cache load via `utils.retrieve_object_from_cache(kind, id)`**: Load from pickle file
   - If exists and not stale: return early

b. **`update_from_db(client)`**: Load from SQLite
   - If exists: populate from database, write pickle, return

c. **`update_from_api(client)`**: Fetch from Spotify API
   - Make API call with rate limiting
   - Populate all attributes
   - Load related entities (recursive calls to get_album, get_artists)

### 3. Persistence: `sync_to_db()`

- Save entity to SQLite
- Insert/update relationships (album, artists, genres)
- Update `updated_at` timestamp
- Set `created_at` on first insert (immutable)
- Update `last_seen_at` on every sync

---

## Orphaned Tracks & Track Lifecycle

### Orphaned Tracks (CRITICAL)

**Definition**: Tracks in the `tracks` table but not in any playlist (zero rows in `playlists_tracks`)

**Purpose**: Serve as a "negative cache" to prevent re-discovering intentionally removed tracks

**Behavior**: `discover_from_playlists` skips orphaned tracks

**Lifecycle**:
1. User adds track to playlist → created in database
2. User removes track from playlist → becomes orphaned
3. `discover_from_playlists` runs → skips orphaned track
4. Track accumulates in database (never deleted)
5. If user re-adds track to new playlist → `last_seen_at` updates

**Why never delete orphaned tracks**:
- User intentionally removed the track → don't re-discover
- Deleting would cause re-discovery on next run → user frustration
- Tracks not seen in 90+ days could be cleaned with explicit opt-in

### Track Lifecycle Timestamps

- **`created_at`**: Set on first discovery, never changes (immutable)
- **`last_seen_at`**: Updated every time track appears in a playlist
- **Purpose**: Enable intelligent discovery and optional cleanup

---

## Features & Commands

### Spotify Commands

#### `update-playlists`
**Purpose**: Sync all configured playlists from Spotify to local database

**Behavior**:
1. Fetch all playlists from Spotify
2. For each playlist: fetch all tracks via paginated API calls
3. Create/update Track, Album, Artist entities
4. Update `playlists_tracks` relationships with `added_at` timestamps
5. Log progress and summary

**Rate limiting**: 0.1s between individual track API calls (Spotify batch endpoints removed Feb 2026)

**Example**:
```bash
spfm spotify update-playlists
```

#### `discover-from-playlists`
**Purpose**: Find new tracks in source playlists and add to discover playlist

**Algorithm**:
1. Load all tracks from source playlists
2. Create Track objects (cache hits → skip API calls)
3. Query database for orphaned tracks
4. Filter: new tracks = source tracks - database tracks - orphaned tracks
5. Add filtered tracks to destination playlist
6. Sync destination playlist to database

**Orphaned Track Handling**:
- Skip any track that exists in `tracks` table but no playlists
- Preserves user's intentional removals

**Example**:
```bash
spfm spotify discover-from-playlists
```

#### `find-duplicate-ids`
**Purpose**: Find tracks appearing in multiple playlists (exact ID match)

**Implementation**:
- Query database only (no API calls)
- GROUP BY track_id, find where count(playlists) > 1
- Support CSV export and console output

**Example**:
```bash
spfm spotify find-duplicate-ids
spfm spotify find-duplicate-ids -o dupes.csv
```

#### `find-duplicate-names`
**Purpose**: Find similar tracks using fuzzy string matching

**Implementation**:
- Query all tracks from database
- Use rapidfuzz with 4 algorithms: ratio, partial_ratio, token_sort_ratio, token_set_ratio
- Configurable similarity threshold (0-100, default 95)
- Support CSV export

**Example**:
```bash
spfm spotify find-duplicate-names -t 90
spfm spotify find-duplicate-names -o similar.csv
```

#### `find-relinked-tracks`
**Purpose**: Find tracks that Spotify replaced (relinked due to artist merges, etc.)

**Implementation**:
- Query tracks with relink information from Spotify API
- Export to CSV with original and new track IDs

### Last.FM Commands

#### `recent-scrobbles`
**Purpose**: Fetch recent listening history from Last.FM with automatic state tracking

**State Tracking Behavior**:
- **First run**: Initializes state file (`~/.spotfm/lastfm_state.json`) with current playcount, fetches up to `--limit` scrobbles
- **Subsequent runs**: Fetches ALL new scrobbles since last run (ignores `--limit`), auto-updates state
- **State file**: Stores `last_scrobble_count` and `last_run_date` for tracking
- **Error handling**: If fetch fails, state is not advanced (safe rollback)

**Parameters**:
- `-l, --limit`: Scrobbles to fetch on first run (default: 50; ignored on subsequent runs)
- `-s, --scrobbles-minimum`: Minimum total scrobbles to include (default: 4, configurable via `spotfm.toml`)
- `-p, --period`: Period in days to count scrobbles within (default: 90)
- `--period-minimum`: Minimum scrobbles required in period window (default: unset = no filter; configurable via `spotfm.toml`)
- `-i, --interactive`: Open results in `$EDITOR` with automatic deduplication (default: false)

**Config Defaults** (optional in `spotfm.toml`):
```toml
[lastfm]
scrobbles_minimum = 2   # Minimum total scrobbles (default: 4)
```

**Output**: Deduplicated list of tracks with format: `Artist - Title - period_scrobbles - total_scrobbles - url`

**Examples**:
```bash
# Basic: Initialize state and fetch 50 scrobbles
spfm lastfm recent-scrobbles

# First run with custom limit
spfm lastfm recent-scrobbles -l 100

# Subsequent runs: Automatically fetches all new scrobbles
spfm lastfm recent-scrobbles

# Filter by minimum scrobbles in period
spfm lastfm recent-scrobbles --period-minimum 2

# Interactive mode with deduplication in editor
spfm lastfm recent-scrobbles -i

# Combine filters: total ≥2 AND period ≥2
spfm lastfm recent-scrobbles -s 2 --period-minimum 2

# With config defaults, interactive mode
spfm lastfm recent-scrobbles -i
```

---

## Critical Design Decisions

### 1. Orphaned Tracks as Negative Cache

**Decision**: Keep deleted tracks in database, skip them in discovery

**Rationale**:
- User removes track intentionally
- Next discovery run should not re-add it
- Prevents "why does this keep coming back?" frustration
- One-way flow: discovery adds, user removes, discovery respects removal

**Alternative Considered**: Delete tracks from database
- ❌ Would cause re-discovery of removed tracks
- ❌ Loses information about what user removed
- ❌ No way to prevent repeated re-adding

### 2. Three-Tier Caching

**Decision**: Pickle + SQLite + API hierarchy

**Rationale**:
- Pickle: Fast for single-entity lookups
- SQLite: Fast for complex queries and offline use
- API: Authoritative source, used as last resort

**Alternative Considered**: Only API calls with in-memory cache
- ❌ No offline querying capability
- ❌ Requires API calls for every operation
- ❌ Slow for large playlists

### 3. Singleton Database Connection

**Decision**: Global module-level SQLite connection, reused by all code

**Rationale**:
- SQLite file-based mode is single-writer, thread-limited
- Persistent connection reduces overhead
- Automatic cleanup via atexit handler

**Alternative Considered**: Connection pool
- ❌ SQLite doesn't benefit from pooling (file-based)
- ❌ More complexity
- ❌ Concurrent writes still blocked

### 4. String Sanitization for SQL Safety

**Decision**: Remove single quotes from all user-facing strings before SQL interpolation

**Rationale**:
- Using f-strings in SQL (TODO: migrate to parameterized)
- Need defense-in-depth until parameterized queries implemented
- Sanitize at CLI boundary

**Example**:
```python
from spotfm.utils import sanitize_string

playlist_name = sanitize_string(user_input)  # Removes single quotes
```

### 5. Rate Limiting via Sleep Calls

**Decision**: Strategic sleep() calls to prevent Spotify 429 errors

**Locations**:
- 0.1s between individual track API calls (track.py)
- 0.05s between individual album/artist API calls (album.py, artist.py)

**Rationale**:
- Spotify rate limit: ~10 requests/second
- Proactive sleep prevents 429 Too Many Requests errors
- Individual endpoints (Spotify removed batch endpoints Feb 2026)
- No retries configured (client uses retries=0); sleep is the primary strategy

**Do not remove** without understanding impact.

---

## Testing Strategy

### Test Organization

Tests are organized by type and marked accordingly:

- `@pytest.mark.unit`: Fast unit tests, no I/O
- `@pytest.mark.integration`: Integration tests using temp databases
- `@pytest.mark.slow`: Long-running tests

### Database Isolation (CRITICAL)

All tests MUST use temporary databases:

```python
def test_track_sync(self, temp_database, temp_cache_dir, monkeypatch):
    monkeypatch.setattr(utils, "DATABASE", temp_database)
    monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)
    # Now test uses temp database, not ~/.spotfm/spotify.db
```

### Fixtures

**conftest.py** provides:
- `temp_database`: Fresh SQLite with complete schema
- `temp_cache_dir`: Temporary cache directory
- `mock_spotify_client`: Mock Spotipy client with sample responses
- `sample_*_data`: Sample entity data for testing
- `reset_module_state`: Auto-run cleanup (clears global caches)

### Coverage Requirements

- **Target**: ≥90% coverage on modified code
- **Measurement**: Branch coverage (lines + branches)
- **Enforcement**: Pre-commit validation

### CI/CD

GitHub Actions runs on all PRs:
- Python 3.14 (only supported version)
- Multiple platforms (Ubuntu, macOS)
- Full test suite

---

## Future Enhancements

See [TODO.md](TODO.md) for detailed specifications:

### Planned Features (Priority Order)

1. **Logging Improvements** (HIGH)
   - Better progress output during long operations
   - Summary results (e.g., "discovered 12 new tracks from Indie Mix")
   - Less noise in standard output mode

2. **Duplicate Detection Improvements** (MEDIUM)
   - Smart suffix parsing (ignore "- 2011 remaster", "- Nouvelle Ecole")
   - Better track core comparison

3. **Random Playlist Generator** (LOW)
   - Command: `spfm spotify random-playlist <size>`
   - Config: `random_exclude_playlists`, `random_history_runs`
   - Tracks selection without replacement
   - Implementation effort: ~1-2 hours

4. **CHANGELOG Automation** (LOW)
   - Auto-generate release notes from commits
   - Maintain CHANGELOG.md format

---

## References

- **User Documentation**: [README.md](README.md)
- **Contributing Guide**: [CONTRIBUTING.md](CONTRIBUTING.md)
- **Agent Guidance**: [CLAUDE.md](CLAUDE.md)
- **Roadmap**: [TODO.md](TODO.md)
- **Release Notes**: [CHANGELOG.md](CHANGELOG.md)

---

**Last Updated**: 2026-03-08
**Maintainer**: @jmlrt
