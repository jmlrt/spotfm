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
        """Test Track.get_tracks makes individual API calls."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        track_ids = [f"track{i}" for i in range(1, 101)]  # 100 tracks

        mock_spotify_client.track.side_effect = lambda id, market: {
            "id": id,
            "name": f"Track {id}",
            "album": {"id": f"album{id}", "name": f"Album {id}"},
            "artists": [{"id": f"artist{id}", "name": f"Artist {id}"}],
        }

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
            tracks = Track.get_tracks(track_ids, mock_spotify_client)

        # Should make 100 individual API calls (batch endpoints removed)
        assert mock_spotify_client.track.call_count == 100
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

        # Setup individual track mock
        def mock_track_response(id, market):
            tracks = {
                "track1": {
                    "id": "track1",
                    "name": "Rock Song",
                    "album": {"id": "album1", "name": "Album 1"},
                    "artists": [{"id": "artist1", "name": "Rock Artist"}],
                },
                "track2": {
                    "id": "track2",
                    "name": "Pop Song",
                    "album": {"id": "album2", "name": "Album 2"},
                    "artists": [{"id": "artist2", "name": "Pop Artist"}],
                },
            }
            return tracks.get(id)

        mock_spotify_client.track.side_effect = mock_track_response

        # Setup individual albums API
        def mock_album_response(id, market):
            albums = {
                "album1": {
                    "id": "album1",
                    "name": "Album 1",
                    "release_date": "2024-01-01",
                    "artists": [{"id": "artist1", "name": "Rock Artist"}],
                },
                "album2": {
                    "id": "album2",
                    "name": "Album 2",
                    "release_date": "2024-01-01",
                    "artists": [{"id": "artist2", "name": "Pop Artist"}],
                },
            }
            return albums.get(id)

        mock_spotify_client.album.side_effect = mock_album_response

        # Setup individual artists API
        def mock_artist_response(id):
            artists = {
                "artist1": {"id": "artist1", "name": "Rock Artist", "genres": ["rock", "alternative"]},
                "artist2": {"id": "artist2", "name": "Pop Artist", "genres": ["pop", "electronic"]},
            }
            return artists.get(id)

        mock_spotify_client.artist.side_effect = mock_artist_response

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

        # Setup individual track mock - invalid raises KeyError (expected for unavailable)
        def mock_track_response(id, market):
            if id == "invalid":
                raise KeyError("Track not found")
            tracks = {
                "valid1": {
                    "id": "valid1",
                    "name": "Valid Track 1",
                    "album": {"id": "album1", "name": "Album 1"},
                    "artists": [{"id": "artist1", "name": "Artist 1"}],
                },
                "valid2": {
                    "id": "valid2",
                    "name": "Valid Track 2",
                    "album": {"id": "album2", "name": "Album 2"},
                    "artists": [{"id": "artist2", "name": "Artist 2"}],
                },
            }
            return tracks.get(id)

        mock_spotify_client.track.side_effect = mock_track_response

        # Setup individual album mock
        def mock_album_response(id, market):
            albums = {
                "album1": {
                    "id": "album1",
                    "name": "Album 1",
                    "release_date": "2024-01-01",
                    "artists": [{"id": "artist1", "name": "Artist 1"}],
                },
                "album2": {
                    "id": "album2",
                    "name": "Album 2",
                    "release_date": "2024-01-01",
                    "artists": [{"id": "artist2", "name": "Artist 2"}],
                },
            }
            return albums.get(id)

        mock_spotify_client.album.side_effect = mock_album_response

        # Setup individual artist mock
        def mock_artist_response(id):
            artists = {
                "artist1": {"id": "artist1", "name": "Artist 1", "genres": []},
                "artist2": {"id": "artist2", "name": "Artist 2", "genres": []},
            }
            return artists.get(id)

        mock_spotify_client.artist.side_effect = mock_artist_response

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
        assert len(playlist.tracks) == 0


@pytest.mark.integration
class TestDiscoverFromPlaylists:
    """Integration tests for discover_from_playlists.

    Tests verify the complete discover workflow and catch regressions, particularly
    the pre-sync bug where Track.get_tracks() inside Playlist.update_from_api()
    would sync new tracks to the DB before discover_from_playlists could check
    if they were truly new — causing them to be treated as orphaned and skipped.
    """

    SOURCE_PL_ID = "source_pl"
    DEST_PL_ID = "dest_pl"

    def _configure_client(self, client, source_track_ids, dest_track_ids=None):
        """Set up mock Spotify client responses for discover tests."""
        if dest_track_ids is None:
            dest_track_ids = []

        def playlist_side_effect(id, fields=None, market=None):
            name = "Discover Dest" if id == self.DEST_PL_ID else "Discover Source"
            return {"id": id, "name": name, "owner": {"id": "testuser"}, "snapshot_id": f"snap_{id}"}

        def playlist_items_side_effect(id, fields=None, market=None, additional_types=None):
            track_ids = dest_track_ids if id == self.DEST_PL_ID else source_track_ids
            return {
                "items": [{"track": {"id": tid}, "added_at": "2024-01-01T00:00:00Z"} for tid in track_ids],
                "next": None,
            }

        def track_side_effect(id, market=None):
            return {
                "id": id,
                "name": f"Track {id}",
                "album": {"id": f"alb_{id}", "name": f"Album {id}"},
                "artists": [{"id": f"art_{id}", "name": f"Artist {id}"}],
            }

        def album_side_effect(id, market=None):
            artist_id = id.replace("alb_", "art_")
            return {"id": id, "name": f"Album {id}", "release_date": "2024-01-01", "artists": [{"id": artist_id}]}

        def artist_side_effect(id):
            return {"id": id, "name": f"Artist {id}", "genres": ["pop"]}

        client.playlist.side_effect = playlist_side_effect
        client.playlist_items.side_effect = playlist_items_side_effect
        client.track.side_effect = track_side_effect
        client.album.side_effect = album_side_effect
        client.artist.side_effect = artist_side_effect

    @freeze_time("2024-03-15")
    def test_new_track_is_discovered_and_added(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Regression test: tracks not in DB are discovered and added to the destination playlist.

        This test catches the pre-sync bug where Playlist.update_from_api() called
        Track.get_tracks() which synced new tracks to the tracks table before
        discover_from_playlists could check if they were truly new. Because the
        tracks were in the DB (but not in playlists_tracks), is_orphaned() returned
        True and they were silently skipped instead of being added to discover dest.

        With the fix, Track.get_tracks() is called with sync_to_db=False during
        update_from_api(), so new tracks are NOT pre-synced. discover_from_playlists
        detects them via the in_db_before pre-check and correctly adds them.
        """
        import sqlite3 as _sqlite3
        from unittest.mock import MagicMock, patch

        from spotfm.spotify.misc import discover_from_playlists

        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)
        self._configure_client(mock_spotify_client, source_track_ids=["new_track"])

        client_wrapper = MagicMock()
        client_wrapper.client = mock_spotify_client

        with (
            patch("spotfm.spotify.track.sleep"),
            patch("spotfm.spotify.album.sleep"),
            patch("spotfm.spotify.artist.sleep"),
        ):
            discover_from_playlists(client_wrapper, self.DEST_PL_ID, [self.SOURCE_PL_ID])

        # The new track must have been submitted to the Spotify API for addition
        mock_spotify_client.playlist_add_items.assert_called_once()
        dest_id, added_ids = mock_spotify_client.playlist_add_items.call_args[0]
        assert dest_id == self.DEST_PL_ID
        assert "new_track" in added_ids

        # The track must also be persisted to the local DB after discovery
        conn = _sqlite3.connect(temp_database)
        track_in_db = conn.execute("SELECT id FROM tracks WHERE id = 'new_track'").fetchone()
        conn.close()
        assert track_in_db is not None, "Discovered track must be synced to DB"

    @freeze_time("2024-03-15")
    def test_orphaned_track_is_not_readded(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Orphaned tracks (in DB but not in any playlists_tracks) must not be re-added.

        This is the negative-cache feature: tracks previously removed from all
        playlists are kept in the DB as orphans so discover skips them,
        preventing re-discovery of intentionally rejected tracks.
        """
        import sqlite3 as _sqlite3
        from unittest.mock import MagicMock, patch

        from spotfm.spotify.misc import discover_from_playlists

        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        # Pre-seed DB: track exists but has NO playlists_tracks entry (orphaned)
        conn = _sqlite3.connect(temp_database)
        conn.execute("INSERT INTO artists VALUES ('art_orphan', 'Orphan Artist', '2024-01-01')")
        conn.execute("INSERT INTO albums VALUES ('alb_orphan', 'Orphan Album', '2024-01-01', '2024-01-01')")
        conn.execute(
            "INSERT INTO tracks VALUES ('orphan_track', 'Orphan Track', '2024-01-01', '2024-01-01', '2024-01-01')"
        )
        conn.execute("INSERT INTO albums_tracks VALUES ('alb_orphan', 'orphan_track')")
        conn.execute("INSERT INTO tracks_artists VALUES ('orphan_track', 'art_orphan')")
        conn.commit()
        conn.close()

        self._configure_client(mock_spotify_client, source_track_ids=["orphan_track"])

        client_wrapper = MagicMock()
        client_wrapper.client = mock_spotify_client

        with (
            patch("spotfm.spotify.track.sleep"),
            patch("spotfm.spotify.album.sleep"),
            patch("spotfm.spotify.artist.sleep"),
        ):
            discover_from_playlists(client_wrapper, self.DEST_PL_ID, [self.SOURCE_PL_ID])

        mock_spotify_client.playlist_add_items.assert_not_called()

    @freeze_time("2024-03-15")
    def test_track_in_managed_playlist_is_skipped(
        self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client
    ):
        """Tracks already in a managed playlist must not be added to the discover destination."""
        import sqlite3 as _sqlite3
        from unittest.mock import MagicMock, patch

        from spotfm.spotify.misc import discover_from_playlists

        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        # Pre-seed DB: track exists AND is in a managed playlist
        conn = _sqlite3.connect(temp_database)
        conn.execute("INSERT INTO artists VALUES ('art_existing', 'Existing Artist', '2024-01-01')")
        conn.execute("INSERT INTO albums VALUES ('alb_existing', 'Existing Album', '2024-01-01', '2024-01-01')")
        conn.execute(
            "INSERT INTO tracks VALUES ('existing_track', 'Existing Track', '2024-01-01', '2024-01-01', '2024-01-01')"
        )
        conn.execute("INSERT INTO albums_tracks VALUES ('alb_existing', 'existing_track')")
        conn.execute("INSERT INTO tracks_artists VALUES ('existing_track', 'art_existing')")
        conn.execute("INSERT INTO playlists VALUES ('managed_pl', 'My Playlist', 'testuser', '2024-01-01')")
        conn.execute("INSERT INTO playlists_tracks VALUES ('managed_pl', 'existing_track', '2024-01-01')")
        conn.commit()
        conn.close()

        self._configure_client(mock_spotify_client, source_track_ids=["existing_track"])

        client_wrapper = MagicMock()
        client_wrapper.client = mock_spotify_client

        with (
            patch("spotfm.spotify.track.sleep"),
            patch("spotfm.spotify.album.sleep"),
            patch("spotfm.spotify.artist.sleep"),
        ):
            discover_from_playlists(client_wrapper, self.DEST_PL_ID, [self.SOURCE_PL_ID])

        mock_spotify_client.playlist_add_items.assert_not_called()

    @freeze_time("2024-03-15")
    def test_mixed_source_playlist(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Source playlist with new, orphaned, and managed tracks: only new ones are added."""
        import sqlite3 as _sqlite3
        from unittest.mock import MagicMock, patch

        from spotfm.spotify.misc import discover_from_playlists

        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        # Set up: 3 tracks in source playlist with different DB states
        # - "new_t": not in DB → should be discovered
        # - "orphan_t": in DB, not in playlists_tracks → should be skipped
        # - "managed_t": in DB, in playlists_tracks → should be skipped
        conn = _sqlite3.connect(temp_database)
        for tid in ("orphan_t", "managed_t"):
            conn.execute(f"INSERT INTO artists VALUES ('art_{tid}', 'Artist', '2024-01-01')")
            conn.execute(f"INSERT INTO albums VALUES ('alb_{tid}', 'Album', '2024-01-01', '2024-01-01')")
            conn.execute(f"INSERT INTO tracks VALUES ('{tid}', 'Track', '2024-01-01', '2024-01-01', '2024-01-01')")
            conn.execute(f"INSERT INTO albums_tracks VALUES ('alb_{tid}', '{tid}')")
            conn.execute(f"INSERT INTO tracks_artists VALUES ('{tid}', 'art_{tid}')")
        conn.execute("INSERT INTO playlists VALUES ('managed_pl', 'My Playlist', 'testuser', '2024-01-01')")
        conn.execute("INSERT INTO playlists_tracks VALUES ('managed_pl', 'managed_t', '2024-01-01')")
        conn.commit()
        conn.close()

        self._configure_client(mock_spotify_client, source_track_ids=["new_t", "orphan_t", "managed_t"])

        client_wrapper = MagicMock()
        client_wrapper.client = mock_spotify_client

        with (
            patch("spotfm.spotify.track.sleep"),
            patch("spotfm.spotify.album.sleep"),
            patch("spotfm.spotify.artist.sleep"),
        ):
            discover_from_playlists(client_wrapper, self.DEST_PL_ID, [self.SOURCE_PL_ID])

        mock_spotify_client.playlist_add_items.assert_called_once()
        dest_id, added_ids = mock_spotify_client.playlist_add_items.call_args[0]
        assert dest_id == self.DEST_PL_ID
        assert added_ids == ["new_t"]


@pytest.mark.integration
class TestRemovePlaylistDupes:
    """Integration tests for remove_playlist_dupes."""

    TARGET_PL_ID = "target_pl"
    OTHER_PL_ID = "other_pl"

    def _seed_db(self, conn, track_ids_in_target, track_ids_in_other):
        """Seed the DB with two playlists and their tracks."""
        conn.execute(f"INSERT INTO playlists VALUES ('{self.TARGET_PL_ID}', 'Target', 'user', '2024-01-01')")
        conn.execute(f"INSERT INTO playlists VALUES ('{self.OTHER_PL_ID}', 'Other', 'user', '2024-01-01')")
        all_ids = set(track_ids_in_target) | set(track_ids_in_other)
        for tid in all_ids:
            conn.execute(
                f"INSERT OR IGNORE INTO tracks VALUES ('{tid}', 'Track {tid}', '2024-01-01', '2024-01-01', '2024-01-01')"
            )
        for tid in track_ids_in_target:
            conn.execute(f"INSERT INTO playlists_tracks VALUES ('{self.TARGET_PL_ID}', '{tid}', '2024-01-01')")
        for tid in track_ids_in_other:
            conn.execute(f"INSERT INTO playlists_tracks VALUES ('{self.OTHER_PL_ID}', '{tid}', '2024-01-01')")
        conn.commit()

    def test_removes_duplicate_track_ids_from_spotify_and_db(self, temp_database, monkeypatch, mock_spotify_client):
        """Duplicate tracks (same ID in target and another playlist) are removed from Spotify and DB."""
        import sqlite3 as _sqlite3
        from unittest.mock import MagicMock

        from spotfm import sqlite
        from spotfm.spotify.misc import remove_playlist_dupes

        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(sqlite, "DATABASE", temp_database)

        conn = _sqlite3.connect(temp_database)
        self._seed_db(conn, track_ids_in_target=["dupe_track", "unique_track"], track_ids_in_other=["dupe_track"])
        conn.close()

        client_wrapper = MagicMock()
        client_wrapper.client = mock_spotify_client
        mock_spotify_client.playlist_remove_all_occurrences_of_items.return_value = {}

        remove_playlist_dupes(client_wrapper, self.TARGET_PL_ID)

        # Spotify API called with the duplicate track ID
        mock_spotify_client.playlist_remove_all_occurrences_of_items.assert_called_once()
        call_args = mock_spotify_client.playlist_remove_all_occurrences_of_items.call_args[0]
        assert call_args[0] == self.TARGET_PL_ID
        assert "dupe_track" in call_args[1]

        # DB row for dupe removed; unique track row remains
        conn = _sqlite3.connect(temp_database)
        remaining = {
            r[0]
            for r in conn.execute(
                f"SELECT track_id FROM playlists_tracks WHERE playlist_id = '{self.TARGET_PL_ID}'"
            ).fetchall()
        }
        conn.close()
        assert "dupe_track" not in remaining
        assert "unique_track" in remaining

    def test_no_duplicates_skips_api_call(self, temp_database, monkeypatch, mock_spotify_client):
        """When no duplicates exist, Spotify API is not called."""
        import sqlite3 as _sqlite3
        from unittest.mock import MagicMock

        from spotfm import sqlite
        from spotfm.spotify.misc import remove_playlist_dupes

        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(sqlite, "DATABASE", temp_database)

        conn = _sqlite3.connect(temp_database)
        self._seed_db(conn, track_ids_in_target=["track_a"], track_ids_in_other=["track_b"])
        conn.close()

        client_wrapper = MagicMock()
        remove_playlist_dupes(client_wrapper.client, self.TARGET_PL_ID)

        mock_spotify_client.playlist_remove_all_occurrences_of_items.assert_not_called()

    def test_batches_large_dupe_list(self, temp_database, monkeypatch, mock_spotify_client):
        """When duplicates exceed 50, Spotify API is called in batches."""
        import sqlite3 as _sqlite3
        from unittest.mock import MagicMock

        from spotfm import sqlite
        from spotfm.spotify.misc import remove_playlist_dupes

        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(sqlite, "DATABASE", temp_database)

        # 60 tracks that are all duplicates
        dupe_ids = [f"dupe_{i}" for i in range(60)]

        conn = _sqlite3.connect(temp_database)
        self._seed_db(conn, track_ids_in_target=dupe_ids, track_ids_in_other=dupe_ids)
        conn.close()

        client_wrapper = MagicMock()
        client_wrapper.client = mock_spotify_client
        mock_spotify_client.playlist_remove_all_occurrences_of_items.return_value = {}

        remove_playlist_dupes(client_wrapper, self.TARGET_PL_ID)

        # Should be called twice: batch of 50 + batch of 10
        assert mock_spotify_client.playlist_remove_all_occurrences_of_items.call_count == 2
