import contextlib
import json
import logging
import tempfile
from datetime import datetime
from pathlib import Path

import pylast

from spotfm import utils

LASTFM_BASE_URL = "https://www.last.fm"
PREDEFINED_PERIODS = [7, 30, 90, 180, 365]
LASTFM_STATE_FILE = utils.WORK_DIR / "lastfm_state.json"


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

    def get_playcount(self):
        """Get total scrobble count for the authenticated user."""
        return int(self.user.get_playcount())

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


def read_lastfm_state(state_file=None):
    """Read Last.FM state from file. Returns dict with last_scrobble_count, or None if not found/unreadable."""
    path = Path(state_file) if state_file else LASTFM_STATE_FILE
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError as e:
                logging.warning(f"Corrupted Last.FM state file at {path}, ignoring: {e}")
                return None
    except (OSError, UnicodeDecodeError) as e:
        logging.warning(f"Could not read Last.FM state file at {path}, ignoring: {e}")
        return None


def save_lastfm_state(scrobble_count, state_file=None):
    """Save current Last.FM scrobble count to state file using atomic writes."""
    path = Path(state_file) if state_file else LASTFM_STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "last_scrobble_count": scrobble_count,
        "last_run_date": datetime.today().strftime("%Y-%m-%d"),
    }
    tmp_path = None
    try:
        # Write to temporary file in same directory, then atomically replace destination
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False, suffix=".tmp") as tmp_file:
            json.dump(state, tmp_file, indent=2)
            tmp_path = Path(tmp_file.name)
        tmp_path.replace(path)
    except OSError as e:
        # Clean up orphaned temp file if replace failed
        if tmp_path and tmp_path.exists():
            with contextlib.suppress(OSError):
                tmp_path.unlink()
        logging.error(f"Failed to save Last.FM state file at {path}: {e}")
