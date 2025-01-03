import logging
from collections import Counter
from datetime import date
from time import sleep

import spotipy
from spotipy.oauth2 import CacheFileHandler, SpotifyOAuth

from spotfm import utils

REDIRECT_URI = "http://127.0.0.1:9090"
SCOPE = "user-library-read playlist-read-private playlist-read-collaborative"
TOKEN_CACHE_FILE = utils.WORK_DIR / "spotify-token-cache"
MARKET="FR"

# TODO:
# - use query params instead of f-strings
#    (https://docs.python.org/3/library/sqlite3.html#sqlite3-placeholders)


class Client:
    def __init__(self, client_id, client_secret, redirect_uri=REDIRECT_URI, scope=SCOPE):
        handler = CacheFileHandler(cache_path=TOKEN_CACHE_FILE)
        self.client = spotipy.Spotify(
            retries=0,
            auth_manager=SpotifyOAuth(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
                scope=scope,
                cache_handler=handler,
            ),
        )

    def get_playlists_id(self, excluded_playlists=[]):
        playlists_ids = []
        user = self.client.current_user()["id"]

        def filter_playlists(playlists):
            for playlist in playlists["items"]:
                if playlist["owner"]["id"] == user and playlist["id"] not in excluded_playlists:
                    yield playlist["id"]

        playlists = self.client.current_user_playlists()
        for playlist in filter_playlists(playlists):
            playlists_ids.append(playlist)
        while playlists["next"]:
            playlists = self.client.next(playlists)
            for playlist in filter_playlists(playlists):
                playlists_ids.append(playlist)

        return playlists_ids

    def update_playlists(self, excluded_playlists=[]):
        playlists_id = self.get_playlists_id(excluded_playlists)
        utils.query_db(utils.DATABASE, ["DELETE FROM playlists", "DELETE FROM playlists_tracks"])
        for playlist_id in playlists_id:
            Playlist(playlist_id, self.client)


class Playlist:
    def __init__(self, playlist_id, client=None, refresh=True):
        self.id = utils.parse_url(playlist_id)
        logging.info("Initializing Playlist %s", self.id)
        self.name = None
        self.owner = None
        self.tracks = None  # [(id, added_at)]
        self.updated = None
        # TODO: self._tracks
        # TODO: self._tracks_names
        # TODO: self._sorted_tracks

        if (refresh and client is not None) or (not self.update_from_db() and client is not None):
            self.update_from_api(client)
            self.sync_to_db(client)

    def __repr__(self):
        return f"Playlist({self.owner} - {self.name})"

    def __str__(self):
        return f"{self.owner} - {self.name}"

    # TODO
    # @property
    # def tracks(self):
    #     if self._tracks is not None:
    #         return self._tracks
    #     self._tracks = []
    #     for track_id in self.tracks_id:
    #         self._tracks.append(Track(track_id))
    #     return self._tracks

    # TODO
    # @property
    # def tracks_names(self):
    #     if self._tracks_names is not None:
    #         return self._tracks_names
    #     self._tracks_names = []
    #     for track in self.tracks:
    #         self._tracks_names.append(track.__str__())
    #     return self._tracks_names

    # TODO
    # @property
    # def sorted_tracks(self):
    #     if self._sorted_tracks is not None:
    #         return self._sorted_tracks
    #     self._sorted_tracks = sorted(self.tracks)
    #     return self._sorted_tracks

    def update_from_db(self):
        try:
            self.name, self.owner, self.updated = utils.select_db(
                utils.DATABASE, f"SELECT name, owner, updated_at FROM playlists WHERE id == '{self.id}'"
            ).fetchone()
        except TypeError:
            logging.info("Playlist ID %s not found in database", self.id)
            return False
        results = utils.select_db(
            utils.DATABASE, f"SELECT track_id, added_at FROM playlists_tracks WHERE playlist_id == '{self.id}'"
        ).fetchall()
        self.tracks = [(col[0], col[1]) for col in results]
        logging.info("Playlist ID %s retrieved from database", self.id)
        return True

    def update_from_api(self, client):
        playlist = client.playlist(self.id, fields="name,owner.id", market=MARKET)
        self.name = utils.sanitize_string(playlist["name"])
        logging.info("Fetching playlist %s - %s from api", self.id, self.name)
        self.owner = utils.sanitize_string(playlist["owner"]["id"])
        results = client.playlist_items(
            self.id, fields="items(added_at,track.id),next", market=MARKET, additional_types=["track"]
        )
        tracks = results["items"]
        while results["next"]:
            results = client.next(results)
            tracks.extend(results["items"])
        self.tracks = [(track["track"]["id"], track["added_at"]) for track in tracks if track["track"] is not None]
        self.updated = str(date.today())

    def sync_to_db(self, client):
        logging.info("Syncing playlist %s to database", self.id)
        queries = []
        queries.append(
            f"INSERT OR IGNORE INTO playlists VALUES ('{self.id}', '{self.name}', '{self.owner}', '{self.updated}')"
        )
        for track in self.tracks:
            Track(track[0], client)
            queries.append(f"INSERT OR IGNORE INTO playlists_tracks VALUES ('{self.id}', '{track[0]}', '{track[1]}')")
        logging.debug(queries)
        utils.query_db(utils.DATABASE, queries)

    def get_playlist_genres(self):
        genres = []
        for track in self.tracks:
            for genre in track.genres:
                genres.append(genre)
        return Counter(genres)

    # TODO
    # def remove_track(self, track_id):
    #     self.client.playlist_remove_all_occurrences_of_items(self.id, [track_id])

    # TODO
    # def add_track(self, track_id):
    #     try:
    #         self.client.playlist_add_items(self.id, [track_id])
    #     except TypeError:
    #         print(f"Error: Failed to add {Track(self.client, track_id)}")


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


class Track:
    def __init__(self, track_id, client=None, refresh=False, update=True):
        logging.info("Initializing Track %s", track_id)
        self.id = utils.parse_url(track_id)
        self.name = None
        self.album_id = None
        self.album = None
        self.release_date = None
        self.artists_id = None
        self.updated = None
        self.artists = None
        self._genres = None

        if update and ((refresh and client is not None) or (not self.update_from_db() and client is not None)):
            self.update_from_api(client)
            self.sync_to_db(client)

    def __repr__(self):
        artists_names = [artist.name for artist in self.artists]
        return f"Track({', '.join(artists_names)} - {self.name})"

    def __str__(self):
        artists_names = [artist.name for artist in self.artists]
        return f"{', '.join(artists_names)} - {self.name}"

    def __lt__(self, other):
        return self.__repr__() < other.__repr__()

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

    def update_from_db(self):
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
        album = Album(self.album_id)
        # TODO: add Album object instead
        self.album = album.name
        self.release_date = album.release_date
        results = utils.select_db(
            utils.DATABASE, f"SELECT artist_id FROM tracks_artists WHERE track_id == '{self.id}'"
        ).fetchall()
        self.artists_id = [col[0] for col in results]
        self.artists = [Artist(id) for id in self.artists_id]
        logging.info("Track ID %s retrieved from database", self.id)
        return True

    def update_from_api(self, client):
        logging.info("Fetching track %s from api", self.id)
        track = client.track(self.id, market=MARKET)
        self.name = utils.sanitize_string(track["name"])
        self.album_id = track["album"]["id"]
        album = Album(self.album_id)
        self.album = album.name
        self.release_date = album.release_date
        self.artists_id = [artist["id"] for artist in track["artists"]]
        self.artists = [Artist(id, client) for id in self.artists_id]
        self.updated = str(date.today())

    def update_from_track(self, track, client):
        self.name = utils.sanitize_string(track["name"])
        self.album_id = track["album"]["id"]
        album = Album(self.album_id)
        self.album = album.name
        self.release_date = album.release_date
        self.artists_id = [artist["id"] for artist in track["artists"]]
        self.artists = [Artist(id, client) for id in self.artists_id]
        self.updated = str(date.today())

    def sync_to_db(self, client):
        logging.info("Syncing track %s to database", self.id)
        Album(self.album_id, client)
        queries = []
        queries.append(f"INSERT OR IGNORE INTO tracks VALUES ('{self.id}', '{self.name}', '{self.updated}')")
        queries.append(f"INSERT OR IGNORE INTO albums_tracks VALUES ('{self.album_id}', '{self.id}')")
        for artist in self.artists:
            queries.append(f"INSERT OR IGNORE INTO tracks_artists VALUES ('{self.id}', '{artist.id}')")
        logging.debug(queries)
        utils.query_db(utils.DATABASE, queries)

    def get_artists_names(self):
        artists_names = []
        for artist in self.artists:
            artists_names.append(artist.name)
        return ", ".join(artists_names)

    def get_genres_names(self):
        return ", ".join(self.genres)


class Artist:
    def __init__(self, artist_id, client=None, refresh=False):
        logging.info("Initializing Artist %s", artist_id)
        self.id = utils.parse_url(artist_id)
        self.name = None
        self.genres = []
        self.updated = None

        if (refresh and client is not None) or (not self.update_from_db() and client is not None):
            self.update_from_api(client)
            self.sync_to_db()

    def __repr__(self):
        return f"Artist({self.name})"

    def __str__(self):
        return self.name

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


def add_tracks_from_file(client, file_path):
    tracks_ids = utils.manage_tracks_ids_file(file_path)

    for track_id in tracks_ids:
        logging.info(f"Initializing track {track_id}")
        track = Track(track_id, client.client)

        if track.name is not None and track.artists is not None and track.album is not None:
            track.sync_to_db(client)
            logging.info(f"Track {track.id} added to db")
        else:
            logging.info(f"Error: Track {track.id} not found")
        
        # Prevent rate limiting (429 errors)
        sleep(0.1)


def add_tracks_from_file_batch(client, file_path, batch_size=50):
    tracks_ids = utils.manage_tracks_ids_file(file_path)

    # split tracks_ids in batches
    tracks_ids_batches = [tracks_ids[i : i + batch_size] for i in range(0, len(tracks_ids), batch_size)]

    for i, batch in enumerate(tracks_ids_batches):
        logging.info(f"Batch: {i}/{len(tracks_ids_batches)}")
        tracks = client.client.tracks(batch, market=MARKET)

        for raw_track in tracks["tracks"]:
            try:
                logging.info(f"Initializing track {raw_track['id']}")
                track = Track(raw_track["id"], update=False)
                track.update_from_track(raw_track, client.client)
                track.sync_to_db(client.client)
                logging.info(f"Track {track.id} added to db")
            except TypeError:
                logging.info(f"Error: Track not found")
        
        # Prevent rate limiting (429 errors)
        sleep(1)


def count_tracks_by_playlists():
    return utils.select_db(
        utils.DATABASE,
        "SELECT name, count(*) FROM playlists, playlists_tracks WHERE id = playlists_tracks.playlist_id GROUP BY name;",
    ).fetchall()


def count_tracks(playlists_pattern=None):
    if playlists_pattern:
        results = utils.select_db(utils.DATABASE, "SELECT id FROM playlists WHERE name LIKE ?;", (playlists_pattern,))
        ids = [id[0] for id in results]
        query = f"""
          WITH t AS (SELECT DISTINCT track_id FROM playlists_tracks WHERE playlist_id IN ({','.join(['?']*len(ids))}))
          SELECT count(*) AS tracks FROM t;
        """
        return utils.select_db(utils.DATABASE, query, ids).fetchone()[0]
    return utils.select_db(
        utils.DATABASE,
        "WITH t AS (SELECT DISTINCT track_id FROM playlists_tracks) SELECT count(*) AS tracks FROM t;",
    ).fetchone()[0]
