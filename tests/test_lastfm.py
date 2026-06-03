import argparse
from unittest.mock import MagicMock, patch

import pytest
from freezegun import freeze_time

from spotfm.cli import _non_negative_int, _positive_int, recent_scrobbles
from spotfm.lastfm import (
    PREDEFINED_PERIODS,
    Track,
    UnknownPeriodError,
    User,
    read_lastfm_state,
    save_lastfm_state,
)


@pytest.mark.unit
class TestUserGetPlaycount:
    """Tests for User.get_playcount method."""

    def test_get_playcount_returns_int(self):
        """Test that get_playcount returns an integer."""
        mock_pylast_user = MagicMock()
        mock_pylast_user.get_playcount.return_value = "12345"

        user = User.__new__(User)
        user.user = mock_pylast_user

        result = user.get_playcount()
        assert result == 12345
        assert isinstance(result, int)

    def test_get_playcount_calls_api(self):
        """Test that get_playcount calls the underlying pylast user method."""
        mock_pylast_user = MagicMock()
        mock_pylast_user.get_playcount.return_value = "0"

        user = User.__new__(User)
        user.user = mock_pylast_user

        user.get_playcount()
        mock_pylast_user.get_playcount.assert_called_once()

    def test_get_playcount_large_number(self):
        """Test get_playcount with a large scrobble count."""
        mock_pylast_user = MagicMock()
        mock_pylast_user.get_playcount.return_value = "99999"

        user = User.__new__(User)
        user.user = mock_pylast_user

        assert user.get_playcount() == 99999


@pytest.mark.unit
class TestRecentScrobblesCli:
    """Tests for recent_scrobbles CLI function."""

    def _make_user(self, playcount=150):
        user = MagicMock()
        user.get_playcount.return_value = playcount
        user.get_recent_tracks_scrobbles.return_value = iter(
            [
                {
                    "artist": "Artist",
                    "title": "Track",
                    "period_scrobbles": 5,
                    "total_scrobbles": 10,
                    "url": "http://last.fm/track",
                }
            ]
        )
        return user

    def _make_config(self):
        return {"limit": 50, "scrobbles_minimum": 4, "period_minimum": None}

    def test_normal_run_saves_state(self, tmp_path):
        """Test that a normal run saves the current scrobble count."""
        state_file = tmp_path / "lastfm_state.json"
        user = self._make_user(playcount=150)

        with patch("spotfm.lastfm.LASTFM_STATE_FILE", state_file):
            recent_scrobbles(user, limit=10, scrobbles_minimum=0, period=90, period_minimum=None, interactive=False, config=self._make_config())

        state = read_lastfm_state(state_file=state_file)
        assert state["last_scrobble_count"] == 150

    def test_first_run_initializes_state(self, tmp_path, capsys):
        """Test first run with no state file initializes tracking and fetches limit scrobbles."""
        state_file = tmp_path / "nonexistent.json"
        user = self._make_user()

        with patch("spotfm.lastfm.LASTFM_STATE_FILE", state_file):
            recent_scrobbles(user, limit=10, scrobbles_minimum=0, period=90, period_minimum=None, interactive=False, config=self._make_config())

        captured = capsys.readouterr()
        assert "Initializing scrobble tracking" in captured.out
        # Should fetch the limit amount on first run
        user.get_recent_tracks_scrobbles.assert_called_once_with(limit=10, scrobbles_minimum=0, period=90, period_minimum=None)

    def test_since_last_time_no_new_scrobbles(self, tmp_path, capsys):
        """Test incremental mode when count has not changed."""
        state_file = tmp_path / "lastfm_state.json"
        save_lastfm_state(150, state_file=state_file)
        user = self._make_user(playcount=150)

        # With saved state, uses incremental mode regardless of explicit limit
        with patch("spotfm.lastfm.LASTFM_STATE_FILE", state_file):
            recent_scrobbles(user, limit=10, scrobbles_minimum=0, period=90, period_minimum=None, interactive=False, config=self._make_config())

        captured = capsys.readouterr()
        assert "No new scrobbles" in captured.out
        user.get_recent_tracks_scrobbles.assert_not_called()

    def test_since_last_time_fetches_diff(self, tmp_path):
        """Test incremental mode computes correct limit from diff, ignoring explicit limit."""
        state_file = tmp_path / "lastfm_state.json"
        save_lastfm_state(135, state_file=state_file)
        user = self._make_user(playcount=173)

        # Even with explicit limit=100, incremental mode uses diff (38)
        with patch("spotfm.lastfm.LASTFM_STATE_FILE", state_file):
            recent_scrobbles(user, limit=100, scrobbles_minimum=0, period=90, period_minimum=None, interactive=False, config=self._make_config())

        user.get_recent_tracks_scrobbles.assert_called_once()
        call_args = user.get_recent_tracks_scrobbles.call_args
        assert call_args[1]["limit"] == 38  # limit = 173 - 135

    def test_since_last_time_updates_state(self, tmp_path):
        """Test incremental mode updates the state file after fetching."""
        state_file = tmp_path / "lastfm_state.json"
        save_lastfm_state(135, state_file=state_file)
        user = self._make_user(playcount=173)

        # Incremental mode computes limit as diff (38), fetches all new scrobbles
        with patch("spotfm.lastfm.LASTFM_STATE_FILE", state_file):
            recent_scrobbles(user, limit=100, scrobbles_minimum=0, period=90, period_minimum=None, interactive=False, config=self._make_config())

        state = read_lastfm_state(state_file=state_file)
        assert state["last_scrobble_count"] == 173

    def test_since_last_time_fetches_all_scrobbles_ignoring_limit(self, tmp_path):
        """Test incremental mode ignores explicit limit and fetches only new scrobbles."""
        state_file = tmp_path / "lastfm_state.json"
        save_lastfm_state(135, state_file=state_file)
        user = self._make_user(playcount=173)

        # With saved state, incremental mode ignores limit=10, fetches diff (38 scrobbles)
        with patch("spotfm.lastfm.LASTFM_STATE_FILE", state_file):
            recent_scrobbles(user, limit=10, scrobbles_minimum=0, period=90, period_minimum=None, interactive=False, config=self._make_config())

        state = read_lastfm_state(state_file=state_file)
        # State should advance to current count since we fetch all scrobbles
        assert state["last_scrobble_count"] == 173

    def test_since_last_time_prints_diff_info(self, tmp_path, capsys):
        """Test incremental mode prints informational message with counts."""
        state_file = tmp_path / "lastfm_state.json"
        save_lastfm_state(135, state_file=state_file)
        user = self._make_user(playcount=173)

        # Incremental mode ignores limit=100 when saved state exists
        with patch("spotfm.lastfm.LASTFM_STATE_FILE", state_file):
            recent_scrobbles(user, limit=100, scrobbles_minimum=0, period=90, period_minimum=None, interactive=False, config=self._make_config())

        captured = capsys.readouterr()
        # Should show that fetching happened in incremental mode
        assert "new scrobbles" in captured.out

    def test_first_run_uses_limit_parameter(self, tmp_path):
        """Test that on first run (no state file), the limit parameter is used."""
        state_file = tmp_path / "lastfm_state.json"
        user = self._make_user(playcount=200)

        with patch("spotfm.lastfm.LASTFM_STATE_FILE", state_file):
            recent_scrobbles(user, limit=42, scrobbles_minimum=0, period=90, period_minimum=None, interactive=False, config=self._make_config())

        call_args = user.get_recent_tracks_scrobbles.call_args
        assert call_args[1]["limit"] == 42

    def test_interactive_mode_opens_editor(self, tmp_path):
        """Test that --interactive mode opens editor with deduplicated results."""
        state_file = tmp_path / "lastfm_state.json"
        user = self._make_user(playcount=150)
        user.get_recent_tracks_scrobbles.return_value = iter(
            [
                {
                    "artist": "Artist 1",
                    "title": "Track 1",
                    "period_scrobbles": 5,
                    "total_scrobbles": 10,
                    "url": "http://last.fm/track1",
                },
                {
                    "artist": "Artist 2",
                    "title": "Track 2",
                    "period_scrobbles": 3,
                    "total_scrobbles": 5,
                    "url": "http://last.fm/track2",
                },
                {
                    "artist": "Artist 1",
                    "title": "Track 1",
                    "period_scrobbles": 5,
                    "total_scrobbles": 10,
                    "url": "http://last.fm/track1",
                },  # duplicate
            ]
        )

        with (
            patch("spotfm.lastfm.LASTFM_STATE_FILE", state_file),
            patch.dict("os.environ", {"EDITOR": "vim", "VISUAL": ""}),
            patch("subprocess.run") as mock_run,
            patch("spotfm.cli.os.unlink") as mock_unlink,
        ):
            recent_scrobbles(user, limit=10, scrobbles_minimum=0, period=90, period_minimum=None, interactive=True, config=self._make_config())

        # Verify subprocess.run was called
        assert mock_run.called
        call_args = mock_run.call_args[0][0]
        # First element should be the editor command
        assert call_args[0] == "vim"
        # Last element should be the temp file path
        assert call_args[-1].endswith(".txt")

        # Verify temp file was cleaned up
        assert mock_unlink.called

    def test_interactive_mode_empty_results(self, tmp_path, capsys):
        """Test that interactive mode with no results prints message and doesn't open editor."""
        state_file = tmp_path / "lastfm_state.json"
        user = self._make_user(playcount=150)
        user.get_recent_tracks_scrobbles.return_value = iter([])

        with patch("spotfm.lastfm.LASTFM_STATE_FILE", state_file), patch("subprocess.run") as mock_run:
            recent_scrobbles(user, limit=10, scrobbles_minimum=0, period=90, period_minimum=None, interactive=True, config=self._make_config())

        captured = capsys.readouterr()
        assert "No results found" in captured.out
        # Editor should not be opened
        mock_run.assert_not_called()


@pytest.mark.unit
class TestTrack:
    """Test Track class functionality."""

    def test_track_init(self):
        """Test Track initialization."""
        mock_user = MagicMock()
        track = Track("Artist Name", "Track Title", "http://last.fm/track", mock_user)

        assert track.artist == "Artist Name"
        assert track.title == "Track Title"
        assert track.url == "http://last.fm/track"
        assert track.user == mock_user
        assert track._scrobbles_cache is None

    def test_track_str(self):
        """Test Track string representation."""
        mock_user = MagicMock()
        track = Track("The Beatles", "Hey Jude", "http://last.fm/track", mock_user)
        assert str(track) == "The Beatles - Hey Jude"

    def test_track_str_truncates_long_names(self):
        """Test Track string representation truncates long names."""
        mock_user = MagicMock()
        long_artist = "A" * 100
        long_title = "B" * 100
        track = Track(long_artist, long_title, "http://last.fm/track", mock_user)

        result = str(track)
        assert len(result.split(" - ")[0]) == 50
        assert len(result.split(" - ")[1]) == 50


class TestTrackScrobbleCaching:
    """Test scrobble caching functionality."""

    @freeze_time("2024-01-15 12:00:00")
    def test_scrobbles_property_caches_on_first_access(self):
        """First access to scrobbles property fetches from API and caches."""
        mock_user = MagicMock()
        mock_scrobbles = [
            MagicMock(timestamp="1704067200"),  # 2024-01-01 00:00:00
            MagicMock(timestamp="1704153600"),  # 2024-01-02 00:00:00
            MagicMock(timestamp="1704240000"),  # 2024-01-03 00:00:00
        ]
        mock_user.get_track_scrobbles.return_value = mock_scrobbles

        track = Track("Artist", "Title", "url", mock_user)

        # First access - should fetch from API
        result = track.scrobbles

        assert result == mock_scrobbles
        assert track._scrobbles_cache == mock_scrobbles
        mock_user.get_track_scrobbles.assert_called_once_with("Artist", "Title")

    @freeze_time("2024-01-15 12:00:00")
    def test_scrobbles_property_returns_cached_data_on_subsequent_access(self):
        """Subsequent accesses return cached data without API call."""
        mock_user = MagicMock()
        mock_scrobbles = [
            MagicMock(timestamp="1704067200"),
            MagicMock(timestamp="1704153600"),
        ]
        mock_user.get_track_scrobbles.return_value = mock_scrobbles

        track = Track("Artist", "Title", "url", mock_user)

        # First access
        first_result = track.scrobbles
        mock_user.get_track_scrobbles.reset_mock()

        # Second access - should use cache
        second_result = track.scrobbles

        assert second_result == first_result
        assert second_result == mock_scrobbles
        # Verify NO additional API call
        mock_user.get_track_scrobbles.assert_not_called()

    @freeze_time("2024-01-15 12:00:00")
    def test_scrobbles_property_called_multiple_times_only_fetches_once(self):
        """Multiple accesses to scrobbles property only make one API call."""
        mock_user = MagicMock()
        mock_scrobbles = [MagicMock(timestamp="1704067200")]
        mock_user.get_track_scrobbles.return_value = mock_scrobbles

        track = Track("Artist", "Title", "url", mock_user)

        # Access scrobbles 5 times
        for _ in range(5):
            _ = track.scrobbles

        # Should only call API once
        assert mock_user.get_track_scrobbles.call_count == 1


class TestGetScrobblesCount:
    """Test get_scrobbles_count method."""

    @freeze_time("2024-01-15 12:00:00")
    def test_get_scrobbles_count_without_period_returns_total(self):
        """get_scrobbles_count without period returns total count."""
        mock_user = MagicMock()
        mock_scrobbles = [
            MagicMock(timestamp="1704067200"),  # 2024-01-01
            MagicMock(timestamp="1704153600"),  # 2024-01-02
            MagicMock(timestamp="1704240000"),  # 2024-01-03
        ]
        mock_user.get_track_scrobbles.return_value = mock_scrobbles

        track = Track("Artist", "Title", "url", mock_user)
        count = track.get_scrobbles_count()

        assert count == 3

    @freeze_time("2024-01-15 12:00:00")
    def test_get_scrobbles_count_with_period_filters_by_days(self):
        """get_scrobbles_count with period filters scrobbles by days."""
        mock_user = MagicMock()
        # Current time: 2024-01-15 12:00:00
        # Scrobbles at different times
        mock_scrobbles = [
            MagicMock(timestamp="1704067200"),  # 2024-01-01 (14 days ago)
            MagicMock(timestamp="1704931200"),  # 2024-01-11 (4 days ago)
            MagicMock(timestamp="1705276800"),  # 2024-01-15 (today)
        ]
        mock_user.get_track_scrobbles.return_value = mock_scrobbles

        track = Track("Artist", "Title", "url", mock_user)

        # Test with 7-day period - should only get last 2 scrobbles
        count_7_days = track.get_scrobbles_count(period=7)
        assert count_7_days == 2

        # Test with 30-day period - should get all 3
        count_30_days = track.get_scrobbles_count(period=30)
        assert count_30_days == 3

    @freeze_time("2024-01-15 12:00:00")
    def test_get_scrobbles_count_reuses_cached_scrobbles(self):
        """get_scrobbles_count reuses cached scrobbles data."""
        mock_user = MagicMock()
        mock_scrobbles = [
            MagicMock(timestamp="1704067200"),
            MagicMock(timestamp="1704153600"),
        ]
        mock_user.get_track_scrobbles.return_value = mock_scrobbles

        track = Track("Artist", "Title", "url", mock_user)

        # Call get_scrobbles_count multiple times with different periods
        _ = track.get_scrobbles_count()
        _ = track.get_scrobbles_count(period=7)
        _ = track.get_scrobbles_count(period=30)

        # Should only make ONE API call (all use cached scrobbles)
        assert mock_user.get_track_scrobbles.call_count == 1


class TestGetScrobblesUrl:
    """Test get_scrobbles_url method."""

    def test_get_scrobbles_url_without_period(self):
        """get_scrobbles_url without period returns base URL."""
        mock_user = MagicMock()
        mock_user.name = "testuser"
        track = Track("Artist", "Title", "https://www.last.fm/music/Artist/_/Title", mock_user)

        url = track.get_scrobbles_url()
        assert url == "https://www.last.fm/user/testuser/library/music/Artist/_/Title"

    def test_get_scrobbles_url_with_period(self):
        """get_scrobbles_url with period adds date_preset parameter."""
        mock_user = MagicMock()
        mock_user.name = "testuser"
        track = Track("Artist", "Title", "https://www.last.fm/music/Artist/_/Title", mock_user)

        url = track.get_scrobbles_url(period="LAST_90_DAYS")
        assert url == "https://www.last.fm/user/testuser/library/music/Artist/_/Title?date_preset=LAST_90_DAYS"

    def test_get_scrobbles_url_handles_missing_url(self):
        """get_scrobbles_url handles missing URL gracefully."""
        mock_user = MagicMock()
        track = Track("Artist", "Title", None, mock_user)

        url = track.get_scrobbles_url()
        assert url is None


class TestGetRecentTracksScrobbles:
    """Test User.get_recent_tracks_scrobbles method."""

    @freeze_time("2024-01-15 12:00:00")
    @patch("spotfm.lastfm.sleep")  # Mock sleep to speed up tests
    def test_get_recent_tracks_scrobbles_basic(self, mock_sleep):
        """Test basic functionality of get_recent_tracks_scrobbles."""
        # Setup mock user
        mock_client = MagicMock()
        mock_pylast_user = MagicMock()
        mock_client.get_authenticated_user.return_value = mock_pylast_user

        # Mock recent tracks
        mock_track1 = MagicMock()
        mock_track1.track.artist.name = "Artist 1"
        mock_track1.track.title = "Track 1"
        mock_track1.track.get_url.return_value = "http://last.fm/track1"

        mock_track2 = MagicMock()
        mock_track2.track.artist.name = "Artist 2"
        mock_track2.track.title = "Track 2"
        mock_track2.track.get_url.return_value = "http://last.fm/track2"

        mock_pylast_user.get_recent_tracks.return_value = [mock_track1, mock_track2]

        # Mock scrobbles for each track
        scrobbles1 = [MagicMock(timestamp="1704067200"), MagicMock(timestamp="1705276800")]
        scrobbles2 = [MagicMock(timestamp="1704153600")]

        def mock_get_scrobbles(artist, title):
            if artist == "Artist 1":
                return scrobbles1
            elif artist == "Artist 2":
                return scrobbles2
            return []

        mock_pylast_user.get_track_scrobbles.side_effect = mock_get_scrobbles

        # Create user and call method
        user = User(mock_client)
        results = list(user.get_recent_tracks_scrobbles(limit=2, scrobbles_minimum=0, period=90, period_minimum=None))

        # Verify results
        assert len(results) == 2
        assert results[0]["artist"] == "Artist 1"
        assert results[0]["title"] == "Track 1"
        assert results[0]["period_scrobbles"] == 2
        assert results[0]["total_scrobbles"] == 2
        assert results[1]["artist"] == "Artist 2"
        assert results[1]["title"] == "Track 2"
        assert results[1]["period_scrobbles"] == 1
        assert results[1]["total_scrobbles"] == 1

        # Verify API calls
        mock_pylast_user.get_recent_tracks.assert_called_once_with(limit=2)
        assert mock_pylast_user.get_track_scrobbles.call_count == 2

    @freeze_time("2024-01-15 12:00:00")
    @patch("spotfm.lastfm.sleep")
    def test_get_recent_tracks_scrobbles_no_now_playing_check(self, mock_sleep):
        """Verify get_recent_tracks_scrobbles does not check now playing."""
        mock_client = MagicMock()
        mock_pylast_user = MagicMock()
        mock_client.get_authenticated_user.return_value = mock_pylast_user

        mock_pylast_user.get_recent_tracks.return_value = []

        user = User(mock_client)
        list(user.get_recent_tracks_scrobbles(period_minimum=None))

        # Verify get_now_playing is NEVER called
        assert not mock_pylast_user.get_now_playing.called

    @freeze_time("2024-01-15 12:00:00")
    @patch("spotfm.lastfm.sleep")
    def test_get_recent_tracks_scrobbles_deduplicates_tracks(self, mock_sleep):
        """get_recent_tracks_scrobbles deduplicates duplicate tracks."""
        mock_client = MagicMock()
        mock_pylast_user = MagicMock()
        mock_client.get_authenticated_user.return_value = mock_pylast_user

        # Same track appears twice in recent tracks
        mock_track1 = MagicMock()
        mock_track1.track.artist.name = "Artist"
        mock_track1.track.title = "Track"
        mock_track1.track.get_url.return_value = "http://last.fm/track"

        mock_track2 = MagicMock()
        mock_track2.track.artist.name = "Artist"
        mock_track2.track.title = "Track"  # Same track
        mock_track2.track.get_url.return_value = "http://last.fm/track"

        mock_pylast_user.get_recent_tracks.return_value = [mock_track1, mock_track2]

        scrobbles = [MagicMock(timestamp="1704067200")]
        mock_pylast_user.get_track_scrobbles.return_value = scrobbles

        user = User(mock_client)
        results = list(user.get_recent_tracks_scrobbles(limit=2, period_minimum=None))

        # Should only return one track
        assert len(results) == 1
        # Should only fetch scrobbles once (not twice)
        assert mock_pylast_user.get_track_scrobbles.call_count == 1

    @freeze_time("2024-01-15 12:00:00")
    @patch("spotfm.lastfm.sleep")
    def test_get_recent_tracks_scrobbles_filters_by_minimum(self, mock_sleep):
        """get_recent_tracks_scrobbles filters tracks by minimum scrobble count."""
        mock_client = MagicMock()
        mock_pylast_user = MagicMock()
        mock_client.get_authenticated_user.return_value = mock_pylast_user

        # Two tracks with different scrobble counts
        mock_track1 = MagicMock()
        mock_track1.track.artist.name = "Artist 1"
        mock_track1.track.title = "Track 1"
        mock_track1.track.get_url.return_value = "http://last.fm/track1"

        mock_track2 = MagicMock()
        mock_track2.track.artist.name = "Artist 2"
        mock_track2.track.title = "Track 2"
        mock_track2.track.get_url.return_value = "http://last.fm/track2"

        mock_pylast_user.get_recent_tracks.return_value = [mock_track1, mock_track2]

        # Track 1 has 5 scrobbles, Track 2 has 2 scrobbles
        def mock_get_scrobbles(artist, title):
            if artist == "Artist 1":
                return [MagicMock(timestamp="1704067200")] * 5
            elif artist == "Artist 2":
                return [MagicMock(timestamp="1704067200")] * 2
            return []

        mock_pylast_user.get_track_scrobbles.side_effect = mock_get_scrobbles

        user = User(mock_client)
        # Set minimum to 3 - should only get Track 1
        results = list(user.get_recent_tracks_scrobbles(limit=2, scrobbles_minimum=3, period_minimum=None))

        assert len(results) == 1
        assert results[0]["artist"] == "Artist 1"
        assert results[0]["title"] == "Track 1"

    @freeze_time("2024-01-15 12:00:00")
    @patch("spotfm.lastfm.sleep")
    def test_get_recent_tracks_scrobbles_calculates_period_counts_correctly(self, mock_sleep):
        """get_recent_tracks_scrobbles calculates period scrobble counts correctly."""
        mock_client = MagicMock()
        mock_pylast_user = MagicMock()
        mock_client.get_authenticated_user.return_value = mock_pylast_user

        mock_track = MagicMock()
        mock_track.track.artist.name = "Artist"
        mock_track.track.title = "Track"
        mock_track.track.get_url.return_value = "http://last.fm/track"

        mock_pylast_user.get_recent_tracks.return_value = [mock_track]

        # Scrobbles: 2 within 7 days, 1 older (14 days ago)
        # Current time: 2024-01-15 12:00:00
        scrobbles = [
            MagicMock(timestamp="1704067200"),  # 2024-01-01 (14 days ago)
            MagicMock(timestamp="1704931200"),  # 2024-01-11 (4 days ago)
            MagicMock(timestamp="1705276800"),  # 2024-01-15 (today)
        ]
        mock_pylast_user.get_track_scrobbles.return_value = scrobbles

        user = User(mock_client)
        results = list(user.get_recent_tracks_scrobbles(limit=1, period=7, period_minimum=None))

        # Should show 2 scrobbles in last 7 days, 3 total
        assert len(results) == 1
        assert results[0]["period_scrobbles"] == 2
        assert results[0]["total_scrobbles"] == 3

    @patch("spotfm.lastfm.sleep")
    def test_get_recent_tracks_scrobbles_invalid_period_raises_error(self, mock_sleep):
        """get_recent_tracks_scrobbles raises error for invalid period."""
        mock_client = MagicMock()
        mock_pylast_user = MagicMock()
        mock_client.get_authenticated_user.return_value = mock_pylast_user

        user = User(mock_client)

        with pytest.raises(UnknownPeriodError) as exc_info:
            list(user.get_recent_tracks_scrobbles(period=999, period_minimum=None))

        assert "period should be part of" in str(exc_info.value)
        assert str(PREDEFINED_PERIODS) in str(exc_info.value)

    @freeze_time("2024-01-15 12:00:00")
    @patch("spotfm.lastfm.sleep")
    def test_get_recent_tracks_scrobbles_rate_limiting(self, mock_sleep):
        """get_recent_tracks_scrobbles calls sleep for rate limiting."""
        mock_client = MagicMock()
        mock_pylast_user = MagicMock()
        mock_client.get_authenticated_user.return_value = mock_pylast_user

        # Create 3 unique tracks
        tracks = []
        for i in range(3):
            mock_track = MagicMock()
            mock_track.track.artist.name = f"Artist {i}"
            mock_track.track.title = f"Track {i}"
            mock_track.track.get_url.return_value = f"http://last.fm/track{i}"
            tracks.append(mock_track)

        mock_pylast_user.get_recent_tracks.return_value = tracks
        mock_pylast_user.get_track_scrobbles.return_value = [MagicMock(timestamp="1704067200")]

        user = User(mock_client)
        list(user.get_recent_tracks_scrobbles(limit=3, period_minimum=None))

        # Should call sleep 3 times (once per track) with 0.2 seconds
        assert mock_sleep.call_count == 3
        for call in mock_sleep.call_args_list:
            assert call[0][0] == 0.2  # First positional argument should be 0.2

    @freeze_time("2024-01-15 12:00:00")
    @patch("spotfm.lastfm.sleep")
    def test_get_recent_tracks_scrobbles_filters_by_period_minimum(self, mock_sleep):
        """get_recent_tracks_scrobbles filters tracks by period_minimum."""
        mock_client = MagicMock()
        mock_pylast_user = MagicMock()
        mock_client.get_authenticated_user.return_value = mock_pylast_user

        # Two tracks with different period scrobble counts
        mock_track1 = MagicMock()
        mock_track1.track.artist.name = "Artist 1"
        mock_track1.track.title = "Track 1"
        mock_track1.track.get_url.return_value = "http://last.fm/track1"

        mock_track2 = MagicMock()
        mock_track2.track.artist.name = "Artist 2"
        mock_track2.track.title = "Track 2"
        mock_track2.track.get_url.return_value = "http://last.fm/track2"

        mock_pylast_user.get_recent_tracks.return_value = [mock_track1, mock_track2]

        # Track 1 has 3 scrobbles in period (past 7 days), Track 2 has 1
        # Current time: 2024-01-15
        def mock_get_scrobbles(artist, title):
            if artist == "Artist 1":
                return [
                    MagicMock(timestamp="1704931200"),  # 2024-01-11 (4 days ago)
                    MagicMock(timestamp="1705017600"),  # 2024-01-12 (3 days ago)
                    MagicMock(timestamp="1705276800"),  # 2024-01-15 (today)
                ]
            elif artist == "Artist 2":
                return [MagicMock(timestamp="1704067200")]  # 2024-01-01 (14 days ago)
            return []

        mock_pylast_user.get_track_scrobbles.side_effect = mock_get_scrobbles

        user = User(mock_client)
        # Set period_minimum to 2 - should only get Track 1
        results = list(user.get_recent_tracks_scrobbles(limit=2, period=7, period_minimum=2))

        assert len(results) == 1
        assert results[0]["artist"] == "Artist 1"
        assert results[0]["title"] == "Track 1"

    @freeze_time("2024-01-15 12:00:00")
    @patch("spotfm.lastfm.sleep")
    def test_get_recent_tracks_scrobbles_period_minimum_with_scrobbles_minimum(self, mock_sleep):
        """get_recent_tracks_scrobbles applies both scrobbles_minimum and period_minimum."""
        mock_client = MagicMock()
        mock_pylast_user = MagicMock()
        mock_client.get_authenticated_user.return_value = mock_pylast_user

        mock_track1 = MagicMock()
        mock_track1.track.artist.name = "Artist 1"
        mock_track1.track.title = "Track 1"
        mock_track1.track.get_url.return_value = "http://last.fm/track1"

        mock_track2 = MagicMock()
        mock_track2.track.artist.name = "Artist 2"
        mock_track2.track.title = "Track 2"
        mock_track2.track.get_url.return_value = "http://last.fm/track2"

        mock_pylast_user.get_recent_tracks.return_value = [mock_track1, mock_track2]

        # Track 1: 2 total, 2 in period
        # Track 2: 5 total, 1 in period
        def mock_get_scrobbles(artist, title):
            if artist == "Artist 1":
                return [
                    MagicMock(timestamp="1704931200"),  # 2024-01-11 (4 days ago)
                    MagicMock(timestamp="1705276800"),  # 2024-01-15 (today)
                ]
            elif artist == "Artist 2":
                return [
                    MagicMock(timestamp="1704067200"),  # 2024-01-01 (old)
                    MagicMock(timestamp="1704153600"),  # 2024-01-02 (old)
                    MagicMock(timestamp="1704240000"),  # 2024-01-03 (old)
                    MagicMock(timestamp="1704326400"),  # 2024-01-04 (old)
                    MagicMock(timestamp="1705276800"),  # 2024-01-15 (today)
                ]
            return []

        mock_pylast_user.get_track_scrobbles.side_effect = mock_get_scrobbles

        user = User(mock_client)
        # scrobbles_minimum=2, period_minimum=2
        # Track 1: 2 total (pass) but 2 in period (pass) -> INCLUDED
        # Track 2: 5 total (pass) but 1 in period (fail) -> EXCLUDED
        results = list(user.get_recent_tracks_scrobbles(limit=2, scrobbles_minimum=2, period=7, period_minimum=2))

        assert len(results) == 1
        assert results[0]["artist"] == "Artist 1"
        assert results[0]["title"] == "Track 1"

    @freeze_time("2024-01-15 12:00:00")
    @patch("spotfm.lastfm.sleep")
    def test_get_recent_tracks_scrobbles_output_format(self, mock_sleep):
        """get_recent_tracks_scrobbles returns structured dict with artist, title, counts, and url."""
        mock_client = MagicMock()
        mock_pylast_user = MagicMock()
        mock_client.get_authenticated_user.return_value = mock_pylast_user
        mock_pylast_user.name = "testuser"

        mock_track = MagicMock()
        mock_track.track.artist.name = "The Beatles"
        mock_track.track.title = "Hey Jude"
        mock_track.track.get_url.return_value = "https://www.last.fm/music/The+Beatles/_/Hey+Jude"

        mock_pylast_user.get_recent_tracks.return_value = [mock_track]

        scrobbles = [
            MagicMock(timestamp="1704067200"),  # 14 days ago
            MagicMock(timestamp="1705276800"),  # today
        ]
        mock_pylast_user.get_track_scrobbles.return_value = scrobbles

        user = User(mock_client)
        results = list(user.get_recent_tracks_scrobbles(limit=1, period=7, period_minimum=None))

        assert len(results) == 1
        track = results[0]
        assert track["artist"] == "The Beatles"
        assert track["title"] == "Hey Jude"
        assert track["period_scrobbles"] == 1  # 1 scrobble in last 7 days
        assert track["total_scrobbles"] == 2  # 2 total scrobbles
        assert "last.fm/user/testuser/library" in track["url"]
        assert "date_preset=LAST_7_DAYS" in track["url"]


@pytest.mark.unit
class TestPositiveIntValidator:
    """Tests for _positive_int validator function."""

    def test_positive_int_accepts_positive_integers(self):
        """_positive_int accepts positive integers."""
        assert _positive_int("1") == 1
        assert _positive_int("10") == 10
        assert _positive_int("999") == 999

    def test_positive_int_rejects_zero(self):
        """_positive_int rejects zero."""
        with pytest.raises(argparse.ArgumentTypeError):
            _positive_int("0")

    def test_positive_int_rejects_negative(self):
        """_positive_int rejects negative integers."""
        with pytest.raises(argparse.ArgumentTypeError):
            _positive_int("-1")
        with pytest.raises(argparse.ArgumentTypeError):
            _positive_int("-100")

    def test_positive_int_rejects_non_integer(self):
        """_positive_int rejects non-integer strings."""
        with pytest.raises(ValueError):
            _positive_int("abc")
        with pytest.raises(ValueError):
            _positive_int("1.5")


@pytest.mark.unit
class TestNonNegativeIntValidator:
    """Tests for _non_negative_int validator function."""

    def test_non_negative_int_accepts_zero(self):
        """_non_negative_int accepts zero."""
        assert _non_negative_int("0") == 0

    def test_non_negative_int_accepts_positive_integers(self):
        """_non_negative_int accepts positive integers."""
        assert _non_negative_int("1") == 1
        assert _non_negative_int("10") == 10
        assert _non_negative_int("999") == 999

    def test_non_negative_int_rejects_negative(self):
        """_non_negative_int rejects negative integers."""
        with pytest.raises(argparse.ArgumentTypeError):
            _non_negative_int("-1")
        with pytest.raises(argparse.ArgumentTypeError):
            _non_negative_int("-100")

    def test_non_negative_int_rejects_non_integer(self):
        """_non_negative_int rejects non-integer strings."""
        with pytest.raises(ValueError):
            _non_negative_int("abc")
        with pytest.raises(ValueError):
            _non_negative_int("1.5")
