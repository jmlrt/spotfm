from datetime import datetime

import pylast

LASTFM_BASE_URL = "https://www.last.fm"
PREDEFINED_PERIODS = [7, 30, 90, 180, 365]


class UnknownPeriodError(Exception):
    pass


class Client:
    def __init__(self, api_key, api_secret, username, password_hash):
        self.client = pylast.LastFMNetwork(
            api_key=api_key,
            api_secret=api_secret,
            username=username,
            password_hash=password_hash,
        )


class Track:
    def __init__(self, artist, title, url, user):
        self.artist = artist
        self.title = title
        self.url = url
        self.user = user
        self._scrobbles_cache = None  # In-memory cache for scrobbles

    def __str__(self):
        return f"{self.artist[0:50]} - {self.title[0:50]}"

    @property
    def scrobbles(self):
        """Fetch scrobbles with in-memory cache (valid for execution only)."""
        if self._scrobbles_cache is None:
            # First access - fetch from API
            self._scrobbles_cache = self.user.get_track_scrobbles(self.artist, self.title)
        return self._scrobbles_cache

    def get_scrobbles_count(self, period=None):
        now = datetime.now()
        scrobbles_ts = []
        for scrobble in self.scrobbles:
            timestamp = datetime.fromtimestamp(int(scrobble.timestamp))
            delta = now - timestamp
            if period is None or delta.days < period:
                scrobbles_ts.append(timestamp)
        return len(scrobbles_ts)

    def get_scrobbles_url(self, period=None):
        try:
            url = self.url.replace(LASTFM_BASE_URL, f"{LASTFM_BASE_URL}/user/{self.user.name}/library")
            if period is not None:
                url = url + f"?date_preset={period}"
        except AttributeError:
            url = self.url
        return url


class User:
    def __init__(self, client):
        self.user = client.get_authenticated_user()

    def get_recent_tracks_scrobbles(self, limit=10, scrobbles_minimum=0, period=90):
        """Get recent tracks with scrobble counts (optimized)."""
        if period not in PREDEFINED_PERIODS:
            raise UnknownPeriodError(f"period shoud be part of {PREDEFINED_PERIODS}")

        # Fetch recent tracks (1 API call)
        recent_tracks = self.user.get_recent_tracks(limit=limit)

        # Build unique track set
        seen_tracks = set()
        tracks_data = []

        for recent_track in recent_tracks:
            track = Track(
                recent_track.track.artist.name,
                recent_track.track.title,
                recent_track.track.get_url(),
                self.user,
            )

            # Deduplicate tracks
            track_key = (track.artist, track.title)
            if track_key in seen_tracks:
                continue
            seen_tracks.add(track_key)

            # CRITICAL: Fetch scrobbles ONCE per track (uses in-memory cache)
            scrobbles = track.scrobbles

            # Calculate counts from the same scrobble list
            now = datetime.now()
            total_count = len(scrobbles)
            period_count = sum(1 for s in scrobbles if (now - datetime.fromtimestamp(int(s.timestamp))).days < period)

            # Apply minimum threshold filter
            if total_count >= scrobbles_minimum:
                url = track.get_scrobbles_url(f"LAST_{period}_DAYS")
                tracks_data.append((track, period_count, total_count, url))

            # Rate limiting: 0.2s between API calls (5 req/sec = Last.FM limit)
            from time import sleep

            sleep(0.2)

        # Yield results (same format as before - backward compatible)
        for track, period_scrobbles, total_scrobbles, url in tracks_data:
            yield f"{track} - {period_scrobbles} - {total_scrobbles} - {url}"
