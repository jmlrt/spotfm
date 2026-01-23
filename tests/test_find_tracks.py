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
        mock_sqlite_select_db.return_value.fetchall.return_value = [
            ("track1_id", "Track One", "2020", "Album A", "Artist X", "pop,rock"),
            ("track2_id", "Track Two", "2021", "Album B", "Artist Y", "jazz"),
        ]
        playlist_ids = ["playlist1"]
        results = misc.find_tracks_by_criteria(playlist_ids)

        assert len(results) == 2
        assert results[0]["track_name"] == "Track One"
        assert results[1]["track_name"] == "Track Two"

        expected_query_part = f"pt.playlist_id IN ({','.join(['?'] * len(playlist_ids))})"
        assert (
            expected_query_part in mock_sqlite_select_db.call_args[0][1]
        )  # Ensure WHERE clause exists for playlist filter
        assert "WHERE" in mock_sqlite_select_db.call_args[0][1]  # Ensure WHERE clause exists for playlist filter
        assert mock_sqlite_select_db.call_args[0][2] == tuple(playlist_ids)

    def test_find_tracks_by_criteria_date_range(self, mock_sqlite_select_db):
        """Test filtering by a start and end date."""
        mock_sqlite_select_db.return_value.fetchall.return_value = [
            ("track1_id", "Track One", "2020", "Album A", "Artist X", "pop")
        ]
        playlist_ids = ["playlist1"]
        start_date = "2020-01-01"
        end_date = "2020-12-31"
        results = misc.find_tracks_by_criteria(playlist_ids, start_date=start_date, end_date=end_date)

        assert len(results) == 1
        assert results[0]["track_name"] == "Track One"

        expected_query_part_playlists = f"pt.playlist_id IN ({','.join(['?'] * len(playlist_ids))})"
        expected_query_part_dates = "al.release_date BETWEEN ? AND ?"

        assert expected_query_part_playlists in mock_sqlite_select_db.call_args[0][1]
        assert expected_query_part_dates in mock_sqlite_select_db.call_args[0][1]
        assert mock_sqlite_select_db.call_args[0][2] == (*playlist_ids, start_date, end_date)

    def test_find_tracks_by_criteria_genre_pattern(self, mock_sqlite_select_db):
        """Test filtering by a genre regex pattern."""
        mock_sqlite_select_db.return_value.fetchall.return_value = [
            ("track1_id", "Track One", "2020", "Album A", "Artist X", "pop,rock")
        ]
        playlist_ids = ["playlist1"]
        genre_pattern = "rock"
        results = misc.find_tracks_by_criteria(playlist_ids, genre_pattern=genre_pattern)

        assert len(results) == 1
        assert results[0]["track_name"] == "Track One"

        expected_query_part_genres = "LOWER(ag2.genre) REGEXP LOWER(?)"
        assert expected_query_part_genres in mock_sqlite_select_db.call_args[0][1]
        assert mock_sqlite_select_db.call_args[0][2] == (*playlist_ids, genre_pattern)

    def test_find_tracks_by_criteria_both_filters(self, mock_sqlite_select_db):
        """Test filtering by both date range and genre pattern."""
        mock_sqlite_select_db.return_value.fetchall.return_value = [
            ("track1_id", "Track One", "2020", "Album A", "Artist X", "pop,rock")
        ]
        playlist_ids = ["playlist1"]
        start_date = "2020-01-01"
        end_date = "2020-12-31"
        genre_pattern = "pop"
        results = misc.find_tracks_by_criteria(
            playlist_ids, start_date=start_date, end_date=end_date, genre_pattern=genre_pattern
        )

        assert len(results) == 1
        assert results[0]["track_name"] == "Track One"

        expected_query_part_playlists = f"pt.playlist_id IN ({','.join(['?'] * len(playlist_ids))})"
        expected_query_part_dates = "al.release_date BETWEEN ? AND ?"
        expected_query_part_genres = "LOWER(ag2.genre) REGEXP LOWER(?)"

        full_query = mock_sqlite_select_db.call_args[0][1]
        assert expected_query_part_playlists in full_query
        assert expected_query_part_dates in full_query
        assert expected_query_part_genres in full_query
        assert mock_sqlite_select_db.call_args[0][2] == (*playlist_ids, start_date, end_date, genre_pattern)

    def test_find_tracks_by_criteria_multiple_playlists(self, mock_sqlite_select_db):
        """Test searching across multiple playlist IDs."""
        mock_sqlite_select_db.return_value.fetchall.return_value = [
            ("track1_id", "Track One", "2020", "Album A", "Artist X", "pop")
        ]
        playlist_ids = ["playlist1", "playlist2"]
        results = misc.find_tracks_by_criteria(playlist_ids)

        assert len(results) == 1
        assert results[0]["track_name"] == "Track One"

        expected_query_part = f"pt.playlist_id IN ({','.join(['?'] * len(playlist_ids))})"
        assert expected_query_part in mock_sqlite_select_db.call_args[0][1]
        assert mock_sqlite_select_db.call_args[0][2] == tuple(playlist_ids)

    @patch("builtins.open", new_callable=mock_open)
    @patch("pathlib.Path.mkdir")
    def test_find_tracks_by_criteria_output_csv(self, mock_mkdir, mock_open_file, mock_sqlite_select_db):
        """Test that the results are correctly written to a CSV file when output_file is provided."""
        mock_sqlite_select_db.return_value.fetchall.return_value = [
            ("track1_id", "Track One", "2020", "Album A", "Artist X", "pop,rock")
        ]
        playlist_ids = ["playlist1"]
        output_file = "output.csv"
        misc.find_tracks_by_criteria(playlist_ids, output_file=output_file)

        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)
        mock_open_file.assert_called_once_with(Path(output_file), "w", newline="")
        handle = mock_open_file()
        handle.write.assert_any_call("Track Name;Artist(s);Album Name;Release Year;Genre(s);Track ID\r\n")
        handle.write.assert_any_call("Track One;Artist X;Album A;2020;pop,rock;track1_id\r\n")

    def test_find_tracks_by_criteria_empty_playlist_ids(self, mock_sqlite_select_db):
        """Test behavior when an empty list of playlist IDs is provided."""
        playlist_ids = []
        results = misc.find_tracks_by_criteria(playlist_ids)

        assert results == []
        mock_sqlite_select_db.assert_not_called()

    def test_find_tracks_by_criteria_no_results(self, mock_sqlite_select_db):
        """Test when no tracks match the criteria."""
        mock_sqlite_select_db.return_value.fetchall.return_value = []
        playlist_ids = ["playlist1"]
        results = misc.find_tracks_by_criteria(playlist_ids, genre_pattern="nonexistent")

        assert results == []
        assert mock_sqlite_select_db.called
