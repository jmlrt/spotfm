import json
import logging
import pickle
import tomllib
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

HOME_DIR = Path.home()
WORK_DIR = HOME_DIR / ".spotfm"
CACHE_DIR = HOME_DIR / ".cache" / "spotfm"
CONFIG_FILE = WORK_DIR / "spotfm.toml"
DATABASE = WORK_DIR / "spotify.db"
LASTFM_STATE_FILE = WORK_DIR / "lastfm_state.json"
DATABASE_LOG_LEVEL = logging.debug


def get_date():
    return datetime.today().strftime("%Y%m%d")


def sanitize_string(string):
    return string.replace("'", "")


def parse_url(url):
    return urlparse(url).path.split("/")[-1]


def parse_config(file=CONFIG_FILE):
    with open(file, mode="rb") as f:
        config = tomllib.load(f)
    return config


# Parse a file with track ids and return a list of track ids
def manage_tracks_ids_file(file_path):
    with open(file_path) as file:
        tracks_ids = file.readlines()
        # remove new line character from each track id
        tracks_ids = [track_id.strip() for track_id in tracks_ids]
        return tracks_ids


def cache_object(object):
    """
    Cache a given object to a file.

    This function serializes the provided object and saves it to a file
    specified by the filename within the CACHE_DIR directory. If the
    directory does not exist, it will be created.
    """
    cache_file = CACHE_DIR / object.kind / f"{object.id}.pickle"
    Path(cache_file).parent.mkdir(parents=True, exist_ok=True)
    with open(cache_file, "wb") as f:
        pickle.dump(object, f)
    logging.info(f"{object} has been cached to {cache_file}")


def read_lastfm_state(state_file=None):
    """Read Last.FM state from file. Returns dict with last_scrobble_count, or None if not found."""
    path = Path(state_file) if state_file else LASTFM_STATE_FILE
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def save_lastfm_state(scrobble_count, state_file=None):
    """Save current Last.FM scrobble count to state file."""
    path = Path(state_file) if state_file else LASTFM_STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "last_scrobble_count": scrobble_count,
        "last_run_date": datetime.today().strftime("%Y-%m-%d"),
    }
    with open(path, "w") as f:
        json.dump(state, f, indent=2)


def retrieve_object_from_cache(kind, id):
    """
    Retrieve an object from the cache if it exists.
    """
    cache_file = CACHE_DIR / kind / f"{id}.pickle"
    if cache_file.exists():
        with open(cache_file, "rb") as f:
            object = pickle.load(f)
            logging.info(f"{object} has been retrieved from {cache_file}")
            return object
    return None
