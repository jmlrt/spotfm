"""Unit tests for spotfm.spotify.artist module."""

import sqlite3

import pytest
from freezegun import freeze_time

from spotfm import utils
from spotfm.spotify.artist import Artist


@pytest.mark.unit
class TestArtistInit:
    """Tests for Artist initialization."""

    def test_artist_init_with_url(self):
        """Test Artist initialization with Spotify URL."""
        url = "https://open.spotify.com/artist/3WrFJ7ztbogyGnTHbHJFl2"
        artist = Artist(url)

        assert artist.id == "3WrFJ7ztbogyGnTHbHJFl2"
        assert artist.name is None
        assert artist.genres == []
        assert artist.updated is None

    def test_artist_init_with_id(self):
        """Test Artist initialization with plain ID."""
        artist = Artist("test_artist_id")

        assert artist.id == "test_artist_id"
        assert artist.name is None
        assert artist.genres == []

    def test_artist_kind_attribute(self):
        """Test Artist has correct kind attribute."""
        artist = Artist("test_id")
        assert artist.kind == "artist"


@pytest.mark.unit
class TestArtistRepresentation:
    """Tests for Artist string representations."""

    def test_artist_repr(self):
        """Test Artist __repr__ method."""
        artist = Artist("test_id")
        artist.name = "The Beatles"

        assert repr(artist) == "Artist(The Beatles)"

    def test_artist_str(self):
        """Test Artist __str__ method."""
        artist = Artist("test_id")
        artist.name = "Pink Floyd"

        assert str(artist) == "Pink Floyd"


@pytest.mark.unit
class TestArtistUpdateFromDb:
    """Tests for Artist.update_from_db method."""

    def test_update_from_db_success(self, temp_database, monkeypatch):
        """Test successful update from database."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)

        # Insert test data
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO artists VALUES ('artist1', 'Test Artist', '2024-01-01')")
        cursor.execute("INSERT INTO artists_genres VALUES ('artist1', 'rock')")
        cursor.execute("INSERT INTO artists_genres VALUES ('artist1', 'alternative')")
        conn.commit()
        conn.close()

        artist = Artist("artist1")
        result = artist.update_from_db()

        assert result is True
        assert artist.name == "Test Artist"
        assert artist.updated == "2024-01-01"
        assert set(artist.genres) == {"rock", "alternative"}

    def test_update_from_db_not_found(self, temp_database, monkeypatch):
        """Test update from database when artist not found."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)

        artist = Artist("nonexistent")
        result = artist.update_from_db()

        assert result is False
        assert artist.name is None

    def test_update_from_db_no_genres(self, temp_database, monkeypatch):
        """Test update from database when artist has no genres."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)

        # Insert artist without genres
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO artists VALUES ('artist2', 'No Genre Artist', '2024-01-01')")
        conn.commit()
        conn.close()

        artist = Artist("artist2")
        result = artist.update_from_db()

        assert result is True
        assert artist.name == "No Genre Artist"
        assert artist.genres == []


@pytest.mark.unit
class TestArtistUpdateFromApi:
    """Tests for Artist.update_from_api method."""

    @freeze_time("2024-03-15")
    def test_update_from_api_success(self, mock_spotify_client):
        """Test successful update from API."""
        mock_spotify_client.artist.return_value = {
            "id": "artist123",
            "name": "The Beatles",
            "genres": ["rock", "pop", "british invasion"],
        }

        artist = Artist("artist123")
        artist.update_from_api(mock_spotify_client)

        assert artist.name == "The Beatles"
        assert artist.genres == ["rock", "pop", "british invasion"]
        assert artist.updated == "2024-03-15"
        mock_spotify_client.artist.assert_called_once_with("artist123")

    @freeze_time("2024-03-15")
    def test_update_from_api_sanitizes_name(self, mock_spotify_client):
        """Test that artist name is sanitized."""
        mock_spotify_client.artist.return_value = {
            "id": "artist123",
            "name": "Guns N' Roses",
            "genres": ["rock"],
        }

        artist = Artist("artist123")
        artist.update_from_api(mock_spotify_client)

        # Single quotes should be removed by sanitize_string
        assert "'" not in artist.name
        assert artist.name == "Guns N Roses"

    @freeze_time("2024-03-15")
    def test_update_from_api_sanitizes_genres(self, mock_spotify_client):
        """Test that genres are sanitized."""
        mock_spotify_client.artist.return_value = {
            "id": "artist123",
            "name": "Test Artist",
            "genres": ["rock 'n' roll", "blues"],
        }

        artist = Artist("artist123")
        artist.update_from_api(mock_spotify_client)

        assert artist.genres == ["rock n roll", "blues"]

    @freeze_time("2024-03-15")
    def test_update_from_api_no_genres(self, mock_spotify_client):
        """Test update from API when artist has no genres."""
        mock_spotify_client.artist.return_value = {
            "id": "artist123",
            "name": "New Artist",
            "genres": [],
        }

        artist = Artist("artist123")
        artist.update_from_api(mock_spotify_client)

        assert artist.name == "New Artist"
        assert artist.genres == []
        assert artist.updated == "2024-03-15"


@pytest.mark.unit
class TestArtistSyncToDb:
    """Tests for Artist.sync_to_db method."""

    def test_sync_to_db_with_genres(self, temp_database, monkeypatch):
        """Test syncing artist with genres to database."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)

        artist = Artist("artist123")
        artist.name = "Test Artist"
        artist.genres = ["rock", "alternative"]
        artist.updated = "2024-01-01"

        artist.sync_to_db()

        # Verify artist was inserted
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        artist_data = cursor.execute("SELECT * FROM artists WHERE id = 'artist123'").fetchone()
        genres = cursor.execute("SELECT genre FROM artists_genres WHERE artist_id = 'artist123'").fetchall()
        conn.close()

        assert artist_data == ("artist123", "Test Artist", "2024-01-01")
        assert {g[0] for g in genres} == {"rock", "alternative"}

    def test_sync_to_db_no_genres(self, temp_database, monkeypatch):
        """Test syncing artist without genres to database."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)

        artist = Artist("artist456")
        artist.name = "No Genre Artist"
        artist.genres = []
        artist.updated = "2024-01-01"

        artist.sync_to_db()

        # Verify artist was inserted but no genres
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        artist_data = cursor.execute("SELECT * FROM artists WHERE id = 'artist456'").fetchone()
        genres = cursor.execute("SELECT genre FROM artists_genres WHERE artist_id = 'artist456'").fetchall()
        conn.close()

        assert artist_data == ("artist456", "No Genre Artist", "2024-01-01")
        assert genres == []

    def test_sync_to_db_ignores_duplicates(self, temp_database, monkeypatch):
        """Test that INSERT OR IGNORE prevents duplicate entries."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)

        artist = Artist("artist789")
        artist.name = "Duplicate Artist"
        artist.genres = ["rock"]
        artist.updated = "2024-01-01"

        # Sync twice
        artist.sync_to_db()
        artist.sync_to_db()

        # Verify only one entry exists
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        count = cursor.execute("SELECT COUNT(*) FROM artists WHERE id = 'artist789'").fetchone()[0]
        genre_count = cursor.execute("SELECT COUNT(*) FROM artists_genres WHERE artist_id = 'artist789'").fetchone()[0]
        conn.close()

        assert count == 1
        assert genre_count == 1


@pytest.mark.unit
class TestArtistGetArtist:
    """Tests for Artist.get_artist class method."""

    def test_get_artist_from_cache(self, temp_cache_dir, monkeypatch):
        """Test getting artist from cache."""
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        # Create and cache an artist
        cached_artist = Artist("cached123")
        cached_artist.name = "Cached Artist"
        cached_artist.genres = ["rock"]
        utils.cache_object(cached_artist)

        # Retrieve from cache
        artist = Artist.get_artist("cached123")

        assert artist.name == "Cached Artist"
        assert artist.genres == ["rock"]

    def test_get_artist_from_db(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Test getting artist from database when not in cache."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        # Insert into database
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO artists VALUES ('db123', 'DB Artist', '2024-01-01')")
        cursor.execute("INSERT INTO artists_genres VALUES ('db123', 'jazz')")
        conn.commit()
        conn.close()

        artist = Artist.get_artist("db123", mock_spotify_client)

        assert artist.name == "DB Artist"
        assert artist.genres == ["jazz"]

    def test_get_artist_from_api(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Test getting artist from API when not in cache or DB."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        mock_spotify_client.artist.return_value = {
            "id": "api123",
            "name": "API Artist",
            "genres": ["electronic"],
        }

        with freeze_time("2024-03-15"):
            artist = Artist.get_artist("api123", mock_spotify_client, sync_to_db=False)

        assert artist.name == "API Artist"
        assert artist.genres == ["electronic"]
        assert artist.updated == "2024-03-15"
        mock_spotify_client.artist.assert_called_once_with("api123")

    def test_get_artist_refresh_forces_api_call(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Test that refresh=True forces API call even with cache."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        # Cache an artist
        cached_artist = Artist("refresh123")
        cached_artist.name = "Old Name"
        utils.cache_object(cached_artist)

        # Mock API to return updated data
        mock_spotify_client.artist.return_value = {
            "id": "refresh123",
            "name": "New Name",
            "genres": ["pop"],
        }

        with freeze_time("2024-03-15"):
            artist = Artist.get_artist("refresh123", mock_spotify_client, refresh=True, sync_to_db=False)

        assert artist.name == "New Name"
        assert artist.genres == ["pop"]
        mock_spotify_client.artist.assert_called_once()

    def test_get_artist_without_client(self, temp_cache_dir, monkeypatch):
        """Test getting artist without client uses only cache."""
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        # Cache an artist
        cached_artist = Artist("noclient123")
        cached_artist.name = "Cached Only"
        utils.cache_object(cached_artist)

        artist = Artist.get_artist("noclient123")

        assert artist.name == "Cached Only"

    def test_get_artist_sync_to_db_option(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Test that sync_to_db=False prevents database sync."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        mock_spotify_client.artist.return_value = {
            "id": "nosync123",
            "name": "No Sync Artist",
            "genres": ["rock"],
        }

        with freeze_time("2024-03-15"):
            artist = Artist.get_artist("nosync123", mock_spotify_client, sync_to_db=False)

        # Verify artist was NOT synced to database
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        result = cursor.execute("SELECT * FROM artists WHERE id = 'nosync123'").fetchone()
        conn.close()

        assert result is None
        assert artist.name == "No Sync Artist"


@pytest.mark.unit
class TestArtistEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_artist_with_special_characters_in_name(self, mock_spotify_client):
        """Test artist with special characters in name."""
        mock_spotify_client.artist.return_value = {
            "id": "special123",
            "name": "AC/DC & Friends",
            "genres": ["rock"],
        }

        artist = Artist("special123")
        artist.update_from_api(mock_spotify_client)

        assert artist.name == "AC/DC & Friends"

    def test_artist_with_very_long_genre_list(self, mock_spotify_client):
        """Test artist with many genres."""
        genres = [f"genre{i}" for i in range(50)]
        mock_spotify_client.artist.return_value = {
            "id": "many_genres",
            "name": "Multi Genre Artist",
            "genres": genres,
        }

        artist = Artist("many_genres")
        artist.update_from_api(mock_spotify_client)

        assert len(artist.genres) == 50
        assert artist.genres == genres

    def test_artist_with_unicode_characters(self, mock_spotify_client):
        """Test artist with Unicode characters in name."""
        mock_spotify_client.artist.return_value = {
            "id": "unicode123",
            "name": "Björk",
            "genres": ["avant-garde"],
        }

        artist = Artist("unicode123")
        artist.update_from_api(mock_spotify_client)

        assert artist.name == "Björk"
