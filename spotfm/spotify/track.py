import logging
from datetime import date
from time import sleep

from spotfm import sqlite, utils
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
        """
        Fetch multiple tracks efficiently, leveraging cache/DB.

        Strategy:
        1. Check cache/DB for all tracks first (respects 3-tier cache)
        2. Only batch fetch missing tracks from API
        3. Collect album/artist IDs from missing tracks
        4. Batch fetch only missing albums and artists
        5. Return all tracks (cached + newly fetched)
        """
        if not tracks_id:
            return []

        tracks = []
        tracks_to_fetch = []

        # Phase 1: Check cache/DB for all tracks (CRITICAL for performance)
        for track_id in tracks_id:
            # Try pickle cache first
            track = retrieve_object_from_cache(cls.kind, track_id)
            if track is not None and not refresh:
                tracks.append(track)
                continue

            # Try DB
            track = Track(track_id, client)
            if not refresh and track.update_from_db(client):
                tracks.append(track)
                continue

            # Track not in cache/DB, need to fetch from API
            tracks_to_fetch.append(track_id)

        # If all tracks cached, return early (typical case for update_playlists)
        if not tracks_to_fetch:
            logging.info(f"All {len(tracks)} tracks retrieved from cache/DB")
            return tracks

        logging.info(f"Retrieved {len(tracks)} tracks from cache/DB, fetching {len(tracks_to_fetch)} from API")

        # Phase 2: Batch fetch missing tracks from API
        tracks_id_batches = [tracks_to_fetch[i : i + batch_size] for i in range(0, len(tracks_to_fetch), batch_size)]
        all_raw_tracks = []

        for i, batch in enumerate(tracks_id_batches):
            logging.info(f"Fetching track batch {i + 1}/{len(tracks_id_batches)}")
            raw_tracks = client.tracks(batch, market=MARKET)

            for raw_track in raw_tracks["tracks"]:
                if raw_track is not None:
                    all_raw_tracks.append(raw_track)

            # Rate limiting: sleep between batches only
            if i < len(tracks_id_batches) - 1:
                sleep(1)

        # Phase 3: Collect album/artist IDs from fetched tracks
        album_ids = []
        artist_ids = []

        for raw_track in all_raw_tracks:
            album_ids.append(raw_track["album"]["id"])
            artist_ids.extend([artist["id"] for artist in raw_track["artists"]])

        # Phase 4: Batch fetch albums (respects cache/DB in get_albums)
        albums_dict = {}
        if album_ids:
            logging.info("Batch fetching albums (checking cache first)")
            unique_album_ids = list(dict.fromkeys(album_ids))
            albums = Album.get_albums(unique_album_ids, client, refresh=refresh)
            albums_dict = {album.id: album for album in albums if album is not None}
            if albums:
                sleep(0.5)

        # Phase 5: Batch fetch artists (respects cache/DB in get_artists)
        artists_dict = {}
        if artist_ids:
            logging.info("Batch fetching artists (checking cache first)")
            unique_artist_ids = list(dict.fromkeys(artist_ids))
            artists = Artist.get_artists(unique_artist_ids, client, refresh=refresh)
            artists_dict = {artist.id: artist for artist in artists if artist is not None}
            if artists:
                sleep(0.5)

        # Phase 6: Populate album.artists
        for album in albums_dict.values():
            if album.artists_id:
                album.artists = [artists_dict[aid] for aid in album.artists_id if aid in artists_dict]

        # Phase 7: Create track objects from fetched data
        for raw_track in all_raw_tracks:
            try:
                track = Track(raw_track["id"], client)
                track.name = utils.sanitize_string(raw_track["name"])
                track.album_id = raw_track["album"]["id"]
                track.updated = str(date.today())

                # Use pre-fetched album
                album = albums_dict.get(track.album_id)
                if album:
                    track.album = album.name
                    track.release_date = album.release_date

                # Use pre-fetched artists
                track.artists_id = [artist["id"] for artist in raw_track["artists"]]
                track.artists = [artists_dict[aid] for aid in track.artists_id if aid in artists_dict]

                cache_object(track)
                tracks.append(track)

            except (TypeError, KeyError) as e:
                logging.info(f"Error processing track: {e}")

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
            self.name, self.updated = sqlite.select_db(
                sqlite.DATABASE, f"SELECT name, updated_at FROM tracks WHERE id == '{self.id}'"
            ).fetchone()
        except TypeError:
            logging.info("Track ID %s not found in database", self.id)
            return False
        try:
            self.album_id = sqlite.select_db(
                sqlite.DATABASE, f"SELECT album_id FROM albums_tracks WHERE track_id == '{self.id}'"
            ).fetchone()[0]
        except TypeError:
            logging.info("Album ID %s not found in database", self.id)
            return False
        album = Album.get_album(self.album_id, client)
        # TODO: add Album object instead
        self.album = album.name
        self.release_date = album.release_date
        results = sqlite.select_db(
            sqlite.DATABASE, f"SELECT artist_id FROM tracks_artists WHERE track_id == '{self.id}'"
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
        # Remove redundant Album.get_album() call
        # Album should already be synced by Track.get_tracks()
        queries = []
        queries.append(f"INSERT OR IGNORE INTO tracks VALUES ('{self.id}', '{self.name}', '{self.updated}')")
        queries.append(f"INSERT OR IGNORE INTO albums_tracks VALUES ('{self.album_id}', '{self.id}')")
        for artist in self.artists:
            queries.append(f"INSERT OR IGNORE INTO tracks_artists VALUES ('{self.id}', '{artist.id}')")
        logging.debug(queries)
        sqlite.query_db(sqlite.DATABASE, queries)
        logging.info(f"Track {self.id} added to db")

    def get_artists_names(self):
        artists_names = []
        for artist in self.artists:
            artists_names.append(artist.name)
        return ", ".join(artists_names)

    def get_genres_names(self):
        return ", ".join(self.genres)
