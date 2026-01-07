import logging
from datetime import date
from time import sleep

from spotfm import utils
from spotfm.spotify.album import Album
from spotfm.spotify.artist import Artist
from spotfm.spotify.constants import BATCH_SIZE, MARKET
from spotfm.utils import cache_object, retrieve_object_from_cache


class Track:
    kind = "track"

    def __init__(self, id, client=None, refresh=False):
        logging.info("Initializing Track %s", id)
        self.id = utils.parse_url(id)
        self.name = None
        self.album_id = None
        self.album = None
        self.release_date = None
        self.artists_id = None
        self.updated = None
        self.artists = None
        self._genres = None

    def __repr__(self):
        artists_names = [artist.name for artist in self.artists]
        return f"Track({', '.join(artists_names)} - {self.name})"

    def __str__(self):
        artists_names = [artist.name for artist in self.artists]
        return f"{', '.join(artists_names)} - {self.name}"

    def __lt__(self, other):
        return self.__repr__() < other.__repr__()

    @classmethod
    def get_track(cls, id, client=None, refresh=False, sync_to_db=True):
        track = retrieve_object_from_cache(cls.kind, id)
        if track is not None and (client is None or not refresh):
            return track

        track = Track(id, client)
        if client is not None and (not track.update_from_db(client) or refresh):
            track.update_from_api(client)
            cache_object(track)
            if sync_to_db:
                track.sync_to_db(client)
        return track

    @classmethod
    def get_tracks(cls, tracks_id, client=None, refresh=False, batch_size=BATCH_SIZE):
        tracks_id_batches = [tracks_id[i : i + batch_size] for i in range(0, len(tracks_id), batch_size)]
        tracks = []

        for i, batch in enumerate(tracks_id_batches):
            logging.info(f"Batch: {i}/{len(tracks_id_batches)}")
            raw_tracks = client.tracks(batch, market=MARKET)

            for raw_track in raw_tracks["tracks"]:
                try:
                    track = Track.get_track(raw_track["id"], refresh=refresh)
                    track.update_from_track(raw_track, client)
                    tracks.append(track)
                except TypeError:
                    logging.info("Error: Track not found")
                # Prevent rate limiting (429 errors)
                sleep(0.1)

            # Prevent rate limiting (429 errors)
            sleep(1)

        return tracks

    @property
    def genres(self):
        if self._genres is not None:
            return self._genres
        genres = []
        for artist in self.artists:
            for genre in artist.genres:
                genres.append(genre)
        self._genres = list(dict.fromkeys(genres))
        return self._genres

    def update_from_db(self, client=None):
        try:
            self.name, self.updated = utils.select_db(
                utils.DATABASE, f"SELECT name, updated_at FROM tracks WHERE id == '{self.id}'"
            ).fetchone()
        except TypeError:
            logging.info("Track ID %s not found in database", self.id)
            return False
        try:
            self.album_id = utils.select_db(
                utils.DATABASE, f"SELECT album_id FROM albums_tracks WHERE track_id == '{self.id}'"
            ).fetchone()[0]
        except TypeError:
            logging.info("Album ID %s not found in database", self.id)
            return False
        album = Album.get_album(self.album_id, client)
        # TODO: add Album object instead
        self.album = album.name
        self.release_date = album.release_date
        results = utils.select_db(
            utils.DATABASE, f"SELECT artist_id FROM tracks_artists WHERE track_id == '{self.id}'"
        ).fetchall()
        self.artists_id = [col[0] for col in results]
        self.artists = [Artist.get_artist(id, client) for id in self.artists_id]
        logging.info("Track ID %s retrieved from database", self.id)
        return True

    def update_from_api(self, client):
        logging.info("Fetching track %s from api", self.id)
        track = client.track(self.id, market=MARKET)
        self.name = utils.sanitize_string(track["name"])
        self.album_id = track["album"]["id"]
        album = Album.get_album(self.album_id, client)
        self.album = album.name
        self.release_date = album.release_date
        self.artists_id = [artist["id"] for artist in track["artists"]]
        self.artists = [Artist.get_artist(id, client) for id in self.artists_id]
        self.updated = str(date.today())

    def update_from_track(self, track, client):
        self.name = utils.sanitize_string(track["name"])
        self.album_id = track["album"]["id"]
        album = Album.get_album(self.album_id, client)
        self.album = album.name
        self.release_date = album.release_date
        self.artists_id = [artist["id"] for artist in track["artists"]]
        self.artists = [Artist.get_artist(id, client) for id in self.artists_id]
        self.updated = str(date.today())

    def sync_to_db(self, client):
        logging.info("Syncing track %s to database", self.id)
        Album.get_album(self.album_id, client)
        queries = []
        queries.append(f"INSERT OR IGNORE INTO tracks VALUES ('{self.id}', '{self.name}', '{self.updated}')")
        queries.append(f"INSERT OR IGNORE INTO albums_tracks VALUES ('{self.album_id}', '{self.id}')")
        for artist in self.artists:
            queries.append(f"INSERT OR IGNORE INTO tracks_artists VALUES ('{self.id}', '{artist.id}')")
        logging.debug(queries)
        utils.query_db(utils.DATABASE, queries)
        logging.info(f"Track {self.id} added to db")

    def get_artists_names(self):
        artists_names = []
        for artist in self.artists:
            artists_names.append(artist.name)
        return ", ".join(artists_names)

    def get_genres_names(self):
        return ", ".join(self.genres)
