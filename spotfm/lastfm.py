import contextlib
import json
import logging
import tempfile
from datetime import datetime
from pathlib import Path
from time import sleep

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

    def get_recent_tracks_scrobbles(self, limit=10, scrobbles_minimum=0, period=90, period_minimum=None):
        """Get recent tracks with scrobble counts (optimized).

        Args:
            limit: Number of recent tracks to fetch
            scrobbles_minimum: Minimum total scrobbles to include in results
            period: Period in days to count scrobbles within
            period_minimum: Minimum scrobbles in the period window (None = no filter)
        """
        if period not in PREDEFINED_PERIODS:
            raise UnknownPeriodError(f"period should be part of {PREDEFINED_PERIODS}")

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

            # Apply minimum threshold filters
            if total_count >= scrobbles_minimum and (period_minimum is None or period_count >= period_minimum):
                url = track.get_scrobbles_url(f"LAST_{period}_DAYS")
                tracks_data.append((track, period_count, total_count, url))

            # Rate limiting: 0.2s between API calls (5 req/sec = Last.FM limit)
            sleep(0.2)

        # Yield structured track data for callers to format as needed
        for track, period_scrobbles, total_scrobbles, url in tracks_data:
            yield {
                "artist": track.artist,
                "title": track.title,
                "period_scrobbles": period_scrobbles,
                "total_scrobbles": total_scrobbles,
                "url": url,
            }


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


def fetch_recent_scrobbles(user, config, *, limit=None, scrobbles_minimum=None, period=90, period_minimum=None):
    """Fetch recent scrobbles with incremental state management.

    Handles the orchestration of reading saved state, computing effective limits,
    and saving state after fetch. This ensures consistent behavior across CLI and web.

    Args:
        user: Last.FM User instance
        config: Last.FM config dict with keys: limit, scrobbles_minimum, period_minimum
        limit: Explicit limit override (if None, uses incremental mode with saved state)
        scrobbles_minimum: Minimum total scrobbles filter (if None, uses config)
        period: Period in days for scrobble counting (default 90)
        period_minimum: Minimum scrobbles in period window (if None, uses config)

    Returns:
        tuple: (tracks: list[dict], mode: str) where mode is "incremental", "full", or "no_new"
    """
    current_count = user.get_playcount()
    scrobble_count_to_save = current_count

    # Resolve config defaults
    effective_limit = limit if limit is not None else config.get("limit", 50)
    effective_scrobbles_minimum = (
        scrobbles_minimum if scrobbles_minimum is not None else config.get("scrobbles_minimum", 4)
    )
    effective_period_minimum = period_minimum if period_minimum is not None else config.get("period_minimum")

    # Check for saved state first. If it exists, use incremental mode (ignore explicit limit)
    state = read_lastfm_state()
    mode = "full"
    if state is not None and isinstance(state, dict):
        last_scrobble_count = state.get("last_scrobble_count")
        if isinstance(last_scrobble_count, int):
            # Saved state exists: always use incremental mode, compute limit from diff
            mode = "incremental"
            computed_limit = current_count - last_scrobble_count
            if computed_limit <= 0:
                save_lastfm_state(current_count)
                return [], "no_new"
            effective_limit = computed_limit
    else:
        # No saved state: use full mode with provided limit or config default
        mode = "full" if limit is not None else "full"

    # Fetch scrobbles
    tracks = list(
        user.get_recent_tracks_scrobbles(
            limit=effective_limit,
            scrobbles_minimum=effective_scrobbles_minimum,
            period=period,
            period_minimum=effective_period_minimum,
        )
    )

    # Save state after successful fetch
    save_lastfm_state(scrobble_count_to_save)

    return tracks, mode
