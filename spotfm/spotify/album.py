import logging
from datetime import date

from spotfm import utils
from spotfm.spotify.artist import Artist
from spotfm.spotify.constants import MARKET
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

    def update_from_db(self, client=None):
        try:
            self.name, self.release_date, self.updated = utils.select_db(
                utils.DATABASE, f"SELECT name, release_date, updated_at FROM albums WHERE id == '{self.id}'"
            ).fetchone()
        except TypeError:
            logging.info("Album ID %s not found in database", self.id)
            return False
        results = utils.select_db(
            utils.DATABASE, f"SELECT artist_id FROM albums_artists WHERE album_id == '{self.id}'"
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
        utils.query_db(utils.DATABASE, queries)
