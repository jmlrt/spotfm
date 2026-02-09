"""Shared pytest fixtures and configuration for spotfm tests."""

import sqlite3
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def temp_dir(tmp_path):
    """Provide a temporary directory for test files."""
    return tmp_path


@pytest.fixture
def temp_database(tmp_path):
    """Create a temporary SQLite database for testing."""
    db_path = tmp_path / "test_spotify.db"

    # Ensure parent directory exists (defensive programming for CI)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Convert to string for sqlite3 compatibility across all platforms
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Create minimal schema for testing
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS tracks (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            created_at TEXT,
            last_seen_at TEXT
        );

        CREATE TABLE IF NOT EXISTS artists (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS artists_genres (
            artist_id TEXT NOT NULL,
            genre TEXT NOT NULL,
            PRIMARY KEY (artist_id, genre),
            FOREIGN KEY (artist_id) REFERENCES artists(id)
        );

        CREATE TABLE IF NOT EXISTS albums (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            release_date TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS playlists (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            owner TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tracks_artists (
            track_id TEXT NOT NULL,
            artist_id TEXT NOT NULL,
            PRIMARY KEY (track_id, artist_id),
            FOREIGN KEY (track_id) REFERENCES tracks(id),
            FOREIGN KEY (artist_id) REFERENCES artists(id)
        );

        CREATE TABLE IF NOT EXISTS albums_tracks (
            album_id TEXT NOT NULL,
            track_id TEXT NOT NULL,
            PRIMARY KEY (album_id, track_id),
            FOREIGN KEY (album_id) REFERENCES albums(id),
            FOREIGN KEY (track_id) REFERENCES tracks(id)
        );

        CREATE TABLE IF NOT EXISTS albums_artists (
            album_id TEXT NOT NULL,
            artist_id TEXT NOT NULL,
            PRIMARY KEY (album_id, artist_id),
            FOREIGN KEY (album_id) REFERENCES albums(id),
            FOREIGN KEY (artist_id) REFERENCES artists(id)
        );

        CREATE TABLE IF NOT EXISTS playlists_tracks (
            playlist_id TEXT NOT NULL,
            track_id TEXT NOT NULL,
            added_at TEXT NOT NULL,
            PRIMARY KEY (playlist_id, track_id),
            FOREIGN KEY (playlist_id) REFERENCES playlists(id),
            FOREIGN KEY (track_id) REFERENCES tracks(id)
        );
    """)

    conn.commit()
    conn.close()

    # Return Path object to match utils.DATABASE type
    return db_path


@pytest.fixture
def temp_cache_dir(tmp_path):
    """Create a temporary cache directory structure."""
    cache_dir = tmp_path / ".cache" / "spotfm"
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Create subdirectories for different object types
    for kind in ["track", "artist", "album", "playlist"]:
        (cache_dir / kind).mkdir(parents=True, exist_ok=True)

    return cache_dir


@pytest.fixture
def temp_config_file(tmp_path):
    """Create a temporary config file for testing."""
    config_dir = tmp_path / ".spotfm"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "spotfm.toml"

    config_content = """
[spotify]
client_id = "test_client_id"
client_secret = "test_client_secret"
excluded_playlists = ["playlist1", "playlist2"]
sources_playlists = ["source1", "source2"]
discover_playlist = "discover_id"

[lastfm]
api_key = "test_api_key"
api_secret = "test_api_secret"
username = "test_user"
password_hash = "test_hash"
"""
    config_file.write_text(config_content)
    return config_file


@pytest.fixture
def mock_spotify_client():
    """Create a mock Spotify client for testing."""
    client = MagicMock()

    # Mock common API responses
    client.artist.return_value = {
        "id": "artist123",
        "name": "Test Artist",
        "genres": ["rock", "alternative"],
    }

    client.album.return_value = {
        "id": "album123",
        "name": "Test Album",
        "release_date": "2024-01-01",
        "artists": [{"id": "artist123", "name": "Test Artist"}],
    }

    client.track.return_value = {
        "id": "track123",
        "name": "Test Track",
        "album": {
            "id": "album123",
            "name": "Test Album",
        },
        "artists": [{"id": "artist123", "name": "Test Artist"}],
    }

    client.tracks.return_value = {
        "tracks": [
            {
                "id": "track123",
                "name": "Test Track",
                "album": {
                    "id": "album123",
                    "name": "Test Album",
                },
                "artists": [{"id": "artist123", "name": "Test Artist"}],
            }
        ]
    }

    client.playlist.return_value = {
        "id": "playlist123",
        "name": "Test Playlist",
        "owner": {"id": "user123"},
    }

    client.playlist_items.return_value = {
        "items": [
            {
                "track": {"id": "track123"},
                "added_at": "2024-01-01T00:00:00Z",
            }
        ],
        "next": None,
    }

    return client


@pytest.fixture
def sample_artist_data():
    """Provide sample artist data for testing."""
    return {
        "id": "artist123",
        "name": "The Beatles",
        "genres": ["rock", "pop", "british invasion"],
    }


@pytest.fixture
def sample_album_data():
    """Provide sample album data for testing."""
    return {
        "id": "album123",
        "name": "Abbey Road",
        "release_date": "1969-09-26",
        "artists": [{"id": "artist123", "name": "The Beatles"}],
    }


@pytest.fixture
def sample_track_data():
    """Provide sample track data for testing."""
    return {
        "id": "track123",
        "name": "Come Together",
        "album": {
            "id": "album123",
            "name": "Abbey Road",
        },
        "artists": [{"id": "artist123", "name": "The Beatles"}],
    }


@pytest.fixture
def sample_playlist_data():
    """Provide sample playlist data for testing."""
    return {
        "id": "playlist123",
        "name": "Rock Classics",
        "owner": {"id": "user123"},
    }


@pytest.fixture(autouse=True)
def reset_module_state():
    """Reset module-level state between tests."""
    # This fixture runs automatically before each test
    # Clean up any module-level caches or connections
    from spotfm import sqlite as db_module

    # Close connection before and after each test to ensure clean state
    db_module.close_db_connection()
    # Clear migrated databases set to allow migration to run on fresh test databases
    db_module.reset_migration_state_for_tests()
    yield
    # Cleanup after test runs - close the global database connection
    db_module.close_db_connection()
    # Clear migrated databases set after test
    db_module.reset_migration_state_for_tests()
