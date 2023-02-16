import json
import logging
from datetime import date
from pathlib import Path

from spotfm import utils

EXPORTS_PATH = Path.home() / ".spotfm" / "exports"


def prepare_artists_queries(data):
    queries = []
    id = data["id"]
    name = utils.sanitize_string(data["name"])
    genres = data["genres"]
    updated_at = date.today()

    artist_query = f"INSERT OR IGNORE INTO artists VALUES ('{id}', '{name}', '{updated_at}')"
    queries.append(artist_query)

    if len(genres) > 0:
        values = ""
        for genre in genres:
            values += f"('{id}','{utils.sanitize_string(genre)}'),"
        genre_query = f"INSERT OR IGNORE INTO artists_genres VALUES {values}".rstrip(",")
        queries.append(genre_query)
    return queries


def prepare_tracks_queries(data):
    queries = []
    id = data["id"]
    name = utils.sanitize_string(data["name"])
    artists = data["artists"]
    updated_at = date.today()

    track_query = f"INSERT OR IGNORE INTO tracks VALUES ('{id}', '{name}', '{updated_at}')"
    queries.append(track_query)

    if len(artists) > 0:
        values = ""
        for artist in artists:
            artist_id = artist["id"]
            values += f"('{id}','{artist_id}'),"
        artists_query = f"INSERT OR IGNORE INTO tracks_artists VALUES {values}".rstrip(",")
        queries.append(artists_query)
    return queries


def prepare_albums_queries(data):
    queries = []
    track_id = data["id"]
    album_id = data["album"]["id"]
    album_name = utils.sanitize_string(data["album"]["name"])
    album_release_date = data["album"]["release_date"]
    album_artists = data["album"]["artists"]
    updated_at = date.today()

    album_query = (
        f"INSERT OR IGNORE INTO albums VALUES ('{album_id}', '{album_name}', '{album_release_date}', '{updated_at}')"
    )
    queries.append(album_query)

    album_track_query = f"INSERT OR IGNORE INTO albums_tracks VALUES ('{album_id}','{track_id}')"
    queries.append(album_track_query)

    if len(album_artists) > 0:
        values = ""
        for artist in album_artists:
            artist_id = artist["id"]
            values += f"('{album_id}','{artist_id}'),"
        album_artists_query = f"INSERT OR IGNORE INTO albums_artists VALUES {values}".rstrip(",")
        queries.append(album_artists_query)
    return queries


def prepare_playlists_queries(data):
    queries = []
    id = data["id"]
    name = utils.sanitize_string(data["name"])
    owner = utils.sanitize_string(data["owner"]["id"])
    tracks = data["tracks"]["items"]
    updated_at = date.today()
    playlist_query = f"INSERT OR IGNORE INTO playlists VALUES ('{id}', '{name}', '{owner}', '{updated_at}')"
    queries.append(playlist_query)

    if len(tracks) > 0:
        values = ""
        for track in tracks:
            try:
                track_id = track["track"]["id"]
            except TypeError:
                continue
            added_date = track["added_at"]
            values += f"('{id}','{track_id}', '{added_date}'),"
        tracks_query = f"INSERT OR IGNORE INTO playlists_tracks VALUES {values}".rstrip(",")
        queries.append(tracks_query)
    return queries


def import_json(kind):
    export_path = EXPORTS_PATH / kind
    for json_file in export_path.rglob("*.json"):
        logging.info("importing %s", json_file)

        with open(json_file) as f:
            data = json.load(f)

        match kind:
            case "artists":
                queries = prepare_artists_queries(data)
            case "tracks":
                queries = prepare_tracks_queries(data)
                queries = prepare_albums_queries(data)
            case "playlists":
                queries = prepare_playlists_queries(data)

        utils.query_db(utils.DATABASE, queries)


def main():
    logging.basicConfig(level=logging.INFO)
    for kind in ["artists", "tracks", "playlists"]:
        import_json(kind)


if __name__ == "__main__":
    main()
