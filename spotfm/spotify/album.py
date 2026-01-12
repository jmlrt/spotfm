import logging
from datetime import date

from spotfm import sqlite, utils
from spotfm.spotify.artist import Artist
from spotfm.spotify.constants import ALBUM_BATCH_SIZE, MARKET
from spotfm.utils import cache_object, retrieve_object_from_cache


class Album:
    kind = "album"

    def __init__(self, id, client=None, refresh=False):
        logging.info("Initializing Album %s", id)
        self.id = utils.parse_url(id)
        self.name = None
        self.release_date = None
        self.updated = None
        self.artists_id = []
        self.artists = []
        # TODO: add self.tracks

    def __repr__(self):
        return f"Album({self.name})"

    def __str__(self):
        return self.name

    @classmethod
    def get_album(cls, id, client=None, refresh=False, sync_to_db=True):
        album = retrieve_object_from_cache(cls.kind, id)
        if album is not None and (client is None or not refresh):
            return album

        album = Album(id, client)
        if client is not None and (not album.update_from_db(client) or refresh):
            album.update_from_api(client)
            cache_object(album)
            if sync_to_db:
                album.sync_to_db()
        return album

    @classmethod
    def get_albums(cls, album_ids, client=None, refresh=False, sync_to_db=True):
        """Fetch multiple albums efficiently using batch API calls."""
        if not album_ids:
            return []

        # Remove duplicates while preserving order
        unique_ids = list(dict.fromkeys(album_ids))

        # Try cache/DB first
        albums_dict = {}
        ids_to_fetch = []

        for album_id in unique_ids:
            album = retrieve_object_from_cache(cls.kind, album_id)
            if album is not None and (client is None or not refresh):
                albums_dict[album_id] = album
            else:
                album = Album(album_id, client)
                if client is not None and (not album.update_from_db(client) or refresh):
                    ids_to_fetch.append(album_id)
                else:
                    albums_dict[album_id] = album

        # Batch fetch from API using ALBUM_BATCH_SIZE (Spotify API limit for albums)
        if ids_to_fetch and client is not None:
            for i in range(0, len(ids_to_fetch), ALBUM_BATCH_SIZE):
                batch_ids = ids_to_fetch[i : i + ALBUM_BATCH_SIZE]
                batch_num = i // ALBUM_BATCH_SIZE + 1
                total_batches = (len(ids_to_fetch) + ALBUM_BATCH_SIZE - 1) // ALBUM_BATCH_SIZE
                logging.info(f"Fetching album batch {batch_num}/{total_batches}")
                raw_albums = client.albums(batch_ids, market=MARKET)

                for raw_album in raw_albums["albums"]:
                    if raw_album is None:
                        continue

                    album = Album(raw_album["id"], client)
                    album.name = utils.sanitize_string(raw_album["name"])
                    album.release_date = raw_album["release_date"]
                    album.artists_id = [artist["id"] for artist in raw_album["artists"]]
                    album.artists = []  # Populated by caller
                    album.updated = str(date.today())

                    albums_dict[raw_album["id"]] = album
                    cache_object(album)

                    if sync_to_db:
                        album.sync_to_db()

        # Return in original order
        return [albums_dict.get(album_id) for album_id in album_ids if album_id in albums_dict]

    def update_from_db(self, client=None):
        try:
            self.name, self.release_date, self.updated = sqlite.select_db(
                sqlite.DATABASE, f"SELECT name, release_date, updated_at FROM albums WHERE id == '{self.id}'"
            ).fetchone()
        except TypeError:
            logging.info("Album ID %s not found in database", self.id)
            return False
        results = sqlite.select_db(
            sqlite.DATABASE, f"SELECT artist_id FROM albums_artists WHERE album_id == '{self.id}'"
        ).fetchall()
        self.artists_id = [col[0] for col in results]
        self.artists = [Artist.get_artist(id, client) for id in self.artists_id]
        logging.info("Album ID %s retrieved from database", self.id)
        return True

    def update_from_api(self, client):
        logging.info("Fetching album %s from api", self.id)
        album = client.album(self.id, market=MARKET)
        self.name = utils.sanitize_string(album["name"])
        self.release_date = album["release_date"]
        self.artists_id = [artist["id"] for artist in album["artists"]]
        self.artists = [Artist.get_artist(id, client) for id in self.artists_id]
        self.updated = str(date.today())

    def sync_to_db(self):
        logging.info("Syncing album %s to database", self.id)
        queries = []
        queries.append(
            f"INSERT OR IGNORE INTO albums VALUES ('{self.id}', '{self.name}', '{self.release_date}', '{self.updated}')"
        )
        for artist in self.artists:
            queries.append(f"INSERT OR IGNORE INTO albums_artists VALUES ('{self.id}', '{artist.id}')")
        logging.debug(queries)
        sqlite.query_db(sqlite.DATABASE, queries)
