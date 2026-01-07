import argparse
import logging
from pathlib import Path

from spotfm import sqlite

CREATE_TABLES_SCRIPT = Path("hacks") / "create-tables.sql"
ADD_INDEXES_SCRIPT = Path("hacks") / "add-indexes.sql"
TABLES = [
    "albums_artists",
    "albums_tracks",
    "artists_genres",
    "tracks_artists",
    "albums",
    "artists",
    "playlists",
    "tracks",
]


def clean_tables():
    queries = []
    for table in TABLES:
        queries.append(f"DELETE FROM {table}")
    sqlite.query_db(sqlite.DATABASE, queries)


def create_tables():
    with open(CREATE_TABLES_SCRIPT) as f:
        query_script = "".join(f.readlines())
    sqlite.query_db(sqlite.DATABASE, [query_script], script=True)


def add_indexes():
    with open(ADD_INDEXES_SCRIPT) as f:
        query_script = "".join(f.readlines())
    sqlite.query_db(sqlite.DATABASE, [query_script], script=True)


def main():
    logging.basicConfig(level=logging.DEBUG)
    parser = argparse.ArgumentParser(prog="manage-spotfm-db")
    parser.add_argument("command", choices=["clean-tables", "create-tables", "add-indexes"])
    args = parser.parse_args()

    match args.command:
        case "clean-tables":
            clean_tables()
        case "create-tables":
            create_tables()
        case "add-indexes":
            add_indexes()


if __name__ == "__main__":
    main()
