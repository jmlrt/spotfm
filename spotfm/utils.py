import logging
import pickle
import tomllib
from datetime import datetime
from pathlib import Path

HOME_DIR = Path.home()
CONFIG_FILE = HOME_DIR / ".spotfm.toml"
WORK_DIR = HOME_DIR / ".spotfm"
CACHE_DIR = WORK_DIR / "cache"


def get_date():
    return datetime.today().strftime("%Y%m%d")


def parse_config(file=CONFIG_FILE):
    with open(file, mode="rb") as f:
        config = tomllib.load(f)
    return config


def cache_object(object, filename):
    cache_file = CACHE_DIR / filename
    Path(cache_file).parent.mkdir(parents=True, exist_ok=True)
    with open(cache_file, "wb") as f:
        pickle.dump(object, f)
    logging.info(f"{object} has been cached to {cache_file}")


def retrieve_object_from_cache(filename):
    cache_file = CACHE_DIR / filename
    if cache_file.exists():
        with open(cache_file, "rb") as f:
            object = pickle.load(f)
            logging.info(f"{object} has been retrieved from {cache_file}")
            return object
    return None
