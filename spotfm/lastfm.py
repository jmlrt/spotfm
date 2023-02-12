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

    def __str__(self):
        return f"{self.artist[0:50]} - {self.title[0:50]}"

    @property
    def scrobbles(self):
        return self.user.get_track_scrobbles(self.artist, self.title)

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
        if period not in PREDEFINED_PERIODS:
            raise UnknownPeriodError(f"period shoud be part of {PREDEFINED_PERIODS}")

        tracks = set()

        current_track = self.user.get_now_playing()
        if current_track is not None:
            track = Track(
                current_track.artist.name,
                current_track.title,
                current_track.get_url(),
                self.user,
            )
            scrobble_count = track.get_scrobbles_count() + 1
            if scrobble_count >= scrobbles_minimum:
                tracks.add(track)

        recent_tracks = self.user.get_recent_tracks(limit=limit)
        for recent_track in recent_tracks:
            track = Track(
                recent_track.track.artist.name,
                recent_track.track.title,
                recent_track.track.get_url(),
                self.user,
            )
            scrobble_count = track.get_scrobbles_count()
            if scrobble_count >= scrobbles_minimum:
                tracks.add(track)

        for track in tracks:
            period_scrobbles = track.get_scrobbles_count(period)
            total_scrobbles = track.get_scrobbles_count()
            url = track.get_scrobbles_url(f"LAST_{period}_DAYS")
            yield (f"{track} - {period_scrobbles} - {total_scrobbles} - {url}")
