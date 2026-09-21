"""Tests for hacks/move_tracks.py"""

from unittest.mock import MagicMock

import pytest

from spotfm import sqlite, utils
from spotfm.spotify import playlist as playlist_module


@pytest.mark.unit
def test_parse_playlist_identifier_url():
    """URL with ?si= param → 22-char ID extracted"""
    from hacks.move_tracks import parse_playlist_identifier

    url = "https://open.spotify.com/playlist/4V8O33t0hSCnK4ABozG6xc?si=bdaaafd5b0f54b96"
    result = parse_playlist_identifier(url)
    assert result == "4V8O33t0hSCnK4ABozG6xc"


@pytest.mark.unit
def test_parse_playlist_identifier_plain_id():
    """Plain 22-char ID → returned unchanged"""
    from hacks.move_tracks import parse_playlist_identifier

    playlist_id = "4V8O33t0hSCnK4ABozG6xc"
    result = parse_playlist_identifier(playlist_id)
    assert result == playlist_id


@pytest.mark.unit
def test_parse_playlist_identifier_name():
    """Name string → returned unchanged"""
    from hacks.move_tracks import parse_playlist_identifier

    name = "My Favorite Tracks"
    result = parse_playlist_identifier(name)
    assert result == name


@pytest.mark.unit
def test_parse_playlist_identifier_url_without_query():
    """URL without query params → ID extracted"""
    from hacks.move_tracks import parse_playlist_identifier

    url = "https://open.spotify.com/playlist/4V8O33t0hSCnK4ABozG6xc"
    result = parse_playlist_identifier(url)
    assert result == "4V8O33t0hSCnK4ABozG6xc"


@pytest.mark.unit
def test_resolve_identifier_direct_id(monkeypatch, temp_database):
    """Direct 22-char ID → returned without DB lookup"""
    from hacks.move_tracks import resolve_identifier

    monkeypatch.setattr(utils, "DATABASE", temp_database)
    monkeypatch.setattr(sqlite, "DATABASE", temp_database)

    playlist_id = "4V8O33t0hSCnK4ABozG6xc"
    result = resolve_identifier(playlist_id, "Test")
    assert result == playlist_id


@pytest.mark.unit
def test_resolve_identifier_by_name(monkeypatch, temp_database):
    """Name pattern → resolved via resolve_playlist_patterns_to_ids()"""
    from hacks.move_tracks import resolve_identifier

    monkeypatch.setattr(utils, "DATABASE", temp_database)
    monkeypatch.setattr(sqlite, "DATABASE", temp_database)

    mock_resolve = MagicMock(return_value=["4V8O33t0hSCnK4ABozG6xc"])
    monkeypatch.setattr("hacks.move_tracks.resolve_playlist_patterns_to_ids", mock_resolve)

    result = resolve_identifier("My Playlist", "Test")
    assert result == "4V8O33t0hSCnK4ABozG6xc"
    mock_resolve.assert_called_once_with("My Playlist")


@pytest.mark.unit
def test_resolve_identifier_not_found(monkeypatch, temp_database):
    """Playlist not found → sys.exit(1)"""
    from hacks.move_tracks import resolve_identifier

    monkeypatch.setattr(utils, "DATABASE", temp_database)
    monkeypatch.setattr(sqlite, "DATABASE", temp_database)

    mock_resolve = MagicMock(return_value=[])
    monkeypatch.setattr("hacks.move_tracks.resolve_playlist_patterns_to_ids", mock_resolve)

    with pytest.raises(SystemExit) as exc_info:
        resolve_identifier("Nonexistent", "Test")

    assert exc_info.value.code == 1


@pytest.mark.unit
def test_move_tracks_dry_run_skips_api_calls(monkeypatch, temp_database):
    """dry-run=True: no add/remove called"""
    from hacks.move_tracks import move_tracks

    monkeypatch.setattr(utils, "DATABASE", temp_database)
    monkeypatch.setattr(sqlite, "DATABASE", temp_database)

    mock_client = MagicMock()
    mock_client.update_playlists = MagicMock()

    mock_artist = MagicMock()
    mock_artist.name = "Artist A"

    track1 = MagicMock()
    track1.id = "track1"
    track1.name = "Track 1"
    track1.album = "Album A"
    track1.artists = [mock_artist]

    mock_source = MagicMock()
    mock_source.tracks = [track1]
    mock_source.add_tracks = MagicMock()
    mock_source.remove_tracks = MagicMock()

    monkeypatch.setattr(playlist_module.Playlist, "get_playlist", MagicMock(return_value=mock_source))

    track_ids = move_tracks(mock_client, "source_id", "dest_id", 1, dry_run=True)

    assert track_ids == ["track1"]
    mock_source.add_tracks.assert_not_called()
    mock_source.remove_tracks.assert_not_called()


@pytest.mark.unit
def test_move_tracks_dry_run_skips_post_update(monkeypatch, temp_database):
    """dry-run=True: post-op update_playlists not called"""
    from hacks.move_tracks import move_tracks

    monkeypatch.setattr(utils, "DATABASE", temp_database)
    monkeypatch.setattr(sqlite, "DATABASE", temp_database)

    mock_client = MagicMock()
    mock_client.update_playlists = MagicMock()

    mock_artist = MagicMock()
    mock_artist.name = "Artist A"

    track1 = MagicMock()
    track1.id = "track1"
    track1.name = "Track 1"
    track1.album = "Album A"
    track1.artists = [mock_artist]

    mock_source = MagicMock()
    mock_source.tracks = [track1]

    monkeypatch.setattr(playlist_module.Playlist, "get_playlist", MagicMock(return_value=mock_source))

    move_tracks(mock_client, "source_id", "dest_id", 1, dry_run=True)

    assert mock_client.update_playlists.call_count == 2


@pytest.mark.unit
def test_move_tracks_sorting(monkeypatch, temp_database):
    """Tracks sorted by artist name then album name"""
    from hacks.move_tracks import move_tracks

    monkeypatch.setattr(utils, "DATABASE", temp_database)
    monkeypatch.setattr(sqlite, "DATABASE", temp_database)

    mock_client = MagicMock()
    mock_client.update_playlists = MagicMock()

    artist_a = MagicMock()
    artist_a.name = "Artist A"
    artist_b = MagicMock()
    artist_b.name = "Artist B"
    artist_a_alt = MagicMock()
    artist_a_alt.name = "Artist A"

    track1 = MagicMock()
    track1.id = "track1"
    track1.name = "Track 1"
    track1.album = "Album Z"
    track1.artists = [artist_b]

    track2 = MagicMock()
    track2.id = "track2"
    track2.name = "Track 2"
    track2.album = "Album A"
    track2.artists = [artist_a]

    track3 = MagicMock()
    track3.id = "track3"
    track3.name = "Track 3"
    track3.album = "Album M"
    track3.artists = [artist_a_alt]

    mock_source = MagicMock()
    mock_source.tracks = [track1, track2, track3]

    monkeypatch.setattr(playlist_module.Playlist, "get_playlist", MagicMock(return_value=mock_source))

    track_ids = move_tracks(mock_client, "source_id", "dest_id", 3, dry_run=True)

    assert track_ids == ["track2", "track3", "track1"]


@pytest.mark.unit
def test_move_tracks_sorting_case_insensitive(monkeypatch, temp_database):
    """Sorting is case-insensitive"""
    from hacks.move_tracks import move_tracks

    monkeypatch.setattr(utils, "DATABASE", temp_database)
    monkeypatch.setattr(sqlite, "DATABASE", temp_database)

    mock_client = MagicMock()
    mock_client.update_playlists = MagicMock()

    artist_lower = MagicMock()
    artist_lower.name = "artist a"
    artist_upper = MagicMock()
    artist_upper.name = "Artist B"

    track1 = MagicMock()
    track1.id = "track1"
    track1.name = "Track 1"
    track1.album = "ALBUM Z"
    track1.artists = [artist_upper]

    track2 = MagicMock()
    track2.id = "track2"
    track2.name = "Track 2"
    track2.album = "album a"
    track2.artists = [artist_lower]

    mock_source = MagicMock()
    mock_source.tracks = [track1, track2]

    monkeypatch.setattr(playlist_module.Playlist, "get_playlist", MagicMock(return_value=mock_source))

    track_ids = move_tracks(mock_client, "source_id", "dest_id", 2, dry_run=True)

    assert track_ids == ["track2", "track1"]


@pytest.mark.unit
def test_move_tracks_count_limits_selection(monkeypatch, temp_database):
    """Only first N sorted tracks selected"""
    from hacks.move_tracks import move_tracks

    monkeypatch.setattr(utils, "DATABASE", temp_database)
    monkeypatch.setattr(sqlite, "DATABASE", temp_database)

    mock_client = MagicMock()
    mock_client.update_playlists = MagicMock()

    tracks = []
    for i in range(10):
        artist = MagicMock()
        artist.name = f"Artist {i:02d}"
        track = MagicMock()
        track.id = f"track{i}"
        track.name = f"Track {i}"
        track.album = f"Album {i}"
        track.artists = [artist]
        tracks.append(track)

    mock_source = MagicMock()
    mock_source.tracks = tracks

    monkeypatch.setattr(playlist_module.Playlist, "get_playlist", MagicMock(return_value=mock_source))

    track_ids = move_tracks(mock_client, "source_id", "dest_id", 3, dry_run=True)

    assert len(track_ids) == 3


@pytest.mark.unit
def test_move_tracks_missing_artist_fallback(monkeypatch, temp_database):
    """Missing artist handled gracefully (fallback "" sorts first)"""
    from hacks.move_tracks import move_tracks

    monkeypatch.setattr(utils, "DATABASE", temp_database)
    monkeypatch.setattr(sqlite, "DATABASE", temp_database)

    mock_client = MagicMock()
    mock_client.update_playlists = MagicMock()

    artist_a = MagicMock()
    artist_a.name = "Artist A"

    track_with_artist = MagicMock()
    track_with_artist.id = "track1"
    track_with_artist.name = "Track 1"
    track_with_artist.album = "Album A"
    track_with_artist.artists = [artist_a]

    track_no_artist = MagicMock()
    track_no_artist.id = "track2"
    track_no_artist.name = "Track 2"
    track_no_artist.album = "Album B"
    track_no_artist.artists = []

    mock_source = MagicMock()
    mock_source.tracks = [track_with_artist, track_no_artist]

    monkeypatch.setattr(playlist_module.Playlist, "get_playlist", MagicMock(return_value=mock_source))

    track_ids = move_tracks(mock_client, "source_id", "dest_id", 2, dry_run=True)

    assert track_ids == ["track2", "track1"]


@pytest.mark.unit
def test_move_tracks_missing_album_fallback(monkeypatch, temp_database):
    """Missing album handled gracefully (fallback "" sorts first within same artist)"""
    from hacks.move_tracks import move_tracks

    monkeypatch.setattr(utils, "DATABASE", temp_database)
    monkeypatch.setattr(sqlite, "DATABASE", temp_database)

    mock_client = MagicMock()
    mock_client.update_playlists = MagicMock()

    artist = MagicMock()
    artist.name = "Artist A"

    track_with_album = MagicMock()
    track_with_album.id = "track1"
    track_with_album.name = "Track 1"
    track_with_album.album = "Album A"
    track_with_album.artists = [artist]

    track_no_album = MagicMock()
    track_no_album.id = "track2"
    track_no_album.name = "Track 2"
    track_no_album.album = None
    track_no_album.artists = [artist]

    mock_source = MagicMock()
    mock_source.tracks = [track_with_album, track_no_album]

    monkeypatch.setattr(playlist_module.Playlist, "get_playlist", MagicMock(return_value=mock_source))

    track_ids = move_tracks(mock_client, "source_id", "dest_id", 2, dry_run=True)

    assert track_ids == ["track2", "track1"]


@pytest.mark.unit
def test_move_tracks_pre_update_always_runs(monkeypatch, temp_database):
    """Pre-flight update_playlists called in both dry-run and non dry-run"""
    from hacks.move_tracks import move_tracks

    monkeypatch.setattr(utils, "DATABASE", temp_database)
    monkeypatch.setattr(sqlite, "DATABASE", temp_database)

    mock_client = MagicMock()
    mock_client.update_playlists = MagicMock()

    mock_artist = MagicMock()
    mock_artist.name = "Artist A"

    track1 = MagicMock()
    track1.id = "track1"
    track1.name = "Track 1"
    track1.album = "Album A"
    track1.artists = [mock_artist]

    mock_source = MagicMock()
    mock_source.tracks = [track1]

    monkeypatch.setattr(playlist_module.Playlist, "get_playlist", MagicMock(return_value=mock_source))

    mock_client.update_playlists.reset_mock()
    move_tracks(mock_client, "source_id", "dest_id", 1, dry_run=True)

    assert mock_client.update_playlists.call_count == 2
    mock_client.update_playlists.assert_any_call(playlists_patterns=["source_id"])
    mock_client.update_playlists.assert_any_call(playlists_patterns=["dest_id"])


@pytest.mark.unit
def test_move_tracks_non_dry_run_adds_before_removes(monkeypatch, temp_database):
    """Non dry-run: add_tracks called before remove_tracks"""
    from hacks.move_tracks import move_tracks

    monkeypatch.setattr(utils, "DATABASE", temp_database)
    monkeypatch.setattr(sqlite, "DATABASE", temp_database)

    mock_client = MagicMock()
    mock_client.update_playlists = MagicMock()

    mock_artist = MagicMock()
    mock_artist.name = "Artist A"

    track1 = MagicMock()
    track1.id = "track1"
    track1.name = "Track 1"
    track1.album = "Album A"
    track1.artists = [mock_artist]

    mock_source = MagicMock()
    mock_source.tracks = [track1]
    mock_source.remove_tracks = MagicMock()

    mock_dest = MagicMock()
    mock_dest.add_tracks = MagicMock()

    call_order = []

    def track_add_calls(*_, **__):
        call_order.append("add")

    def track_remove_calls(*_, **__):
        call_order.append("remove")

    mock_dest.add_tracks.side_effect = track_add_calls
    mock_source.remove_tracks.side_effect = track_remove_calls

    def get_playlist_side_effect(playlist_id, *_, **__):
        if playlist_id == "source_id":
            return mock_source
        return mock_dest

    monkeypatch.setattr(playlist_module.Playlist, "get_playlist", MagicMock(side_effect=get_playlist_side_effect))

    move_tracks(mock_client, "source_id", "dest_id", 1, dry_run=False)

    assert call_order == ["add", "remove"]


@pytest.mark.unit
def test_move_tracks_non_dry_run_post_update_runs(monkeypatch, temp_database):
    """Non dry-run: update_playlists called after operation"""
    from hacks.move_tracks import move_tracks

    monkeypatch.setattr(utils, "DATABASE", temp_database)
    monkeypatch.setattr(sqlite, "DATABASE", temp_database)

    mock_client = MagicMock()
    mock_client.update_playlists = MagicMock()

    mock_artist = MagicMock()
    mock_artist.name = "Artist A"

    track1 = MagicMock()
    track1.id = "track1"
    track1.name = "Track 1"
    track1.album = "Album A"
    track1.artists = [mock_artist]

    mock_source = MagicMock()
    mock_source.tracks = [track1]
    mock_source.remove_tracks = MagicMock()

    mock_dest = MagicMock()
    mock_dest.add_tracks = MagicMock()

    def get_playlist_side_effect(playlist_id, *_, **__):
        if playlist_id == "source_id":
            return mock_source
        return mock_dest

    monkeypatch.setattr(playlist_module.Playlist, "get_playlist", MagicMock(side_effect=get_playlist_side_effect))

    mock_client.update_playlists.reset_mock()
    move_tracks(mock_client, "source_id", "dest_id", 1, dry_run=False)

    assert mock_client.update_playlists.call_count == 4


@pytest.mark.unit
def test_move_tracks_returns_track_ids(monkeypatch, temp_database):
    """move_tracks returns list of moved track IDs"""
    from hacks.move_tracks import move_tracks

    monkeypatch.setattr(utils, "DATABASE", temp_database)
    monkeypatch.setattr(sqlite, "DATABASE", temp_database)

    mock_client = MagicMock()
    mock_client.update_playlists = MagicMock()

    artist = MagicMock()
    artist.name = "Artist"

    track1 = MagicMock()
    track1.id = "track1"
    track1.name = "Track 1"
    track1.album = "Album A"
    track1.artists = [artist]

    track2 = MagicMock()
    track2.id = "track2"
    track2.name = "Track 2"
    track2.album = "Album B"
    track2.artists = [artist]

    mock_source = MagicMock()
    mock_source.tracks = [track1, track2]

    monkeypatch.setattr(playlist_module.Playlist, "get_playlist", MagicMock(return_value=mock_source))

    result = move_tracks(mock_client, "source_id", "dest_id", 2, dry_run=True)

    assert result == ["track1", "track2"]
