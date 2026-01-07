"""Unit tests for spotfm.utils module."""

import pickle
import sqlite3
from pathlib import Path

import pytest
from freezegun import freeze_time

from spotfm import sqlite as db_module
from spotfm import utils


@pytest.mark.unit
class TestGetDate:
    """Tests for get_date function."""

    @freeze_time("2024-01-15")
    def test_get_date_returns_correct_format(self):
        """Test that get_date returns date in YYYYMMDD format."""
        result = utils.get_date()
        assert result == "20240115"

    @freeze_time("2024-12-31")
    def test_get_date_handles_year_end(self):
        """Test get_date at year end."""
        result = utils.get_date()
        assert result == "20241231"


@pytest.mark.unit
class TestSanitizeString:
    """Tests for sanitize_string function."""

    def test_sanitize_removes_single_quotes(self):
        """Test that single quotes are removed."""
        input_str = "O'Connor's song"
        expected = "OConnors song"
        assert utils.sanitize_string(input_str) == expected

    def test_sanitize_empty_string(self):
        """Test sanitizing empty string."""
        assert utils.sanitize_string("") == ""

    def test_sanitize_no_quotes(self):
        """Test string without quotes remains unchanged."""
        input_str = "Normal string"
        assert utils.sanitize_string(input_str) == input_str

    def test_sanitize_multiple_quotes(self):
        """Test multiple single quotes are all removed."""
        input_str = "It's a rock 'n' roll song"
        expected = "Its a rock n roll song"
        assert utils.sanitize_string(input_str) == expected

    def test_sanitize_preserves_double_quotes(self):
        """Test that double quotes are preserved."""
        input_str = 'He said "hello"'
        assert utils.sanitize_string(input_str) == input_str


@pytest.mark.unit
class TestParseUrl:
    """Tests for parse_url function."""

    def test_parse_spotify_track_url(self):
        """Test parsing Spotify track URL."""
        url = "https://open.spotify.com/track/3n3Ppam7vgaVa1iaRUc9Lp"
        assert utils.parse_url(url) == "3n3Ppam7vgaVa1iaRUc9Lp"

    def test_parse_spotify_artist_url(self):
        """Test parsing Spotify artist URL."""
        url = "https://open.spotify.com/artist/3WrFJ7ztbogyGnTHbHJFl2"
        assert utils.parse_url(url) == "3WrFJ7ztbogyGnTHbHJFl2"

    def test_parse_spotify_album_url(self):
        """Test parsing Spotify album URL."""
        url = "https://open.spotify.com/album/0ETFjACtuP2ADo6LFhL6HN"
        assert utils.parse_url(url) == "0ETFjACtuP2ADo6LFhL6HN"

    def test_parse_spotify_playlist_url(self):
        """Test parsing Spotify playlist URL."""
        url = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
        assert utils.parse_url(url) == "37i9dQZF1DXcBWIGoYBM5M"

    def test_parse_url_with_query_params(self):
        """Test parsing URL with query parameters - they get stripped."""
        url = "https://open.spotify.com/track/3n3Ppam7vgaVa1iaRUc9Lp?si=xyz123"
        # parse_url only extracts the path component, query params are in the last segment
        assert utils.parse_url(url) == "3n3Ppam7vgaVa1iaRUc9Lp"

    def test_parse_plain_id(self):
        """Test that plain IDs are returned as-is."""
        id_str = "3n3Ppam7vgaVa1iaRUc9Lp"
        assert utils.parse_url(id_str) == id_str

    def test_parse_empty_path(self):
        """Test parsing URL with empty path."""
        url = "https://open.spotify.com/"
        assert utils.parse_url(url) == ""


@pytest.mark.unit
class TestParseConfig:
    """Tests for parse_config function."""

    def test_parse_valid_config(self, temp_config_file):
        """Test parsing valid TOML config file."""
        config = utils.parse_config(temp_config_file)

        assert "spotify" in config
        assert config["spotify"]["client_id"] == "test_client_id"
        assert config["spotify"]["client_secret"] == "test_client_secret"
        assert "lastfm" in config
        assert config["lastfm"]["api_key"] == "test_api_key"

    def test_parse_config_missing_file(self):
        """Test parsing non-existent config file raises error."""
        with pytest.raises(FileNotFoundError):
            utils.parse_config(Path("/nonexistent/config.toml"))

    def test_parse_config_invalid_toml(self, tmp_path):
        """Test parsing invalid TOML raises error."""
        import tomllib

        invalid_file = tmp_path / "invalid.toml"
        invalid_file.write_text("this is { not valid toml")

        with pytest.raises(tomllib.TOMLDecodeError):
            utils.parse_config(invalid_file)


@pytest.mark.unit
class TestQueryDb:
    """Tests for query_db function."""

    def test_query_db_single_insert(self, temp_database):
        """Test single INSERT query."""
        queries = ["INSERT INTO tracks VALUES ('track1', 'Test Track', '2024-01-01', '2024-01-01', '2024-01-01')"]
        db_module.query_db(temp_database, queries)

        # Verify data was inserted
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        result = cursor.execute("SELECT * FROM tracks WHERE id = 'track1'").fetchone()
        conn.close()

        assert result == ("track1", "Test Track", "2024-01-01", "2024-01-01", "2024-01-01")

    def test_query_db_multiple_queries(self, temp_database):
        """Test multiple queries in one call."""
        queries = [
            "INSERT INTO tracks VALUES ('track1', 'Track 1', '2024-01-01', '2024-01-01', '2024-01-01')",
            "INSERT INTO tracks VALUES ('track2', 'Track 2', '2024-01-02', '2024-01-02', '2024-01-02')",
        ]
        db_module.query_db(temp_database, queries)

        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        count = cursor.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
        conn.close()

        assert count == 2

    def test_query_db_with_script(self, temp_database):
        """Test executescript mode."""
        queries = [
            """
            INSERT INTO tracks VALUES ('track1', 'Track 1', '2024-01-01', '2024-01-01', '2024-01-01');
            INSERT INTO tracks VALUES ('track2', 'Track 2', '2024-01-02', '2024-01-02', '2024-01-02');
            """
        ]
        db_module.query_db(temp_database, queries, script=True)

        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        count = cursor.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
        conn.close()

        assert count == 2


@pytest.mark.unit
class TestSelectDb:
    """Tests for select_db function."""

    def test_select_db_basic_query(self, temp_database):
        """Test basic SELECT query."""
        # Insert test data
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO tracks VALUES ('track1', 'Test Track', '2024-01-01', '2024-01-01', '2024-01-01')")
        conn.commit()
        conn.close()

        # Query using select_db
        result = db_module.select_db(temp_database, "SELECT name FROM tracks WHERE id = 'track1'")
        name = result.fetchone()[0]

        assert name == "Test Track"

    def test_select_db_with_params(self, temp_database):
        """Test SELECT query with parameters."""
        # Insert test data
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO tracks VALUES ('track1', 'Test Track', '2024-01-01', '2024-01-01', '2024-01-01')")
        conn.commit()
        conn.close()

        # Query with parameters (safer than f-strings)
        result = db_module.select_db(temp_database, "SELECT * FROM tracks WHERE id = ?", ("track1",))
        row = result.fetchone()

        assert row == ("track1", "Test Track", "2024-01-01", "2024-01-01", "2024-01-01")

    def test_select_db_no_results(self, temp_database):
        """Test SELECT query with no results."""
        result = db_module.select_db(temp_database, "SELECT * FROM tracks WHERE id = 'nonexistent'")
        assert result.fetchone() is None


@pytest.mark.unit
class TestQueryDbSelect:
    """Tests for query_db_select function."""

    def test_query_db_select_basic(self, temp_database):
        """Test basic SELECT query with automatic cleanup."""
        # Insert test data
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO tracks VALUES ('track1', 'Test Track', '2024-01-01', '2024-01-01', '2024-01-01')")
        cursor.execute("INSERT INTO tracks VALUES ('track2', 'Track Two', '2024-01-02', '2024-01-02', '2024-01-02')")
        conn.commit()
        conn.close()

        # Query using query_db_select
        results = db_module.query_db_select(temp_database, "SELECT * FROM tracks ORDER BY id")

        assert len(results) == 2
        assert results[0] == ("track1", "Test Track", "2024-01-01", "2024-01-01", "2024-01-01")
        assert results[1] == ("track2", "Track Two", "2024-01-02", "2024-01-02", "2024-01-02")

    def test_query_db_select_with_params(self, temp_database):
        """Test query_db_select with parameters."""
        # Insert test data
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO tracks VALUES ('track1', 'Test Track', '2024-01-01', '2024-01-01', '2024-01-01')")
        conn.commit()
        conn.close()

        # Query with parameters
        results = db_module.query_db_select(temp_database, "SELECT name FROM tracks WHERE id = ?", ("track1",))

        assert len(results) == 1
        assert results[0][0] == "Test Track"

    def test_query_db_select_no_results(self, temp_database):
        """Test query_db_select with no results."""
        results = db_module.query_db_select(temp_database, "SELECT * FROM tracks")
        assert results == []


@pytest.mark.unit
class TestQueryDbWithResults:
    """Tests for query_db with results parameter."""

    def test_query_db_with_results_true(self, temp_database):
        """Test query_db with results=True."""
        # Insert test data first
        db_module.query_db(
            temp_database,
            ["INSERT INTO tracks VALUES ('track1', 'Test Track', '2024-01-01', '2024-01-01', '2024-01-01')"],
        )

        # Query with results=True
        results = db_module.query_db(temp_database, ["SELECT * FROM tracks WHERE id = 'track1'"], results=True)

        assert results is not None
        assert len(results) == 1
        assert results[0] == ("track1", "Test Track", "2024-01-01", "2024-01-01", "2024-01-01")


@pytest.mark.unit
class TestDatabaseSwitching:
    """Tests for database connection switching."""

    def test_connection_switches_between_databases(self, tmp_path):
        """Test that connection properly switches when database changes."""
        # Create two separate databases
        db1 = tmp_path / "db1.db"
        db2 = tmp_path / "db2.db"

        # Create schema for both
        for db in [db1, db2]:
            conn = sqlite3.connect(db)
            conn.execute("CREATE TABLE test (id TEXT, value TEXT)")
            conn.commit()
            conn.close()

        # Insert different data in each database
        db_module.query_db(db1, ["INSERT INTO test VALUES ('1', 'database1')"])
        db_module.query_db(db2, ["INSERT INTO test VALUES ('2', 'database2')"])

        # Query db1
        result1 = db_module.select_db(db1, "SELECT value FROM test").fetchone()
        assert result1[0] == "database1"

        # Query db2 - should switch connection
        result2 = db_module.select_db(db2, "SELECT value FROM test").fetchone()
        assert result2[0] == "database2"

        # Query db1 again - should switch back
        result3 = db_module.select_db(db1, "SELECT value FROM test").fetchone()
        assert result3[0] == "database1"


@pytest.mark.unit
class TestGetAttr:
    """Tests for __getattr__ function."""

    def test_getattr_database(self):
        """Test accessing DATABASE via __getattr__."""
        assert db_module.DATABASE == utils.DATABASE

    def test_getattr_database_log_level(self):
        """Test accessing DATABASE_LOG_LEVEL via __getattr__."""
        assert db_module.DATABASE_LOG_LEVEL == utils.DATABASE_LOG_LEVEL

    def test_getattr_invalid_attribute(self):
        """Test that invalid attributes raise AttributeError."""
        with pytest.raises(AttributeError, match="has no attribute 'INVALID_ATTR'"):
            _ = db_module.INVALID_ATTR


@pytest.mark.unit
class TestManageTracksIdsFile:
    """Tests for manage_tracks_ids_file function."""

    def test_parse_track_ids_file(self, tmp_path):
        """Test parsing file with track IDs."""
        file_path = tmp_path / "tracks.txt"
        file_path.write_text("track1\ntrack2\ntrack3\n")

        result = utils.manage_tracks_ids_file(file_path)

        assert result == ["track1", "track2", "track3"]

    def test_parse_track_ids_with_empty_lines(self, tmp_path):
        """Test parsing file with empty lines."""
        file_path = tmp_path / "tracks.txt"
        file_path.write_text("track1\n\ntrack2\n\ntrack3\n")

        result = utils.manage_tracks_ids_file(file_path)

        assert result == ["track1", "", "track2", "", "track3"]

    def test_parse_track_ids_strips_whitespace(self, tmp_path):
        """Test that whitespace is stripped from each line."""
        file_path = tmp_path / "tracks.txt"
        file_path.write_text("  track1  \n  track2  \n  track3  \n")

        result = utils.manage_tracks_ids_file(file_path)

        assert result == ["track1", "track2", "track3"]

    def test_parse_empty_file(self, tmp_path):
        """Test parsing empty file."""
        file_path = tmp_path / "tracks.txt"
        file_path.write_text("")

        result = utils.manage_tracks_ids_file(file_path)

        assert result == []


@pytest.mark.unit
class TestCacheObject:
    """Tests for cache_object function."""

    def test_cache_object_creates_file(self, temp_cache_dir, monkeypatch):
        """Test that cache_object creates a pickle file."""
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        # Create a simple object (MagicMock can't be pickled)
        from spotfm.spotify.artist import Artist

        obj = Artist("test123")
        obj.name = "Test Artist"

        utils.cache_object(obj)

        cache_file = temp_cache_dir / "artist" / "test123.pickle"
        assert cache_file.exists()

    def test_cache_object_creates_subdirectory(self, temp_cache_dir, monkeypatch):
        """Test that cache_object creates subdirectories if needed."""
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        from spotfm.spotify.artist import Artist
        from spotfm.spotify.track import Track

        obj = Track("test123")
        obj.name = "Test Track"
        # Track needs artists to be serializable
        artist = Artist("artist1")
        artist.name = "Artist"
        artist.genres = []
        obj.artists = [artist]

        utils.cache_object(obj)

        cache_file = temp_cache_dir / "track" / "test123.pickle"
        assert cache_file.parent.exists()
        assert cache_file.exists()

    def test_cache_object_serializes_correctly(self, temp_cache_dir, monkeypatch):
        """Test that cached object can be deserialized."""
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        # Use actual spotfm class
        from spotfm.spotify.artist import Artist

        obj = Artist("test123")
        obj.name = "Test Track"

        utils.cache_object(obj)

        # Read back the pickle file
        cache_file = temp_cache_dir / "artist" / "test123.pickle"
        with open(cache_file, "rb") as f:
            loaded_obj = pickle.load(f)

        assert loaded_obj.id == "test123"
        assert loaded_obj.name == "Test Track"


@pytest.mark.unit
class TestRetrieveObjectFromCache:
    """Tests for retrieve_object_from_cache function."""

    def test_retrieve_existing_object(self, temp_cache_dir, monkeypatch):
        """Test retrieving object from cache."""
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        # Create and cache an object using actual spotfm class
        from spotfm.spotify.artist import Artist

        obj = Artist("artist123")
        obj.name = "Test Artist"

        cache_file = temp_cache_dir / "artist" / "artist123.pickle"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_file, "wb") as f:
            pickle.dump(obj, f)

        # Retrieve the object
        retrieved = utils.retrieve_object_from_cache("artist", "artist123")

        assert retrieved is not None
        assert retrieved.id == "artist123"
        assert retrieved.name == "Test Artist"

    def test_retrieve_nonexistent_object(self, temp_cache_dir, monkeypatch):
        """Test retrieving non-existent object returns None."""
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        result = utils.retrieve_object_from_cache("track", "nonexistent")

        assert result is None

    def test_retrieve_from_nonexistent_directory(self, temp_cache_dir, monkeypatch):
        """Test retrieving from non-existent kind directory."""
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        result = utils.retrieve_object_from_cache("unknown_type", "test123")

        assert result is None


@pytest.mark.unit
class TestConstants:
    """Tests for module constants."""

    def test_home_dir_is_path(self):
        """Test HOME_DIR is a Path object."""
        assert isinstance(utils.HOME_DIR, Path)

    def test_work_dir_under_home(self):
        """Test WORK_DIR is under HOME_DIR."""
        assert utils.WORK_DIR.parent == utils.HOME_DIR

    def test_cache_dir_structure(self):
        """Test CACHE_DIR structure."""
        assert utils.CACHE_DIR.parts[-2:] == (".cache", "spotfm")

    def test_config_file_path(self):
        """Test CONFIG_FILE path."""
        assert utils.CONFIG_FILE.name == "spotfm.toml"
        assert utils.CONFIG_FILE.parent == utils.WORK_DIR

    def test_database_path(self):
        """Test DATABASE path."""
        from pathlib import Path

        db_path = Path(utils.DATABASE)
        assert db_path.name == "spotify.db"
        assert db_path.parent == utils.WORK_DIR
