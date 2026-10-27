"""Regression tests for the CLI presentation layer.

These guard against commands silently producing no output when presentation
is moved out of the business-logic modules (e.g. dupes returning structured
data that must still be printed by the CLI dispatch).
"""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import spotfm.cli as cli
from spotfm.spotify import client as spotify_client_module
from spotfm.spotify import dupes as spotify_dupes


@pytest.fixture
def cli_config():
    return {"spotify": {"client_id": "id", "client_secret": "secret", "excluded_playlists": ["ex1"]}}


def _run_spotify_command(monkeypatch, command, config, **arg_overrides):
    monkeypatch.setattr(spotify_client_module, "Client", MagicMock())
    arg_values = {
        "command": command,
        "playlists": None,
        "file": None,
        "output": None,
        "start_date": None,
        "end_date": None,
        "genre": None,
        "threshold": 95,
        "log_counts": False,
    }
    arg_values.update(arg_overrides)
    cli.spotify_cli(SimpleNamespace(**arg_values), config)


@pytest.mark.unit
def test_find_duplicate_ids_prints_csv_rows(capsys, monkeypatch, cli_config):
    """find-duplicate-ids must print CSV rows (playlists,artists,track) to stdout."""
    duplicates = [
        {
            "type": "id",
            "track": "tid1",
            "track_name": "Track, One",
            "artists": "Artist A",
            "count": 2,
            "playlists": "PL1, PL2",
        },
        {"type": "id", "track": "tid2", "track_name": "Track Two", "artists": "", "count": 3, "playlists": "PL3"},
    ]
    monkeypatch.setattr(spotify_dupes, "find_duplicate_ids", lambda excluded_playlist_ids: duplicates)

    _run_spotify_command(monkeypatch, "find-duplicate-ids", cli_config)
    out = capsys.readouterr().out

    # Fields containing commas are quoted; empty artists stay an empty field
    assert '"PL1, PL2",Artist A,"Track, One"' in out
    assert "PL3,,Track Two" in out


@pytest.mark.unit
def test_find_duplicate_ids_no_results_prints_nothing(capsys, monkeypatch, cli_config):
    monkeypatch.setattr(spotify_dupes, "find_duplicate_ids", lambda excluded_playlist_ids: [])

    _run_spotify_command(monkeypatch, "find-duplicate-ids", cli_config)
    out = capsys.readouterr().out
    assert out == ""


@pytest.mark.unit
def test_find_duplicate_ids_passes_excluded_playlists(monkeypatch, cli_config):
    """Excluded playlists from config must be forwarded to the dupes module."""
    recorded = {}
    monkeypatch.setattr(
        spotify_dupes,
        "find_duplicate_ids",
        lambda excluded_playlist_ids: recorded.update(excluded=excluded_playlist_ids) or [],
    )

    _run_spotify_command(monkeypatch, "find-duplicate-ids", cli_config)
    assert recorded["excluded"] == ["ex1"]


@pytest.mark.unit
def test_find_duplicate_names_prints_csv_rows(capsys, monkeypatch, cli_config):
    """find-duplicate-names must print CSV rows (playlists1,playlists2,artists1,artists2,track1,track2,score)."""
    duplicates = [
        {
            "track1": "Song A",
            "artists1": "Artist X",
            "playlists1": "P1",
            "track2": "Song B",
            "artists2": "Artist Y",
            "playlists2": "P2",
            "score": 96.5,
            "ratio_type": "full",
        }
    ]
    monkeypatch.setattr(spotify_dupes, "find_duplicate_names", lambda excluded_playlist_ids, threshold: duplicates)

    _run_spotify_command(monkeypatch, "find-duplicate-names", cli_config)
    out = capsys.readouterr().out

    assert "P1,P2,Artist X,Artist Y,Song A,Song B,96.50" in out


@pytest.mark.unit
def test_find_duplicate_names_passes_threshold(monkeypatch, cli_config):
    """--threshold must be forwarded to find_duplicate_names."""
    recorded = {}
    monkeypatch.setattr(
        spotify_dupes,
        "find_duplicate_names",
        lambda excluded_playlist_ids, threshold: recorded.update(threshold=threshold) or [],
    )

    _run_spotify_command(monkeypatch, "find-duplicate-names", cli_config, threshold=90)
    assert recorded["threshold"] == 90


@pytest.mark.unit
def test_cli_output_not_tty_still_prints(capsys, monkeypatch, cli_config):
    """Piped stdout must still receive rows — the output must not depend on isatty()."""
    assert not sys.stdout.isatty()
    monkeypatch.setattr(
        spotify_dupes,
        "find_duplicate_ids",
        lambda excluded_playlist_ids: [
            {
                "type": "id",
                "track": "tid",
                "track_name": "Track One",
                "artists": "Artist A",
                "count": 2,
                "playlists": "PL1",
            },
        ],
    )

    _run_spotify_command(monkeypatch, "find-duplicate-ids", cli_config)
    assert "PL1,Artist A,Track One" in capsys.readouterr().out


@pytest.mark.unit
def test_find_liked_only_prints_rows(capsys, monkeypatch, cli_config):
    """find-liked-only must print liked-only tracks to stdout."""
    from spotfm.spotify import misc as spotify_misc

    tracks = [
        {
            "track_id": "t1",
            "track_name": "Track One",
            "release_year": "2020",
            "album_name": "Album",
            "liked": True,
            "artist_names": "Artist A",
            "artist_genres": "rap",
        }
    ]
    monkeypatch.setattr(spotify_misc, "find_liked_only_tracks", lambda output_file=None: tracks)

    _run_spotify_command(monkeypatch, "find-liked-only", cli_config)
    out = capsys.readouterr().out
    assert "Artist A - Track One - Album - 2020 - rap" in out


@pytest.mark.unit
def test_count_tracks_prints_total_and_liked(capsys, monkeypatch, cli_config):
    """count-tracks prints both the total and the liked count."""
    from spotfm.spotify import misc as spotify_misc

    monkeypatch.setattr(spotify_misc, "count_tracks", lambda playlists_patterns=None: 5)
    monkeypatch.setattr(spotify_misc, "count_liked_tracks", lambda: 3)

    _run_spotify_command(monkeypatch, "count-tracks", cli_config)
    out = capsys.readouterr().out
    assert "tracks: 5" in out
    assert "liked tracks: 3" in out


@pytest.mark.unit
def test_update_playlists_does_not_sync_liked(monkeypatch, cli_config):
    """update-playlists is playlists-only; the liked sync is the update-liked command."""
    monkeypatch.setattr(spotify_client_module, "Client", MagicMock())

    _run_spotify_command(monkeypatch, "update-playlists", cli_config)
    client = spotify_client_module.Client.return_value
    client.update_playlists.assert_called_once_with(["ex1"], None)


@pytest.mark.unit
def test_update_liked_runs_standalone_sync(monkeypatch, cli_config):
    """update-liked syncs Liked Songs alone, without touching playlists."""
    from spotfm.spotify import misc as spotify_misc

    synced = {}
    monkeypatch.setattr(spotify_misc, "update_liked_tracks", lambda client: synced.setdefault("client", client))

    _run_spotify_command(monkeypatch, "update-liked", cli_config)

    client = spotify_client_module.Client.return_value
    assert synced["client"] is client.client
    client.update_playlists.assert_not_called()
