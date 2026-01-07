"""Unit tests for spotfm.spotify.album module."""

import sqlite3

import pytest
from freezegun import freeze_time

from spotfm import utils
from spotfm.spotify.album import Album
from spotfm.spotify.artist import Artist


@pytest.mark.unit
class TestAlbumInit:
    """Tests for Album initialization."""

    def test_album_init_with_url(self):
        """Test Album initialization with Spotify URL."""
        url = "https://open.spotify.com/album/0ETFjACtuP2ADo6LFhL6HN"
        album = Album(url)

        assert album.id == "0ETFjACtuP2ADo6LFhL6HN"
        assert album.name is None
        assert album.release_date is None
        assert album.artists == []

    def test_album_init_with_id(self):
        """Test Album initialization with plain ID."""
        album = Album("test_album_id")

        assert album.id == "test_album_id"
        assert album.kind == "album"


@pytest.mark.unit
class TestAlbumRepresentation:
    """Tests for Album string representations."""

    def test_album_repr(self):
        """Test Album __repr__ method."""
        album = Album("album1")
        album.name = "Abbey Road"

        assert repr(album) == "Album(Abbey Road)"

    def test_album_str(self):
        """Test Album __str__ method."""
        album = Album("album1")
        album.name = "Dark Side of the Moon"

        assert str(album) == "Dark Side of the Moon"


@pytest.mark.unit
class TestAlbumUpdateFromDb:
    """Tests for Album.update_from_db method."""

    def test_update_from_db_success(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Test successful update from database."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        # Insert test data
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO albums VALUES ('album1', 'Test Album', '2024-01-01', '2024-01-01')")
        cursor.execute("INSERT INTO artists VALUES ('artist1', 'Test Artist', '2024-01-01')")
        cursor.execute("INSERT INTO albums_artists VALUES ('album1', 'artist1')")
        conn.commit()
        conn.close()

        album = Album("album1")
        result = album.update_from_db(mock_spotify_client)

        assert result is True
        assert album.name == "Test Album"
        assert album.release_date == "2024-01-01"
        assert album.updated == "2024-01-01"
        assert len(album.artists) == 1
        assert album.artists[0].id == "artist1"

    def test_update_from_db_not_found(self, temp_database, monkeypatch):
        """Test update from database when album not found."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)

        album = Album("nonexistent")
        result = album.update_from_db()

        assert result is False
        assert album.name is None

    def test_update_from_db_multiple_artists(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Test album with multiple artists."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        # Insert test data
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO albums VALUES ('album1', 'Collab Album', '2024-01-01', '2024-01-01')")
        cursor.execute("INSERT INTO artists VALUES ('artist1', 'Artist 1', '2024-01-01')")
        cursor.execute("INSERT INTO artists VALUES ('artist2', 'Artist 2', '2024-01-01')")
        cursor.execute("INSERT INTO albums_artists VALUES ('album1', 'artist1')")
        cursor.execute("INSERT INTO albums_artists VALUES ('album1', 'artist2')")
        conn.commit()
        conn.close()

        album = Album("album1")
        result = album.update_from_db(mock_spotify_client)

        assert result is True
        assert len(album.artists) == 2


@pytest.mark.unit
class TestAlbumUpdateFromApi:
    """Tests for Album.update_from_api method."""

    @freeze_time("2024-03-15")
    def test_update_from_api_success(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Test successful update from API."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        mock_spotify_client.album.return_value = {
            "id": "album123",
            "name": "Test Album",
            "release_date": "2024-01-01",
            "artists": [
                {"id": "artist1", "name": "Artist 1"},
                {"id": "artist2", "name": "Artist 2"},
            ],
        }

        mock_spotify_client.artist.side_effect = [
            {"id": "artist1", "name": "Artist 1", "genres": ["rock"]},
            {"id": "artist2", "name": "Artist 2", "genres": ["pop"]},
        ]

        album = Album("album123")
        album.update_from_api(mock_spotify_client)

        assert album.name == "Test Album"
        assert album.release_date == "2024-01-01"
        assert album.updated == "2024-03-15"
        assert len(album.artists) == 2
        assert album.artists_id == ["artist1", "artist2"]

    @freeze_time("2024-03-15")
    def test_update_from_api_sanitizes_name(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Test that album name is sanitized."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        mock_spotify_client.album.return_value = {
            "id": "album123",
            "name": "Queen's Greatest Hits",
            "release_date": "1981-10-26",
            "artists": [{"id": "artist1", "name": "Queen"}],
        }

        mock_spotify_client.artist.return_value = {
            "id": "artist1",
            "name": "Queen",
            "genres": ["rock"],
        }

        album = Album("album123")
        album.update_from_api(mock_spotify_client)

        assert "'" not in album.name
        assert album.name == "Queens Greatest Hits"


@pytest.mark.unit
class TestAlbumSyncToDb:
    """Tests for Album.sync_to_db method."""

    def test_sync_to_db_success(self, temp_database, monkeypatch):
        """Test syncing album to database."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)

        album = Album("album123")
        album.name = "Test Album"
        album.release_date = "2024-01-01"
        album.updated = "2024-01-01"

        artist = Artist("artist123")
        artist.name = "Test Artist"
        album.artists = [artist]

        album.sync_to_db()

        # Verify album was inserted
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        album_data = cursor.execute("SELECT * FROM albums WHERE id = 'album123'").fetchone()
        album_artist = cursor.execute("SELECT * FROM albums_artists WHERE album_id = 'album123'").fetchone()
        conn.close()

        assert album_data == ("album123", "Test Album", "2024-01-01", "2024-01-01")
        assert album_artist == ("album123", "artist123")

    def test_sync_to_db_multiple_artists(self, temp_database, monkeypatch):
        """Test syncing album with multiple artists."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)

        album = Album("album456")
        album.name = "Collab Album"
        album.release_date = "2024-01-01"
        album.updated = "2024-01-01"

        artist1 = Artist("artist1")
        artist1.name = "Artist 1"

        artist2 = Artist("artist2")
        artist2.name = "Artist 2"

        album.artists = [artist1, artist2]

        album.sync_to_db()

        # Verify both artists are linked
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        artists = cursor.execute("SELECT artist_id FROM albums_artists WHERE album_id = 'album456'").fetchall()
        conn.close()

        assert len(artists) == 2
        assert ("artist1",) in artists
        assert ("artist2",) in artists


@pytest.mark.unit
class TestAlbumGetAlbum:
    """Tests for Album.get_album class method."""

    def test_get_album_from_cache(self, temp_cache_dir, monkeypatch):
        """Test getting album from cache."""
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        # Create and cache an album
        cached_album = Album("cached123")
        cached_album.name = "Cached Album"
        cached_album.release_date = "2024-01-01"
        utils.cache_object(cached_album)

        # Retrieve from cache
        album = Album.get_album("cached123")

        assert album.name == "Cached Album"
        assert album.release_date == "2024-01-01"

    def test_get_album_from_api(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Test getting album from API when not in cache or DB."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        mock_spotify_client.album.return_value = {
            "id": "api123",
            "name": "API Album",
            "release_date": "2024-01-01",
            "artists": [{"id": "artist1", "name": "Artist"}],
        }

        mock_spotify_client.artist.return_value = {
            "id": "artist1",
            "name": "Artist",
            "genres": ["rock"],
        }

        with freeze_time("2024-03-15"):
            album = Album.get_album("api123", mock_spotify_client, sync_to_db=False)

        assert album.name == "API Album"
        assert album.release_date == "2024-01-01"
        mock_spotify_client.album.assert_called_once_with("api123", market="FR")

    def test_get_album_refresh_forces_api_call(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Test that refresh=True forces API call."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        # Cache an album
        cached_album = Album("refresh123")
        cached_album.name = "Old Name"
        utils.cache_object(cached_album)

        # Mock API
        mock_spotify_client.album.return_value = {
            "id": "refresh123",
            "name": "New Name",
            "release_date": "2024-02-01",
            "artists": [{"id": "artist1", "name": "Artist"}],
        }

        mock_spotify_client.artist.return_value = {
            "id": "artist1",
            "name": "Artist",
            "genres": [],
        }

        with freeze_time("2024-03-15"):
            album = Album.get_album("refresh123", mock_spotify_client, refresh=True, sync_to_db=False)

        assert album.name == "New Name"
        mock_spotify_client.album.assert_called_once()


@pytest.mark.unit
class TestAlbumEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_album_with_special_characters(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Test album with special characters in name."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        mock_spotify_client.album.return_value = {
            "id": "special123",
            "name": "Greatest Hits: Volume 1",
            "release_date": "2024-01-01",
            "artists": [{"id": "artist1", "name": "Artist"}],
        }

        mock_spotify_client.artist.return_value = {
            "id": "artist1",
            "name": "Artist",
            "genres": [],
        }

        album = Album("special123")
        album.update_from_api(mock_spotify_client)

        assert album.name == "Greatest Hits: Volume 1"

    def test_album_with_unicode_characters(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Test album with Unicode characters."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        mock_spotify_client.album.return_value = {
            "id": "unicode123",
            "name": "Café del Mar",
            "release_date": "2024-01-01",
            "artists": [{"id": "artist1", "name": "Various"}],
        }

        mock_spotify_client.artist.return_value = {
            "id": "artist1",
            "name": "Various",
            "genres": [],
        }

        album = Album("unicode123")
        album.update_from_api(mock_spotify_client)

        assert album.name == "Café del Mar"

    def test_album_with_partial_date(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Test album with partial release date (year only)."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        mock_spotify_client.album.return_value = {
            "id": "partial123",
            "name": "Old Album",
            "release_date": "1969",
            "artists": [{"id": "artist1", "name": "Artist"}],
        }

        mock_spotify_client.artist.return_value = {
            "id": "artist1",
            "name": "Artist",
            "genres": [],
        }

        album = Album("partial123")
        album.update_from_api(mock_spotify_client)

        assert album.release_date == "1969"
