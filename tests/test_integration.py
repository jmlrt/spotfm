"""Integration and regression tests for spotfm.

These tests verify end-to-end workflows and catch regressions in
the three-tier caching strategy (pickle cache -> SQLite -> Spotify API).
"""

import sqlite3
from unittest.mock import patch

import pytest
from freezegun import freeze_time

from spotfm import utils
from spotfm.spotify.artist import Artist
from spotfm.spotify.playlist import Playlist
from spotfm.spotify.track import Track


@pytest.mark.integration
class TestThreeTierCachingStrategy:
    """Test the three-tier caching strategy for all entities."""

    @freeze_time("2024-03-15")
    def test_artist_three_tier_caching(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Test Artist flows through all three cache tiers."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        artist_id = "integration_artist_123"

        # First fetch: Should hit API
        mock_spotify_client.artist.return_value = {
            "id": artist_id,
            "name": "Integration Artist",
            "genres": ["rock", "alternative"],
        }

        artist1 = Artist.get_artist(artist_id, mock_spotify_client)
        assert artist1.name == "Integration Artist"
        assert mock_spotify_client.artist.call_count == 1

        # Second fetch: Should hit pickle cache (no DB or API call)
        mock_spotify_client.reset_mock()
        artist2 = Artist.get_artist(artist_id)
        assert artist2.name == "Integration Artist"
        assert mock_spotify_client.artist.call_count == 0

        # Verify database has the data
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        db_artist = cursor.execute(f"SELECT name FROM artists WHERE id = '{artist_id}'").fetchone()
        conn.close()
        assert db_artist[0] == "Integration Artist"

    @freeze_time("2024-03-15")
    def test_track_with_dependencies(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Test Track properly loads Album and Artist dependencies."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        # Setup mock responses
        mock_spotify_client.track.return_value = {
            "id": "track123",
            "name": "Integration Track",
            "album": {
                "id": "album123",
                "name": "Integration Album",
            },
            "artists": [{"id": "artist123", "name": "Integration Artist"}],
        }

        mock_spotify_client.album.return_value = {
            "id": "album123",
            "name": "Integration Album",
            "release_date": "2024-01-01",
            "artists": [{"id": "artist123", "name": "Integration Artist"}],
        }

        mock_spotify_client.artist.return_value = {
            "id": "artist123",
            "name": "Integration Artist",
            "genres": ["rock"],
        }

        # Fetch track
        track = Track.get_track("track123", mock_spotify_client)

        # Verify all dependencies are loaded
        assert track.name == "Integration Track"
        assert track.album == "Integration Album"
        assert len(track.artists) == 1
        assert track.artists[0].name == "Integration Artist"
        assert track.genres == ["rock"]

        # Verify database contains all related data
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()

        track_data = cursor.execute("SELECT * FROM tracks WHERE id = 'track123'").fetchone()
        album_data = cursor.execute("SELECT * FROM albums WHERE id = 'album123'").fetchone()
        artist_data = cursor.execute("SELECT * FROM artists WHERE id = 'artist123'").fetchone()
        track_artist = cursor.execute("SELECT * FROM tracks_artists WHERE track_id = 'track123'").fetchone()
        album_track = cursor.execute("SELECT * FROM albums_tracks WHERE track_id = 'track123'").fetchone()

        conn.close()

        assert track_data is not None
        assert album_data is not None
        assert artist_data is not None
        assert track_artist is not None
        assert album_track is not None


@pytest.mark.integration
class TestDatabaseConsistency:
    """Test database consistency and integrity."""

    def test_no_orphaned_relationships(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Test that relationship tables don't create orphaned entries."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        # Create track with artist
        mock_spotify_client.track.return_value = {
            "id": "track999",
            "name": "Test Track",
            "album": {"id": "album999", "name": "Test Album"},
            "artists": [{"id": "artist999", "name": "Test Artist"}],
        }

        mock_spotify_client.album.return_value = {
            "id": "album999",
            "name": "Test Album",
            "release_date": "2024-01-01",
            "artists": [{"id": "artist999", "name": "Test Artist"}],
        }

        mock_spotify_client.artist.return_value = {
            "id": "artist999",
            "name": "Test Artist",
            "genres": ["test"],
        }

        with freeze_time("2024-03-15"):
            Track.get_track("track999", mock_spotify_client)

        # Verify all foreign keys reference existing records
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()

        # Check tracks_artists
        orphaned = cursor.execute("""
            SELECT ta.track_id, ta.artist_id
            FROM tracks_artists ta
            LEFT JOIN tracks t ON ta.track_id = t.id
            LEFT JOIN artists a ON ta.artist_id = a.id
            WHERE t.id IS NULL OR a.id IS NULL
        """).fetchall()

        # Check albums_tracks
        orphaned_albums = cursor.execute("""
            SELECT at.album_id, at.track_id
            FROM albums_tracks at
            LEFT JOIN albums a ON at.album_id = a.id
            LEFT JOIN tracks t ON at.track_id = t.id
            WHERE a.id IS NULL OR t.id IS NULL
        """).fetchall()

        conn.close()

        assert len(orphaned) == 0, f"Found orphaned track-artist relationships: {orphaned}"
        assert len(orphaned_albums) == 0, f"Found orphaned album-track relationships: {orphaned_albums}"

    def test_duplicate_prevention(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Test that INSERT OR IGNORE prevents duplicates."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        # Insert same artist twice
        mock_spotify_client.artist.return_value = {
            "id": "dup_artist",
            "name": "Duplicate Artist",
            "genres": ["rock"],
        }

        with freeze_time("2024-03-15"):
            artist1 = Artist.get_artist("dup_artist", mock_spotify_client, refresh=True)
            artist1.sync_to_db()
            artist1.sync_to_db()  # Sync again

        # Verify only one entry
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        count = cursor.execute("SELECT COUNT(*) FROM artists WHERE id = 'dup_artist'").fetchone()[0]
        genre_count = cursor.execute("SELECT COUNT(*) FROM artists_genres WHERE artist_id = 'dup_artist'").fetchone()[0]
        conn.close()

        assert count == 1
        assert genre_count == 1  # Only one "rock" genre entry


@pytest.mark.integration
class TestRefreshWorkflow:
    """Test refresh=True forces fresh API data."""

    @freeze_time("2024-03-15")
    def test_refresh_bypasses_cache(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Test that refresh=True fetches fresh data from API."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        # First fetch
        mock_spotify_client.artist.return_value = {
            "id": "refresh_test",
            "name": "Old Name",
            "genres": ["rock"],
        }

        artist1 = Artist.get_artist("refresh_test", mock_spotify_client)
        assert artist1.name == "Old Name"

        # Update mock to return new data
        mock_spotify_client.artist.return_value = {
            "id": "refresh_test",
            "name": "New Name",
            "genres": ["pop"],
        }

        # Refresh should get new data
        artist2 = Artist.get_artist("refresh_test", mock_spotify_client, refresh=True)
        assert artist2.name == "New Name"
        assert artist2.genres == ["pop"]


@pytest.mark.integration
class TestBatchOperations:
    """Test batch operations work correctly."""

    def test_get_tracks_batching(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Test Track.get_tracks properly batches requests."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        track_ids = [f"track{i}" for i in range(1, 101)]  # 100 tracks

        def mock_tracks_call(ids, market):
            return {
                "tracks": [
                    {
                        "id": tid,
                        "name": f"Track {tid}",
                        "album": {"id": f"album{tid}", "name": f"Album {tid}"},
                        "artists": [{"id": f"artist{tid}", "name": f"Artist {tid}"}],
                    }
                    for tid in ids
                ]
            }

        mock_spotify_client.tracks.side_effect = mock_tracks_call

        mock_spotify_client.album.side_effect = lambda id, market: {
            "id": id,
            "name": f"Album {id}",
            "release_date": "2024-01-01",
            "artists": [{"id": f"artist{id}", "name": f"Artist {id}"}],
        }

        mock_spotify_client.artist.side_effect = lambda id: {
            "id": id,
            "name": f"Artist {id}",
            "genres": [],
        }

        with patch("spotfm.spotify.track.sleep"):
            tracks = Track.get_tracks(track_ids, mock_spotify_client, batch_size=50)

        # Should make 2 API calls for 100 tracks with batch size 50
        assert mock_spotify_client.tracks.call_count == 2
        assert len(tracks) == 100


@pytest.mark.integration
class TestStringSanitization:
    """Regression tests for SQL injection prevention via string sanitization."""

    def test_single_quotes_removed_everywhere(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Test that single quotes are sanitized to prevent SQL injection."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        # Artist with single quotes
        mock_spotify_client.artist.return_value = {
            "id": "quote_artist",
            "name": "O'Connor's Band",
            "genres": ["rock 'n' roll"],
        }

        with freeze_time("2024-03-15"):
            artist = Artist.get_artist("quote_artist", mock_spotify_client)

        # Verify quotes are removed
        assert "'" not in artist.name
        assert "'" not in artist.genres[0]

        # Verify can be stored in database without SQL errors
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        result = cursor.execute("SELECT name FROM artists WHERE id = 'quote_artist'").fetchone()
        conn.close()

        assert result is not None
        assert "'" not in result[0]


@pytest.mark.integration
@pytest.mark.slow
class TestPlaylistWorkflow:
    """Test complete playlist workflow."""

    @freeze_time("2024-03-15")
    def test_playlist_fetch_and_analyze(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Test fetching playlist and analyzing its genres."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        # Setup playlist mock
        mock_spotify_client.playlist.return_value = {
            "id": "workflow_playlist",
            "name": "Integration Test Playlist",
            "owner": {"id": "testuser"},
        }

        mock_spotify_client.playlist_items.return_value = {
            "items": [
                {"track": {"id": "track1"}, "added_at": "2024-01-01T00:00:00Z"},
                {"track": {"id": "track2"}, "added_at": "2024-01-02T00:00:00Z"},
            ],
            "next": None,
        }

        # Setup tracks mock
        mock_spotify_client.tracks.return_value = {
            "tracks": [
                {
                    "id": "track1",
                    "name": "Rock Song",
                    "album": {"id": "album1", "name": "Album 1"},
                    "artists": [{"id": "artist1", "name": "Rock Artist"}],
                },
                {
                    "id": "track2",
                    "name": "Pop Song",
                    "album": {"id": "album2", "name": "Album 2"},
                    "artists": [{"id": "artist2", "name": "Pop Artist"}],
                },
            ]
        }

        # Setup albums and artists
        mock_spotify_client.album.side_effect = [
            {
                "id": "album1",
                "name": "Album 1",
                "release_date": "2024-01-01",
                "artists": [{"id": "artist1", "name": "Rock Artist"}],
            },
            {
                "id": "album2",
                "name": "Album 2",
                "release_date": "2024-01-01",
                "artists": [{"id": "artist2", "name": "Pop Artist"}],
            },
        ]

        mock_spotify_client.artist.side_effect = [
            {"id": "artist1", "name": "Rock Artist", "genres": ["rock", "alternative"]},
            {"id": "artist2", "name": "Pop Artist", "genres": ["pop", "electronic"]},
        ]

        # Fetch playlist
        with patch("spotfm.spotify.track.sleep"):
            playlist = Playlist.get_playlist("workflow_playlist", mock_spotify_client, sync_to_db=False)

        # Verify playlist structure
        assert playlist.name == "Integration Test Playlist"
        assert len(playlist.tracks) == 2

        # Get genre distribution
        genres = playlist.get_playlist_genres()
        assert "rock" in genres
        assert "pop" in genres
        assert "alternative" in genres
        assert "electronic" in genres


@pytest.mark.integration
class TestErrorHandling:
    """Test error handling and edge cases."""

    def test_missing_track_in_batch(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Test that missing tracks (None) are handled gracefully."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        track_ids = ["valid1", "invalid", "valid2"]

        mock_spotify_client.tracks.return_value = {
            "tracks": [
                {
                    "id": "valid1",
                    "name": "Valid Track 1",
                    "album": {"id": "album1", "name": "Album 1"},
                    "artists": [{"id": "artist1", "name": "Artist 1"}],
                },
                None,  # Invalid/deleted track
                {
                    "id": "valid2",
                    "name": "Valid Track 2",
                    "album": {"id": "album2", "name": "Album 2"},
                    "artists": [{"id": "artist2", "name": "Artist 2"}],
                },
            ]
        }

        mock_spotify_client.album.side_effect = [
            {
                "id": "album1",
                "name": "Album 1",
                "release_date": "2024-01-01",
                "artists": [{"id": "artist1", "name": "Artist 1"}],
            },
            {
                "id": "album2",
                "name": "Album 2",
                "release_date": "2024-01-01",
                "artists": [{"id": "artist2", "name": "Artist 2"}],
            },
        ]

        mock_spotify_client.artist.side_effect = [
            {"id": "artist1", "name": "Artist 1", "genres": []},
            {"id": "artist2", "name": "Artist 2", "genres": []},
        ]

        with patch("spotfm.spotify.track.sleep"):
            tracks = Track.get_tracks(track_ids, mock_spotify_client)

        # Should return only valid tracks
        assert len(tracks) == 2
        assert tracks[0].name == "Valid Track 1"
        assert tracks[1].name == "Valid Track 2"

    def test_empty_playlist(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Test handling of empty playlist."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        mock_spotify_client.playlist.return_value = {
            "id": "empty_playlist",
            "name": "Empty Playlist",
            "owner": {"id": "user"},
        }

        mock_spotify_client.playlist_items.return_value = {
            "items": [],
            "next": None,
        }

        with freeze_time("2024-03-15"):
            playlist = Playlist.get_playlist("empty_playlist", mock_spotify_client, sync_to_db=False)

        assert playlist.name == "Empty Playlist"
        assert len(playlist.raw_tracks) == 0
