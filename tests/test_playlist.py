"""Unit tests for spotfm.spotify.playlist module."""

import sqlite3
from collections import Counter
from unittest.mock import patch

import pytest
from freezegun import freeze_time

from spotfm import utils
from spotfm.spotify.artist import Artist
from spotfm.spotify.playlist import Playlist
from spotfm.spotify.track import Track


@pytest.mark.unit
class TestPlaylistInit:
    """Tests for Playlist initialization."""

    def test_playlist_init_with_url(self):
        """Test Playlist initialization with Spotify URL."""
        url = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
        playlist = Playlist(url)

        assert playlist.id == "37i9dQZF1DXcBWIGoYBM5M"
        assert playlist.name is None
        assert playlist.owner is None
        assert playlist.raw_tracks is None

    def test_playlist_init_with_id(self):
        """Test Playlist initialization with plain ID."""
        playlist = Playlist("test_playlist_id")

        assert playlist.id == "test_playlist_id"
        assert playlist.kind == "playlist"


@pytest.mark.unit
class TestPlaylistRepresentation:
    """Tests for Playlist string representations."""

    def test_playlist_repr(self):
        """Test Playlist __repr__ method."""
        playlist = Playlist("playlist1")
        playlist.owner = "user123"
        playlist.name = "Rock Classics"

        assert repr(playlist) == "Playlist(user123 - Rock Classics)"

    def test_playlist_str(self):
        """Test Playlist __str__ method."""
        playlist = Playlist("playlist1")
        playlist.owner = "spotify"
        playlist.name = "Today's Top Hits"

        assert str(playlist) == "spotify - Today's Top Hits"


@pytest.mark.unit
class TestPlaylistUpdateFromDb:
    """Tests for Playlist.update_from_db method."""

    def test_update_from_db_success(self, temp_database, monkeypatch):
        """Test successful update from database."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)

        # Insert test data
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO playlists VALUES ('playlist1', 'Test Playlist', 'user123', '2024-01-01')")
        cursor.execute("INSERT INTO playlists_tracks VALUES ('playlist1', 'track1', '2024-01-01T00:00:00Z')")
        cursor.execute("INSERT INTO playlists_tracks VALUES ('playlist1', 'track2', '2024-01-02T00:00:00Z')")
        conn.commit()
        conn.close()

        playlist = Playlist("playlist1")
        result = playlist.update_from_db()

        assert result is True
        assert playlist.name == "Test Playlist"
        assert playlist.owner == "user123"
        assert playlist.updated == "2024-01-01"
        assert len(playlist.tracks) == 2

    def test_update_from_db_not_found(self, temp_database, monkeypatch):
        """Test update from database when playlist not found."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)

        playlist = Playlist("nonexistent")
        result = playlist.update_from_db()

        assert result is False
        assert playlist.name is None


@pytest.mark.unit
class TestPlaylistUpdateFromApi:
    """Tests for Playlist.update_from_api method."""

    @freeze_time("2024-03-15")
    def test_update_from_api_success(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Test successful update from API."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)
        monkeypatch.setattr(utils, "DATABASE", temp_database)

        mock_spotify_client.playlist.return_value = {
            "id": "playlist123",
            "name": "My Playlist",
            "owner": {"id": "user123"},
        }

        mock_spotify_client.playlist_items.return_value = {
            "items": [
                {
                    "track": {"id": "track1"},
                    "added_at": "2024-01-01T00:00:00Z",
                },
                {
                    "track": {"id": "track2"},
                    "added_at": "2024-01-02T00:00:00Z",
                },
            ],
            "next": None,
        }

        mock_spotify_client.tracks.return_value = {
            "tracks": [
                {
                    "id": "track1",
                    "name": "Track 1",
                    "album": {"id": "album1", "name": "Album 1"},
                    "artists": [{"id": "artist1", "name": "Artist 1"}],
                },
                {
                    "id": "track2",
                    "name": "Track 2",
                    "album": {"id": "album2", "name": "Album 2"},
                    "artists": [{"id": "artist2", "name": "Artist 2"}],
                },
            ]
        }

        # Mock batch albums API
        mock_spotify_client.albums.return_value = {
            "albums": [
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
        }

        # Mock batch artists API
        mock_spotify_client.artists.return_value = {
            "artists": [
                {"id": "artist1", "name": "Artist 1", "genres": ["rock"]},
                {"id": "artist2", "name": "Artist 2", "genres": ["pop"]},
            ]
        }

        playlist = Playlist("playlist123")

        with patch("spotfm.spotify.track.sleep"):
            playlist.update_from_api(mock_spotify_client)

        assert playlist.name == "My Playlist"
        assert playlist.owner == "user123"
        assert playlist.updated == "2024-03-15"
        assert len(playlist.raw_tracks) == 2
        assert len(playlist.tracks) == 2

    @freeze_time("2024-03-15")
    def test_update_from_api_sanitizes_name(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Test that playlist name is sanitized."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        mock_spotify_client.playlist.return_value = {
            "id": "playlist123",
            "name": "John's Favorites",
            "owner": {"id": "user123"},
        }

        mock_spotify_client.playlist_items.return_value = {
            "items": [],
            "next": None,
        }

        playlist = Playlist("playlist123")
        playlist.update_from_api(mock_spotify_client)

        assert "'" not in playlist.name
        assert playlist.name == "Johns Favorites"

    @freeze_time("2024-03-15")
    def test_update_from_api_paginated_results(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Test handling paginated playlist items."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        mock_spotify_client.playlist.return_value = {
            "id": "playlist123",
            "name": "Big Playlist",
            "owner": {"id": "user123"},
        }

        # First page
        first_page = {
            "items": [{"track": {"id": "track1"}, "added_at": "2024-01-01T00:00:00Z"}],
            "next": "next_url",
        }

        # Second page
        second_page = {
            "items": [{"track": {"id": "track2"}, "added_at": "2024-01-02T00:00:00Z"}],
            "next": None,
        }

        mock_spotify_client.playlist_items.return_value = first_page
        mock_spotify_client.next.return_value = second_page

        mock_spotify_client.tracks.return_value = {
            "tracks": [
                {
                    "id": "track1",
                    "name": "Track 1",
                    "album": {"id": "album1", "name": "Album 1"},
                    "artists": [{"id": "artist1", "name": "Artist 1"}],
                },
                {
                    "id": "track2",
                    "name": "Track 2",
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

        playlist = Playlist("playlist123")

        with patch("spotfm.spotify.track.sleep"):
            playlist.update_from_api(mock_spotify_client)

        assert len(playlist.raw_tracks) == 2
        mock_spotify_client.next.assert_called_once()

    @freeze_time("2024-03-15")
    def test_update_from_api_handles_relinked_tracks(
        self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client
    ):
        """Test that relinked tracks use the original track ID from linked_from."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        mock_spotify_client.playlist.return_value = {
            "id": "playlist123",
            "name": "Test Playlist",
            "owner": {"id": "user123"},
        }

        # Simulate a relinked track scenario
        # Track was originally track2, but Spotify relinked it to track1 for this market
        mock_spotify_client.playlist_items.return_value = {
            "items": [
                {
                    "track": {
                        "id": "track1",  # Relinked track ID
                        "linked_from": {"id": "track2"},  # Original track ID
                    },
                    "added_at": "2024-01-01T00:00:00Z",
                }
            ],
            "next": None,
        }

        mock_spotify_client.tracks.return_value = {
            "tracks": [
                {
                    "id": "track2",
                    "name": "Track 2",
                    "album": {"id": "album2", "name": "Album 2"},
                    "artists": [{"id": "artist2", "name": "Artist 2"}],
                }
            ]
        }

        mock_spotify_client.albums.return_value = {
            "albums": [
                {
                    "id": "album2",
                    "name": "Album 2",
                    "release_date": "2024-01-01",
                    "artists": [{"id": "artist2", "name": "Artist 2"}],
                }
            ]
        }

        mock_spotify_client.artists.return_value = {
            "artists": [{"id": "artist2", "name": "Artist 2", "genres": ["pop"]}]
        }

        playlist = Playlist("playlist123")

        with patch("spotfm.spotify.track.sleep"):
            playlist.update_from_api(mock_spotify_client)

        # Should use the original track ID from linked_from
        assert len(playlist.raw_tracks) == 1
        assert playlist.raw_tracks[0][0] == "track2"  # Original track ID, not track1
        assert playlist.raw_tracks[0][1] == "2024-01-01T00:00:00Z"

    @freeze_time("2024-03-15")
    def test_update_from_api_filters_null_tracks(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Test that null tracks are filtered out."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        mock_spotify_client.playlist.return_value = {
            "id": "playlist123",
            "name": "Playlist with Nulls",
            "owner": {"id": "user123"},
        }

        mock_spotify_client.playlist_items.return_value = {
            "items": [
                {"track": {"id": "track1"}, "added_at": "2024-01-01T00:00:00Z"},
                {"track": None, "added_at": "2024-01-02T00:00:00Z"},  # Removed track
                {"track": {"id": "track2"}, "added_at": "2024-01-03T00:00:00Z"},
            ],
            "next": None,
        }

        mock_spotify_client.tracks.return_value = {
            "tracks": [
                {
                    "id": "track1",
                    "name": "Track 1",
                    "album": {"id": "album1", "name": "Album 1"},
                    "artists": [{"id": "artist1", "name": "Artist 1"}],
                },
                {
                    "id": "track2",
                    "name": "Track 2",
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

        playlist = Playlist("playlist123")

        with patch("spotfm.spotify.track.sleep"):
            playlist.update_from_api(mock_spotify_client)

        # Should only have 2 tracks (null track filtered out)
        assert len(playlist.raw_tracks) == 2


@pytest.mark.unit
class TestPlaylistSyncToDb:
    """Tests for Playlist.sync_to_db method."""

    def test_sync_to_db_success(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Test syncing playlist to database."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        playlist = Playlist("playlist123")
        playlist.name = "Test Playlist"
        playlist.owner = "user123"
        playlist.updated = "2024-01-01"
        playlist.raw_tracks = [("track1", "2024-01-01T00:00:00Z")]

        # Create mock tracks
        track1 = Track("track1")
        track1.name = "Track 1"
        track1.album_id = "album1"
        track1.updated = "2024-01-01"
        track1.artists = []

        playlist.tracks = [track1]

        # Mock album.get_album
        with patch("spotfm.spotify.track.Album.get_album"):
            playlist.sync_to_db(mock_spotify_client)

        # Verify playlist was inserted
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        playlist_data = cursor.execute("SELECT * FROM playlists WHERE id = 'playlist123'").fetchone()
        playlist_tracks = cursor.execute("SELECT * FROM playlists_tracks WHERE playlist_id = 'playlist123'").fetchall()
        conn.close()

        assert playlist_data == ("playlist123", "Test Playlist", "user123", "2024-01-01")
        assert len(playlist_tracks) == 1
        assert playlist_tracks[0] == ("playlist123", "track1", "2024-01-01T00:00:00Z")

    def test_sync_to_db_removes_old_tracks(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Test that sync_to_db removes tracks that are no longer in the playlist."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        # First sync: playlist with 3 tracks
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO playlists VALUES ('playlist123', 'Test Playlist', 'user123', '2024-01-01')")
        cursor.execute("INSERT INTO playlists_tracks VALUES ('playlist123', 'track1', '2024-01-01T00:00:00Z')")
        cursor.execute("INSERT INTO playlists_tracks VALUES ('playlist123', 'track2', '2024-01-02T00:00:00Z')")
        cursor.execute("INSERT INTO playlists_tracks VALUES ('playlist123', 'track3', '2024-01-03T00:00:00Z')")
        conn.commit()
        conn.close()

        # Second sync: playlist now only has track1 and track3 (track2 was removed)
        playlist = Playlist("playlist123")
        playlist.name = "Test Playlist"
        playlist.owner = "user123"
        playlist.updated = "2024-01-02"
        playlist.raw_tracks = [("track1", "2024-01-01T00:00:00Z"), ("track3", "2024-01-03T00:00:00Z")]

        track1 = Track("track1")
        track1.name = "Track 1"
        track1.album_id = "album1"
        track1.updated = "2024-01-01"
        track1.artists = []

        track3 = Track("track3")
        track3.name = "Track 3"
        track3.album_id = "album3"
        track3.updated = "2024-01-03"
        track3.artists = []

        playlist.tracks = [track1, track3]

        # Mock album.get_album
        with patch("spotfm.spotify.track.Album.get_album"):
            playlist.sync_to_db(mock_spotify_client)

        # Verify track2 was removed
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        playlist_tracks = cursor.execute(
            "SELECT track_id FROM playlists_tracks WHERE playlist_id = 'playlist123' ORDER BY track_id"
        ).fetchall()
        conn.close()

        # Should only have track1 and track3, track2 should be deleted
        assert len(playlist_tracks) == 2
        assert playlist_tracks[0][0] == "track1"
        assert playlist_tracks[1][0] == "track3"

    def test_sync_to_db_handles_duplicate_tracks(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Test that sync_to_db handles playlists with the same track multiple times."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        # Playlist with track1 added twice (same track, different added_at timestamps)
        playlist = Playlist("playlist123")
        playlist.name = "Test Playlist"
        playlist.owner = "user123"
        playlist.updated = "2024-01-01"
        playlist.raw_tracks = [("track1", "2024-01-01T00:00:00Z"), ("track1", "2024-01-05T00:00:00Z")]

        track1 = Track("track1")
        track1.name = "Track 1"
        track1.album_id = "album1"
        track1.updated = "2024-01-01"
        track1.artists = []

        # tracks list should only have unique tracks
        playlist.tracks = [track1]

        # Mock album.get_album
        with patch("spotfm.spotify.track.Album.get_album"):
            playlist.sync_to_db(mock_spotify_client)

        # Verify only one entry is stored (first occurrence due to INSERT OR IGNORE)
        conn = sqlite3.connect(temp_database)
        cursor = conn.cursor()
        playlist_tracks = cursor.execute(
            "SELECT track_id, added_at FROM playlists_tracks WHERE playlist_id = 'playlist123'"
        ).fetchall()
        conn.close()

        # Should only have one entry (first one wins with INSERT OR IGNORE)
        assert len(playlist_tracks) == 1
        assert playlist_tracks[0] == ("track1", "2024-01-01T00:00:00Z")


@pytest.mark.unit
class TestPlaylistGetPlaylist:
    """Tests for Playlist.get_playlist class method."""

    def test_get_playlist_from_cache(self, temp_cache_dir, monkeypatch):
        """Test getting playlist from cache."""
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)

        # Create and cache a playlist
        cached_playlist = Playlist("cached123")
        cached_playlist.name = "Cached Playlist"
        cached_playlist.owner = "user123"
        utils.cache_object(cached_playlist)

        # Retrieve from cache
        playlist = Playlist.get_playlist("cached123")

        assert playlist.name == "Cached Playlist"
        assert playlist.owner == "user123"


@pytest.mark.unit
class TestPlaylistGetTracks:
    """Tests for Playlist.get_tracks method."""

    def test_get_tracks_success(self, temp_database, temp_cache_dir, monkeypatch, mock_spotify_client):
        """Test getting tracks from playlist."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)
        monkeypatch.setattr(utils, "DATABASE", temp_database)

        playlist = Playlist("playlist123")
        playlist.raw_tracks = [("track1", "2024-01-01"), ("track2", "2024-01-02")]

        mock_spotify_client.tracks.return_value = {
            "tracks": [
                {
                    "id": "track1",
                    "name": "Track 1",
                    "album": {"id": "album1", "name": "Album 1"},
                    "artists": [{"id": "artist1", "name": "Artist 1"}],
                },
                {
                    "id": "track2",
                    "name": "Track 2",
                    "album": {"id": "album2", "name": "Album 2"},
                    "artists": [{"id": "artist2", "name": "Artist 2"}],
                },
            ]
        }

        # Mock batch albums API
        mock_spotify_client.albums.return_value = {
            "albums": [
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
        }

        # Mock batch artists API
        mock_spotify_client.artists.return_value = {
            "artists": [
                {"id": "artist1", "name": "Artist 1", "genres": []},
                {"id": "artist2", "name": "Artist 2", "genres": []},
            ]
        }

        with patch("spotfm.spotify.track.sleep"):
            tracks = playlist.get_tracks(mock_spotify_client)

        assert len(tracks) == 2


@pytest.mark.unit
class TestPlaylistGetPlaylistGenres:
    """Tests for Playlist.get_playlist_genres method."""

    def test_get_playlist_genres_success(self):
        """Test getting genre counts from playlist."""
        playlist = Playlist("playlist123")

        # Create mock tracks with artists and genres
        track1 = Track("track1")
        artist1 = Artist("artist1")
        artist1.genres = ["rock", "alternative"]
        track1.artists = [artist1]

        track2 = Track("track2")
        artist2 = Artist("artist2")
        artist2.genres = ["rock", "pop"]
        track2.artists = [artist2]

        playlist.tracks = [track1, track2]

        genres = playlist.get_playlist_genres()

        assert isinstance(genres, Counter)
        assert genres["rock"] == 2
        assert genres["alternative"] == 1
        assert genres["pop"] == 1


@pytest.mark.unit
class TestPlaylistAddTracks:
    """Tests for Playlist.add_tracks method."""

    def test_add_tracks_single_batch(self, mock_spotify_client):
        """Test adding tracks in single batch."""
        playlist = Playlist("playlist123")

        track1 = Track("track1")
        track1.id = "track1"

        track2 = Track("track2")
        track2.id = "track2"

        tracks = [track1, track2]

        playlist.add_tracks(tracks, mock_spotify_client)

        mock_spotify_client.playlist_add_items.assert_called_once_with("playlist123", ["track1", "track2"])

    def test_add_tracks_multiple_batches(self, mock_spotify_client):
        """Test adding tracks across multiple batches."""
        playlist = Playlist("playlist123")

        # Create 5 tracks with batch_size of 2
        tracks = []
        for i in range(1, 6):
            track = Track(f"track{i}")
            track.id = f"track{i}"
            tracks.append(track)

        playlist.add_tracks(tracks, mock_spotify_client, batch_size=2)

        # Should make 3 calls (2+2+1)
        assert mock_spotify_client.playlist_add_items.call_count == 3

    def test_add_tracks_handles_errors(self, mock_spotify_client):
        """Test that errors are caught and logged."""
        playlist = Playlist("playlist123")

        track = Track("track1")
        track.id = "track1"

        mock_spotify_client.playlist_add_items.side_effect = TypeError("Test error")

        # Should not raise, just print error
        playlist.add_tracks([track], mock_spotify_client)
