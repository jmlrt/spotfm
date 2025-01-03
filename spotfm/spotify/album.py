import logging
from datetime import date

from spotfm import utils
from spotfm.spotify.artist import Artist
from spotfm.spotify.constants import MARKET


class Album:
    def __init__(self, album_id, client=None, refresh=False):
        logging.info("Initializing Album %s", album_id)
        self.id = utils.parse_url(album_id)
        self.name = None
        self.release_date = None
        self.updated = None
        self.artists_id = []
        self.artists = []
        # TODO: add self.tracks

        if (refresh and client is not None) or (not self.update_from_db() and client is not None):
            self.update_from_api(client)
            self.sync_to_db()

    def __repr__(self):
        return f"Album({self.name})"

    def __str__(self):
        return self.name

    def update_from_db(self):
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
        self.artists = [Artist(id) for id in self.artists_id]
        logging.info("Album ID %s retrieved from database", self.id)
        return True

    def update_from_api(self, client):
        logging.info("Fetching album %s from api", self.id)
        album = client.album(self.id, market=MARKET)
        self.name = utils.sanitize_string(album["name"])
        self.release_date = album["release_date"]
        self.artists_id = [artist["id"] for artist in album["artists"]]
        self.artists = [Artist(id, client) for id in self.artists_id]
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
