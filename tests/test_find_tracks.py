from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

from spotfm import sqlite
from spotfm.spotify import misc


@pytest.fixture
def mock_sqlite_select_db(monkeypatch):
    """Fixture to mock sqlite.select_db."""
    mock_db = MagicMock()
    monkeypatch.setattr(sqlite, "select_db", mock_db)
    return mock_db


@pytest.fixture
def mock_path_mkdir(monkeypatch):
    """Fixture to mock Path.parent.mkdir."""
    monkeypatch.setattr(Path, "mkdir", MagicMock())


class TestFindTracksByCriteria:
    def test_find_tracks_by_criteria_no_filters(self, mock_sqlite_select_db):
        """Test basic track retrieval without any date or genre filters."""
        # Call 1: exact ID match (returns empty for name pattern)
        mock_cursor_id = MagicMock()
        mock_cursor_id.fetchall.return_value = []
        # Call 2: LIKE pattern match (returns the playlist)
        mock_cursor_like = MagicMock()
        mock_cursor_like.fetchall.return_value = [("playlist1_id", "My Playlist")]
        # Call 3: track query
        mock_cursor_tracks = MagicMock()
        mock_cursor_tracks.fetchall.return_value = [
            ("track1_id", "Track One", "2020", "Album A", "Artist X", "pop,rock"),
            ("track2_id", "Track Two", "2021", "Album B", "Artist Y", "jazz"),
        ]
        mock_sqlite_select_db.side_effect = [mock_cursor_id, mock_cursor_like, mock_cursor_tracks]

        playlist_patterns = ["My Playlist"]
        results = misc.find_tracks_by_criteria(playlist_patterns)

        assert len(results) == 2
        assert results[0]["track_name"] == "Track One"
        assert results[1]["track_name"] == "Track Two"

        # Check the third call (track query) has the playlist ID filter
        expected_query_part = "pt.playlist_id IN (?)"
        assert expected_query_part in mock_sqlite_select_db.call_args_list[2][0][1]
        assert "WHERE" in mock_sqlite_select_db.call_args_list[2][0][1]
        assert mock_sqlite_select_db.call_args_list[2][0][2] == ("playlist1_id",)

    def test_find_tracks_by_criteria_date_range(self, mock_sqlite_select_db):
        """Test filtering by a start and end date."""
        mock_cursor_id = MagicMock()
        mock_cursor_id.fetchall.return_value = []
        mock_cursor_like = MagicMock()
        mock_cursor_like.fetchall.return_value = [("playlist1_id", "My Playlist")]
        mock_cursor_tracks = MagicMock()
        mock_cursor_tracks.fetchall.return_value = [("track1_id", "Track One", "2020", "Album A", "Artist X", "pop")]
        mock_sqlite_select_db.side_effect = [mock_cursor_id, mock_cursor_like, mock_cursor_tracks]

        playlist_patterns = ["My Playlist"]
        start_date = "2020-01-01"
        end_date = "2020-12-31"
        results = misc.find_tracks_by_criteria(playlist_patterns, start_date=start_date, end_date=end_date)

        assert len(results) == 1
        assert results[0]["track_name"] == "Track One"

        expected_query_part_playlists = "pt.playlist_id IN (?)"
        expected_query_part_dates = "al.release_date BETWEEN ? AND ?"

        query = mock_sqlite_select_db.call_args_list[2][0][1]
        assert expected_query_part_playlists in query
        assert expected_query_part_dates in query
        assert mock_sqlite_select_db.call_args_list[2][0][2] == ("playlist1_id", start_date, end_date)

    def test_find_tracks_by_criteria_genre_pattern(self, mock_sqlite_select_db):
        """Test filtering by a genre regex pattern."""
        mock_cursor_id = MagicMock()
        mock_cursor_id.fetchall.return_value = []
        mock_cursor_like = MagicMock()
        mock_cursor_like.fetchall.return_value = [("playlist1_id", "My Playlist")]
        mock_cursor_tracks = MagicMock()
        mock_cursor_tracks.fetchall.return_value = [
            ("track1_id", "Track One", "2020", "Album A", "Artist X", "pop,rock")
        ]
        mock_sqlite_select_db.side_effect = [mock_cursor_id, mock_cursor_like, mock_cursor_tracks]

        playlist_patterns = ["My Playlist"]
        genre_pattern = "rock"
        results = misc.find_tracks_by_criteria(playlist_patterns, genre_pattern=genre_pattern)

        assert len(results) == 1
        assert results[0]["track_name"] == "Track One"

        expected_query_part_genres = "LOWER(ag2.genre) REGEXP LOWER(?)"
        query = mock_sqlite_select_db.call_args_list[2][0][1]
        assert expected_query_part_genres in query
        assert mock_sqlite_select_db.call_args_list[2][0][2] == ("playlist1_id", genre_pattern)

    def test_find_tracks_by_criteria_both_filters(self, mock_sqlite_select_db):
        """Test filtering by both date range and genre pattern."""
        mock_cursor_id = MagicMock()
        mock_cursor_id.fetchall.return_value = []
        mock_cursor_like = MagicMock()
        mock_cursor_like.fetchall.return_value = [("playlist1_id", "My Playlist")]
        mock_cursor_tracks = MagicMock()
        mock_cursor_tracks.fetchall.return_value = [
            ("track1_id", "Track One", "2020", "Album A", "Artist X", "pop,rock")
        ]
        mock_sqlite_select_db.side_effect = [mock_cursor_id, mock_cursor_like, mock_cursor_tracks]

        playlist_patterns = ["My Playlist"]
        start_date = "2020-01-01"
        end_date = "2020-12-31"
        genre_pattern = "pop"
        results = misc.find_tracks_by_criteria(
            playlist_patterns, start_date=start_date, end_date=end_date, genre_pattern=genre_pattern
        )

        assert len(results) == 1
        assert results[0]["track_name"] == "Track One"

        expected_query_part_playlists = "pt.playlist_id IN (?)"
        expected_query_part_dates = "al.release_date BETWEEN ? AND ?"
        expected_query_part_genres = "LOWER(ag2.genre) REGEXP LOWER(?)"

        full_query = mock_sqlite_select_db.call_args_list[2][0][1]
        assert expected_query_part_playlists in full_query
        assert expected_query_part_dates in full_query
        assert expected_query_part_genres in full_query
        assert mock_sqlite_select_db.call_args_list[2][0][2] == ("playlist1_id", start_date, end_date, genre_pattern)

    def test_find_tracks_by_criteria_multiple_playlists(self, mock_sqlite_select_db):
        """Test searching across multiple playlist patterns."""
        mock_cursor_id = MagicMock()
        mock_cursor_id.fetchall.return_value = []
        mock_cursor_like = MagicMock()
        mock_cursor_like.fetchall.return_value = [("playlist1_id", "Playlist One"), ("playlist2_id", "Playlist Two")]
        mock_cursor_tracks = MagicMock()
        mock_cursor_tracks.fetchall.return_value = [("track1_id", "Track One", "2020", "Album A", "Artist X", "pop")]
        mock_sqlite_select_db.side_effect = [mock_cursor_id, mock_cursor_like, mock_cursor_tracks]

        playlist_patterns = ["Playlist%"]
        results = misc.find_tracks_by_criteria(playlist_patterns)

        assert len(results) == 1
        assert results[0]["track_name"] == "Track One"

        expected_query_part = "pt.playlist_id IN (?,?)"
        assert expected_query_part in mock_sqlite_select_db.call_args_list[2][0][1]
        assert mock_sqlite_select_db.call_args_list[2][0][2] == ("playlist1_id", "playlist2_id")

    @patch("builtins.open", new_callable=mock_open)
    @patch("pathlib.Path.mkdir")
    def test_find_tracks_by_criteria_output_csv(self, mock_mkdir, mock_open_file, mock_sqlite_select_db):
        """Test that the results are correctly written to a CSV file when output_file is provided."""
        mock_cursor_id = MagicMock()
        mock_cursor_id.fetchall.return_value = []
        mock_cursor_like = MagicMock()
        mock_cursor_like.fetchall.return_value = [("playlist1_id", "My Playlist")]
        mock_cursor_tracks = MagicMock()
        mock_cursor_tracks.fetchall.return_value = [
            ("track1_id", "Track One", "2020", "Album A", "Artist X", "pop,rock")
        ]
        mock_sqlite_select_db.side_effect = [mock_cursor_id, mock_cursor_like, mock_cursor_tracks]

        playlist_patterns = ["My Playlist"]
        output_file = "output.csv"
        misc.find_tracks_by_criteria(playlist_patterns, output_file=output_file)

        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)
        mock_open_file.assert_called_once_with(Path(output_file), "w", newline="")
        handle = mock_open_file()
        handle.write.assert_any_call("Artist(s);Track Name;Album Name;Release Year;Genre(s);Track ID\r\n")
        handle.write.assert_any_call("Artist X;Track One;Album A;2020;pop,rock;track1_id\r\n")

    def test_find_tracks_by_criteria_empty_playlist_patterns(self, mock_sqlite_select_db):
        """Test behavior when an empty list of playlist patterns is provided."""
        playlist_patterns = []
        results = misc.find_tracks_by_criteria(playlist_patterns)

        assert results == []
        mock_sqlite_select_db.assert_not_called()

    def test_find_tracks_by_criteria_no_matching_playlists(self, mock_sqlite_select_db):
        """Test when no playlists match the pattern."""
        # First call: exact ID match (returns empty)
        mock_cursor1 = MagicMock()
        mock_cursor1.fetchall.return_value = []
        # Second call: LIKE pattern match (returns empty)
        mock_cursor2 = MagicMock()
        mock_cursor2.fetchall.return_value = []
        mock_sqlite_select_db.side_effect = [mock_cursor1, mock_cursor2]

        playlist_patterns = ["Nonexistent%"]
        results = misc.find_tracks_by_criteria(playlist_patterns)

        assert results == []
        assert mock_sqlite_select_db.call_count == 2  # Exact ID lookup + LIKE pattern lookup

    def test_find_tracks_by_criteria_no_tracks_match(self, mock_sqlite_select_db):
        """Test when no tracks match the criteria."""
        mock_cursor_id = MagicMock()
        mock_cursor_id.fetchall.return_value = []
        mock_cursor_like = MagicMock()
        mock_cursor_like.fetchall.return_value = [("playlist1_id", "My Playlist")]
        mock_cursor_tracks = MagicMock()
        mock_cursor_tracks.fetchall.return_value = []  # No tracks match
        mock_sqlite_select_db.side_effect = [mock_cursor_id, mock_cursor_like, mock_cursor_tracks]

        playlist_patterns = ["My Playlist"]
        results = misc.find_tracks_by_criteria(playlist_patterns, genre_pattern="nonexistent")

        assert results == []
        assert mock_sqlite_select_db.call_count == 3

    def test_find_tracks_by_criteria_with_playlist_id(self, mock_sqlite_select_db):
        """Test using a direct playlist ID (22 alphanumeric chars)."""
        # When using a playlist ID, it fetches the name from DB first
        mock_cursor_name = MagicMock()
        mock_cursor_name.fetchone.return_value = ("My Playlist",)
        mock_cursor_tracks = MagicMock()
        mock_cursor_tracks.fetchall.return_value = [("track1_id", "Track One", "2020", "Album A", "Artist X", "pop")]
        mock_sqlite_select_db.side_effect = [mock_cursor_name, mock_cursor_tracks]

        # 22 alphanumeric characters - treated as a direct playlist ID
        playlist_id = "3iunZ1EyEIWUv3irhm1Au1"
        results = misc.find_tracks_by_criteria([playlist_id])

        assert len(results) == 1
        assert results[0]["track_name"] == "Track One"

        # First call gets playlist name, second call gets tracks
        assert mock_sqlite_select_db.call_count == 2
        assert "pt.playlist_id IN (?)" in mock_sqlite_select_db.call_args_list[1][0][1]
        assert mock_sqlite_select_db.call_args_list[1][0][2] == (playlist_id,)
