import logging
from datetime import date

from spotfm import utils
from spotfm.utils import cache_object, retrieve_object_from_cache


class Artist:
    kind = "artist"

    def __init__(self, id, client=None, refresh=False):
        logging.info("Initializing Artist %s", id)
        self.id = utils.parse_url(id)
        self.name = None
        self.genres = []
        self.updated = None

    def __repr__(self):
        return f"Artist({self.name})"

    def __str__(self):
        return self.name

    @classmethod
    def get_artist(cls, id, client=None, refresh=False, sync_to_db=True):
        artist = retrieve_object_from_cache(cls.kind, id)
        if artist is not None and (client is None or not refresh):
            return artist

        artist = Artist(id, client)
        if client is not None and (not artist.update_from_db() or refresh):
            artist.update_from_api(client)
            cache_object(artist)
            if sync_to_db:
                artist.sync_to_db()
        return artist

    def update_from_db(self):
        try:
            self.name, self.updated = utils.select_db(
                utils.DATABASE, f"SELECT name, updated_at FROM artists WHERE id == '{self.id}'"
            ).fetchone()
        except TypeError:
            logging.info("Artist ID %s not found in database", self.id)
            return False
        results = utils.select_db(
            utils.DATABASE, f"SELECT genre FROM artists_genres WHERE artist_id == '{self.id}'"
        ).fetchall()
        self.genres = [col[0] for col in results]
        logging.info("Artist ID %s retrieved from database", self.id)
        return True

    def update_from_api(self, client):
        logging.info("Fetching artist %s from api", self.id)
        artist = client.artist(self.id)
        self.name = utils.sanitize_string(artist["name"])
        self.genres = [utils.sanitize_string(genre) for genre in artist["genres"]]
        self.updated = str(date.today())

    def sync_to_db(self):
        logging.info("Syncing artist %s to database", self.id)
        queries = []
        queries.append(f"INSERT OR IGNORE INTO artists VALUES ('{self.id}', '{self.name}', '{self.updated}')")
        if len(self.genres) > 0:
            values = ""
            for genre in self.genres:
                values += f"('{self.id}','{utils.sanitize_string(genre)}'),"
            queries.append(f"INSERT OR IGNORE INTO artists_genres VALUES {values}".rstrip(","))
        logging.debug(queries)
        utils.query_db(utils.DATABASE, queries)
