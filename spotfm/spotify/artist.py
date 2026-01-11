import logging
from datetime import date

from spotfm import sqlite, utils
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

    @classmethod
    def get_artists(cls, artist_ids, client=None, refresh=False, sync_to_db=True):
        """Fetch multiple artists efficiently using batch API calls."""
        if not artist_ids:
            return []

        # Remove duplicates while preserving order
        unique_ids = list(dict.fromkeys(artist_ids))

        # Try cache/DB first
        artists_dict = {}
        ids_to_fetch = []

        for artist_id in unique_ids:
            artist = retrieve_object_from_cache(cls.kind, artist_id)
            if artist is not None and (client is None or not refresh):
                artists_dict[artist_id] = artist
            else:
                artist = Artist(artist_id, client)
                if client is not None and (not artist.update_from_db() or refresh):
                    ids_to_fetch.append(artist_id)
                else:
                    artists_dict[artist_id] = artist

        # Batch fetch from API (50 per batch)
        if ids_to_fetch and client is not None:
            for i in range(0, len(ids_to_fetch), 50):
                batch_ids = ids_to_fetch[i : i + 50]
                logging.info(f"Fetching artist batch {i // 50 + 1}/{(len(ids_to_fetch) + 49) // 50}")
                raw_artists = client.artists(batch_ids)

                for raw_artist in raw_artists["artists"]:
                    if raw_artist is None:
                        continue

                    artist = Artist(raw_artist["id"], client)
                    artist.name = utils.sanitize_string(raw_artist["name"])
                    artist.genres = [utils.sanitize_string(genre) for genre in raw_artist["genres"]]
                    artist.updated = str(date.today())

                    artists_dict[raw_artist["id"]] = artist
                    cache_object(artist)

                    if sync_to_db:
                        artist.sync_to_db()

        # Return in original order
        return [artists_dict.get(artist_id) for artist_id in artist_ids if artist_id in artists_dict]

    def update_from_db(self):
        try:
            self.name, self.updated = sqlite.select_db(
                sqlite.DATABASE, f"SELECT name, updated_at FROM artists WHERE id == '{self.id}'"
            ).fetchone()
        except TypeError:
            logging.info("Artist ID %s not found in database", self.id)
            return False
        results = sqlite.select_db(
            sqlite.DATABASE, f"SELECT genre FROM artists_genres WHERE artist_id == '{self.id}'"
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
        sqlite.query_db(sqlite.DATABASE, queries)
