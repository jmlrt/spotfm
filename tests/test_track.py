"""Unit tests for spotfm.spotify.track module."""

import sqlite3
from unittest.mock import patch

import pytest
from freezegun import freeze_time

from spotfm import utils
from spotfm.spotify.artist import Artist
from spotfm.spotify.track import Track


@pytest.mark.unit
class TestTrackInit:
    """Tests for Track initialization."""

    def test_track_init_with_url(self):
        """Test Track initialization with Spotify URL."""
        url = "https://open.spotify.com/track/3n3Ppam7vgaVa1iaRUc9Lp"
        track = Track(url)

        assert track.id == "3n3Ppam7vgaVa1iaRUc9Lp"
        assert track.name is None
        assert track.album_id is None
        assert track.artists is None

    def test_track_init_with_id(self):
        """Test Track initialization with plain ID."""
        track = Track("test_track_id")

        assert track.id == "test_track_id"
        assert track.kind == "track"


@pytest.mark.unit
class TestTrackRepresentation:
    """Tests for Track string representations."""

    def test_track_repr_single_artist(self):
        """Test Track __repr__ with single artist."""
        track = Track("track1")
        track.name = "Bohemian Rhapsody"

        artist = Artist("artist1")
        artist.name = "Queen"
        artist.genres = []
        track.artists = [artist]

        assert repr(track) == "Track(Queen - Bohemian Rhapsody)"

    def test_track_repr_multiple_artists(self):
        """Test Track __repr__ with multiple artists."""
        track = Track("track1")
        track.name = "Collaboration Song"

        artist1 = Artist("artist1")
        artist1.name = "Artist One"
        artist1.genres = []
        artist2 = Artist("artist2")
        artist2.name = "Artist Two"
        artist2.genres = []
        track.artists = [artist1, artist2]

        assert repr(track) == "Track(Artist One, Artist Two - Collaboration Song)"

    def test_track_str(self):
        """Test Track __str__ method."""
        track = Track("track1")
        track.name = "Test Song"

        artist = Artist("artist1")
        artist.name = "Test Artist"
        artist.genres = []
        track.artists = [artist]

        assert str(track) == "Test Artist - Test Song"

    def test_track_lt_comparison(self):
        """Test Track sorting with __lt__."""
        track1 = Track("track1")
        track1.name = "B Song"
        artist1 = Artist("artist1")
        artist1.name = "Artist"
        artist1.genres = []
        track1.artists = [artist1]

        track2 = Track("track2")
        track2.name = "A Song"
        artist2 = Artist("artist2")
        artist2.name = "Artist"
        artist2.genres = []
        track2.artists = [artist2]

        # track2 should come before track1
        assert track2 < track1
        assert sorted([track1, track2]) == [track2, track1]


@pytest.mark.unit
class TestTrackGenresProperty:
    """Tests for Track.genres property."""

    def test_genres_from_single_artist(self):
        """Test genres aggregation from single artist."""
        track = Track("track1")

        artist = Artist("artist1")
        artist.genres = ["rock", "alternative"]
        track.artists = [artist]

        assert track.genres == ["rock", "alternative"]

    def test_genres_from_multiple_artists(self):
        """Test genres aggregation from multiple artists."""
        track = Track("track1")

        artist1 = Artist("artist1")
        artist1.genres = ["rock", "pop"]

        artist2 = Artist("artist2")
        artist2.genres = ["pop", "electronic"]

        track.artists = [artist1, artist2]

        genres = track.genres
        assert "rock" in genres
        assert "pop" in genres
        assert "electronic" in genres

    def test_genres_removes_duplicates(self):
        """Test that genres from multiple artists are deduplicated."""
        track = Track("track1")

        artist1 = Artist("artist1")
        artist1.genres = ["rock", "pop"]

        artist2 = Artist("artist2")
        artist2.genres = ["pop", "rock"]

        track.artists = [artist1, artist2]

        genres = track.genres
        assert genres.count("rock") == 1
        assert genres.count("pop") == 1

    def test_genres_caching(self):
        """Test that genres property is cached."""
        track = Track("track1")

        artist = Artist("artist1")
        artist.genres = ["rock"]
        track.artists = [artist]

        # First access
        genres1 = track.genres
        # Second access should return cached value
        genres2 = track.genres

        assert genres1 is genres2


@pytest.mark.unit
class TestTrackUpdateFromDb:
    """Tests for Track.update_from_db method."""

    def test_update_from_db_success(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Test successful update from database."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        # Insert test data
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO tracks VALUES ('track1', 'Test Track', '2024-01-01', '2024-01-01', '2024-01-01')")
        cursor.execute("INSERT INTO albums VALUES ('album1', 'Test Album', '2024-01-01', '2024-01-01')")
        cursor.execute("INSERT INTO albums_tracks VALUES ('album1', 'track1')")
        cursor.execute("INSERT INTO artists VALUES ('artist1', 'Test Artist', '2024-01-01')")
        cursor.execute("INSERT INTO tracks_artists VALUES ('track1', 'artist1')")
        conn.commit()
        conn.close()

        track = Track("track1")
        result = track.update_from_db(mock_spotify_client)

        assert result is True
        assert track.name == "Test Track"
        assert track.updated == "2024-01-01"
        assert track.created_at == "2024-01-01"  # New: verify lifecycle timestamp
        assert track.last_seen_at == "2024-01-01"  # New: verify lifecycle timestamp
        assert track.album_id == "album1"
        assert len(track.artists) == 1
        assert track.artists[0].id == "artist1"

    def test_update_from_db_not_found(self, temp_database, monkeypatch):
        """Test update from database when track not found."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)

        track = Track("nonexistent")
        result = track.update_from_db()

        assert result is False
        assert track.name is None


@pytest.mark.unit
class TestTrackUpdateFromApi:
    """Tests for Track.update_from_api method."""

    @freeze_time("2024-03-15")
    def test_update_from_api_success(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Test successful update from API."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        mock_spotify_client.track.return_value = {
            "id": "track123",
            "name": "Test Track",
            "album": {
                "id": "album123",
                "name": "Test Album",
                "release_date": "2024-01-01",
                "artists": [{"id": "artist123", "name": "Test Artist"}],
            },
            "artists": [{"id": "artist123", "name": "Test Artist"}],
        }

        mock_spotify_client.album.return_value = {
            "id": "album123",
            "name": "Test Album",
            "release_date": "2024-01-01",
            "artists": [{"id": "artist123", "name": "Test Artist"}],
        }

        mock_spotify_client.artist.return_value = {
            "id": "artist123",
            "name": "Test Artist",
            "genres": ["rock"],
        }

        track = Track("track123")
        track.update_from_api(mock_spotify_client)

        assert track.name == "Test Track"
        assert track.album_id == "album123"
        assert track.album == "Test Album"
        assert track.updated == "2024-03-15"
        assert len(track.artists) == 1

    @freeze_time("2024-03-15")
    def test_update_from_api_sanitizes_name(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Test that track name is sanitized."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        mock_spotify_client.track.return_value = {
            "id": "track123",
            "name": "Don't Stop Believin'",
            "album": {
                "id": "album123",
                "name": "Test Album",
                "release_date": "2024-01-01",
                "artists": [{"id": "artist123", "name": "Test Artist"}],
            },
            "artists": [{"id": "artist123", "name": "Test Artist"}],
        }

        mock_spotify_client.album.return_value = {
            "id": "album123",
            "name": "Test Album",
            "release_date": "2024-01-01",
            "artists": [{"id": "artist123", "name": "Test Artist"}],
        }

        mock_spotify_client.artist.return_value = {
            "id": "artist123",
            "name": "Test Artist",
            "genres": ["rock"],
        }

        track = Track("track123")
        track.update_from_api(mock_spotify_client)

        # Single quotes should be removed
        assert "'" not in track.name
        assert track.name == "Dont Stop Believin"


@pytest.mark.unit
class TestTrackSyncToDb:
    """Tests for Track.sync_to_db method."""

    def test_sync_to_db_success(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Test syncing track to database."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        track = Track("track123")
        track.name = "Test Track"
        track.album_id = "album123"
        track.updated = "2024-01-01"

        artist = Artist("artist123")
        artist.name = "Test Artist"
        track.artists = [artist]

        # Mock album
        mock_spotify_client.album.return_value = {
            "id": "album123",
            "name": "Test Album",
            "release_date": "2024-01-01",
            "artists": [{"id": "artist123", "name": "Test Artist"}],
        }

        track.sync_to_db(mock_spotify_client)

        # Verify track was inserted
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        track_data = cursor.execute("SELECT * FROM tracks WHERE id = 'track123'").fetchone()
        album_track = cursor.execute("SELECT * FROM albums_tracks WHERE track_id = 'track123'").fetchone()
        track_artist = cursor.execute("SELECT * FROM tracks_artists WHERE track_id = 'track123'").fetchone()
        conn.close()

        # Check track data (now includes lifecycle columns)
        assert track_data[0] == "track123"  # id
        assert track_data[1] == "Test Track"  # name
        assert track_data[2] == "2024-01-01"  # updated_at
        assert track_data[3] is not None  # created_at
        assert track_data[4] is not None  # last_seen_at
        assert album_track[0] == "album123"
        assert track_artist[1] == "artist123"


@pytest.mark.unit
class TestTrackGetTrack:
    """Tests for Track.get_track class method."""

    def test_get_track_from_cache(self, temp_cache_dir, monkeypatch):
        """Test getting track from cache."""
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        # Create and cache a track
        cached_track = Track("cached123")
        cached_track.name = "Cached Track"
        artist = Artist("artist1")
        artist.name = "Cached Artist"
        cached_track.artists = [artist]
        utils.cache_object(cached_track)

        # Retrieve from cache
        track = Track.get_track("cached123")

        assert track.name == "Cached Track"
        assert track.artists[0].name == "Cached Artist"

    def test_get_track_refresh_forces_api_call(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Test that refresh=True forces API call."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        # Cache a track
        cached_track = Track("refresh123")
        cached_track.name = "Old Name"
        # Track needs artists to be cacheable
        from spotfm.spotify.artist import Artist

        artist = Artist("old_artist")
        artist.name = "Old Artist"
        artist.genres = []
        cached_track.artists = [artist]
        utils.cache_object(cached_track)

        # Mock API
        mock_spotify_client.track.return_value = {
            "id": "refresh123",
            "name": "New Name",
            "album": {
                "id": "album123",
                "name": "Album",
                "release_date": "2024-01-01",
                "artists": [{"id": "artist123", "name": "Artist"}],
            },
            "artists": [{"id": "artist123", "name": "Artist"}],
        }

        mock_spotify_client.album.return_value = {
            "id": "album123",
            "name": "Album",
            "release_date": "2024-01-01",
            "artists": [{"id": "artist123", "name": "Artist"}],
        }

        mock_spotify_client.artist.return_value = {
            "id": "artist123",
            "name": "Artist",
            "genres": [],
        }

        with freeze_time("2024-03-15"):
            track = Track.get_track("refresh123", mock_spotify_client, refresh=True, sync_to_db=False)

        assert track.name == "New Name"
        mock_spotify_client.track.assert_called_once()


@pytest.mark.unit
class TestTrackGetTracks:
    """Tests for Track.get_tracks class method."""

    def test_get_tracks_single_batch(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Test getting multiple tracks with individual API calls."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        track_ids = ["track1", "track2", "track3"]

        # Mock individual track API responses
        def mock_track_response(id, market):
            return {
                "id": id,
                "name": f"Track {id[-1]}",
                "album": {"id": f"album{id[-1]}", "name": f"Album {id[-1]}"},
                "artists": [{"id": f"artist{id[-1]}", "name": f"Artist {id[-1]}"}],
            }

        mock_spotify_client.track.side_effect = mock_track_response

        # Mock individual album API responses
        def mock_album_response(id, market):
            return {
                "id": id,
                "name": f"Album {id[-1]}",
                "release_date": "2024-01-01",
                "artists": [{"id": f"artist{id[-1]}", "name": f"Artist {id[-1]}"}],
            }

        mock_spotify_client.album.side_effect = mock_album_response

        # Mock individual artist API responses
        def mock_artist_response(id):
            return {"id": id, "name": f"Artist {id[-1]}", "genres": []}

        mock_spotify_client.artist.side_effect = mock_artist_response

        with patch("spotfm.spotify.track.sleep"):  # Mock sleep to speed up test
            tracks = Track.get_tracks(track_ids, mock_spotify_client)

        assert len(tracks) == 3
        assert tracks[0].name == "Track 1"
        assert tracks[1].name == "Track 2"
        assert tracks[2].name == "Track 3"
        # Verify individual calls were made
        assert mock_spotify_client.track.call_count == 3

    def test_get_tracks_multiple_batches(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Test getting tracks with individual API calls."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        # Create 5 track IDs
        track_ids = [f"track{i}" for i in range(1, 6)]

        # Mock individual track API responses
        def mock_track_response(id, market):
            return {
                "id": id,
                "name": f"Track {id}",
                "album": {"id": f"album{id}", "name": f"Album {id}"},
                "artists": [{"id": f"artist{id}", "name": f"Artist {id}"}],
            }

        mock_spotify_client.track.side_effect = mock_track_response

        # Mock individual album API responses
        def mock_album_response(id, market):
            return {
                "id": id,
                "name": f"Album {id}",
                "release_date": "2024-01-01",
                "artists": [{"id": f"artist{id}", "name": f"Artist {id}"}],
            }

        mock_spotify_client.album.side_effect = mock_album_response

        # Mock individual artist API responses
        def mock_artist_response(id):
            return {"id": id, "name": f"Artist {id}", "genres": []}

        mock_spotify_client.artist.side_effect = mock_artist_response

        with patch("spotfm.spotify.track.sleep"):
            tracks = Track.get_tracks(track_ids, mock_spotify_client, batch_size=2)

        assert len(tracks) == 5
        # Should have made 5 individual calls for tracks (batch_size param is now ignored)
        assert mock_spotify_client.track.call_count == 5

    def test_get_tracks_handles_none_track(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Test that None/invalid tracks are skipped."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        track_ids = ["track1", "invalid", "track2"]

        # Mock individual track API responses - invalid raises exception
        def mock_track_response(id, market):
            if id == "invalid":
                raise Exception("Track not found")
            return {
                "id": id,
                "name": f"Track {id[-1]}",
                "album": {"id": f"album{id[-1]}", "name": f"Album {id[-1]}"},
                "artists": [{"id": f"artist{id[-1]}", "name": f"Artist {id[-1]}"}],
            }

        mock_spotify_client.track.side_effect = mock_track_response

        # Mock individual album API responses
        def mock_album_response(id, market):
            return {
                "id": id,
                "name": f"Album {id[-1]}",
                "release_date": "2024-01-01",
                "artists": [{"id": f"artist{id[-1]}", "name": f"Artist {id[-1]}"}],
            }

        mock_spotify_client.album.side_effect = mock_album_response

        # Mock individual artist API responses
        def mock_artist_response(id):
            return {"id": id, "name": f"Artist {id[-1]}", "genres": []}

        mock_spotify_client.artist.side_effect = mock_artist_response

        with patch("spotfm.spotify.track.sleep"):
            tracks = Track.get_tracks(track_ids, mock_spotify_client)

        # Should only return 2 valid tracks (invalid track is skipped)
        assert len(tracks) == 2


@pytest.mark.unit
class TestTrackHelperMethods:
    """Tests for Track helper methods."""

    def test_get_artists_names_single_artist(self):
        """Test get_artists_names with single artist."""
        track = Track("track1")
        artist = Artist("artist1")
        artist.name = "Solo Artist"
        artist.genres = []
        track.artists = [artist]

        assert track.get_artists_names() == "Solo Artist"

    def test_get_artists_names_multiple_artists(self):
        """Test get_artists_names with multiple artists."""
        track = Track("track1")

        artist1 = Artist("artist1")
        artist1.name = "Artist One"
        artist1.genres = []

        artist2 = Artist("artist2")
        artist2.name = "Artist Two"
        artist2.genres = []

        track.artists = [artist1, artist2]

        assert track.get_artists_names() == "Artist One, Artist Two"

    def test_get_genres_names(self):
        """Test get_genres_names method."""
        track = Track("track1")

        artist1 = Artist("artist1")
        artist1.genres = ["rock", "pop"]

        artist2 = Artist("artist2")
        artist2.genres = ["electronic"]

        track.artists = [artist1, artist2]

        genres_str = track.get_genres_names()
        assert "rock" in genres_str
        assert "pop" in genres_str
        assert "electronic" in genres_str


@pytest.mark.unit
class TestTrackLifecycleTracking:
    """Tests for Track lifecycle tracking (created_at, last_seen_at)."""

    @freeze_time("2024-01-15")
    def test_lifecycle_timestamps_on_first_sync(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Test that tracks get lifecycle timestamps on first sync."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        # Create new track with API data
        track = Track.get_track("newtrack1", client=mock_spotify_client, refresh=True)

        # Verify timestamps are set
        assert hasattr(track, "created_at")
        assert hasattr(track, "last_seen_at")
        assert track.created_at == "2024-01-15"
        assert track.last_seen_at == "2024-01-15"

        # Verify in DB
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        result = cursor.execute("SELECT created_at, last_seen_at FROM tracks WHERE id = 'newtrack1'").fetchone()
        conn.close()

        assert result == ("2024-01-15", "2024-01-15")

    def test_lifecycle_preserves_created_at_on_update(
        self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client
    ):
        """Test that created_at is preserved when track is updated."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        # First sync at 2024-01-01
        with freeze_time("2024-01-01"):
            track = Track.get_track("track123", client=mock_spotify_client, refresh=True)
            assert track.created_at == "2024-01-01"
            assert track.last_seen_at == "2024-01-01"

        # Update track at 2024-01-15
        with freeze_time("2024-01-15"):
            track = Track.get_track("track123", client=mock_spotify_client, refresh=True)

        # Verify created_at preserved, last_seen_at updated
        assert track.created_at == "2024-01-01"  # Preserved
        assert track.last_seen_at == "2024-01-15"  # Updated

        # Verify in DB
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        result = cursor.execute("SELECT created_at, last_seen_at FROM tracks WHERE id = 'track123'").fetchone()
        conn.close()

        assert result == ("2024-01-01", "2024-01-15")

    def test_is_orphaned_returns_true_when_not_in_playlists(self, temp_database, monkeypatch):
        """Test that is_orphaned() returns True for tracks not in any playlist."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)

        # Create track in DB but not in playlists_tracks
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO tracks VALUES ('orphan1', 'Orphaned Track', '2024-01-01', '2024-01-01', '2024-01-10')"
        )
        cursor.execute("INSERT INTO albums VALUES ('album1', 'Album 1', '2024-01-01', '2024-01-01')")
        cursor.execute("INSERT INTO albums_tracks VALUES ('album1', 'orphan1')")
        cursor.execute("INSERT INTO artists VALUES ('artist1', 'Artist 1', '2024-01-01')")
        cursor.execute("INSERT INTO tracks_artists VALUES ('orphan1', 'artist1')")
        conn.commit()
        conn.close()

        # Create track object
        track = Track("orphan1")
        track.update_from_db()

        # Verify is_orphaned returns True
        assert track.is_orphaned() is True

    def test_is_orphaned_returns_false_when_in_playlist(self, temp_database, monkeypatch):
        """Test that is_orphaned() returns False for tracks in playlists."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)

        # Create track in DB and in playlists_tracks
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO playlists VALUES ('playlist1', 'Test Playlist', 'user123', '2024-01-01')")
        cursor.execute(
            "INSERT INTO tracks VALUES ('active1', 'Active Track', '2024-01-01', '2024-01-01', '2024-01-01')"
        )
        cursor.execute("INSERT INTO albums VALUES ('album1', 'Album 1', '2024-01-01', '2024-01-01')")
        cursor.execute("INSERT INTO albums_tracks VALUES ('album1', 'active1')")
        cursor.execute("INSERT INTO artists VALUES ('artist1', 'Artist 1', '2024-01-01')")
        cursor.execute("INSERT INTO tracks_artists VALUES ('active1', 'artist1')")
        cursor.execute("INSERT INTO playlists_tracks VALUES ('playlist1', 'active1', '2024-01-01')")
        conn.commit()
        conn.close()

        # Create track object
        track = Track("active1")
        track.update_from_db()

        # Verify is_orphaned returns False
        assert track.is_orphaned() is False

    def test_update_from_db_handles_null_lifecycle_timestamps(self, temp_database, monkeypatch):
        """Test that update_from_db() handles NULL lifecycle timestamps gracefully."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)

        # Manually insert track with old schema (NULL timestamps)
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        # Use UPDATE to set columns to NULL after INSERT
        cursor.execute("INSERT INTO tracks VALUES ('oldtrack1', 'Old Track', '2024-01-01', '2024-01-01', '2024-01-01')")
        cursor.execute("UPDATE tracks SET created_at = NULL, last_seen_at = NULL WHERE id = 'oldtrack1'")
        cursor.execute("INSERT INTO albums VALUES ('album1', 'Album 1', '2024-01-01', '2024-01-01')")
        cursor.execute("INSERT INTO albums_tracks VALUES ('album1', 'oldtrack1')")
        cursor.execute("INSERT INTO artists VALUES ('artist1', 'Artist 1', '2024-01-01')")
        cursor.execute("INSERT INTO tracks_artists VALUES ('oldtrack1', 'artist1')")
        conn.commit()
        conn.close()

        # Try to load track (should not crash)
        track = Track("oldtrack1")
        result = track.update_from_db()

        # Verify it loaded successfully
        assert result is True
        assert track.name == "Old Track"
        # Note: The graceful fallback in update_from_db sets default values
        # We're not testing the specific default behavior, just that it doesn't crash
