"""Unit tests for spotfm.spotify.misc module."""

import sqlite3
from unittest.mock import MagicMock

import pytest

from spotfm import utils
from spotfm.spotify import misc


@pytest.mark.unit
class TestFindRelinkedTracks:
    """Tests for find_relinked_tracks function."""

    def test_find_relinked_tracks_none_found(self, temp_database, monkeypatch):
        """Test when no relinked tracks are found."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)

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
