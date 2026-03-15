"""Unit tests for spotfm.spotify.misc module."""

import sqlite3
from unittest.mock import MagicMock

import pytest

from spotfm import sqlite, utils
from spotfm.spotify import misc


@pytest.mark.unit
class TestFindRelinkedTracks:
    """Tests for find_relinked_tracks function."""

    def test_find_relinked_tracks_none_found(self, temp_database, monkeypatch):
        """Test when no relinked tracks are found."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(sqlite, "DATABASE", temp_database)

        # Setup database with a playlist
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO playlists VALUES ('playlist1', 'Test Playlist', 'user123', '2024-01-01')")
        conn.commit()
        conn.close()

        # Mock Spotify client
        mock_client = MagicMock()
        mock_client.playlist_items.return_value = {
            "items": [
                {
                    "track": {
                        "id": "track1",
                        "name": "Track 1",
                        "artists": [{"name": "Artist 1"}],
                        # No linked_from field
                    },
                    "added_at": "2024-01-01T00:00:00Z",
                }
            ],
            "next": None,
        }

        result = misc.find_relinked_tracks(mock_client)

        assert len(result) == 0
        mock_client.playlist_items.assert_called_once()

    def test_find_relinked_tracks_with_relinked_track(self, temp_database, monkeypatch):
        """Test finding a relinked track."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(sqlite, "DATABASE", temp_database)

        # Setup database with a playlist
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO playlists VALUES ('playlist1', 'Test Playlist', 'user123', '2024-01-01')")
        conn.commit()
        conn.close()

        # Mock Spotify client
        mock_client = MagicMock()
        mock_client.playlist_items.return_value = {
            "items": [
                {
                    "track": {
                        "id": "replacement_track_id",
                        "name": "Replacement Track",
                        "artists": [{"name": "Replacement Artist"}],
                        "linked_from": {"id": "original_track_id"},
                    },
                    "added_at": "2024-01-01T00:00:00Z",
                }
            ],
            "next": None,
        }

        # Mock fetching the original track details
        mock_client.track.return_value = {
            "id": "original_track_id",
            "name": "Original Track",
            "artists": [{"name": "Original Artist"}],
        }

        result = misc.find_relinked_tracks(mock_client)

        assert len(result) == 1
        assert result[0]["playlist_name"] == "Test Playlist"
        assert result[0]["original_id"] == "original_track_id"
        assert result[0]["replacement_id"] == "replacement_track_id"
        assert result[0]["original_track"] == "Original Artist - Original Track"
        assert result[0]["replacement_track"] == "Replacement Artist - Replacement Track"

    def test_find_relinked_tracks_excludes_playlists(self, temp_database, monkeypatch):
        """Test that excluded playlists are not checked."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(sqlite, "DATABASE", temp_database)

        # Setup database with two playlists
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO playlists VALUES ('playlist1', 'Test Playlist 1', 'user123', '2024-01-01')")
        cursor.execute("INSERT INTO playlists VALUES ('playlist2', 'Test Playlist 2', 'user123', '2024-01-01')")
        conn.commit()
        conn.close()

        # Mock Spotify client
        mock_client = MagicMock()
        mock_client.playlist_items.return_value = {"items": [], "next": None}

        misc.find_relinked_tracks(mock_client, excluded_playlist_ids=["playlist2"])

        # Should only call playlist_items once (for playlist1)
        assert mock_client.playlist_items.call_count == 1
        call_args = mock_client.playlist_items.call_args[0]
        assert call_args[0] == "playlist1"

    def test_find_relinked_tracks_handles_null_tracks(self, temp_database, monkeypatch):
        """Test that null tracks are handled gracefully."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(sqlite, "DATABASE", temp_database)

        # Setup database with a playlist
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO playlists VALUES ('playlist1', 'Test Playlist', 'user123', '2024-01-01')")
        conn.commit()
        conn.close()

        # Mock Spotify client with null track
        mock_client = MagicMock()
        mock_client.playlist_items.return_value = {
            "items": [{"track": None, "added_at": "2024-01-01T00:00:00Z"}],
            "next": None,
        }

        result = misc.find_relinked_tracks(mock_client)

        assert len(result) == 0

    def test_find_relinked_tracks_handles_pagination(self, temp_database, monkeypatch):
        """Test that pagination is handled correctly."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(sqlite, "DATABASE", temp_database)

        # Setup database with a playlist
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO playlists VALUES ('playlist1', 'Test Playlist', 'user123', '2024-01-01')")
        conn.commit()
        conn.close()

        # Mock Spotify client with pagination
        mock_client = MagicMock()

        # First page
        first_page = {
            "items": [
                {
                    "track": {
                        "id": "replacement1",
                        "name": "Track 1",
                        "artists": [{"name": "Artist 1"}],
                        "linked_from": {"id": "original1"},
                    },
                    "added_at": "2024-01-01T00:00:00Z",
                }
            ],
            "next": "next_url",
        }

        # Second page
        second_page = {
            "items": [
                {
                    "track": {
                        "id": "replacement2",
                        "name": "Track 2",
                        "artists": [{"name": "Artist 2"}],
                        "linked_from": {"id": "original2"},
                    },
                    "added_at": "2024-01-02T00:00:00Z",
                }
            ],
            "next": None,
        }

        mock_client.playlist_items.return_value = first_page
        mock_client.next.return_value = second_page
        mock_client.track.side_effect = [
            {"name": "Original 1", "artists": [{"name": "Orig Artist 1"}]},
            {"name": "Original 2", "artists": [{"name": "Orig Artist 2"}]},
        ]

        result = misc.find_relinked_tracks(mock_client)

        assert len(result) == 2
        assert result[0]["original_id"] == "original1"
        assert result[1]["original_id"] == "original2"
        mock_client.next.assert_called_once()

    def test_find_relinked_tracks_handles_fetch_error(self, temp_database, monkeypatch):
        """Test that errors fetching original track are handled gracefully."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(sqlite, "DATABASE", temp_database)

        # Setup database with a playlist
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO playlists VALUES ('playlist1', 'Test Playlist', 'user123', '2024-01-01')")
        conn.commit()
        conn.close()

        # Mock Spotify client
        mock_client = MagicMock()
        mock_client.playlist_items.return_value = {
            "items": [
                {
                    "track": {
                        "id": "replacement_track_id",
                        "name": "Replacement Track",
                        "artists": [{"name": "Replacement Artist"}],
                        "linked_from": {"id": "original_track_id"},
                    },
                    "added_at": "2024-01-01T00:00:00Z",
                }
            ],
            "next": None,
        }

        # Mock track fetch to raise an exception
        mock_client.track.side_effect = Exception("Track not found")

        result = misc.find_relinked_tracks(mock_client)

        assert len(result) == 1
        assert result[0]["original_track"] == "Unknown - Unknown"

    def test_find_relinked_tracks_skips_same_metadata(self, temp_database, monkeypatch):
        """Test that relinked tracks with identical metadata are not reported."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(sqlite, "DATABASE", temp_database)

        # Setup database with a playlist
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO playlists VALUES ('playlist1', 'Test Playlist', 'user123', '2024-01-01')")
        conn.commit()
        conn.close()

        # Mock Spotify client with a relinked track that has identical metadata
        mock_client = MagicMock()
        mock_client.playlist_items.return_value = {
            "items": [
                {
                    "track": {
                        "id": "replacement_track_id",
                        "name": "Same Track Name",
                        "artists": [{"name": "Same Artist"}],
                        "linked_from": {"id": "original_track_id"},
                    },
                    "added_at": "2024-01-01T00:00:00Z",
                }
            ],
            "next": None,
        }

        # Mock fetching the original track - same metadata as replacement
        mock_client.track.return_value = {
            "id": "original_track_id",
            "name": "Same Track Name",
            "artists": [{"name": "Same Artist"}],
        }

        result = misc.find_relinked_tracks(mock_client)

        # Should not report this relinked track since metadata is identical
        assert len(result) == 0

    def test_find_relinked_tracks_outputs_to_csv(self, temp_database, tmp_path, monkeypatch):
        """Test that results are written to CSV file."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(sqlite, "DATABASE", temp_database)

        # Setup database with a playlist
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO playlists VALUES ('playlist1', 'Test Playlist', 'user123', '2024-01-01')")
        conn.commit()
        conn.close()

        # Mock Spotify client
        mock_client = MagicMock()
        mock_client.playlist_items.return_value = {
            "items": [
                {
                    "track": {
                        "id": "replacement_track_id",
                        "name": "Replacement Track",
                        "artists": [{"name": "Replacement Artist"}],
                        "linked_from": {"id": "original_track_id"},
                    },
                    "added_at": "2024-01-01T00:00:00Z",
                }
            ],
            "next": None,
        }

        mock_client.track.return_value = {
            "id": "original_track_id",
            "name": "Original Track",
            "artists": [{"name": "Original Artist"}],
        }

        output_file = tmp_path / "relinked.csv"
        misc.find_relinked_tracks(mock_client, output_file=str(output_file))

        # Verify CSV was created
        assert output_file.exists()

        # Verify CSV content
        content = output_file.read_text()
        assert "Test Playlist" in content
        assert "Original Artist - Original Track" in content
        assert "Replacement Artist - Replacement Track" in content
        assert "original_track_id" in content
        assert "replacement_track_id" in content


@pytest.mark.unit
class TestWriteRelinkedTracksCsv:
    """Tests for write_relinked_tracks_csv function."""

    def test_write_csv_creates_file(self, tmp_path):
        """Test that CSV file is created."""
        output_file = tmp_path / "output.csv"

        relinked_tracks = [
            {
                "playlist_name": "Test Playlist",
                "original_track": "Artist 1 - Track 1",
                "original_id": "track1",
                "replacement_track": "Artist 2 - Track 2",
                "replacement_id": "track2",
                "added_at": "2024-01-01T00:00:00Z",
            }
        ]

        misc.write_relinked_tracks_csv(relinked_tracks, str(output_file))

        assert output_file.exists()

    def test_write_csv_creates_parent_directory(self, tmp_path):
        """Test that parent directories are created if needed."""
        output_file = tmp_path / "subdir" / "output.csv"

        relinked_tracks = [
            {
                "playlist_name": "Test Playlist",
                "original_track": "Artist 1 - Track 1",
                "original_id": "track1",
                "replacement_track": "Artist 2 - Track 2",
                "replacement_id": "track2",
                "added_at": "2024-01-01T00:00:00Z",
            }
        ]

        misc.write_relinked_tracks_csv(relinked_tracks, str(output_file))

        assert output_file.exists()
        assert output_file.parent.exists()

    def test_write_csv_content_format(self, tmp_path):
        """Test that CSV content is formatted correctly."""
        output_file = tmp_path / "output.csv"

        relinked_tracks = [
            {
                "playlist_name": "My Playlist",
                "original_track": "Original Artist - Original Song",
                "original_id": "orig123",
                "replacement_track": "New Artist - New Song",
                "replacement_id": "new456",
                "added_at": "2024-01-15T10:30:00Z",
            }
        ]

        misc.write_relinked_tracks_csv(relinked_tracks, str(output_file))

        content = output_file.read_text()
        lines = content.strip().split("\n")

        # Check header
        assert "Playlist;Original Track;Original ID;Replacement Track;Replacement ID;Added At" in lines[0]

        # Check data row
        assert (
            "My Playlist;Original Artist - Original Song;orig123;New Artist - New Song;new456;2024-01-15T10:30:00Z"
            in lines[1]
        )


@pytest.mark.unit
class TestCountTracks:
    """Tests for count_tracks function."""

    def test_count_tracks_no_pattern(self, temp_database, monkeypatch):
        """Test counting all tracks without a pattern."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(sqlite, "DATABASE", temp_database)

        # Setup database with playlists and tracks
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO playlists VALUES ('p1', 'Playlist 1', 'user1', '2024-01-01')")
        cursor.execute("INSERT INTO playlists VALUES ('p2', 'Playlist 2', 'user1', '2024-01-01')")
        cursor.execute("INSERT INTO playlists_tracks VALUES ('p1', 't1', '2024-01-01')")
        cursor.execute("INSERT INTO playlists_tracks VALUES ('p1', 't2', '2024-01-01')")
        cursor.execute("INSERT INTO playlists_tracks VALUES ('p2', 't1', '2024-01-01')")  # Same track in p2
        cursor.execute("INSERT INTO playlists_tracks VALUES ('p2', 't3', '2024-01-01')")
        conn.commit()
        conn.close()

        result = misc.count_tracks()

        # Should return 3 unique tracks (t1, t2, t3)
        assert result == 3

    def test_count_tracks_single_pattern_as_list(self, temp_database, monkeypatch):
        """Test counting tracks with a single pattern passed as list."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(sqlite, "DATABASE", temp_database)

        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO playlists VALUES ('p1', 'IR Playlist', 'user1', '2024-01-01')")
        cursor.execute("INSERT INTO playlists VALUES ('p2', 'Other', 'user1', '2024-01-01')")
        cursor.execute("INSERT INTO playlists_tracks VALUES ('p1', 't1', '2024-01-01')")
        cursor.execute("INSERT INTO playlists_tracks VALUES ('p1', 't2', '2024-01-01')")
        cursor.execute("INSERT INTO playlists_tracks VALUES ('p2', 't3', '2024-01-01')")
        conn.commit()
        conn.close()

        # Pass pattern as list (how argparse provides it with nargs="+")
        result = misc.count_tracks(["IR%"])

        assert result == 2

    def test_count_tracks_single_pattern_as_string(self, temp_database, monkeypatch):
        """Test counting tracks with a single pattern passed as string."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(sqlite, "DATABASE", temp_database)

        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO playlists VALUES ('p1', 'IR Playlist', 'user1', '2024-01-01')")
        cursor.execute("INSERT INTO playlists VALUES ('p2', 'Other', 'user1', '2024-01-01')")
        cursor.execute("INSERT INTO playlists_tracks VALUES ('p1', 't1', '2024-01-01')")
        cursor.execute("INSERT INTO playlists_tracks VALUES ('p1', 't2', '2024-01-01')")
        cursor.execute("INSERT INTO playlists_tracks VALUES ('p2', 't3', '2024-01-01')")
        conn.commit()
        conn.close()

        # Pass pattern as string (for backwards compatibility)
        result = misc.count_tracks("IR%")

        assert result == 2

    def test_count_tracks_multiple_patterns(self, temp_database, monkeypatch):
        """Test counting tracks with multiple patterns."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(sqlite, "DATABASE", temp_database)

        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO playlists VALUES ('p1', 'IR Playlist', 'user1', '2024-01-01')")
        cursor.execute("INSERT INTO playlists VALUES ('p2', 'Jazz Hits', 'user1', '2024-01-01')")
        cursor.execute("INSERT INTO playlists VALUES ('p3', 'Rock', 'user1', '2024-01-01')")
        cursor.execute("INSERT INTO playlists_tracks VALUES ('p1', 't1', '2024-01-01')")
        cursor.execute("INSERT INTO playlists_tracks VALUES ('p2', 't2', '2024-01-01')")
        cursor.execute("INSERT INTO playlists_tracks VALUES ('p3', 't3', '2024-01-01')")
        conn.commit()
        conn.close()

        # Multiple patterns matching IR and Jazz
        result = misc.count_tracks(["IR%", "Jazz%"])

        assert result == 2

    def test_count_tracks_no_matching_playlists(self, temp_database, monkeypatch):
        """Test counting tracks when no playlists match the pattern."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(sqlite, "DATABASE", temp_database)

        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO playlists VALUES ('p1', 'Rock', 'user1', '2024-01-01')")
        cursor.execute("INSERT INTO playlists_tracks VALUES ('p1', 't1', '2024-01-01')")
        conn.commit()
        conn.close()

        result = misc.count_tracks(["NonExistent%"])

        assert result == 0

    def test_count_tracks_deduplicates_across_playlists(self, temp_database, monkeypatch):
        """Test that tracks appearing in multiple matching playlists are counted once."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(sqlite, "DATABASE", temp_database)

        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO playlists VALUES ('p1', 'IR A', 'user1', '2024-01-01')")
        cursor.execute("INSERT INTO playlists VALUES ('p2', 'IR B', 'user1', '2024-01-01')")
        # Same track in both playlists
        cursor.execute("INSERT INTO playlists_tracks VALUES ('p1', 't1', '2024-01-01')")
        cursor.execute("INSERT INTO playlists_tracks VALUES ('p2', 't1', '2024-01-01')")
        conn.commit()
        conn.close()

        result = misc.count_tracks(["IR%"])

        # Should count t1 only once even though it's in both playlists
        assert result == 1


@pytest.mark.unit
class TestListPlaylistsWithTrackCounts:
    def test_returns_correct_format_and_order(self, mock_sqlite_select_db):
        """Test that the function returns data in the correct format and order."""
        mock_sqlite_select_db.return_value.fetchall.return_value = [
            ("Playlist A", "id_A", 5),
            ("Playlist B", "id_B", 15),
            ("Playlist C", "id_C", 10),
        ]

        result = misc.list_playlists_with_track_counts()

        # The SQL query applies ORDER BY p.name COLLATE NOCASE, so this mock data is already in expected output order
        assert result == [
            ("Playlist A", "id_A", 5),
            ("Playlist B", "id_B", 15),
            ("Playlist C", "id_C", 10),
        ]
        mock_sqlite_select_db.assert_called_once()
        # Check key SQL clauses are present (normalized whitespace)
        query = " ".join(mock_sqlite_select_db.call_args[0][1].split())
        assert "SELECT p.name, p.id, COUNT(pt.track_id) AS track_count" in query
        assert "FROM playlists AS p" in query
        assert "LEFT JOIN playlists_tracks AS pt ON p.id = pt.playlist_id" in query
        assert "GROUP BY p.id, p.name" in query
        assert "ORDER BY p.name COLLATE NOCASE" in query

    def test_empty_database(self, mock_sqlite_select_db):
        """Test with an empty database."""
        mock_sqlite_select_db.return_value.fetchall.return_value = []

        result = misc.list_playlists_with_track_counts()
        assert result == []
        mock_sqlite_select_db.assert_called_once()

    def test_playlists_without_tracks(self, mock_sqlite_select_db):
        """Test with playlists that have no tracks."""
        mock_sqlite_select_db.return_value.fetchall.return_value = [
            ("Empty Playlist", "id_empty", 0),
            ("Has Tracks", "id_full", 20),
        ]

        result = misc.list_playlists_with_track_counts()
        assert result == [
            ("Empty Playlist", "id_empty", 0),
            ("Has Tracks", "id_full", 20),
        ]
        mock_sqlite_select_db.assert_called_once()


@pytest.mark.unit
class TestRemoveTracksFromFile:
    """Tests for remove_tracks_from_file function."""

    def test_remove_tracks_from_file(self, temp_database, temp_cache_dir, tmp_path, monkeypatch, mock_spotify_client):
        """Test removing tracks from a playlist via file."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(sqlite, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        # Setup database with a playlist and tracks
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO playlists VALUES ('playlist123', 'Test Playlist', 'user123', '2024-01-01')")
        cursor.execute("INSERT INTO playlists_tracks VALUES ('playlist123', 'track1', '2024-01-01T00:00:00Z')")
        cursor.execute("INSERT INTO playlists_tracks VALUES ('playlist123', 'track2', '2024-01-01T00:00:00Z')")
        cursor.execute("INSERT INTO tracks VALUES ('track1', 'Track 1', '2024-01-01', '2024-01-01', '2024-01-01')")
        cursor.execute("INSERT INTO tracks VALUES ('track2', 'Track 2', '2024-01-01', '2024-01-01', '2024-01-01')")
        conn.commit()
        conn.close()

        # Create a file with track IDs to remove
        file_path = tmp_path / "remove.txt"
        file_path.write_text("track1\ntrack2\n")

        # Create mock client
        client = MagicMock()
        client.client = mock_spotify_client

        # Call the function
        misc.remove_tracks_from_file(client, "playlist123", str(file_path))

        # Verify playlist_remove_all_occurrences_of_items was called
        mock_spotify_client.playlist_remove_all_occurrences_of_items.assert_called_once()

        # Verify tracks were removed from DB
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        remaining = cursor.execute("SELECT track_id FROM playlists_tracks WHERE playlist_id = 'playlist123'").fetchall()
        conn.close()

        assert len(remaining) == 0

    def test_remove_tracks_preserves_tracks_table(
        self, temp_database, temp_cache_dir, tmp_path, monkeypatch, mock_spotify_client
    ):
        """Test that remove_tracks_from_file doesn't delete from tracks table."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(sqlite, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        # Setup database
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO playlists VALUES ('playlist123', 'Test Playlist', 'user123', '2024-01-01')")
        cursor.execute("INSERT INTO playlists_tracks VALUES ('playlist123', 'track1', '2024-01-01T00:00:00Z')")
        cursor.execute("INSERT INTO tracks VALUES ('track1', 'Track 1', '2024-01-01', '2024-01-01', '2024-01-01')")
        conn.commit()
        conn.close()

        # Create file with track ID
        file_path = tmp_path / "remove.txt"
        file_path.write_text("track1\n")

        # Create mock client
        client = MagicMock()
        client.client = mock_spotify_client

        # Call the function
        misc.remove_tracks_from_file(client, "playlist123", str(file_path))

        # Verify track still exists in tracks table (orphaned)
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        track = cursor.execute("SELECT id FROM tracks WHERE id = 'track1'").fetchone()
        conn.close()

        assert track is not None
        assert track[0] == "track1"

    def test_remove_tracks_from_file_with_urls(
        self, temp_database, temp_cache_dir, tmp_path, monkeypatch, mock_spotify_client
    ):
        """Test removing tracks using Spotify URLs."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(sqlite, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        # Setup database
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO playlists VALUES ('playlist123', 'Test Playlist', 'user123', '2024-01-01')")
        cursor.execute("INSERT INTO playlists_tracks VALUES ('playlist123', 'track1', '2024-01-01T00:00:00Z')")
        cursor.execute("INSERT INTO tracks VALUES ('track1', 'Track 1', '2024-01-01', '2024-01-01', '2024-01-01')")
        conn.commit()
        conn.close()

        # Create file with Spotify URL
        file_path = tmp_path / "remove.txt"
        file_path.write_text("spotify:track:track1\n")

        # Create mock client
        client = MagicMock()
        client.client = mock_spotify_client

        # Call the function
        misc.remove_tracks_from_file(client, "playlist123", str(file_path))

        # Verify playlist_remove_all_occurrences_of_items was called with parsed track ID
        mock_spotify_client.playlist_remove_all_occurrences_of_items.assert_called_once()
        call_args = mock_spotify_client.playlist_remove_all_occurrences_of_items.call_args[0]
        assert call_args[1] == ["track1"]  # URL parsed to track ID

    def test_remove_tracks_from_file_empty_file(
        self, temp_database, temp_cache_dir, tmp_path, monkeypatch, mock_spotify_client
    ):
        """Test that empty/whitespace-only files don't trigger API calls or DB mutations."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(sqlite, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        # Setup database
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO playlists VALUES ('playlist123', 'Test Playlist', 'user123', '2024-01-01')")
        cursor.execute("INSERT INTO playlists_tracks VALUES ('playlist123', 'track1', '2024-01-01T00:00:00Z')")
        conn.commit()
        conn.close()

        # Create file with only blank lines and whitespace
        file_path = tmp_path / "empty.txt"
        file_path.write_text("\n\n  \n\t\n")

        # Create mock client
        client = MagicMock()
        client.client = mock_spotify_client

        # Call the function
        misc.remove_tracks_from_file(client, "playlist123", str(file_path))

        # Verify no API calls were made
        mock_spotify_client.playlist_remove_all_occurrences_of_items.assert_not_called()

        # Verify no DB changes were made
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        remaining = cursor.execute("SELECT track_id FROM playlists_tracks WHERE playlist_id = 'playlist123'").fetchall()
        conn.close()

        assert len(remaining) == 1
        assert remaining[0][0] == "track1"


@pytest.mark.unit
class TestLogTrackCounts:
    """Tests for log_track_counts function."""

    def test_log_track_counts_creates_file_with_headers(self, temp_database, tmp_path, monkeypatch):
        """Test that log file is created with correct headers on first run."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(sqlite, "DATABASE", temp_database)

        # Setup database with some tracks
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO playlists VALUES ('p1', 'Playlist 1', 'user1', '2024-01-01')")
        cursor.execute("INSERT INTO playlists_tracks VALUES ('p1', 't1', '2024-01-01')")
        cursor.execute("INSERT INTO playlists_tracks VALUES ('p1', 't2', '2024-01-01')")
        conn.commit()
        conn.close()

        log_file = tmp_path / "track-counts.csv"
        config = {"spotify": {"track_counts_log": str(log_file)}}

        misc.log_track_counts(config)

        # Verify file was created
        assert log_file.exists()

        # Verify content has header and one row
        content = log_file.read_text()
        lines = content.strip().split("\n")
        assert len(lines) == 2  # header + one data row
        assert lines[0] == "timestamp;total_tracks;ir_tracks"

    def test_log_track_counts_appends_on_subsequent_runs(self, temp_database, tmp_path, monkeypatch):
        """Test that subsequent calls append new rows without duplicating headers."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(sqlite, "DATABASE", temp_database)

        # Setup database
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO playlists VALUES ('p1', 'Test', 'user1', '2024-01-01')")
        cursor.execute("INSERT INTO playlists_tracks VALUES ('p1', 't1', '2024-01-01')")
        conn.commit()
        conn.close()

        log_file = tmp_path / "track-counts.csv"
        config = {"spotify": {"track_counts_log": str(log_file)}}

        # First call
        misc.log_track_counts(config)
        first_content = log_file.read_text()
        first_lines = first_content.strip().split("\n")
        assert len(first_lines) == 2  # header + one row

        # Second call
        misc.log_track_counts(config)
        second_content = log_file.read_text()
        second_lines = second_content.strip().split("\n")

        # Should have header + 2 data rows (header should not be duplicated)
        assert len(second_lines) == 3
        assert second_lines[0] == "timestamp;total_tracks;ir_tracks"
        # Both data rows should be valid CSV rows (contain semicolons)
        assert ";" in second_lines[1]
        assert ";" in second_lines[2]

    def test_log_track_counts_uses_default_path(self, temp_database, monkeypatch, tmp_path):
        """Test that default path is ~/.spotfm/track-counts.csv when no config provided."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(sqlite, "DATABASE", temp_database)
        # Mock the utils.WORK_DIR to a temp location for testing
        mock_work_dir = tmp_path / ".spotfm"
        monkeypatch.setattr(utils, "WORK_DIR", mock_work_dir)

        # Setup database
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO playlists VALUES ('p1', 'Test', 'user1', '2024-01-01')")
        cursor.execute("INSERT INTO playlists_tracks VALUES ('p1', 't1', '2024-01-01')")
        conn.commit()
        conn.close()

        # Call without config
        misc.log_track_counts()

        # Verify default location was used
        expected_log = mock_work_dir / "track-counts.csv"
        assert expected_log.exists()

    def test_log_track_counts_respects_custom_path(self, temp_database, tmp_path, monkeypatch):
        """Test that custom path from config is used."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(sqlite, "DATABASE", temp_database)

        # Setup database
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO playlists VALUES ('p1', 'Test', 'user1', '2024-01-01')")
        cursor.execute("INSERT INTO playlists_tracks VALUES ('p1', 't1', '2024-01-01')")
        conn.commit()
        conn.close()

        custom_log = tmp_path / "subdir" / "my-counts.csv"
        config = {"spotify": {"track_counts_log": str(custom_log)}}

        misc.log_track_counts(config)

        # Verify custom location was used
        assert custom_log.exists()
        assert custom_log.parent.exists()

    def test_log_track_counts_tracks_ir_playlist_counts(self, temp_database, tmp_path, monkeypatch):
        """Test that IR-prefixed playlists are counted correctly."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(sqlite, "DATABASE", temp_database)

        # Setup database with IR and non-IR playlists
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO playlists VALUES ('ir1', 'IR Playlist', 'user1', '2024-01-01')")
        cursor.execute("INSERT INTO playlists VALUES ('p2', 'Regular Playlist', 'user1', '2024-01-01')")
        cursor.execute("INSERT INTO playlists_tracks VALUES ('ir1', 't1', '2024-01-01')")
        cursor.execute("INSERT INTO playlists_tracks VALUES ('ir1', 't2', '2024-01-01')")
        cursor.execute("INSERT INTO playlists_tracks VALUES ('p2', 't3', '2024-01-01')")
        conn.commit()
        conn.close()

        log_file = tmp_path / "track-counts.csv"
        config = {"spotify": {"track_counts_log": str(log_file)}}

        misc.log_track_counts(config)

        content = log_file.read_text()
        lines = content.strip().split("\n")
        data = lines[1].split(";")

        # total_tracks = 3, ir_tracks = 2
        assert data[1] == "3"  # total_tracks
        assert data[2] == "2"  # ir_tracks

    def test_log_track_counts_handles_empty_file(self, temp_database, tmp_path, monkeypatch):
        """Test that empty pre-existing file gets headers written."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(sqlite, "DATABASE", temp_database)

        # Setup database
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO playlists VALUES ('p1', 'Test', 'user1', '2024-01-01')")
        cursor.execute("INSERT INTO playlists_tracks VALUES ('p1', 't1', '2024-01-01')")
        conn.commit()
        conn.close()

        log_file = tmp_path / "track-counts.csv"
        # Create empty file
        log_file.touch()

        config = {"spotify": {"track_counts_log": str(log_file)}}
        misc.log_track_counts(config)

        content = log_file.read_text()
        lines = content.strip().split("\n")

        # Should have header + one row (even though file existed)
        assert len(lines) == 2
        assert lines[0] == "timestamp;total_tracks;ir_tracks"

    def test_log_track_counts_rejects_empty_config_path(self, temp_database, monkeypatch):
        """Test that empty string path in config raises ValueError."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(sqlite, "DATABASE", temp_database)

        config = {"spotify": {"track_counts_log": ""}}

        with pytest.raises(ValueError, match="Invalid track_counts_log"):
            misc.log_track_counts(config)

    def test_log_track_counts_rejects_directory_path(self, temp_database, tmp_path, monkeypatch):
        """Test that directory path in config raises ValueError."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(sqlite, "DATABASE", temp_database)

        # Create a directory
        dir_path = tmp_path / "mydir"
        dir_path.mkdir()

        config = {"spotify": {"track_counts_log": str(dir_path)}}

        with pytest.raises(ValueError, match="must be a file path, not a directory"):
            misc.log_track_counts(config)

    def test_log_track_counts_creates_parent_directories(self, temp_database, tmp_path, monkeypatch):
        """Test that parent directories are created if they don't exist."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(sqlite, "DATABASE", temp_database)

        # Setup database
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO playlists VALUES ('p1', 'Test', 'user1', '2024-01-01')")
        cursor.execute("INSERT INTO playlists_tracks VALUES ('p1', 't1', '2024-01-01')")
        conn.commit()
        conn.close()

        # Use a path with non-existent parent directories
        log_file = tmp_path / "a" / "b" / "c" / "track-counts.csv"
        config = {"spotify": {"track_counts_log": str(log_file)}}

        misc.log_track_counts(config)

        # Verify file was created and all parent directories exist
        assert log_file.exists()
        assert log_file.parent.exists()
