import logging
import sqlite3
import time
import tomllib
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

HOME_DIR = Path.home()
WORK_DIR = HOME_DIR / ".spotfm"
CACHE_DIR = WORK_DIR / "cache"
CONFIG_FILE = WORK_DIR / "spotfm.toml"
DATABASE = WORK_DIR / "spotify.db"
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


def query_db(database, queries, script=False):
    con = sqlite3.connect(database)
    con.set_trace_callback(DATABASE_LOG_LEVEL)
    cur = con.cursor()
    for query in queries:
        if script:
            cur.executescript(query)
        else:
            cur.execute(query)
    con.commit()
    con.close()
    # spare CPU load
    time.sleep(0.01)


def select_db(database, query, params=""):
    con = sqlite3.connect(database)
    con.set_trace_callback(DATABASE_LOG_LEVEL)
    cur = con.cursor()
    res = cur.execute(query, params)
    return res
