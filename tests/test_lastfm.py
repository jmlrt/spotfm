from unittest.mock import MagicMock, patch

import pytest
from freezegun import freeze_time

from spotfm.lastfm import PREDEFINED_PERIODS, Track, UnknownPeriodError, User


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
    @patch("time.sleep")  # Mock sleep to speed up tests
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
        results = list(user.get_recent_tracks_scrobbles(limit=2, scrobbles_minimum=0, period=90))

        # Verify results
        assert len(results) == 2
        assert "Artist 1 - Track 1" in results[0]
        assert "2 - 2" in results[0]  # period_scrobbles - total_scrobbles
        assert "Artist 2 - Track 2" in results[1]
        assert "1 - 1" in results[1]

        # Verify API calls
        mock_pylast_user.get_recent_tracks.assert_called_once_with(limit=2)
        assert mock_pylast_user.get_track_scrobbles.call_count == 2

    @freeze_time("2024-01-15 12:00:00")
    @patch("time.sleep")
    def test_get_recent_tracks_scrobbles_no_now_playing_check(self, mock_sleep):
        """Verify get_recent_tracks_scrobbles does not check now playing."""
        mock_client = MagicMock()
        mock_pylast_user = MagicMock()
        mock_client.get_authenticated_user.return_value = mock_pylast_user

        mock_pylast_user.get_recent_tracks.return_value = []

        user = User(mock_client)
        list(user.get_recent_tracks_scrobbles())

        # Verify get_now_playing is NEVER called
        assert not mock_pylast_user.get_now_playing.called

    @freeze_time("2024-01-15 12:00:00")
    @patch("time.sleep")
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
        results = list(user.get_recent_tracks_scrobbles(limit=2))

        # Should only return one track
        assert len(results) == 1
        # Should only fetch scrobbles once (not twice)
        assert mock_pylast_user.get_track_scrobbles.call_count == 1

    @freeze_time("2024-01-15 12:00:00")
    @patch("time.sleep")
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
        results = list(user.get_recent_tracks_scrobbles(limit=2, scrobbles_minimum=3))

        assert len(results) == 1
        assert "Artist 1 - Track 1" in results[0]

    @freeze_time("2024-01-15 12:00:00")
    @patch("time.sleep")
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
        results = list(user.get_recent_tracks_scrobbles(limit=1, period=7))

        # Should show 2 scrobbles in last 7 days, 3 total
        assert len(results) == 1
        assert "2 - 3" in results[0]  # period_count=2, total_count=3

    @patch("time.sleep")
    def test_get_recent_tracks_scrobbles_invalid_period_raises_error(self, mock_sleep):
        """get_recent_tracks_scrobbles raises error for invalid period."""
        mock_client = MagicMock()
        mock_pylast_user = MagicMock()
        mock_client.get_authenticated_user.return_value = mock_pylast_user

        user = User(mock_client)

        with pytest.raises(UnknownPeriodError) as exc_info:
            list(user.get_recent_tracks_scrobbles(period=999))

        assert "period shoud be part of" in str(exc_info.value)
        assert str(PREDEFINED_PERIODS) in str(exc_info.value)

    @freeze_time("2024-01-15 12:00:00")
    @patch("time.sleep")
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
        list(user.get_recent_tracks_scrobbles(limit=3))

        # Should call sleep 3 times (once per track) with 0.2 seconds
        assert mock_sleep.call_count == 3
        for call in mock_sleep.call_args_list:
            assert call[0][0] == 0.2  # First positional argument should be 0.2

    @freeze_time("2024-01-15 12:00:00")
    @patch("time.sleep")
    def test_get_recent_tracks_scrobbles_output_format(self, mock_sleep):
        """get_recent_tracks_scrobbles maintains backward-compatible output format."""
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
        results = list(user.get_recent_tracks_scrobbles(limit=1, period=7))

        # Format: "Artist - Title - period_scrobbles - total_scrobbles - url"
        assert len(results) == 1
        parts = results[0].split(" - ")
        assert parts[0] == "The Beatles"
        assert parts[1] == "Hey Jude"
        assert parts[2] == "1"  # 1 scrobble in last 7 days
        assert parts[3] == "2"  # 2 total scrobbles
        assert "last.fm/user/testuser/library" in parts[4]
        assert "date_preset=LAST_7_DAYS" in parts[4]
